#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3_trading 模块：基于v3.0算法规格书的交易性质判断

结合涨停池数据、情绪评分和情绪阶段，判断当前市场交易性质
（如：趋势主升 / 震荡轮动 / 情绪博弈 / 趋势破位 等）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _derive_inputs(ctx: Context) -> Dict[str, Any]:
    """从Context中提取交易性质判断所需数据"""
    md = ctx.market_data or {}
    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}

    return {
        "ztgc": pools.get("ztgc") or [],
        "sentiment": md.get("v3", {}).get("sentiment") if isinstance(md.get("v3"), dict) else {},
        "mood_stage": md.get("moodStage") or {},
        "mood": md.get("mood") or {},
    }


def _compute(ctx: Context) -> Dict[str, Any]:
    """v3 tradingNature 计算主函数"""
    try:
        from daily_review.metrics.v3_trading_nature import determine_trade_nature

        inputs = _derive_inputs(ctx)

        # determine_trade_nature(stock_info: Dict, market_context: Dict)
        # 取连板最高的股票作为代表，构造 stock_info
        ztgc = inputs["ztgc"] or []
        rep_stock = {}
        if ztgc:
            top = max(ztgc, key=lambda s: int(s.get("lbc", 0) or 0)) if isinstance(ztgc[0], dict) else {}
            rep_stock = {
                "name": top.get("name", ""),
                "code": top.get("code", ""),
                "consecutive_boards": int(top.get("lbc", 0) or 0),
                "chg_pct": float(top.get("chg", top.get("change_pct", 0)) or 0),
                "yest_chg_pct": float(top.get("yest_chg", 0) or 0),
                "is_zt": bool(top.get("is_zt", False)),
            }

        sentiment_obj = inputs["sentiment"]
        sentiment_score = (
            float(sentiment_obj.get("score", 5.0))
            if isinstance(sentiment_obj, dict) else 5.0
        )
        phase = (
            sentiment_obj.get("phase", "")
            if isinstance(sentiment_obj, dict) else ""
        )

        market_context = {
            "sentiment_score": sentiment_score,
            "phase": phase,
            "mood_stage": inputs["mood_stage"],
            "mood": inputs["mood"],
        }

        result = determine_trade_nature(rep_stock, market_context)

        output = (vars(result) if hasattr(result, "__dataclass_fields__") else result) or {}
        # JSON 兼容：Enum / dataclass 里可能包含不可序列化对象
        try:
            nature_obj = output.get("nature")
            if nature_obj is not None:
                # TradeNature(Enum) 里自定义了 name 属性（中文），_name_ 为枚举键
                output["nature"] = {
                    "code": getattr(nature_obj, "_name_", None),
                    "label": getattr(nature_obj, "name", None),
                    "risk_level": getattr(nature_obj, "risk_level", None),
                    "max_position": getattr(nature_obj, "max_position", None),
                    "stop_loss": getattr(nature_obj, "stop_loss", None),
                    "target_gain": getattr(nature_obj, "target_gain", None),
                }
        except Exception:
            pass

        return {"marketData.v3.tradingNature": output}
    except Exception as e:
        return {"marketData.v3.tradingNature": {"error": str(e), "confidence": 0}}


# 注册Module
V3_TRADING_MODULE = Module(
    name="v3_trading",
    requires=[
        "raw.pools.ztgc",
        "marketData.v3.sentiment",
        "marketData.moodStage",
        "marketData.mood",
    ],
    provides=["marketData.v3.tradingNature"],
    compute=_compute,
)
