#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3_fullpos 模块：基于v3.0算法规格书的满仓共振检查

综合指数走势、主题面板、龙头评分和情绪评分，
判断当前是否满足"满仓共振"条件（多维度同时看多）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _derive_inputs(ctx: Context) -> Dict[str, Any]:
    """从Context中提取满仓共振检查所需数据"""
    md = ctx.market_data or {}

    return {
        "indices": md.get("indices") or [],
        "theme_panels": md.get("themePanels") or {},
        "dragon": md.get("v3", {}).get("dragon") if isinstance(md.get("v3"), dict) else {},
        "sentiment": md.get("v3", {}).get("sentiment") if isinstance(md.get("v3"), dict) else {},
        "mainstream": md.get("v3", {}).get("mainstream") if isinstance(md.get("v3"), dict) else {},
        "mood_stage": md.get("moodStage") or {},
    }


def _compute(ctx: Context) -> Dict[str, Any]:
    """v3 fullPosition 计算主函数"""
    try:
        from daily_review.metrics.v3_fullposition import check_full_position_resonance

        inputs = _derive_inputs(ctx)

        # 提取情绪分
        sentiment_obj = inputs["sentiment"]
        sentiment_score = (
            float(sentiment_obj.get("score", 5.0))
            if isinstance(sentiment_obj, dict) else 5.0
        )

        # check_full_position_resonance(*, indices=, sector_data=, stock_data=, sentiment_score=)
        result = check_full_position_resonance(
            indices=inputs["indices"],
            sector_data=inputs["mainstream"],  # 用 mainstream 数据作为 sector_data
            stock_data=inputs["dragon"] if inputs["dragon"] else None,
            sentiment_score=sentiment_score,
        )

        output = (
            vars(result) if hasattr(result, "__dataclass_fields__")
            else result
        )

        return {"marketData.v3.fullPosition": output}
    except Exception as e:
        return {"marketData.v3.fullPosition": {"error": str(e), "confidence": 0}}


# 注册Module
V3_FULLPOS_MODULE = Module(
    name="v3_fullpos",
    requires=[
        "marketData.indices",
        "marketData.themePanels",
        "marketData.v3.dragon",
        "marketData.v3.sentiment",
        "marketData.v3.mainstream",
        "marketData.moodStage",
    ],
    provides=["marketData.v3.fullPosition"],
    compute=_compute,
)
