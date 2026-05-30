#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""core_tide 模块：生成 marketData.coreTideSignal。"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.core_tide import build_core_tide_signal
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    market_data = ctx.market_data if isinstance(ctx.market_data, dict) else {}
    tide_signal = market_data.get("tideSignal") if isinstance(market_data.get("tideSignal"), dict) else {}
    # 消息面缓存由编排层注入；缺失时核心算法按中性消息分处理，不在模块内读文件。
    catalyst_data = (ctx.raw.get("catalyst_cache") or {}) if isinstance(ctx.raw, dict) else {}
    signal = build_core_tide_signal(
        market_data=market_data,
        tide_signal=tide_signal,
        catalyst_data=catalyst_data,
    )
    return {"marketData.coreTideSignal": signal}


CORE_TIDE_MODULE = Module(
    name="core_tide_signal",
    requires=[
        "marketData.tideSignal",
        "marketData.indices",
        "marketData.sentiment",
        "marketData.panorama",
        "marketData.volume",
    ],
    provides=["marketData.coreTideSignal"],
    compute=_compute,
)
