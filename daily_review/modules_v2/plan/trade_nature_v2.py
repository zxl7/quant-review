#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
trade_nature_v2 模块：模块⑥（交易性质六分类系统）
输出到 marketData.v2.trade_nature
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.trade_nature_v2 import decide_trade_nature
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    md = ctx.market_data or {}
    v2 = md.get("v2") if isinstance(md.get("v2"), dict) else {}
    out = decide_trade_nature(md)
    return {"marketData.v2": {**v2, "trade_nature": out}}


TRADE_NATURE_V2_MODULE = Module(
    name="trade_nature_v2",
    requires=["marketData.v2"],
    provides=["marketData.v2"],
    compute=_compute,
)

