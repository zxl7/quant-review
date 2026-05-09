#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
summary3 模块（v2）：遵循 pipeline.Module 协议

输出：
- marketData.summary3

说明：
- 复用 daily_review.render.render_html 的 build_summary3（纯计算，不做外部请求）
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module
from daily_review.render.render_html import build_summary3


def _compute(ctx: Context) -> Dict[str, Any]:
    s3 = build_summary3(market_data=ctx.market_data)
    return {"marketData.summary3": s3}


SUMMARY3_MODULE = Module(
    name="summary3",
    requires=["marketData.actionGuideV2", "marketData.moodStage", "marketData.ladder", "marketData.themePanels"],
    provides=["marketData.summary3"],
    compute=_compute,
)

