#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
features.stock_ranker：六维评分（百分制） + BUY/WATCH 行动分级

职责（纯计算，无 I/O）：
- 在 M3 SectorResolution + M4 LadderResult 的基础上，对主线成员股做精选评分
- 每股得分 0-100，由 6 维 + 3 项加分组成
- 按主线分组，输出 BUY (Top3) / WATCH (3-5) 行动建议 + summary 一句话

非职责：
- 不发起网络 I/O
- 不决定主线（依赖 M4 LadderResult.main_lines）
- 不做 UI 编排（输出 dataclass，由调用方序列化）

评分体系（百分制，spec 六维权重重新分配）：
    主线贴合度 (0-20)   - 在主线 constituents 内 confidence × lbc 综合
    梯队位置   (0-20)   - 先锋龙(2板+评分) / 容量核心(首板+大量能) / 空间板
    量能量级   (0-15)   - 成交额 100/30/10亿 三档（流动性门槛）
    封板质量   (0-15)   - 用 market_data.leaders[].score 代理 seal_score
    板块强度   (0-10)   - 同主线板块涨停数共振
    换手健康度 (0-10)   - 3-15% 适中, 15-30% 分歧, 否则极端
    加分      (0-10)   - 先锋龙(+5) / 独立逻辑(+2) / 20cm(+3)
    -----------------
    合计 0-100
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from daily_review.features.ladder_builder import LadderResult, MainLine, TierCell


Action = Literal["buy", "watch", "skip"]


@dataclass
class StockScore:
    code: str
    name: str
    action: Action
    score: int                              # 六维 + 加分总分 0-33
    main_line: str                          # 所属主线名
    primary_sector: str                     # confidence 最高的板块
    primary_confidence: float
    # 评分明细（spec 六维）
    breakdown: dict[str, int] = field(default_factory=dict)
    bonus: int = 0
    bonus_reasons: list[str] = field(default_factory=list)
    # 关键因子（用户可直接看懂为何买入/观察）
    reasons: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    # 原始数据（透传给 UI）
    lbc: int = 0
    cje_yi: float = 0.0
    seal_fund_yi: float = 0.0
    turnover: float = 0.0
    leaders_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "action": self.action,
            "score": self.score,
            "main_line": self.main_line,
            "primary_sector": self.primary_sector,
            "primary_confidence": round(self.primary_confidence, 3),
            "breakdown": self.breakdown,
            "bonus": self.bonus,
            "bonus_reasons": self.bonus_reasons,
            "reasons": self.reasons,
            "cautions": self.cautions,
            "lbc": self.lbc,
            "cje_yi": round(self.cje_yi, 2),
            "seal_fund_yi": round(self.seal_fund_yi, 2),
            "turnover": round(self.turnover, 2),
            "leaders_score": round(self.leaders_score, 2),
        }


@dataclass
class MainLinePicks:
    main_line: str
    confidence: float
    is_chain: bool
    constituents: list[str] = field(default_factory=list)
    buy: list[StockScore] = field(default_factory=list)
    watch: list[StockScore] = field(default_factory=list)
    summary: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "main_line": self.main_line,
            "confidence": round(self.confidence, 3),
            "is_chain": self.is_chain,
            "constituents": self.constituents,
            "buy": [s.to_dict() for s in self.buy],
            "watch": [s.to_dict() for s in self.watch],
            "summary": self.summary,
            "diagnostics": self.diagnostics,
        }


@dataclass
class PicksAdvisorResult:
    date: str
    main_line_picks: list[MainLinePicks] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "main_line_picks": [m.to_dict() for m in self.main_line_picks],
            "diagnostics": self.diagnostics,
        }


# ---------------------------------------------------------------------------
# 核心评分（六维 + 加分）
# ---------------------------------------------------------------------------


