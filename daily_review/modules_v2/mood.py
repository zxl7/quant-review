#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
mood 模块（v2）：遵循 pipeline.Module 协议
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.mood import rebuild_mood
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    inputs = (ctx.features.get("mood_inputs") or {})
    patch = rebuild_mood(inputs)
    return {
        "marketData.mood": patch["mood"],
        "marketData.moodStage": patch["moodStage"],
        "marketData.moodCards": patch["moodCards"],
    }


MOOD_MODULE = Module(
    name="mood",
    requires=["features.mood_inputs"],
    provides=["marketData.mood", "marketData.moodStage", "marketData.moodCards"],
    compute=_compute,
)

