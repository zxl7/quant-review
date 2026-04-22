#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
action_guide 模块（v2）：遵循 pipeline.Module 协议

输出：
- marketData.actionGuideV2

说明：
- 复用 daily_review.render.render_html 里的 build_action_guide_v2（纯计算，不做外部请求）
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module
from daily_review.render.render_html import build_action_guide_v2


def _compute(ctx: Context) -> Dict[str, Any]:
    ag = build_action_guide_v2(ctx.market_data)
    return {"marketData.actionGuideV2": ag}


ACTION_GUIDE_MODULE = Module(
    name="action_guide",
    # 这些依赖用于 partial 自动补齐（缺 provider 的会被 runner 忽略，不影响运行）
    requires=[
        "marketData.themePanels",
        "marketData.ladder",
        "marketData.ztgc",
        "marketData.zt_code_themes",
        "marketData.moodStage",
    ],
    provides=["marketData.actionGuideV2"],
    compute=_compute,
)

