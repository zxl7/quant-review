#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""picks_advisor 模块：基于主线与评分的个股精选建议。"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.features.stock_ranker import build_picks_advisor
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    # 依赖梯队结果 (ladder) 和 市场大盘数据 (用于提取领导者评分)
    ladder = ctx.get("features.ladder")
    market_data = ctx.market_data
    
    if not ladder:
        return {}

    # 调用重构后的 stock_ranker 逻辑
    result = build_picks_advisor(
        ladder=ladder,
        market_data=market_data,
        top_k_lines=3,
        buy_n=3,
        watch_n=5
    )
    
    return {"marketData.picksAdvisor": result.to_dict()}


PICKS_ADVISOR_MODULE = Module(
    name="picks_advisor",
    requires=[
        "features.ladder",
        "marketData.leaders",
    ],
    provides=["marketData.picksAdvisor"],
    compute=_compute,
)
