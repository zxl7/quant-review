#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3_position 模块：基于v3.0算法规格书的胜率仓位计算

根据情绪评分和当前市场状态，计算推荐的仓位比例，
结合胜率预期和T+1惩罚因子给出最终仓位建议。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _derive_inputs(ctx: Context) -> Dict[str, Any]:
    """从Context中提取仓位计算所需数据"""
    md = ctx.market_data or {}

    return {
        "sentiment": md.get("v3", {}).get("sentiment") if isinstance(md.get("v3"), dict) else {},
        "mood": md.get("mood") or {},
        "mood_stage": md.get("moodStage") or {},
        "indices": md.get("indices") or [],
    }


def _compute(ctx: Context) -> Dict[str, Any]:
    """v3 positionV3 计算主函数"""
    try:
        from daily_review.metrics.v3_position import calc_win_rate_position
        from daily_review.metrics.v3_t1_penalty import calc_t1_penalty

        inputs = _derive_inputs(ctx)
        md = ctx.market_data or {}

        # 提取情绪分
        sentiment_obj = inputs["sentiment"]
        sentiment_score = (
            float(sentiment_obj.get("score", 5.0))
            if isinstance(sentiment_obj, dict) else 5.0
        )
        phase = (
            sentiment_obj.get("phase", "")
            if isinstance(sentiment_obj, dict) else ""
        )

        # calc_win_rate_position 使用正确的关键字参数名
        position_result = calc_win_rate_position(
            sentiment_score=sentiment_score,
        )

        # T+1 惩罚调整
        mi = ((md.get("features") or {}).get("mood_inputs") or {}) if isinstance(md.get("features"), dict) else {}
        zab_rate = float(mi.get("zb_rate", 0) or 0)

        t1_result = calc_t1_penalty(
            sentiment_score=sentiment_score,
            phase=phase,
            zab_rate=zab_rate,
        )

        # 应用T+1惩罚到仓位
        base_capital_pct = (
            getattr(position_result, "capital_pct", 0.5)
            if hasattr(position_result, "__dataclass_fields__")
            else float(position_result.get("capital_pct", 0.5) if isinstance(position_result, dict) else 0.5)
        )
        adjusted_pct = t1_result["adjust_position"](base_capital_pct)

        base_output = (
            vars(position_result) if hasattr(position_result, "__dataclass_fields__")
            else (position_result if isinstance(position_result, dict) else {})
        )

        output = {
            **base_output,
            "capital_pct_adjusted": adjusted_pct,
            "t1_penalty": {
                "penalty_ratio": t1_result["penalty_ratio"],
                "penalty_pct": t1_result["penalty_pct"],
                "reasons": t1_result["reasons"],
                "is_significant": t1_result["is_significant"],
            },
        }

        return {"marketData.v3.positionV3": output}
    except Exception as e:
        return {"marketData.v3.positionV3": {"error": str(e), "confidence": 0}}


# 注册Module
V3_POSITION_MODULE = Module(
    name="v3_position",
    requires=[
        "marketData.v3.sentiment",
        "marketData.mood",
        "marketData.moodStage",
        "marketData.indices",
        "features.mood_inputs",
    ],
    provides=["marketData.v3.positionV3"],
    compute=_compute,
)
