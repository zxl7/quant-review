#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3_rightside 模块：基于v3.0算法规格书的右侧交易决策

综合指数走势、情绪评分和主流方向，输出右侧交易建议：
是否适合右侧追涨、入场点位、止损位等。
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _derive_inputs(ctx: Context) -> Dict[str, Any]:
    """从Context中提取右侧交易决策所需数据"""
    md = ctx.market_data or {}

    return {
        "indices": md.get("indices") or [],
        "sentiment": md.get("v3", {}).get("sentiment") if isinstance(md.get("v3"), dict) else {},
        "mainstream": md.get("v3", {}).get("mainstream") if isinstance(md.get("v3"), dict) else {},
        "mood_stage": md.get("moodStage") or {},
    }


def _compute(ctx: Context) -> Dict[str, Any]:
    """v3 rightside 计算主函数"""
    try:
        from daily_review.metrics.v3_rightside import right_side_decision

        inputs = _derive_inputs(ctx)

        # right_side_decision(stock_info, market_context)
        # stock_info 可以为 None/{} 表示市场级判断
        stock_info = {}

        sentiment_obj = inputs["sentiment"]
        sentiment_score = (
            float(sentiment_obj.get("score", 5.0))
            if isinstance(sentiment_obj, dict) else 5.0
        )

        market_context = {
            "indices": inputs["indices"],
            "mainline": inputs["mainstream"],
            "sentiment_score": sentiment_score,
            "mood_stage": inputs["mood_stage"],
            "catalyst": "",
        }

        result = right_side_decision(stock_info, market_context)

        output = (
            vars(result) if hasattr(result, "__dataclass_fields__")
            else result
        )

        return {"marketData.v3.rightside": output}
    except Exception as e:
        return {"marketData.v3.rightside": {"error": str(e), "confidence": 0}}


# 注册Module
V3_RIGHTSIDE_MODULE = Module(
    name="v3_rightside",
    requires=[
        "marketData.indices",
        "marketData.v3.sentiment",
        "marketData.v3.mainstream",
        "marketData.moodStage",
    ],
    provides=["marketData.v3.rightside"],
    compute=_compute,
)
