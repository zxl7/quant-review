#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
theme_trend 模块（v2）：主线题材近5日持续性（marketData.themeTrend）

数据来源：
- raw.theme_trend_cache（来自 cache/theme_trend_cache.json）

说明：
- 不做网络请求
- 缓存由 cli --fetch 维护（历史日累积 + 当日更新）
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except Exception:
        return default


def _compute(ctx: Context) -> Dict[str, Any]:
    cache = (ctx.raw.get("theme_trend_cache") or {}) if isinstance(ctx.raw, dict) else {}
    by_day = (cache.get("by_day") or {}) if isinstance(cache, dict) else {}
    if not isinstance(by_day, dict) or not by_day:
        cur = ctx.market_data.get("themeTrend") or {"dates": [], "series": [], "palette": []}
        return {"marketData.themeTrend": cur}

    report_day = str((ctx.meta.get("date") if isinstance(ctx.meta, dict) else "") or ctx.market_data.get("date") or "")
    days_all = sorted([d for d in by_day.keys() if isinstance(d, str)])
    if report_day:
        days_all = [d for d in days_all if d <= report_day]
    days = days_all[-5:]
    if len(days) < 2:
        cur = ctx.market_data.get("themeTrend") or {"dates": [], "series": [], "palette": []}
        return {"marketData.themeTrend": cur}

    # 选 TOP3 题材：以最新一天的 count 排序
    last_map = by_day.get(days[-1]) or {}
    last_map = last_map if isinstance(last_map, dict) else {}
    ranked = sorted([(k, _to_int(v, 0)) for k, v in last_map.items() if str(k).strip()], key=lambda x: -x[1])
    top_names = [k for k, _ in ranked[:3]]

    series = []
    for name in top_names:
        vals = []
        for d in days:
            m = by_day.get(d) or {}
            m = m if isinstance(m, dict) else {}
            vals.append(_to_int(m.get(name), 0))
        series.append({"name": name, "values": vals})

    palette = (
        (ctx.market_data.get("features") or {}).get("chart_palette")
        or ["#ef4444", "#f97316", "#f59e0b", "#fb7185"]
    )

    return {
        "marketData.themeTrend": {
            "dates": [d[5:] for d in days],
            "series": series,
            "palette": palette,
        }
    }


THEME_TREND_MODULE = Module(
    name="theme_trend",
    requires=["raw.theme_trend_cache"],
    provides=["marketData.themeTrend"],
    compute=_compute,
)

