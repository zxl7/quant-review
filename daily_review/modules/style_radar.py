#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
市场风格雷达模块（部分更新示例）

设计原则：
- 输入：market_data（必须包含 features.style_strengths 与 features.chart_palette）
- 输出：{"styleRadar": {...}} 覆盖 marketData.styleRadar

这样你只想改“风格雷达的指标/权重/展示口径”时：
- 改这个文件
- 然后跑 partial update（不必全量重抓取数据）
"""

from __future__ import annotations

from typing import Any, Dict, List

from daily_review.metrics.style_radar import calc_style_strengths


def rebuild_style_radar(market_data: Dict[str, Any]) -> Dict[str, Any]:
    features = market_data.get("features") or {}
    strengths = features.get("style_strengths") or {}
    if not strengths:
        strengths = calc_style_strengths(features.get("style_inputs") or {})
    palette = features.get("chart_palette") or market_data.get("styleRadar", {}).get("palette") or ["#ef4444", "#f97316", "#f59e0b", "#fb7185"]

    indicators: List[str] = [
        "连板接力",
        "低位试错",
        "20cm弹性",
        "题材集中",
        "资金抱团",
        "高位博弈",
    ]
    values = [
        int(strengths.get("relay_strength", 0)),
        int(strengths.get("low_trial_strength", 0)),
        int(strengths.get("elastic_strength", 0)),
        int(strengths.get("theme_focus_strength", 0)),
        int(strengths.get("capital_focus_strength", 0)),
        int(strengths.get("high_game_strength", 0)),
    ]

    return {
        "styleRadar": {
            "indicators": indicators,
            "values": values,
            "palette": palette,
        }
    }
