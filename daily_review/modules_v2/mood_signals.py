#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
mood_signals 模块（v2）：输出实时盯盘触发器 + 赚钱效应 hm2Compare（后端口径统一）。
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.mood_signals import build_hm2_compare, build_mood_signals
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    md = ctx.market_data or {}
    return {
        "marketData.moodSignals": build_mood_signals(md),
        "marketData.hm2Compare": build_hm2_compare(md),
    }


MOOD_SIGNALS_MODULE = Module(
    name="mood_signals",
    requires=[
        "features.mood_inputs",
        "marketData.mood",
        "marketData.moodStage",
        "marketData.styleRadar",
        "marketData.themePanels",
    ],
    provides=["marketData.moodSignals", "marketData.hm2Compare"],
    compute=_compute,
)

