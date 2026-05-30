#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
features.ladder_builder：梯队推测 + 主线置信度评分

职责（纯计算，无 I/O）：
- 输入：M3 的 SectorResolution + pools_cache（涨停池） + 可选 market_data（已算好的 score）
- 输出：
  · tiers:           按真实连板数 lbc 分层的 TierCell 列表
  · main_lines:      多源置信度加权排序后的主线（含产业链合并）
  · resonance_map:   {sector: 板块共振强度（同板块涨停数/同步度）}

非职责：
- 不做候选池筛选（5/Top-N 选择逻辑由后续 watch 流程承担）
- 不发起网络 I/O

主线 confidence 公式（设计于 2026-05）：
    biying_signal = min(1.0, 该链/板块涨停股数 / 6)
    em_signal     = max((1 - rank/15) for s in chain if rank<=15) * (1 + 0.3*has_hot)
    xgb_signal    = min(1.0, total_events / 5) + 0.2 * has_description
    confidence    = 0.40 * biying + 0.35 * em + 0.25 * xgb
权重设计依据：
- biying 占 0.40：涨停股本身就是事实信号（不是预测）
- em     占 0.35：明日主题排名是预测信号但官方加权
- xgb    占 0.25：异动事件较细碎，作为补强
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from daily_review.features.sector_resolver import (
    CHAIN_MAP,
    SectorResolution,
    normalize_code,
)


# ---------------------------------------------------------------------------
# 输出 dataclass
# ---------------------------------------------------------------------------


@dataclass
class TierCell:
    code: str                      # 6位代码
    name: str                      # 简称
    lbc: int                       # 真实连板数
    cje_yi: float                  # 成交额（亿）
    turnover: float                # 换手率%
    seal_fund_yi: float            # 封单金额（亿）
    zbc: int                       # 炸板次数
    score: float                   # 综合分（来自 market_data.leaders；缺省 0）
    sectors: list[tuple[str, float]] = field(default_factory=list)  # (canonical, confidence)
    primary_sector: str = ""       # confidence 最高的板块

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "lbc": self.lbc,
            "cje_yi": round(self.cje_yi, 2),
            "turnover": round(self.turnover, 2),
            "seal_fund_yi": round(self.seal_fund_yi, 2),
            "zbc": self.zbc,
            "score": round(self.score, 2),
            "sectors": [{"sector": s, "confidence": round(c, 3)} for (s, c) in self.sectors],
            "primary_sector": self.primary_sector,
        }


@dataclass
class MainLine:
    name: str                            # 主线名：产业链名或单 sector 名
    is_chain: bool                       # 是否产业链合并
    constituents: list[str]              # 归一化后的板块名清单
    confidence: float                    # 0-1
    biying_signal: float                 # 涨停股数贡献
    em_signal: float                     # 东财主题贡献
    xgb_signal: float                    # 选股宝贡献
    leading_stocks: list[str] = field(default_factory=list)   # 6位代码列表，按 lbc 倒序
    em_rank_min: int | None = None       # 主线下东财最优排名
    em_zt_total: int = 0                 # 主线下东财预估涨停总和
    has_xgb_hot: bool = False
    has_em_hot: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "is_chain": self.is_chain,
            "constituents": self.constituents,
            "confidence": round(self.confidence, 3),
            "signals": {
                "biying": round(self.biying_signal, 3),
                "em": round(self.em_signal, 3),
                "xgb": round(self.xgb_signal, 3),
            },
            "leading_stocks": self.leading_stocks,
            "em_rank_min": self.em_rank_min,
            "em_zt_total": self.em_zt_total,
            "has_xgb_hot": self.has_xgb_hot,
            "has_em_hot": self.has_em_hot,
        }


