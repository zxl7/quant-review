#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
rotation 模块（v2）：高低切换/风格偏好（marketData.rotation）

模板依赖：
- rotation.style / rotation.note
- rotation.highLevelRatio（5板+在涨停池占比）
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _to_int(v: Any, d: int = 0) -> int:
    try:
        return int(float(v))
    except Exception:
        return d


def _compute(ctx: Context) -> Dict[str, Any]:
    mi = (ctx.features.get("mood_inputs") or {}) if isinstance(ctx.features, dict) else {}
    si = (ctx.features.get("style_inputs") or {}) if isinstance(ctx.features, dict) else {}
    strengths = (ctx.features.get("style_strengths") or {}) if isinstance(ctx.features, dict) else {}
    # 若 strengths 不存在（fetch 未算），降级用 style_radar 的 calc（在 style_radar 模块里会补，但这里不依赖它）
    relay = _to_int(strengths.get("relay_strength", 0), 0)
    low_trial = _to_int(strengths.get("low_trial_strength", 0), 0)
    high_game = _to_int(strengths.get("high_game_strength", 0), 0)
    theme_focus = _to_int(strengths.get("theme_focus_strength", 0), 0)

    zt_count = int(mi.get("zt_count", 0) or 0)
    lb5p = int(mi.get("lb_5p", 0) or 0)
    high_ratio = (lb5p / zt_count * 100.0) if zt_count else float(si.get("high_level_ratio", 0) or 0)

    # 风格偏好：按强度最大项给标签（最小可用版）
    style = "均衡"
    if low_trial >= relay and low_trial >= high_game:
        style = "低位试错"
    elif relay >= high_game:
        style = "连板接力"
    else:
        style = "高位博弈"

    note = f"高位占比{high_ratio:.1f}%，题材集中{theme_focus}，接力{relay}/试错{low_trial}"

    return {"marketData.rotation": {"style": style, "note": note, "highLevelRatio": round(high_ratio, 1)}}


ROTATION_MODULE = Module(
    name="rotation",
    requires=["features.mood_inputs", "features.style_inputs"],
    provides=["marketData.rotation"],
    compute=_compute,
)

