#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3 养家仓位-赢面五档映射模型

赢面(胜率*赔率) → 仓位:
60%及以下: 空仓 (市场无机会)
60%-70%: ≤20%仓 (试错仓)
70%-80%: 20%-50%仓 (正常操作)
80%-90%: 50%-80%仓 (重仓出击)
90%以上: 满仓 (但需满足满仓三条件共振双校验)

额外因子修正:
- T+1惩罚因子
- 周末效应(-5%)
- 个人状态不佳(-10%~ -20%)
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class WinRatePosition:
    win_rate: float = 0.0       # 胜率评估 0-100%
    odds_ratio: float = 1.0     # 赔率 (平均盈利/平均亏损)
    edge: float = 0.0           # 赢面 = 胜率 * 赔率因子
    tier: str = ""              # 五档之一
    max_position: float = 0.0   # 最大仓位比例 0-1
    position_range: str = ""    # 如 "20%-50%"
    t1_adjusted: float = 0.0    # T+1惩罚后仓位
    confidence: int = 50


# 五档配置
TIER_CONFIG = [
    {"min_edge": 0.90, "tier": "满仓区", "max_pos": 1.00, "range": "80%-100%"},
    {"min_edge": 0.80, "tier": "重仓区", "max_pos": 0.80, "range": "50%-80%"},
    {"min_edge": 0.70, "tier": "正常区", "max_pos": 0.50, "range": "20%-50%"},
    {"min_edge": 0.60, "tier": "试错区", "max_pos": 0.20, "range": "≤20%"},
    {"min_edge": 0.0,  "tier": "空仓区", "max_pos": 0.0,  "range": "空仓"},
]


def calc_win_rate_position(
    *,
    win_rate: float = 50.0,
    odds_ratio: float = 1.5,
    sentiment_score: float = 5.0,
    t1_penalty_ratio: float = 0.0,
    is_friday: bool = False,
    personal_state: str = "normal",  # normal / tired / tilted / absent
    full_position_passed: bool = False,
) -> WinRatePosition:
    """
    计算仓位建议。

    Args:
        win_rate: 预估胜率 0-100%
        odds_ratio: 赔率 (盈亏比)
        sentiment_score: 市场情绪评分 0-10
        t1_penalty_ratio: T+1惩罚系数 0-0.35
        is_friday: 是否周五
        personal_state: 个人状态
        full_position_passed: 是否通过满仓三条件校验
    """
    # 保护异常输入
    win_rate = max(0.0, min(100.0, win_rate))
    odds_ratio = max(0.1, min(10.0, odds_ratio))

    # 计算赢面（凯利公式简化版）
    if odds_ratio > 0:
        edge_raw = (win_rate / 100.0) * (2.0 - 1.0 / max(0.5, odds_ratio)) + (win_rate - 50) / 200.0
    else:
        edge_raw = 0.0
    edge = round(max(0.0, min(1.2, edge_raw)), 2)

    # 匹配档位
    tier_info = TIER_CONFIG[4]  # 默认空仓
    for tc in TIER_CONFIG:
        if edge >= tc["min_edge"]:
            tier_info = tc
            break

    max_pos = tier_info["max_pos"]

    # T+1惩罚修正
    t1_adjusted = max(0.0, round(max_pos * (1 - t1_penalty_ratio), 2))

    # 周末额外扣减
    if is_friday:
        t1_adjusted *= 0.95

    # 个人状态扣减
    state_penalty = {
        "normal": 1.0,
        "tired": 0.85,
        "tilted": 0.6,
        "absent": 0.0,  # 状态不佳直接空仓
    }
    penalty_factor = state_state.get(personal_state, 1.0) if 'state_state' in dir() else state_penalty.get(personal_state, 1.0)
    # fix: correct variable name reference
    _sp = {"normal": 1.0, "tired": 0.85, "tilted": 0.6, "absent": 0.0}
    penalty_factor = _sp.get(personal_state, 1.0)
    final_pos = round(t1_adjusted * penalty_factor, 2)

    # 满仓安全阀
    if not full_position_passed and final_pos >= 0.9:
        final_pos = 0.7
        tier_info = TIER_CONFIG[1]

    conf = min(95, int(50 + win_rate * 0.3 + (edge * 30)))

    return WinRatePosition(
        win_rate=round(win_rate, 1),
        odds_ratio=round(odds_ratio, 2),
        edge=edge,
        tier=tier_info["tier"],
        max_position=final_pos,
        position_range=tier_info["range"],
        t1_adjusted=t1_adjusted,
        confidence=conf,
    )
