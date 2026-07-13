#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
catalyst_analysis 模块：题材催化分析（Stock Catalyst Hunter 方法论落地）

消费 cache/catalyst_input-YYYYMMDD.json（由 qr.sh catalyst 命令写入），
调用 metrics.catalyst.analyze_catalyst 引擎，注入 marketData.catalystAnalysis。

设计：
- 自包含读 cache（与 learning_notes / v3_tonghuashun 同模式），不依赖其它模块产出。
- 无输入缓存时 fail-soft 返回 available=False，不影响主 pipeline 与 DAG 校验。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _workspace_root() -> Path:
    # .../daily_review/modules_v2/plan/catalyst_analysis.py -> .../workspace
    return Path(__file__).resolve().parents[3]


def _date8(date_str: str) -> str:
    """归一化日期为 YYYYMMDD；空串返回空。"""
    if not date_str:
        return ""
    return str(date_str).replace("-", "").strip()


def _load_catalyst_input(*, root: Path, date8: str) -> Dict[str, Any] | None:
    p = root / "cache" / f"catalyst_input-{date8}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _compute(ctx: Context) -> Dict[str, Any]:
    try:
        from daily_review.metrics.catalyst import (
            analyze_catalyst,
            catalyst_input_from_dict,
        )

        date8 = _date8(ctx.date)
        if not date8:
            return {"marketData.catalystAnalysis": {"available": False, "reason": "no_date"}}

        raw = _load_catalyst_input(root=_workspace_root(), date8=date8)
        if not raw:
            return {"marketData.catalystAnalysis": {"available": False, "reason": "no_catalyst_input"}}

        inp = catalyst_input_from_dict(raw)
        res = analyze_catalyst(inp)

        return {
            "marketData.catalystAnalysis": {
                "available": True,
                "event_summary": res.event_conclusion,
                "theme_strength": res.theme_strength,
                "policy_level": res.policy_level.value,
                "confidence": res.confidence,
                "transmission_layers": res.transmission_layers,
                "sectors": res.sectors,
                "stock_maps": res.stock_maps,
                "main_benefit_directions": res.main_benefit_directions,
                "main_risk_directions": res.main_risk_directions,
            }
        }
    except Exception as e:
        return {"marketData.catalystAnalysis": {"available": False, "error": str(e), "confidence": 0}}


CATALYST_ANALYSIS_MODULE = Module(
    name="catalyst_analysis",
    requires=[],
    provides=["marketData.catalystAnalysis"],
    compute=_compute,
)
