#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
theme_panels 模块（v2）：遵循 pipeline.Module 协议

职责：
- 从 raw.pools（zt/dt/zb）+ raw.themes.code2themes（题材缓存）统计：
  1) marketData.themePanels：涨停/炸板/跌停 TOP3 + 强度表 + overlap
  2) marketData.sectors：板块题材排行（默认：近7天2连板题材聚合；兜底：当日涨停题材）

原则：
- 不做任何网络请求（完全离线可重算）
- 缓存缺失时兜底为“保持现有值”，避免页面模块空指针
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from daily_review.config import DEFAULT_CONFIG
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _as_list(v: Any) -> List[Dict[str, Any]]:
    return v if isinstance(v, list) else []


def _norm_code6(dm: Any) -> str:
    s = "".join([c for c in str(dm or "") if c.isdigit()])
    return s[-6:] if len(s) >= 6 else s


def _class_for_good_rate(rate: float, hi: float = 60, mid: float = 40) -> str:
    if rate >= hi:
        return "red-text"
    if rate >= mid:
        return "orange-text"
    return "green-text"


def _class_for_bad_rate(rate: float, hi: float = 30, mid: float = 15) -> str:
    if rate >= hi:
        return "red-text"
    if rate >= mid:
        return "orange-text"
    return "green-text"


def _clean_theme_name(theme: Any) -> str:
    """
    纯函数：题材清洗（与取数阶段口径尽量对齐）。

    规则：
    - 过滤：exclude_theme_names / noise_themes / noise_prefixes
    - 规范化：A股-热门概念- 前缀去掉
    """
    nm = str(theme or "").strip()
    if not nm:
        return ""
    if nm in DEFAULT_CONFIG.exclude_theme_names:
        return ""
    if nm in DEFAULT_CONFIG.noise_themes:
        return ""
    for pfx in DEFAULT_CONFIG.noise_prefixes:
        if nm.startswith(pfx):
            return ""
    if nm.startswith("A股-热门概念-"):
        nm = nm.replace("A股-热门概念-", "").strip()
    return nm


def _topk_theme_names(theme_counts: Dict[str, int], k: int = 5) -> List[str]:
    return [name for name, _ in sorted(theme_counts.items(), key=lambda x: -x[1])[:k]]


def _build_theme_top_list(theme_counts: Dict[str, int], theme_names: List[str], theme_stocks_map: Dict[str, List[str]], topn: int = 3) -> List[Dict[str, Any]]:
    pairs = [(k, int(theme_counts.get(k, 0) or 0)) for k in theme_names]
    pairs = [p for p in pairs if p[1] > 0]
    pairs.sort(key=lambda x: -x[1])
    out = []
    for name, cnt in pairs[:topn]:
        examples = "·".join((theme_stocks_map.get(name) or [])[:3])
        out.append({"name": name, "count": cnt, "examples": examples})
    return out


def _build_theme_strength_rows(zt_cnt: Dict[str, int], zb_cnt: Dict[str, int], dt_cnt: Dict[str, int], topn: int = 12) -> List[Dict[str, Any]]:
    names = set(zt_cnt.keys()) | set(zb_cnt.keys()) | set(dt_cnt.keys())
    rows = []
    for name in names:
        zt = int(zt_cnt.get(name, 0) or 0)
        zb = int(zb_cnt.get(name, 0) or 0)
        dt = int(dt_cnt.get(name, 0) or 0)
        net = zt * 1.0 - zb * 0.7 - dt * 1.2
        risk = zb * 0.7 + dt * 1.2
        rows.append(
            {
                "name": name,
                "zt": zt,
                "zb": zb,
                "dt": dt,
                "net": round(net, 1),
                "risk": round(risk, 1),
                "netClass": "red-text" if net >= 3 else ("orange-text" if net >= 1 else "green-text"),
                "riskClass": "red-text" if risk >= 3 else ("orange-text" if risk >= 1 else "green-text"),
            }
        )
    rows.sort(key=lambda r: (-r["net"], -r["zt"], r["risk"]))
    return rows[:topn]


def _safe_float(x: Any, default: float = 0.0) -> float:
    """
    纯函数：安全转 float。
    """
    try:
        if x is None or x == "":
            return float(default)
        if isinstance(x, str):
            x = x.replace("%", "").strip()
        return float(x)
    except Exception:
        return float(default)


