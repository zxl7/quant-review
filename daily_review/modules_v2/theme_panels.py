#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
theme_panels 模块（v2）：遵循 pipeline.Module 协议

职责：
- 从 raw.pools（zt/dt/zb）+ raw.themes.code2themes（题材缓存）统计：
  1) marketData.themePanels：涨停/炸板/跌停 TOP3 + 强度表 + overlap
  2) marketData.sectors：板块强度 TOP5（复用主线题材计数）

原则：
- 不做任何网络请求（完全离线可重算）
- 缓存缺失时兜底为“保持现有值”，避免页面模块空指针
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

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


def _compute(ctx: Context) -> Dict[str, Any]:
    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
    zt = _as_list(pools.get("ztgc"))
    zb = _as_list(pools.get("zbgc"))
    dt = _as_list(pools.get("dtgc"))

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
        for t in (code2themes.get(code6) or []):
            if not t:
                continue
            add_stock(theme_count, theme_stocks, str(t), name)

    # 统计炸板题材
    for s in zb:
        code6 = _norm_code6(s.get("dm") or s.get("code"))
        name = str(s.get("mc") or s.get("name") or code6)
        for t in (code2themes.get(code6) or []):
            if not t:
                continue
            add_stock(zb_theme_count, zb_theme_stocks, str(t), name)

    # 统计跌停题材
    for s in dt:
        code6 = _norm_code6(s.get("dm") or s.get("code"))
        name = str(s.get("mc") or s.get("name") or code6)
        for t in (code2themes.get(code6) or []):
            if not t:
                continue
            add_stock(dt_theme_count, dt_theme_stocks, str(t), name)

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

    # 板块强度 TOP5（优化）：对齐 actionGuideV2 的“主线识别”口径
    # 你的反馈：热点解读这里的板块推测不如明日计划准确
    # -> 主要原因是“涨停数虚胖”（广谱题材/多标签映射会被放大）
    # -> 这里改为：优先按 strengthRows 的 score = net - risk*0.6 排序，再补 examples

    def to_num(v: Any, d: float = 0.0) -> float:
        try:
            if v is None:
                return d
            if isinstance(v, str):
                v = v.replace("%", "").strip()
            return float(v)
        except Exception:
            return d

    def pick_examples(theme_name: str) -> str:
        # 从当日涨停池抽样，逻辑与 build_action_guide_v2 保持一致（更准确）
        picks: List[Tuple[float, str]] = []
        for s in zt:
            code = str(s.get("dm") or s.get("code") or "")
            mc = str(s.get("mc") or s.get("name") or "")
            if not code or not mc:
                continue
            code6 = _norm_code6(code)
            ths = code2themes.get(code6) or []
            if theme_name not in ths:
                continue
            lbc = to_num(s.get("lbc"), 1)
            zj = to_num(s.get("zj"), 0)
            zbc = to_num(s.get("zbc"), 0)
            score = lbc * 100 + (zj / 1e8) * 10 - zbc * 2
            picks.append((score, mc))
        picks.sort(reverse=True)
        if picks:
            return "·".join([mc for _, mc in picks[:3]])
        # 兜底：用简单聚合的 stocks（可能略粗）
        return "·".join((theme_stocks.get(theme_name) or [])[:3])

    scored = []
    for r in theme_strength_rows[:12]:
        net = to_num(r.get("net"), 0)
        risk = to_num(r.get("risk"), 0)
        score = net - risk * 0.6
        scored.append((score, net, risk, r))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    def eval_word_and_color(score: float, net: float, risk: float) -> Tuple[str, str]:
        # 文案尽量贴近交易语境
        if net >= 4 and risk <= 2 and score >= 3:
            return "最强", "red-text"
        if score >= 2.0:
            return "爆发", "success"
        if score >= 0.8:
            return "活跃", "primary"
        if score >= 0.0:
            return "分歧", "warning"
        return "退潮", "text-muted"

    sectors = []
    seen = set()
    for _, net, risk, r in scored:
        name = str(r.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        zt_cnt = int(to_num(r.get("zt"), 0))
        eval_word, eval_color = eval_word_and_color(float(_), float(net), float(risk))
        sectors.append(
            {
                "rank": len(sectors) + 1,
                "name": name,
                "count": zt_cnt,
                "detail": pick_examples(name),
                "eval": eval_word,
                "eval_color": eval_color,
                # 额外输出给你后续调优/对比用（前端不用也不影响）
                "net": round(float(net), 1),
                "risk": round(float(risk), 1),
                "score": round(float(_), 2),
            }
        )
        if len(sectors) >= 5:
            break

    return {
        "marketData.themePanels": theme_panels,
        "marketData.sectors": sectors,
    }


THEME_PANELS_MODULE = Module(
    name="theme_panels",
    requires=["raw.pools.ztgc", "raw.pools.zbgc", "raw.pools.dtgc", "raw.themes.code2themes"],
    provides=["marketData.themePanels", "marketData.sectors"],
    compute=_compute,
)
