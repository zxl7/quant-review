#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""tide 模块：生成 marketData.tideSignal。"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.tide import build_tide_signal
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    cache = (ctx.raw.get("theme_trend_cache") or {}) if isinstance(ctx.raw, dict) else {}
    market_data = ctx.market_data if isinstance(ctx.market_data, dict) else {}
    signal = build_tide_signal(market_data=market_data, theme_trend_cache=cache)
    return {"marketData.tideSignal": signal}


TIDE_MODULE = Module(
    name="tide_signal",
    requires=[
        "raw.theme_trend_cache",
        "marketData.prev",
        "marketData.panorama",
        "marketData.volume",
        "marketData.sentiment",
        "marketData.themeTrend",
    ],
    provides=["marketData.tideSignal"],
    compute=_compute,
)

