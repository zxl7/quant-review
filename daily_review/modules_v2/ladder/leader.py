#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
leader 模块（v2）：遵循 pipeline.Module 协议

说明：
- 复用 v1 的 leader 模块实现（market_data -> patch）
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.modules.leader import rebuild_leaders
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    patch = rebuild_leaders(ctx.market_data)
    return {"marketData.leaders": patch.get("leaders") or []}


LEADER_MODULE = Module(
    name="leader",
    requires=["marketData.ztgc", "marketData.zt_code_themes"],
    provides=["marketData.leaders"],
    compute=_compute,
)

