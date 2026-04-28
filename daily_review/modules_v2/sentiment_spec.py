#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
sentiment_spec 模块：按规格书输出 marketData.sentiment / dual_dimension / height_analysis，
并将结果回写到 marketData.mood / marketData.moodStage（兼容现有前端展示）。
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.sentiment_spec import (
    apply_compat_to_mood,
    build_dual_dimension,
    build_height_analysis,
    build_sentiment,
)
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    md = ctx.market_data or {}
    # 若 v2 情绪计分卡已产出，则不再覆盖（避免口径打架）
    if isinstance(md.get("v2"), dict) and isinstance((md.get("v2") or {}).get("sentiment"), dict):
        return {}
    sentiment = build_sentiment(md)
    dual = build_dual_dimension(md, sentiment)
    height = build_height_analysis(md)
    mood, mood_stage = apply_compat_to_mood(sentiment, dual)

    return {
        "marketData.sentiment": sentiment,
        "marketData.dual_dimension": dual,
        "marketData.height_analysis": height,
        # 兼容字段（覆盖旧输出）
        "marketData.mood": {**(md.get("mood") or {}), **mood},
        "marketData.moodStage": {**(md.get("moodStage") or {}), **mood_stage},
    }


SENTIMENT_SPEC_MODULE = Module(
    name="sentiment_spec",
    requires=[
        "features.mood_inputs",
        "marketData.heightTrend",
        "marketData.styleRadar",
        "marketData.themePanels",
        "raw.pools.ztgc",
    ],
    provides=[
        "marketData.sentiment",
        "marketData.dual_dimension",
        "marketData.height_analysis",
        "marketData.mood",
        "marketData.moodStage",
    ],
    compute=_compute,
)
