#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""ladder_features 模块：提供结构化的梯队与主线数据 (features.ladder)。"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.features.ladder_builder import build_ladder
from daily_review.features.sector_resolver import SectorResolution
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    # 依赖 SectorResolution (由 THEME_LAYERS_MODULE 提供)
    resolution = ctx.get("features.sector_resolution")
    if not isinstance(resolution, SectorResolution):
        return {}

    date = ctx.date
    pools_cache = ctx.raw.get("pools") or {}
    market_data = ctx.market_data
    
    # 构建结构化的梯队结果
    ladder_result = build_ladder(
        resolution=resolution,
        pools_cache=pools_cache,
        date=date,
        market_data=market_data
    )
    
    return {"features.ladder": ladder_result}


LADDER_FEATURES_MODULE = Module(
    name="ladder_features",
    requires=[
        "features.sector_resolution",
        "raw.pools.ztgc",
        "marketData.leaders",
    ],
    provides=["features.ladder"],
    compute=_compute,
)
