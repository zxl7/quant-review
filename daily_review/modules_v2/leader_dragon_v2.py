#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模块②③（v2 规格书）：连板高度&龙头诊断 + 龙头三要素
输出到 marketData.v2.height_module / marketData.v2.dragon
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.leader_dragon_v2 import build_dragon_three_elements, build_height_module
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    md = ctx.market_data or {}
    v2 = md.get("v2") if isinstance(md.get("v2"), dict) else {}
    height_module = build_height_module(md)
    dragon = build_dragon_three_elements(md, height_module)
    return {"marketData.v2": {**v2, "height_module": height_module, "dragon": dragon}}


LEADER_DRAGON_V2_MODULE = Module(
    name="leader_dragon_v2",
    requires=["raw.pools.ztgc", "marketData.ztgc", "marketData.v2", "features.mood_inputs", "marketData.themePanels"],
    provides=["marketData.v2"],
    compute=_compute,
)

