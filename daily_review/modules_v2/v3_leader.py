#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3_leader (dragon) 模块：基于v3.0算法规格书的龙头三要素评分

取连板最高3只股票，分别调用 calc_three_elements() 计算龙头三要素：
带领性、突破性、唯一性 → DragonScore 综合排名
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module
from daily_review.modules_v2._utils import map_ztgc_list


def _derive_inputs(ctx: Context) -> Dict[str, Any]:
    """从Context中提取龙头评分所需数据"""
    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
    raw_ztgc = pools.get("ztgc") or []

    md = ctx.market_data or {}
    theme_panels = md.get("themePanels") or {}
    style_radar = md.get("styleRadar") or {}

    return {
        "ztgc": map_ztgc_list(raw_ztgc),  # 字段映射 dm→code, mc→name...
        "theme_panels": theme_panels,
        "style_radar": style_radar,
    }


def _compute(ctx: Context) -> Dict[str, Any]:
    """v3 dragon (leader) 计算主函数"""
    try:
        from daily_review.metrics.v3_god_form import calc_three_elements

        inputs = _derive_inputs(ctx)
        ztgc = inputs["ztgc"]

        if not ztgc or not isinstance(ztgc, list):
            return {
                "marketData.v3.dragon": {
                    "rankings": [],
                    "summary": {"total_candidates": 0},
                },
            }

        # 按连板数降序排列，取前3只作为龙头候选
        candidates = sorted(
            [s for s in ztgc if isinstance(s, dict)],
            key=lambda x: int(x.get("lbc", 0) or 0),
            reverse=True,
        )[:3]

        rankings = []
        for stock in candidates:
            score = calc_three_elements(
                stock,
                {"theme_panels": inputs["theme_panels"], "style_radar": inputs["style_radar"]},
            )
            rankings.append({
                "name": stock.get("name", ""),
                "code": stock.get("code", ""),
                "lbc": stock.get("lbc"),
                "score": (
                    vars(score) if hasattr(score, "__dataclass_fields__")
                    else score
                ),
            })

        # 按综合分排序
        def _get_total(s):
            sc = s.get("score", {})
            if isinstance(sc, dict):
                return float(sc.get("total", 0) or 0)
            return 0

        rankings.sort(key=_get_total, reverse=True)

        return {
            "marketData.v3.dragon": {
                "rankings": rankings,
                "summary": {
                    "total_candidates": len(candidates),
                    "top_dragon_name": rankings[0]["name"] if rankings else None,
                },
            },
        }
    except Exception as e:
        return {
            "marketData.v3.dragon": {"error": str(e), "confidence": 0},
        }


# 注册Module
V3_LEADER_MODULE = Module(
    name="v3_leader",
    requires=[
        "raw.pools.ztgc",
        "marketData.themePanels",
        "marketData.styleRadar",
    ],
    provides=["marketData.v3.dragon"],
    compute=_compute,
)
