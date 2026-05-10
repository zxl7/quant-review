#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""zt_analysis 模块：明日计划涨停个股接力/观察池。"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.zt_analysis import build_zt_analysis
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    return {"marketData.ztAnalysis": build_zt_analysis(market_data=ctx.market_data)}


ZT_ANALYSIS_MODULE = Module(
    name="zt_analysis",
    requires=[
        "marketData.ztgc",
        "marketData.zt_code_themes",
        "marketData.themePanels",
        "marketData.plateRotateTop",
        "marketData.ladder",
        "marketData.moodStage",
        "marketData.volume",
        "marketData.fear",
        "features.mood_inputs",
    ],
    provides=["marketData.ztAnalysis"],
    compute=_compute,
)

