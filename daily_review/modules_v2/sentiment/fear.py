#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
fear 模块（v2）：恐惧/亏钱扩散信息（marketData.fear）

用于模板中的：
- 大面股(-5%↓)
- 非ST跌停
- 亏钱效应（等级+注释）
- 炸板率、封板成功率（展示口径与提示）
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module
from daily_review.utils.stock import filter_non_st_stocks


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _compute(ctx: Context) -> Dict[str, Any]:
    mi = (ctx.features.get("mood_inputs") or {}) if isinstance(ctx.features, dict) else {}
    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
    dt = pools.get("dtgc") or []
    dt = dt if isinstance(dt, list) else []

    # 风险页同时保留“总跌停”和“非 ST 跌停”，便于解释全局口径。
    dt_non_st = filter_non_st_stocks(dt)

    bf_count = int(mi.get("bf_count", 0) or 0)
    bf_names = str(mi.get("bf_names", "") or "")
    dt_count = len(dt_non_st)
    total_dt_count = len(dt)
    zt_count = int(mi.get("zt_count", 0) or 0)

    zb_rate = float(mi.get("zb_rate", 0) or 0)
    fb_rate = float(mi.get("fb_rate", 0) or 0)

    # 亏钱效应等级（粗分档，先让页面不缺失）
    loss = bf_count + dt_count
    if loss <= 2:
        risk_level = "极低"
        note = "亏钱效应极小"
    elif loss <= 5:
        risk_level = "偏低"
        note = "少量亏钱扩散，整体可控"
    elif loss <= 10:
        risk_level = "偏高"
        note = "亏钱扩散偏多，注意回避高位"
    else:
        risk_level = "高"
        note = "大面横飞，建议观望"

    return {
        "marketData.fear": {
            "bigFace": f"{bf_count}只",
            "bigFaceNote": bf_names if bf_names else "无大面股",
            "limitDown": f"{dt_count}只",
            "limitDownNote": f"总跌停{total_dt_count}，剔除ST后{dt_count}",
            "risk": risk_level,
            "riskNote": note,
            "broken": f"{zb_rate:.1f}%",
            "brokenNote": f"炸板越高越偏分歧（涨停{zt_count}）",
            "success": f"{fb_rate:.1f}%",
            "successNote": "封板成功率（涨停/(涨停+炸板)）",
        }
    }


FEAR_MODULE = Module(
    name="fear",
    requires=["features.mood_inputs", "raw.pools.dtgc"],
    provides=["marketData.fear"],
    compute=_compute,
)
