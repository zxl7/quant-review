#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3_mainstream 模块：基于v3.0算法规格书的主流/主线判断

从themePanels构建梯队 + classify_theme_level + judge_mainline 判断主线方向
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module
from daily_review.modules_v2._utils import map_ztgc_list


def _derive_inputs(ctx: Context) -> Dict[str, Any]:
    """从Context中提取主流判断所需数据"""
    md = ctx.market_data or {}
    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
    raw_ztgc = pools.get("ztgc") or []

    return {
        "theme_panels": md.get("themePanels") or {},
        "ztgc": map_ztgc_list(raw_ztgc),  # 统一映射 dm→code, mc→name...
        "mood": md.get("mood") or {},
        "mood_stage": md.get("moodStage") or {},
        "ladder": md.get("ladder") or [],
    }


def _safe(val: Any) -> Any:
    if isinstance(val, (str, int, float, bool, type(None))): return val
    if hasattr(val, "value"): return val.value
    if hasattr(val, "__dataclass_fields__"): return {k: _safe(v) for k, v in vars(val).items()}
    if isinstance(val, (tuple, list)): return [_safe(x) for x in val]
    if isinstance(val, dict): return {k: _safe(v) for k, v in val.items()}
    return str(val)


def _compute(ctx: Context) -> Dict[str, Any]:
    """v3 mainstream 计算主函数"""
    try:
        from daily_review.metrics.v3_mainstream import (
            classify_theme_level,
            build_sector_ladder,
            judge_mainline,
        )

        inputs = _derive_inputs(ctx)

        # build_sector_ladder 需要 List[Dict] 个股列表; 优先 ladder(已有name/code)
        ladder_input = inputs["ladder"] if isinstance(inputs["ladder"], list) else inputs["ztgc"]

        # 统一字段格式（兼容 ladder 的 name/code 和 ztgc 映射后的 name/code）
        mapped_stocks = []
        for s in ladder_input:
            if isinstance(s, dict):
                mapped_stocks.append({
                    "name": s.get("mc") or s.get("name", ""),
                    "code": s.get("dm") or s.get("code", ""),
                    "consecutive_boards": int(s.get("lbc", s.get("consecutive_boards", 0)) or 0),
                    "chg_pct": float(s.get("zf", s.get("chg", s.get("change_pct", s.get("chg_pct", 0)))) or 0),
                    "amount": float(s.get("cje", s.get("amount", s.get("turnover", 0))) or 0),
                })

        try:
            ladder = build_sector_ladder(mapped_stocks)
        except Exception:
            ladder = {"dragon": None, "health_score": 0, "health_grade": "D"}

        # classify_theme_level 接收单个主题信息字典
        try:
            theme_levels = classify_theme_level(inputs["theme_panels"])
        except Exception:
            theme_levels = {"level": "NO_THEME", "score": 0}

        # judge_mainline 接受 (sectors: List[Dict], sentiment_score: float)
        # 从 ladder 构造 sectors 输入
        sentiment_score = 5.0  # 默认值，后续可从 v3.sentiment 获取
        try:
            mainline = judge_mainline(
                [ladder] if isinstance(ladder, dict) else [],
                sentiment_score=sentiment_score,
            )
        except Exception:
            mainline = {"exists": False, "strength": "无", "top_sector": None}

        result = {
            "sector_ladder": (
                vars(ladder) if hasattr(ladder, "__dataclass_fields__")
                else ladder
            ),
            "theme_levels": (
                vars(theme_levels) if hasattr(theme_levels, "__dataclass_fields__")
                else theme_levels
            ),
            "mainline": (
                vars(mainline) if hasattr(mainline, "__dataclass_fields__")
                else mainline
            ),
        }

        return {"marketData.v3.mainstream": _safe(result)}
    except Exception as e:
        return {"marketData.v3.mainstream": {"error": str(e), "confidence": 0}}


# 注册Module
V3_MAINSTREAM_MODULE = Module(
    name="v3_mainstream",
    requires=[
        "marketData.themePanels",
        "raw.pools.ztgc",
        "marketData.ladder",
        "marketData.mood",
    ],
    provides=["marketData.v3.mainstream"],
    compute=_compute,
)
