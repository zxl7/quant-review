#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
市场风格雷达：强度计算逻辑（与渲染解耦）

目标：
- 你在开发阶段只想优化“风格雷达算法”时，只改这里即可；
- partial 更新时不必重抓取数据：输入来自 marketData.features.style_inputs。
"""

from __future__ import annotations

from typing import Any, Dict

from .scoring import clamp


def calc_style_strengths(style_inputs: Dict[str, Any]) -> Dict[str, int]:
    """
    输入（建议字段，缺失会按 0 处理）：
    - jj_rate: 连板晋级率（0~100）
    - first_board_count: 首板数
    - zt_count: 涨停数
    - gem_today_count: 今日创业板涨停数（300开头）
    - gem_height: 创业板高度（高度趋势的 gem[-1]）
    - top3_theme_ratio: 主线集中度（0~100）
    - top10_concentration: TOP10成交额集中度（0~100）
    - high_level_ratio: 5板+占比（0~100）
    - max_lb: 最高板
    """
    jj_rate = float(style_inputs.get("jj_rate", 0) or 0)
    first_board_count = float(style_inputs.get("first_board_count", 0) or 0)
    zt_count = float(style_inputs.get("zt_count", 0) or 0)
    gem_today_count = float(style_inputs.get("gem_today_count", 0) or 0)
    gem_height = float(style_inputs.get("gem_height", 0) or 0)
    top3_theme_ratio = float(style_inputs.get("top3_theme_ratio", 0) or 0)
    top10_concentration = float(style_inputs.get("top10_concentration", 0) or 0)
    high_level_ratio = float(style_inputs.get("high_level_ratio", 0) or 0)
    max_lb = float(style_inputs.get("max_lb", 0) or 0)

    relay_strength = round(clamp(jj_rate * 1.3, 0, 100))
    low_trial_strength = round(clamp(first_board_count / zt_count * 120 if zt_count else 0, 0, 100))
    elastic_strength = round(clamp(gem_today_count * 12 + gem_height * 10, 0, 100))
    theme_focus_strength = round(clamp(top3_theme_ratio * 1.2, 0, 100))
    capital_focus_strength = round(clamp(top10_concentration * 6, 0, 100))
    # 短线高度突破：适当提高“高度”权重（max_lb）
    high_game_strength = round(clamp(high_level_ratio * 5 + max_lb * 10, 0, 100))

    return {
        "relay_strength": int(relay_strength),
        "low_trial_strength": int(low_trial_strength),
        "elastic_strength": int(elastic_strength),
        "theme_focus_strength": int(theme_focus_strength),
        "capital_focus_strength": int(capital_focus_strength),
        "high_game_strength": int(high_game_strength),
    }