@dataclass
class LadderResult:
    date: str
    tiers: dict[int, list[TierCell]] = field(default_factory=dict)
    main_lines: list[MainLine] = field(default_factory=list)
    resonance_map: dict[str, float] = field(default_factory=dict)
    promotion_rates: dict[str, float] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "tiers": {str(k): [c.to_dict() for c in v] for k, v in self.tiers.items()},
            "main_lines": [m.to_dict() for m in self.main_lines],
            "resonance_map": {k: round(v, 3) for k, v in self.resonance_map.items()},
            "promotion_rates": {k: round(v, 3) for k, v in self.promotion_rates.items()},
            "diagnostics": self.diagnostics,
        }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def build_ladder(
    *,
    resolution: SectorResolution,
    pools_cache: dict[str, Any],
    date: str,
    market_data: dict[str, Any] | None = None,
    main_line_top_k: int = 6,
) -> LadderResult:
    """
    主入口：在 M3 输出基础上构造梯队 + 主线。

    参数：
        resolution:   M3 输出
        pools_cache:  必盈涨停池（{"version", "pools": {"ztgc": {date: [...]}}}）
        date:         交易日 YYYY-MM-DD
        market_data:  可选 market_data.json 完整 dict，用于读取 leaders[].score
        main_line_top_k:  保留主线数量上限
    """
    zt_records = _extract_zt_records(pools_cache, date)
    score_by_code = _build_score_map(market_data) if market_data else {}

    # ---- 1) 构造 TierCell ----
    cells_by_code: dict[str, TierCell] = {}
    for rec in zt_records:
        code = normalize_code(rec.get("dm") or rec.get("code") or "")
        if not code:
            continue
        ss = resolution.stock_to_sectors.get(code)
        sectors = [(s, c) for (s, c, _src) in ss.sectors] if ss else []
        primary = sectors[0][0] if sectors else ""
        cell = TierCell(
            code=code,
            name=str(rec.get("mc") or rec.get("name") or ""),
            lbc=int(rec.get("lbc") or 0),
            cje_yi=_to_yi(rec.get("cje")),
            turnover=_to_float(rec.get("hs")),
            seal_fund_yi=_to_yi(rec.get("zj") or rec.get("fba")),
            zbc=int(rec.get("zbc") or 0),
            score=float(score_by_code.get(code, 0.0)),
            sectors=sectors,
            primary_sector=primary,
        )
        cells_by_code[code] = cell

    # ---- 2) 分层 ----
    tiers: dict[int, list[TierCell]] = {1: [], 2: [], 3: [], 4: []}
    for cell in cells_by_code.values():
        bucket = min(max(cell.lbc, 1), 4)
        tiers[bucket].append(cell)
    # 每层内排序：lbc==1 优先按 cje 降序；其它优先按 lbc, score, cje 综合
    tiers[1].sort(key=lambda c: (c.cje_yi, c.score), reverse=True)
    for k in (2, 3, 4):
        tiers[k].sort(key=lambda c: (c.lbc, c.score, c.cje_yi), reverse=True)

    # ---- 3) 板块共振强度 ----
    resonance_map = _compute_resonance(cells_by_code.values())

    # ---- 4) 主线评分 + 排序 ----
    main_lines = _build_main_lines(
        resolution=resolution,
        cells=cells_by_code,
        resonance=resonance_map,
    )
    main_lines.sort(key=lambda m: m.confidence, reverse=True)
    main_lines = main_lines[:main_line_top_k]

    # ---- 5) 晋级率（粗略：当前 vs 上一交易日） ----
    promotion_rates = _compute_promotion_rates(pools_cache, date)

    diagnostics = {
        "zt_total": len(cells_by_code),
        "tier_counts": {k: len(v) for k, v in tiers.items()},
        "sectors_with_zt": sum(1 for v in resonance_map.values() if v > 0),
        "main_lines_total": len(main_lines),
    }

    return LadderResult(
        date=date,
        tiers=tiers,
        main_lines=main_lines,
        resonance_map=resonance_map,
        promotion_rates=promotion_rates,
        diagnostics=diagnostics,
    )


# ---------------------------------------------------------------------------
# 内部 helper
# ---------------------------------------------------------------------------


