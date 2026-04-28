#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
rebound_v2 模块：模块⑨ 反弹三阶段
输出到 marketData.v2.rebound
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.rebound_v2 import identify_rebound_phase
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    md = ctx.market_data or {}
    v2 = md.get("v2") if isinstance(md.get("v2"), dict) else {}
    _, out = identify_rebound_phase(md)
    return {"marketData.v2": {**v2, "rebound": out}}


REBOUND_V2_MODULE = Module(
    name="rebound_v2",
    requires=["marketData.v2", "features.mood_inputs", "marketData.volume", "marketData.themePanels"],
    provides=["marketData.v2"],
    compute=_compute,
)

