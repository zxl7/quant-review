#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
strategy_v2 模块：模块⑤（明日策略生成引擎）
依赖：①情绪计分卡 + ⑧仓位赢面（其余模块逐步接入）
输出：marketData.v2.strategy
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.strategy_v2 import generate_strategy
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    md = ctx.market_data or {}
    v2 = md.get("v2") if isinstance(md.get("v2"), dict) else {}
    v2_sent = v2.get("sentiment") if isinstance(v2.get("sentiment"), dict) else {}
    pos = v2.get("position_model") if isinstance(v2.get("position_model"), dict) else {}
    res = v2.get("resonance") if isinstance(v2.get("resonance"), dict) else {}
    rs = v2.get("rightside") if isinstance(v2.get("rightside"), dict) else {}
    tn = v2.get("trade_nature") if isinstance(v2.get("trade_nature"), dict) else {}

    strategy = generate_strategy(v2_sentiment=v2_sent, position_model=pos, resonance=res, rightside=rs, trade_nature=tn)
    return {"marketData.v2": {**v2, "strategy": strategy}}


STRATEGY_V2_MODULE = Module(
    name="strategy_v2",
    requires=["marketData.v2"],
    provides=["marketData.v2"],
    compute=_compute,
)