def _score_breakdown(
    cell: TierCell,
    *,
    main_line: MainLine,
    sector_zt_count: int,
    leaders_score: float,
    in_ml_top_sector: str,
    in_ml_top_conf: float,
) -> tuple[dict[str, int], int, list[str]]:
    """
    百分制评分（六维 + 加分）。

    in_ml_top_sector / in_ml_top_conf：该股在主线 constituents 内最高 confidence 的板块。
    若为空，表示该股不在主线产业链内（理论上不会被调用，因为前置过滤已剔除）。

    返回：(六维明细 dict 各分 int, 加分 int, 加分原因列表)
    """
    bd: dict[str, int] = {}

    # 1. 主线贴合度 (0-20) —— 核心维度，权重最高
    if in_ml_top_conf >= 0.6 and cell.lbc >= 2:
        bd["贴合度"] = 20   # 主线核心 + 连板
    elif in_ml_top_conf >= 0.6:
        bd["贴合度"] = 16   # 主线核心
    elif in_ml_top_conf >= 0.4 and cell.lbc >= 2:
        bd["贴合度"] = 14   # 主线相关 + 连板
    elif in_ml_top_conf >= 0.4:
        bd["贴合度"] = 10   # 主线相关
    elif in_ml_top_conf > 0:
        bd["贴合度"] = 6    # 主线边缘
    else:
        bd["贴合度"] = 0    # 非主线（理论不会触发）

    # 2. 梯队位置 (0-20)
    if cell.lbc == 2 and leaders_score >= 60:
        bd["梯队"] = 20     # 先锋龙候选
    elif cell.lbc >= 3:
        bd["梯队"] = 17     # 空间板（高位但稀缺）
    elif cell.lbc == 2:
        bd["梯队"] = 14     # 2板未达先锋龙阈值
    elif cell.lbc == 1 and cell.cje_yi >= 100:
        bd["梯队"] = 16     # 容量核心首板
    elif cell.lbc == 1 and cell.cje_yi >= 30:
        bd["梯队"] = 10
    else:
        bd["梯队"] = 6      # 普通首板

    # 3. 量能量级 (0-15)
    if cell.cje_yi >= 100:
        bd["量能"] = 15
    elif cell.cje_yi >= 50:
        bd["量能"] = 12
    elif cell.cje_yi >= 30:
        bd["量能"] = 9
    elif cell.cje_yi >= 10:
        bd["量能"] = 5
    elif cell.cje_yi >= 3:
        bd["量能"] = 2
    else:
        bd["量能"] = 0

    # 4. 封板质量 (0-15) —— 用 leaders.score 代理 seal_score
    if leaders_score >= 90:
        bd["封板"] = 15
    elif leaders_score >= 75:
        bd["封板"] = 11
    elif leaders_score >= 60:
        bd["封板"] = 8
    elif leaders_score >= 40:
        bd["封板"] = 4
    elif cell.seal_fund_yi >= 3:
        bd["封板"] = 6      # leaders 没分但封单大，单独认可
    else:
        bd["封板"] = 0

    # 5. 板块强度 (0-10) —— 同主线板块涨停数共振
    if sector_zt_count >= 8:
        bd["板块"] = 10
    elif sector_zt_count >= 5:
        bd["板块"] = 7
    elif sector_zt_count >= 3:
        bd["板块"] = 4
    else:
        bd["板块"] = 1

    # 6. 换手健康度 (0-10)
    if 3 <= cell.turnover <= 15:
        bd["换手"] = 10
    elif 15 < cell.turnover <= 30:
        bd["换手"] = 6
    elif 0 < cell.turnover < 3:
        bd["换手"] = 3      # 一字板/无参与
    elif cell.turnover > 30:
        bd["换手"] = 2      # 分歧过大
    else:
        bd["换手"] = 0

    # 加分（0-10）
    bonus = 0
    bonus_reasons: list[str] = []
    # 先锋龙加成（2板 + leaders.score >= 60 + 主线核心）
    if in_ml_top_conf > 0 and cell.lbc >= 2 and leaders_score >= 60:
        bonus += 5
        bonus_reasons.append("先锋龙")
    # 独立逻辑（同板块涨停 >=5 但不在主线核心）
    if in_ml_top_conf < 0.6 and sector_zt_count >= 5:
        bonus += 2
        bonus_reasons.append("独立逻辑")
    # 20cm 溢价（创业板/科创板）
    if cell.code.startswith(("300", "688")):
        bonus += 3
        bonus_reasons.append("20cm")

    return bd, bonus, bonus_reasons


