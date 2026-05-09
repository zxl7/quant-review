#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3_rebound 模块：基于v3.0算法规格书的反弹阶段识别

综合指数走势、全景数据和情绪状态，识别当前处于反弹的哪个阶段：
PRE(前反弹) / EARLY(初期) / MID(中期) / LATE(后期) / OVER(结束)
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _derive_inputs(ctx: Context) -> Dict[str, Any]:
    """从Context中提取反弹识别所需数据"""
    md = ctx.market_data or {}
    indices = md.get("indices") or []

    # 提取指数涨跌幅
    index_chg_today = 0.0
    if isinstance(indices, list) and len(indices) > 0:
        idx0 = indices[0] if isinstance(indices[0], dict) else {}
        index_chg_today = float(idx0.get("change_pct", idx0.get("chg_pct", 0)) or 0)

    # 从 mood_inputs 提取基础计数
    mi = ((md.get("features") or {}).get("mood_inputs") or {}) if isinstance(md.get("features"), dict) else {}

    return {
        "index_chg_today": index_chg_today,
        "indices": indices,
        "panorama": md.get("panorama") or {},
        "mood": md.get("mood") or {},
        "volume": md.get("volume") or {},
        "zt_count": mi.get("zt_count"),
        "dt_count": mi.get("dt_count"),
        "max_lianban": mi.get("max_lb"),
    }


def _compute(ctx: Context) -> Dict[str, Any]:
    """v3 rebound 计算主函数"""
    try:
        from daily_review.metrics.v3_rebound import identify_rebound_phase

        inputs = _derive_inputs(ctx)

        # identify_rebound_phase(market_data: Dict[str,Any]) — 单参数
        result = identify_rebound_phase(inputs)

        output = (vars(result) if hasattr(result, "__dataclass_fields__") else result) or {}
        # JSON 兼容：Enum（phase）不可直接序列化
        try:
            ph = output.get("phase")
            if ph is not None:
                output["phase"] = {"code": getattr(ph, "_name_", None), "label": getattr(ph, "value", [None])[0] if getattr(ph, "value", None) else str(ph)}
        except Exception:
            pass

        return {"marketData.v3.rebound": output}
    except Exception as e:
        return {"marketData.v3.rebound": {"error": str(e), "confidence": 0}}


# 注册Module
V3_REBOUND_MODULE = Module(
    name="v3_rebound",
    requires=[
        "marketData.indices",
        "marketData.panorama",
        "marketData.mood",
        "marketData.volume",
        "features.mood_inputs",
    ],
    provides=["marketData.v3.rebound"],
    compute=_compute,
)
