#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
情绪模块（v1 registry 兼容）：基于 features.mood_inputs 重建 mood/moodStage/moodCards
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.mood import rebuild_mood


def rebuild_mood_panel(market_data: Dict[str, Any]) -> Dict[str, Any]:
    features = market_data.get("features") or {}
    inputs = dict(features.get("mood_inputs") or {})
    # 补齐“赚钱效应”口径（更贴近你主观体感：赚钱生态好/坏）
    # 兼容旧缓存：mood_inputs 里可能还没有 effect_verdict_type
    if "effect_verdict_type" not in inputs:
        inputs["effect_verdict_type"] = (market_data.get("effect") or {}).get("verdictType", "")
    patch = rebuild_mood(inputs)
    return patch