def _gen_reasons(
    cell: TierCell,
    bd: dict[str, int],
    main_line: MainLine,
    in_ml_top_sector: str,
    in_ml_top_conf: float,
) -> list[str]:
    """根据评分明细生成"买入/观察"理由短语（前端展示）"""
    out: list[str] = []
    # 主线归属（用 in_ml_top_sector，即该股在主线 constituents 内最强板块）
    if in_ml_top_sector:
        if in_ml_top_conf >= 0.6:
            out.append(f"{in_ml_top_sector}核心({in_ml_top_conf:.2f})")
        else:
            out.append(f"{in_ml_top_sector}({in_ml_top_conf:.2f})")
    # 梯队
    if cell.lbc >= 3:
        out.append(f"{cell.lbc}板高位")
    elif cell.lbc == 2:
        out.append(f"2板{'先锋' if bd.get('梯队', 0) >= 20 else '候选'}")
    elif cell.lbc == 1 and cell.cje_yi >= 100:
        out.append(f"容量核心({cell.cje_yi:.0f}亿)")
    # 量能（首板时已在梯队提到，避免重复）
    if cell.lbc >= 2 and cell.cje_yi >= 30:
        out.append(f"{cell.cje_yi:.0f}亿量能")
    elif cell.lbc == 1 and 30 <= cell.cje_yi < 100:
        out.append(f"{cell.cje_yi:.0f}亿成交")
    # 封单
    if cell.seal_fund_yi >= 3:
        out.append(f"封单{cell.seal_fund_yi:.1f}亿")
    # 板块共振
    if bd.get("板块", 0) >= 10:
        out.append("板块TOP1共振")
    elif bd.get("板块", 0) >= 7:
        out.append("板块强共振")
    # 综合分
    if bd.get("封板", 0) >= 15:
        out.append("封板满分")
    return out[:4]


