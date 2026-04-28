#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
resonance_v2 模块：⑩满仓三条件共振系统
输出到 marketData.v2.resonance
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.resonance_v2 import check_resonance
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    md = ctx.market_data or {}
    v2 = md.get("v2") if isinstance(md.get("v2"), dict) else {}
    out = check_resonance(md)
    return {"marketData.v2": {**v2, "resonance": out}}


RESONANCE_V2_MODULE = Module(
    name="resonance_v2",
    requires=["marketData.v2", "marketData.volume", "marketData.themePanels", "marketData.styleRadar", "features.mood_inputs"],
    provides=["marketData.v2"],
    compute=_compute,
)

