#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
style_radar 模块（v2）：遵循 pipeline.Module 协议
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.modules.style_radar import rebuild_style_radar
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    # 复用现有模块实现：输入 market_data，输出 {"styleRadar": {...}}
    patch = rebuild_style_radar(ctx.market_data)
    # 统一为点路径 patch（也可直接 "styleRadar"）
    return {"marketData.styleRadar": patch["styleRadar"]}


STYLE_RADAR_MODULE = Module(
    name="style_radar",
    requires=["features.style_inputs", "features.chart_palette"],
    provides=["marketData.styleRadar"],
    compute=_compute,
)