def _to_float(v: Any) -> float:
    try:
        if v is None or v == "":
            return 0.0
        return float(v)
    except Exception:
        return 0.0


def _to_yi(v: Any) -> float:
    """元 → 亿"""
    return _to_float(v) / 1.0e8


def _extract_zt_records(pools_cache: dict[str, Any], date: str) -> list[dict[str, Any]]:
    pools = pools_cache.get("pools") if isinstance(pools_cache, dict) else None
    if not isinstance(pools, dict):
        return []
    ztgc = pools.get("ztgc") if isinstance(pools.get("ztgc"), dict) else {}
    rows = ztgc.get(date)
    if isinstance(rows, list):
        return [r for r in rows if isinstance(r, dict)]
    # 兼容：若无该日，取最近一天
    if isinstance(ztgc, dict) and ztgc:
        latest = sorted(ztgc.keys())[-1]
        rows = ztgc.get(latest)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def _build_score_map(market_data: dict[str, Any]) -> dict[str, float]:
    """从 market_data.leaders 提取 {code6: score}。"""
    out: dict[str, float] = {}
    leaders = market_data.get("leaders") if isinstance(market_data, dict) else None
    if not isinstance(leaders, list):
        return out
    for it in leaders:
        if not isinstance(it, dict):
            continue
        code = normalize_code(it.get("code") or it.get("dm") or "")
        if not code:
            continue
        try:
            out[code] = float(it.get("score") or 0.0)
        except Exception:
            pass
    return out


def _compute_resonance(cells) -> dict[str, float]:
    """
    板块共振强度：归一到 [0, 1]
    定义：板块下涨停股数 → log2(1+n)/log2(1+max_n)
    """
    counts: dict[str, int] = {}
    for cell in cells:
        for sector, _conf in cell.sectors:
            counts[sector] = counts.get(sector, 0) + 1
    if not counts:
        return {}
    import math
    max_n = max(counts.values())
    denom = math.log2(1 + max_n) or 1.0
    return {s: math.log2(1 + n) / denom for s, n in counts.items()}


def _build_main_lines(
    *,
    resolution: SectorResolution,
    cells: dict[str, TierCell],
    resonance: dict[str, float],
) -> list[MainLine]:
    """
    主线候选 = 产业链分组 + 未被纳入产业链但单板块表现强的 sector。

    confidence = 0.40 * biying + 0.35 * em + 0.25 * xgb
    """
    main_lines: list[MainLine] = []
    used_sectors: set[str] = set()

    # 1) 产业链合并主线
    for chain_name, members in resolution.chain_groups.items():
        if not members:
            continue
        ml = _score_main_line(
            name=chain_name,
            is_chain=True,
            constituents=members,
            resolution=resolution,
            cells=cells,
            resonance=resonance,
        )
        if ml.confidence > 0:
            main_lines.append(ml)
            used_sectors.update(members)

    # 2) 未被纳入产业链、但有信号的单 sector
    for sector, info in resolution.sector_to_info.items():
        if sector in used_sectors:
            continue
        n_stocks = resonance.get(sector, 0.0)
        if n_stocks <= 0 and not info.em_rank and not info.xgb_description:
            continue
        ml = _score_main_line(
            name=sector,
            is_chain=False,
            constituents=[sector],
            resolution=resolution,
            cells=cells,
            resonance=resonance,
        )
        if ml.confidence > 0:
            main_lines.append(ml)

    return main_lines


