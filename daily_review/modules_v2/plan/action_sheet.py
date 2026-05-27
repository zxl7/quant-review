#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""action_sheet 模块：基于情绪阶段的自动化操作建议单。"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.action_sheet import build_action_sheet
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    # 调用重构后的 action_sheet 逻辑
    sheet = build_action_sheet(ctx.market_data)
    return {"marketData.actionSheet": sheet}


ACTION_SHEET_MODULE = Module(
    name="action_sheet",
    requires=[
        "marketData.moodStage",
        "marketData.themePanels",
        "marketData.ladder",
        "features.mood_inputs",
    ],
    provides=["marketData.actionSheet"],
    compute=_compute,
)
