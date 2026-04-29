#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3_reflexivity 模块：基于v3.0算法规格书的反身性周期分析

结合情绪评分、全景数据和效应数据，进行反身性分析：
- analyze_reflexivity_cycle: 反身性周期阶段判断
- psychological_game_analysis: 心理博弈分析
- behavior_chain_monitor: 行为链监控
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _derive_inputs(ctx: Context) -> Dict[str, Any]:
    """从Context中提取反身性分析所需数据"""
    md = ctx.market_data or {}
    sentiment_obj = md.get("v3", {}).get("sentiment") if isinstance(md.get("v3"), dict) else {}
    mp = md.get("marketPanorama") if isinstance(md.get("marketPanorama"), dict) else {}
    # effect 已下线：用 marketPanorama 生成一个兼容的 effect 代理，供 behavior_chain_monitor 使用
    effect_proxy = md.get("effect") if isinstance(md.get("effect"), dict) else {}
    if not effect_proxy and isinstance(mp, dict) and mp:
        earning = mp.get("earning") if isinstance(mp.get("earning"), dict) else {}
        loss = mp.get("loss") if isinstance(mp.get("loss"), dict) else {}
        effect_proxy = {
            "earning_score": earning.get("score"),
            "earning_stars": earning.get("stars"),
            "loss_score": loss.get("score"),
            "loss_stars": loss.get("stars"),
        }

    return {
        "sentiment_score": (
            float(sentiment_obj.get("score", 5.0))
            if isinstance(sentiment_obj, dict) else 5.0
        ),
        "sentiment": sentiment_obj,
        "panorama": md.get("panorama") or {},
        "effect": effect_proxy or {},
        "mood": md.get("mood") or {},
        "indices": md.get("indices") or [],
    }


def _compute(ctx: Context) -> Dict[str, Any]:
    """v3 reflexivity 计算主函数"""
    try:
        from daily_review.metrics.v3_reflexivity import (
            analyze_reflexivity_cycle,
            psychological_game_analysis,
            behavior_chain_monitor,
        )

        inputs = _derive_inputs(ctx)

        # 1) analyze_reflexivity_cycle(market_state: Dict) — 单参数字典
        market_state = {
            "sentiment_score": inputs["sentiment_score"],
            "zt_count": 0,  # 从 panorama 或 mood_inputs 提取
            "risk_spike": False,
        }
        # 补充 panorama 中的风险信号
        pan = inputs["panorama"]
        if isinstance(pan, dict):
            market_state["risk_spike"] = bool(pan.get("has_extreme_risk", False))

        cycle = analyze_reflexivity_cycle(market_state)

        # 2) psychological_game_analysis(stock: Dict, context: Dict)
        psycho = psychological_game_analysis(
            {},  # 无个股时传空dict表示市场级分析
            {
                "sentiment_score": inputs["sentiment_score"],
                "mood": inputs["mood"],
                "indices": inputs["indices"],
            },
        )

        # 3) behavior_chain_monitor(data: Dict) — 单参数字典
        chain_data = {
            "sentiment_score": inputs["sentiment_score"],
            "panorama": inputs["panorama"],
            "effect": inputs["effect"],
        }
        chain = behavior_chain_monitor(chain_data)

        result = {
            "cycle": cycle if isinstance(cycle, dict) else (vars(cycle) if hasattr(cycle, "__dataclass_fields__") else {}),
            "psychology": psycho if isinstance(psycho, dict) else (vars(psycho) if hasattr(psycho, "__dataclass_fields__") else {}),
            "behavior_chain": chain if isinstance(chain, list) else [],
        }

        return {"marketData.v3.reflexivity": result}
    except Exception as e:
        return {"marketData.v3.reflexivity": {"error": str(e), "confidence": 0}}


# 注册Module
V3_REFLEXIVITY_MODULE = Module(
    name="v3_reflexivity",
    requires=[
        "marketData.v3.sentiment",
        "marketData.panorama",
        "marketData.mood",
        "marketData.indices",
    ],
    provides=["marketData.v3.reflexivity"],
    compute=_compute,
)