def _score_main_line(
    *,
    name: str,
    is_chain: bool,
    constituents: list[str],
    resolution: SectorResolution,
    cells: dict[str, TierCell],
    resonance: dict[str, float],
) -> MainLine:
    # biying_signal：涨停股数（去重）/ 6 截断
    stock_codes: set[str] = set()
    for sector in constituents:
        info = resolution.sector_to_info.get(sector)
        if not info:
            continue
        for code in info.stocks:
            if code in cells:
                stock_codes.add(code)
    biying_signal = min(1.0, len(stock_codes) / 6.0)
    max_lbc = max((cells[code].lbc for code in stock_codes if code in cells), default=0)

    # em_signal：取链内最优 rank（越小越好），有 hot 加成
    best_rank: int | None = None
    em_zt_total = 0
    has_em_hot = False
    for sector in constituents:
        info = resolution.sector_to_info.get(sector)
        if not info:
            continue
        if info.em_rank and (best_rank is None or info.em_rank < best_rank):
            best_rank = info.em_rank
        em_zt_total += info.em_zt_count
        if info.em_is_hot:
            has_em_hot = True
    if best_rank and best_rank <= 15:
        em_signal = (1.0 - best_rank / 15.0) * (1.3 if has_em_hot else 1.0)
    else:
        em_signal = 0.05 * has_em_hot   # 兜底
    em_signal = min(1.0, em_signal)

    # xgb_signal：事件数 + 描述存在
    total_events = 0
    has_xgb_desc = False
    for sector in constituents:
        info = resolution.sector_to_info.get(sector)
        if not info:
            continue
        total_events += info.event_count
        if info.xgb_description:
            has_xgb_desc = True
    xgb_signal = min(1.0, total_events / 5.0 + (0.2 if has_xgb_desc else 0.0))

    confidence = 0.40 * biying_signal + 0.35 * em_signal + 0.25 * xgb_signal
    # 给带空间板的主线一点额外权重，避免高位锚定题材被纯题材热度挤掉。
    if max_lbc >= 5:
        confidence += 0.12
    elif max_lbc >= 4:
        confidence += 0.08
    elif max_lbc >= 3:
        confidence += 0.04
    confidence = min(1.0, confidence)

    # 领头股：构成股按 (lbc, score, cje) 倒序取前 5
    leading = sorted(
        (cells[c] for c in stock_codes),
        key=lambda x: (x.lbc, x.score, x.cje_yi),
        reverse=True,
    )[:5]

    return MainLine(
        name=name,
        is_chain=is_chain,
        constituents=constituents,
        confidence=round(confidence, 3),
        biying_signal=biying_signal,
        em_signal=em_signal,
        xgb_signal=xgb_signal,
        leading_stocks=[c.code for c in leading],
        em_rank_min=best_rank,
        em_zt_total=em_zt_total,
        has_xgb_hot=has_xgb_desc,
        has_em_hot=has_em_hot,
    )


def _compute_promotion_rates(pools_cache: dict[str, Any], date: str) -> dict[str, float]:
    """
    晋级率（粗略口径）：
        1to2 = 今日 tier2 数 / 昨日 tier1 数
        2to3 = 今日 tier3 数 / 昨日 tier2 数
        3to4 = 今日 tier4+ 数 / 昨日 tier3 数

    "昨日"取 pools_cache 中 < date 的最近一天。
    """
    pools = pools_cache.get("pools") if isinstance(pools_cache, dict) else None
    if not isinstance(pools, dict):
        return {}
    ztgc = pools.get("ztgc") if isinstance(pools.get("ztgc"), dict) else {}
    if not isinstance(ztgc, dict):
        return {}
    dates = sorted(d for d in ztgc.keys() if d <= date)
    if len(dates) < 2:
        return {}
    today_rows = ztgc.get(dates[-1]) or []
    yest_rows = ztgc.get(dates[-2]) or []

    def _tier_count(rows: list[Any], tier: int) -> int:
        if tier == 4:
            return sum(1 for r in rows if isinstance(r, dict) and int(r.get("lbc") or 0) >= 4)
        return sum(1 for r in rows if isinstance(r, dict) and int(r.get("lbc") or 0) == tier)

    out: dict[str, float] = {}
    for cur_tier, prev_tier, key in ((2, 1, "1to2"), (3, 2, "2to3"), (4, 3, "3to4")):
        prev_n = _tier_count(yest_rows, prev_tier)
        cur_n = _tier_count(today_rows, cur_tier)
        out[key] = (cur_n / prev_n) if prev_n > 0 else 0.0
    return out
