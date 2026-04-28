#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
rightside_v2 模块：⑦右侧交易确认框架
输出到 marketData.v2.rightside
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.rightside_v2 import build_rightside_confirmation
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    md = ctx.market_data or {}
    v2 = md.get("v2") if isinstance(md.get("v2"), dict) else {}
    out = build_rightside_confirmation(md)
    return {"marketData.v2": {**v2, "rightside": out}}


RIGHTSIDE_V2_MODULE = Module(
    name="rightside_v2",
    requires=["marketData.v2", "marketData.volume", "marketData.themePanels", "marketData.styleRadar", "features.mood_inputs"],
    provides=["marketData.v2"],
    compute=_compute,
)

