#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3 置信度评分系统 — 每个算法模块输出附加confidence(0-100%)字段

置信度评估维度:
- 数据完整度: 关键字段是否齐全
- 样本量充足性: 统计样本是否足够
- 维度一致性: 各子维度评价是否矛盾
- 时效性: 数据是否是最新
"""

from __future__ import annotations
import statistics
from typing import Dict


def calc_confidence(
    *,
    data_completeness: float = 100.0,   # 数据完整度 0-100
    sample_size_score: float = 100.0,   # 样本量得分 0-100
    dimension_consistency: float = 100.0, # 维度一致性 0-100
    timeliness: float = 100.0,          # 时效性 0-100
    extra_deductions: float = 0.0,       # 额外扣分
) -> int:
    """
    计算综合置信度分数(0-100)。

    使用方法: 每个v3模块调用此函数计算自身输出的置信度。
    """
    raw = (
        data_completeness * 0.30 +
        sample_size_score * 0.25 +
        dimension_consistency * 0.25 +
        timeliness * 0.20
    ) - extra_deductions

    return max(10, min(100, int(round(raw))))


def assess_dim_consistency(dim_scores: Dict[str, float]) -> tuple:
    """
    评估各维度评分的一致性。
    返回: (consistency_score 0-100, std_dev, verdict_str)
    """
    values = list(dim_scores.values())
    if not values:
        return 50.0, 0.0, "无数据"

    try:
        std = statistics.stdev(values)
    except statistics.StatisticsError:
        std = 0.0

    if std <= 1.0:
        score = 100.0
        verdict = "各维度高度一致"
    elif std <= 2.0:
        score = 85.0
        verdict = "各维度基本一致"
    elif std <= 3.0:
        score = 65.0
        verdict = "各维度有一定分歧"
    else:
        score = 40.0
        verdict = f"各维度严重分歧(std={std:.1f})，建议人工复核"

    return score, std, verdict


def get_confidence_label(confidence: int) -> str:
    """将置信度数值转为可读标签"""
    if confidence >= 90: return "🟢 高度可信"
    elif confidence >= 70: return "🟡 较可信"
    elif confidence >= 50: return "🟠 参考价值有限"
    else: return "🔴 低置信度，建议谨慎参考"