def _build_sectors_from_zt_themes(
    *,
    zt: List[Dict[str, Any]],
    code2themes: Dict[str, List[str]],
    topn: int = 8,
) -> List[Dict[str, Any]]:
    """
    用「涨停股题材」直接梳理板块排行（更贴近你的需求）：
    - 每只涨停股可能有多个题材，为避免“广谱题材虚胖”，使用 1/k 加权计数（k=该股题材数）。
    - 输出字段尽量兼容旧前端：rank/name/count/detail/eval/eval_color，并额外补充 prob/weight 供你后续调参。

    返回示例（每条）：
    {
      "rank": 1,
      "name": "航天",
      "count": 10,          # 原始出现次数
      "weight": 6.5,        # 1/k 加权后的“有效次数”
      "prob": 18.1,         # weight / 涨停股数 * 100
      "detail": "xx·yy·zz",  # 代表股
      "eval": "爆发",
      "eval_color": "primary"
    }
    """

    # 1) 统计：原始次数 + 加权次数
    raw_cnt: Dict[str, int] = {}
    weight_cnt: Dict[str, float] = {}
    theme_stocks: Dict[str, List[str]] = {}

    def add_theme(theme: str, *, stock_name: str, w: float) -> None:
        """
        有副作用的小函数（只写入局部 dict），将同一只股票对某题材的贡献累加。
        """
        raw_cnt[theme] = int(raw_cnt.get(theme, 0) or 0) + 1
        weight_cnt[theme] = float(weight_cnt.get(theme, 0.0) or 0.0) + float(w)
        arr = theme_stocks.setdefault(theme, [])
        if stock_name and stock_name not in arr:
            arr.append(stock_name)

    for s in zt:
        code6 = _norm_code6(s.get("dm") or s.get("code"))
        name = str(s.get("mc") or s.get("name") or code6).strip()
        ths0 = code2themes.get(code6) or []
        ths = [_clean_theme_name(t) for t in ths0]
        ths = [t for t in ths if t]
        if not ths:
            continue
        w = 1.0 / float(len(ths)) if ths else 0.0
        for t in ths:
            add_theme(t, stock_name=name, w=w)

    total_zt = len([s for s in zt if isinstance(s, dict)])
    if total_zt <= 0 or not weight_cnt:
        return []

    # 2) 代表股：优先用“板数/封单/开板”等排序挑样本（更像交易视角）
    def pick_examples(theme_name: str) -> str:
        picks: List[Tuple[float, str]] = []
        for s in zt:
            code6 = _norm_code6(s.get("dm") or s.get("code"))
            mc = str(s.get("mc") or s.get("name") or "").strip()
            if not code6 or not mc:
                continue
            ths = code2themes.get(code6) or []
            if theme_name not in ths:
                continue
            lbc = _safe_float(s.get("lbc"), 1.0)
            zj = _safe_float(s.get("zj"), 0.0)
            zbc = _safe_float(s.get("zbc"), 0.0)
            score = lbc * 100 + (zj / 1e8) * 10 - zbc * 2
            picks.append((score, mc))
        picks.sort(reverse=True)
        if picks:
            return "·".join([mc for _, mc in picks[:3]])
        return "·".join((theme_stocks.get(theme_name) or [])[:3])

    # 3) 评分/分档：以“加权出现概率”为核心（直观、与你的描述一致）
    def eval_word_and_color(*, prob: float, count: int) -> Tuple[str, str]:
        """
        纯函数：根据题材出现概率（基于涨停池）给出交易语境分档。
        """
        if prob >= 20.0 and count >= 8:
            return "最强", "red-text"
        if prob >= 12.0 and count >= 5:
            return "爆发", "primary"
        if prob >= 6.0 and count >= 3:
            return "活跃", "success"
        return "轮动", "text-muted"

    items = []
    for theme, wcnt in weight_cnt.items():
        cnt = int(raw_cnt.get(theme, 0) or 0)
        prob = (float(wcnt) / float(total_zt)) * 100.0 if total_zt else 0.0
        items.append((float(wcnt), float(prob), cnt, theme))
    # 排序：优先加权次数，其次概率，其次原始次数
    items.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)

    out: List[Dict[str, Any]] = []
    for wcnt, prob, cnt, theme in items[:topn]:
        eval_word, eval_color = eval_word_and_color(prob=prob, count=cnt)
        out.append(
            {
                "rank": len(out) + 1,
                "name": theme,
                "count": cnt,
                "weight": round(float(wcnt), 2),
                "prob": round(float(prob), 1),  # 百分比（0~100）
                "detail": pick_examples(theme),
                "eval": eval_word,
                "eval_color": eval_color,
                # 兼容字段：保留 score/net/risk（即使前端不用也不影响）
                "net": round(float(wcnt), 2),
                "risk": 0.0,
                "score": round(float(prob), 2),
            }
        )
    return out


