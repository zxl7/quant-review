#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
panorama 模块（v2）：遵循 pipeline.Module 协议

职责：
- 从 raw.pools 计算市场全景（涨停/炸板/跌停/封板率）
- 输出 marketData.panorama

数据契约：
- 输入（优先）：ctx.raw.pools.ztgc / dtgc / zbgc（list）
- 兜底：ctx.market_data.panorama（如果 raw 缺失，保持页面可渲染）
"""

from __future__ import annotations

from typing import Any, Dict, List

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _as_list(v: Any) -> List[Dict[str, Any]]:
    return v if isinstance(v, list) else []


def _compute(ctx: Context) -> Dict[str, Any]:
    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
    zt = _as_list(pools.get("ztgc"))
    dt = _as_list(pools.get("dtgc"))
    zb = _as_list(pools.get("zbgc"))

    if not (zt or dt or zb):
        # 兜底：不改动，避免 partial 时因为 raw 缺失导致全景变空
        cur = ctx.market_data.get("panorama") or {}
        return {"marketData.panorama": cur}

    zt_count = len(zt)
    dt_count = len(dt)
    zb_count = len(zb)
    fb_rate = (zt_count / (zt_count + zb_count) * 100.0) if (zt_count + zb_count) else 0.0

    return {
        "marketData.panorama": {
            "limitUp": zt_count,
            "broken": zb_count,
            "limitDown": dt_count,
            "ratio": f"{fb_rate:.1f}%",
        }
    }


PANORAMA_MODULE = Module(
    name="panorama",
    requires=["raw.pools.ztgc", "raw.pools.dtgc", "raw.pools.zbgc"],
    provides=["marketData.panorama"],
    compute=_compute,
)

