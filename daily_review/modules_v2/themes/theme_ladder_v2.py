#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
theme_ladder_v2 模块：模块④（板块梯队&主线判断）
输出到 marketData.v2.sector
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.theme_ladder_v2 import build_sector_ladders, judge_mainline
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    md = ctx.market_data or {}
    v2 = md.get("v2") if isinstance(md.get("v2"), dict) else {}

    theme_trend_cache = (ctx.raw.get("theme_trend_cache") or {}) if isinstance(ctx.raw, dict) else {}
    out = build_sector_ladders(md, theme_trend_cache=theme_trend_cache)
    sectors = out.get("sectors") if isinstance(out.get("sectors"), list) else []

    sent = v2.get("sentiment") if isinstance(v2.get("sentiment"), dict) else {}
    sentiment_score = float(sent.get("score") or 5.0)
    mainline = judge_mainline(sectors, sentiment_score)

    sector_pack = {
        "mainline": mainline,
        "sectors": sectors,
        "all_count": out.get("all_count"),
    }
    return {"marketData.v2": {**v2, "sector": sector_pack}}


THEME_LADDER_V2_MODULE = Module(
    name="theme_ladder_v2",
    requires=["raw.theme_trend_cache.by_day", "marketData.v2", "marketData.ztgc", "raw.pools.ztgc", "raw.themes.code2themes"],
    provides=["marketData.v2"],
    compute=_compute,
)