def _build_sectors_from_2boards_7d(
    *,
    zt_by_day: Dict[str, List[Dict[str, Any]]],
    code2themes: Dict[str, List[str]],
    bonus: float = 1.0,
    topn: int = 8,
) -> List[Dict[str, Any]]:
    """
    用「近7天所有出现过的 2连板（lbc=2）股票」做去重汇总，并按题材聚合。

    规则（贴合你的需求）：
    - 先在近7天涨停池里筛 lbc==2 的股票，按 code6 去重
    - 按题材聚合：同题材出现的 2连板股票越多，越靠前
    - 权重：普通=1，2连板=1+bonus（你说“比普通涨停+1”，这里 bonus=1 => 2.0）
    - 为避免“多题材虚胖”：对每只股票按 1/k 分摊到其 k 个题材上

    输出字段兼容旧前端：rank/name/count/detail/eval/eval_color；
    额外字段：weight/prob/score/net/risk（便于你后续调参/对比）。
    """

    if not isinstance(zt_by_day, dict) or not zt_by_day:
        return []

    # 1) 去重汇总 2连板股票（近7天）
    uniq: Dict[str, Dict[str, Any]] = {}
    days = sorted([d for d in zt_by_day.keys() if isinstance(d, str)])[-7:]
    for d in days:
        rows = zt_by_day.get(d) or []
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict):
                continue
            if int(r.get("lbc", 0) or 0) != 2:
                continue
            c6 = _norm_code6(r.get("dm") or r.get("code"))
            if not c6:
                continue
            name = str(r.get("mc") or r.get("name") or c6).strip()
            if c6 not in uniq:
                uniq[c6] = {"code6": c6, "name": name, "first_date": d, "last_date": d}
            else:
                uniq[c6]["last_date"] = d

    if not uniq:
        return []

    # 2) 题材聚合（加权+分摊）
    base = 1.0
    per_stock_total = base + float(bonus)

    raw_cnt: Dict[str, int] = {}
    weight_cnt: Dict[str, float] = {}
    theme_stocks: Dict[str, List[str]] = {}

    def add_theme(theme: str, *, stock_name: str, w: float) -> None:
        """
        有副作用的小函数（只写入局部 dict），将同一只股票对某题材的贡献累加。
        """
        raw_cnt[theme] = int(raw_cnt.get(theme, 0) or 0) + 1
        weight_cnt[theme] = float(weight_cnt.get(theme, 0.0) or 0.0) + float(w)
        arr = theme_stocks.setdefault(theme, [])
        if stock_name and stock_name not in arr:
            arr.append(stock_name)

    for c6, info in uniq.items():
        ths0 = code2themes.get(c6) or []
        ths = [_clean_theme_name(t) for t in ths0]
        ths = [t for t in ths if t]
        if not ths:
            continue
        w = per_stock_total / float(len(ths)) if ths else 0.0
        for t in ths:
            add_theme(t, stock_name=str(info.get("name") or c6), w=w)

    total_uniq = len(uniq)
    if total_uniq <= 0 or not weight_cnt:
        return []

    def eval_word_and_color(*, prob: float, count: int) -> Tuple[str, str]:
        """
        纯函数：根据题材覆盖率（在“近7天2连板去重集合”中的占比）给出分档。
        """
        if prob >= 20.0 and count >= 4:
            return "最强", "red-text"
        if prob >= 12.0 and count >= 3:
            return "爆发", "primary"
        if prob >= 6.0 and count >= 2:
            return "活跃", "success"
        return "轮动", "text-muted"

    items: List[Tuple[float, float, int, str]] = []
    for theme, wcnt in weight_cnt.items():
        cnt = int(raw_cnt.get(theme, 0) or 0)
        prob = (cnt / float(total_uniq)) * 100.0 if total_uniq else 0.0
        items.append((float(wcnt), float(prob), cnt, str(theme)))
    items.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)

    out: List[Dict[str, Any]] = []
    for wcnt, prob, cnt, theme in items[:topn]:
        eval_word, eval_color = eval_word_and_color(prob=prob, count=cnt)
        out.append(
            {
                "rank": len(out) + 1,
                "name": theme,
                # 兼容旧前端：count 表示该题材命中多少只“2连板（去重）”股票
                "count": cnt,
                "detail": "·".join((theme_stocks.get(theme) or [])[:5]),
                "eval": eval_word,
                "eval_color": eval_color,
                # 额外字段：调参/对比用
                "weight": round(float(wcnt), 2),
                "prob": round(float(prob), 1),
                "score": round(float(wcnt), 2),
                "net": round(float(wcnt), 2),
                "risk": 0.0,
            }
        )
    return out


