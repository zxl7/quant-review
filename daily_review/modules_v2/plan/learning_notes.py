#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
learning_notes 模块（v2）：遵循 pipeline.Module 协议

输出：
- marketData.learningNotes

说明：
- 复用 daily_review.render.render_html 的 build_learning_notes
- 会写 cache/learning_notes_history.json（用于避免每天重复一句）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module
from daily_review.render.render_html import build_learning_notes


def _workspace_root() -> Path:
    # .../daily_review/modules_v2/learning_notes.py -> .../workspace
    return Path(__file__).resolve().parents[2]


def _compute(ctx: Context) -> Dict[str, Any]:
    cache_dir = _workspace_root() / "cache"
    ln = build_learning_notes(market_data=ctx.market_data, cache_dir=cache_dir)
    return {"marketData.learningNotes": ln}


LEARNING_NOTES_MODULE = Module(
    name="learning_notes",
    requires=["marketData.moodStage"],
    provides=["marketData.learningNotes"],
    compute=_compute,
)

