#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
psychology_v2 模块：模块⑪ 人性博弈层 / 反身性分析
输出到 marketData.v2.psychology
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.psychology_v2 import build_psychology_layer
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    md = ctx.market_data or {}
    v2 = md.get("v2") if isinstance(md.get("v2"), dict) else {}
    out = build_psychology_layer(md)
    return {"marketData.v2": {**v2, "psychology": out}}


PSYCHOLOGY_V2_MODULE = Module(
    name="psychology_v2",
    requires=["marketData.v2", "features.mood_inputs"],
    provides=["marketData.v2"],
    compute=_compute,
)