def _gen_cautions(cell: TierCell, bd: dict[str, int]) -> list[str]:
    """生成警示因子（潜在风险）"""
    out: list[str] = []
    if cell.turnover > 30:
        out.append(f"换手{cell.turnover:.0f}%(分歧大)")
    elif cell.turnover < 3 and cell.lbc >= 2:
        out.append("一字板(无参与)")
    if cell.zbc >= 3:
        out.append(f"炸板{cell.zbc}次")
    if cell.lbc == 1 and cell.cje_yi < 5:
        out.append("小单首板,持续性弱")
    if bd.get("贴合度", 0) <= 6:
        out.append("主线归属弱")
    return out[:3]


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def build_picks_advisor(
    *,
    ladder: LadderResult,
    market_data: dict[str, Any] | None = None,
    top_k_lines: int = 3,
    buy_n: int = 3,
    watch_n: int = 5,
    min_main_line_conf: float = 0.40,
) -> PicksAdvisorResult:
    """
    输入：
        ladder:       M4 LadderResult
        market_data:  可选，用于获取 leaders[].score
        top_k_lines:  保留前 N 个主线
        buy_n:        每个主线 BUY 上限
        watch_n:      每个主线 WATCH 上限
        min_main_line_conf:  主线 confidence 阈值

    输出：PicksAdvisorResult
    """
    leaders_score_map = _build_leaders_score_map(market_data) if market_data else {}

    # 收集所有 TierCell（去重，按 code）
    all_cells: dict[str, TierCell] = {}
    for tier_cells in ladder.tiers.values():
        for cell in tier_cells:
            all_cells[cell.code] = cell

    # 同板块涨停数（用 resonance_map 的原始 count 反推；这里用 sector→cell 数）
    sector_zt_count: dict[str, int] = {}
    for cell in all_cells.values():
        for sec, _conf in cell.sectors:
            sector_zt_count[sec] = sector_zt_count.get(sec, 0) + 1

    main_line_picks: list[MainLinePicks] = []
    used_codes: set[str] = set()

    for ml in ladder.main_lines:
        if ml.confidence < min_main_line_conf:
            continue
        if len(main_line_picks) >= top_k_lines:
            break

        # 收集主线成员股（去重 + 未被前面更高 conf 主线占用）
        members: list[StockScore] = []
        for cell in all_cells.values():
            if cell.code in used_codes:
                continue
            # 找该股在主线 constituents 内最强的 sector（confidence 最高）
            in_ml_pairs = [(s, c) for s, c in cell.sectors if s in ml.constituents]
            if not in_ml_pairs:
                continue
            in_ml_top_sector, in_ml_top_conf = max(in_ml_pairs, key=lambda x: x[1])
            ls = leaders_score_map.get(cell.code, 0.0)
            best_sec_count = max(
                (sector_zt_count.get(sec, 0) for sec, _c in in_ml_pairs),
                default=0,
            )
            bd, bonus, bonus_reasons = _score_breakdown(
                cell,
                main_line=ml,
                sector_zt_count=best_sec_count,
                leaders_score=ls,
                in_ml_top_sector=in_ml_top_sector,
                in_ml_top_conf=in_ml_top_conf,
            )
            total = sum(bd.values()) + bonus
            members.append(
                StockScore(
                    code=cell.code,
                    name=cell.name,
                    action="skip",  # 先占位
                    score=total,
                    main_line=ml.name,
                    primary_sector=in_ml_top_sector,  # 关键：用主线内最强板块
                    primary_confidence=in_ml_top_conf,
                    breakdown=bd,
                    bonus=bonus,
                    bonus_reasons=bonus_reasons,
                    reasons=_gen_reasons(cell, bd, ml, in_ml_top_sector, in_ml_top_conf),
                    cautions=_gen_cautions(cell, bd),
                    lbc=cell.lbc,
                    cje_yi=cell.cje_yi,
                    seal_fund_yi=cell.seal_fund_yi,
                    turnover=cell.turnover,
                    leaders_score=ls,
                )
            )

        if not members:
            continue

        # 按 score 降序，平分时优先 lbc 高、cje 大
        members.sort(key=lambda s: (s.score, s.lbc, s.cje_yi), reverse=True)
        buy = members[:buy_n]
        watch = members[buy_n : buy_n + watch_n]

        # 行动标记
        for s in buy:
            s.action = "buy"
        for s in watch:
            s.action = "watch"

        # 占用 codes
        for s in buy + watch:
            used_codes.add(s.code)

        summary = _build_summary(ml, buy, watch)

        main_line_picks.append(
            MainLinePicks(
                main_line=ml.name,
                confidence=ml.confidence,
                is_chain=ml.is_chain,
                constituents=ml.constituents,
                buy=buy,
                watch=watch,
                summary=summary,
                diagnostics={
                    "member_count": len(members),
                    "avg_score": round(sum(s.score for s in members) / max(len(members), 1), 1),
                    "leaders_score_hits": sum(1 for s in members if s.leaders_score > 0),
                },
            )
        )

    diagnostics = {
        "main_lines_total": len(ladder.main_lines),
        "main_lines_picked": len(main_line_picks),
        "total_buy": sum(len(m.buy) for m in main_line_picks),
        "total_watch": sum(len(m.watch) for m in main_line_picks),
        "min_main_line_conf": min_main_line_conf,
    }

    return PicksAdvisorResult(
        date=ladder.date,
        main_line_picks=main_line_picks,
        diagnostics=diagnostics,
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _build_leaders_score_map(market_data: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    leaders = market_data.get("leaders") if isinstance(market_data, dict) else None
    if not isinstance(leaders, list):
        return out
    for it in leaders:
        if not isinstance(it, dict):
            continue
        code = str(it.get("code") or it.get("dm") or "")
        digits = "".join(c for c in code if c.isdigit())[-6:]
        if not digits:
            continue
        try:
            out[digits] = float(it.get("score") or 0.0)
        except Exception:
            pass
    return out


def _build_summary(ml: MainLine, buy: list[StockScore], watch: list[StockScore]) -> str:
    """
    生成主线的一句话总结，类似：
    "半导体主线（0.80），买入鹏鼎控股(2板先锋)、风华高科(容量核心)，
     观察通富微电·双星新材·三安光电（后排候补）"
    """
    if not buy:
        return f"{ml.name}主线({ml.confidence:.2f})暂无明确买入标的"
    buy_strs = []
    for s in buy[:3]:
        tag = s.reasons[0] if s.reasons else f"评分{s.score}"
        buy_strs.append(f"{s.name}({tag})")
    parts = [f"{ml.name}主线({ml.confidence:.2f})"]
    parts.append(f"买入 {' / '.join(buy_strs)}")
    if watch:
        watch_names = [s.name for s in watch[:4]]
        parts.append(f"观察 {' · '.join(watch_names)}")
    return "，".join(parts)
