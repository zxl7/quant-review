#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
position_v2 模块：模块⑧（养家仓位-赢面量化模型）
输出到 marketData.v2.position_model，并提供给策略引擎使用。
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.position_v2 import calc_win_rate
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    md = ctx.market_data or {}
    v2s = (md.get("v2") or {}).get("sentiment") if isinstance(md.get("v2"), dict) else None
    v2s = v2s if isinstance(v2s, dict) else {}
    sentiment_score = float(v2s.get("score") or 5.0)

    v2 = md.get("v2") if isinstance(md.get("v2"), dict) else {}
    dragon = v2.get("dragon") if isinstance(v2.get("dragon"), dict) else {}
    dragon_overall = float(dragon.get("overall") or 5.0)

    # 主线：沿用 sentiment_v2 的 proxy（后续由模块④增强替换）
    mainline = {
        "exists": bool((md.get("sentiment") or {}).get("sub_scores", {}).get("theme_clarity", 0) >= 6),
        "strength": "主线偏强" if bool((md.get("sentiment") or {}).get("sub_scores", {}).get("theme_clarity", 0) >= 7.5) else "主线偏弱",
    }

    model = calc_win_rate(
        {
            "sentiment_score": sentiment_score,
            "mainline": mainline,
            "dragon_overall_score": dragon_overall,
            "nature_compatible": False,  # TODO: 模块⑥接入后替换
            "upside_potential": 0.10,
            "downside_risk": 0.05,
        }
    )

    return {"marketData.v2": {**v2, "position_model": model}}


POSITION_V2_MODULE = Module(
    name="position_v2",
    requires=["marketData.v2", "marketData.sentiment"],
    provides=["marketData.v2"],
    compute=_compute,
)