def _compute(ctx: Context) -> Dict[str, Any]:
    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
    zt = _as_list(pools.get("ztgc"))
    zb = _as_list(pools.get("zbgc"))
    dt = _as_list(pools.get("dtgc"))
    zt_by_day = (pools.get("ztgc_by_day") or {}) if isinstance(pools, dict) else {}

    themes = (ctx.raw.get("themes") or {}) if isinstance(ctx.raw, dict) else {}
    code2themes = (themes.get("code2themes") or {}) if isinstance(themes, dict) else {}

    if not (zt or zb or dt) or not isinstance(code2themes, dict):
        # 兜底：保持现有值（防止旧缓存/缺失 raw 导致页面空）
        patch: Dict[str, Any] = {}
        if "themePanels" in ctx.market_data:
            patch["marketData.themePanels"] = ctx.market_data.get("themePanels") or {}
        if "sectors" in ctx.market_data:
            patch["marketData.sectors"] = ctx.market_data.get("sectors") or []
        return patch

    theme_count: Dict[str, int] = {}
    zb_theme_count: Dict[str, int] = {}
    dt_theme_count: Dict[str, int] = {}
    theme_stocks: Dict[str, List[str]] = {}
    zb_theme_stocks: Dict[str, List[str]] = {}
    dt_theme_stocks: Dict[str, List[str]] = {}

    def add_stock(map_cnt: Dict[str, int], map_stocks: Dict[str, List[str]], theme: str, stock_name: str) -> None:
        map_cnt[theme] = int(map_cnt.get(theme, 0) or 0) + 1
        arr = map_stocks.setdefault(theme, [])
        if stock_name and stock_name not in arr:
            arr.append(stock_name)

    # 统计涨停题材
    for s in zt:
        code6 = _norm_code6(s.get("dm") or s.get("code"))
        name = str(s.get("mc") or s.get("name") or code6)
        for t0 in (code2themes.get(code6) or []):
            t = _clean_theme_name(t0)
            if not t:
                continue
            add_stock(theme_count, theme_stocks, t, name)

    # 统计炸板题材
    for s in zb:
        code6 = _norm_code6(s.get("dm") or s.get("code"))
        name = str(s.get("mc") or s.get("name") or code6)
        for t0 in (code2themes.get(code6) or []):
            t = _clean_theme_name(t0)
            if not t:
                continue
            add_stock(zb_theme_count, zb_theme_stocks, t, name)

    # 统计跌停题材
    for s in dt:
        code6 = _norm_code6(s.get("dm") or s.get("code"))
        name = str(s.get("mc") or s.get("name") or code6)
        for t0 in (code2themes.get(code6) or []):
            t = _clean_theme_name(t0)
            if not t:
                continue
            add_stock(dt_theme_count, dt_theme_stocks, t, name)

    zt_top_names = _topk_theme_names(theme_count, k=8)
    zb_top_names = _topk_theme_names(zb_theme_count, k=8)
    dt_top_names = _topk_theme_names(dt_theme_count, k=8)

    zt_top3 = _build_theme_top_list(theme_count, zt_top_names, theme_stocks, topn=3)
    zb_top3 = _build_theme_top_list(zb_theme_count, zb_top_names, zb_theme_stocks, topn=3)
    dt_top3 = _build_theme_top_list(dt_theme_count, dt_top_names, dt_theme_stocks, topn=3)

    overlap = list(set(_topk_theme_names(theme_count, 5)) & set(_topk_theme_names(zb_theme_count, 5)))
    overlap_score = (len(overlap) / 5 * 100.0) if 5 else 0.0
    theme_strength_rows = _build_theme_strength_rows(theme_count, zb_theme_count, dt_theme_count, topn=12)

    theme_panels = {
        "ztTop": zt_top3,
        "zbTop": zb_top3,
        "dtTop": dt_top3,
        "strengthRows": theme_strength_rows,
        "overlap": {
            "themes": overlap[:5],
            "score": f"{overlap_score:.0f}%",
            "note": "涨停主线与炸板主杀题材的重叠度（越高越提示主线在分歧/退潮）",
        },
    }

    # 板块题材（sectors）：改为“只用涨停股题材直接梳理”
    # - 优先：近7天 2连板（lbc=2）去重汇总 → 按题材聚合（2连权重=普通+1）
    # - 兜底：当日涨停题材（防止历史池缺失/缓存较少时页面无数据）
    sectors = _build_sectors_from_2boards_7d(zt_by_day=zt_by_day, code2themes=code2themes, bonus=1.0, topn=8)
    if not sectors:
        sectors = _build_sectors_from_zt_themes(zt=zt, code2themes=code2themes, topn=8)

    return {
        "marketData.themePanels": theme_panels,
        "marketData.sectors": sectors,
    }


THEME_PANELS_MODULE = Module(
    name="theme_panels",
    requires=[
        "raw.pools.ztgc",
        "raw.pools.zbgc",
        "raw.pools.dtgc",
        "raw.pools.ztgc_by_day",
        "raw.themes.code2themes",
    ],
    provides=["marketData.themePanels", "marketData.sectors"],
    compute=_compute,
)
