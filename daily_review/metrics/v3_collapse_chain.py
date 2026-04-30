#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3 崩溃前兆链5级检测引擎

5级逐级扣分（满分10分）:
L1: 追涨者亏钱 (yest_zt_avg_chg < 1%) → -2
L2: 活跃度骤降 (今日涨停较昨日降>30%) → -2
L3: 诱多形态 (指数冲高回落) → -2 (有数据才判断)
L4: 高位补跌 (高度>=5且核按钮>=2) → -2
L5: 大面积崩溃 (跌停>=30) → 直接归0

天地板额外扣3分

此模块也可作为独立分析组件使用。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CollapseChainResult:
    score: float = 10.0             # 崩溃链得分 0-10 (越高越安全)
    level_triggered: int = 0         # 触发的最高级别(1-5)
    deductions: List[str] = field(default_factory=list)  # 扣分明细
    is_dangerous: bool = False       # 是否危险(score<=4)
    warnings: List[str] = field(default_factory=list)     # 警告列表
    confidence: int = 50


def detect_collapse_chain(
    *,
    yest_zt_avg_chg: float = 0.0,
    zt_count_today: int = 0,
    zt_count_yesterday: int = 0,
    max_lianban: int = 0,
    yest_duanban_nuclear: int = 0,
    dt_count: int = 0,
    has_tiandiban: bool = False,
    index_drop_3d: Optional[float] = None,
    has_trap_pattern: bool = False,
) -> CollapseChainResult:
    """
    检测崩溃前兆链。

    Args:
        yest_zt_avg_chg: 昨日涨停票今日平均涨幅%
        zt_count_today / _yesterday: 今日/昨日涨停数
        max_lianban: 最高连板数
        yest_duanban_nuclear: 昨日断板票今日核按钮家数
        dt_count: 非ST跌停家数
        has_tiandiban: 是否有天地板
        index_drop_3d: 近3日指数跌幅%(可选)
        has_trap_pattern: 是否有诱多形态
    """
    score = 10.0
    deductions = []
    level_max = 0

    # L1: 追涨者亏钱
    if yest_zt_avg_chg < 1.0:
        score -= 2.0
        level_max = max(level_max, 1)
        deductions.append(f"L1-追涨亏损(昨均幅{yest_zt_avg_chg:.1f}%)")

    # L2: 活跃度骤降
    if zt_count_yesterday > 0 and zt_count_today >= 0:
        drop_ratio = (zt_count_yesterday - zt_count_today) / max(1, zt_count_yesterday)
        if drop_ratio > 0.30:
            score -= 2.0
            level_max = max(level_max, 2)
            deductions.append(f"L2-活跃骤降({drop_ratio*100:.0f}%)")

    # L3: 诱多形态
    if index_drop_3d is not None:
        if index_drop_3d > 1.0 and has_trap_pattern:
            score -= 2.0
            level_max = max(level_max, 3)
            deductions.append("L3-抄底诱多(指数冲高回落)")

    # L4: 高位补跌
    if max_lianban >= 5 and yest_duanban_nuclear >= 2:
        score -= 2.0
        level_max = max(level_max, 4)
        deductions.append(f"L4-高位补跌(核按钮{yest_duanban_nuclear}家)")

    # L5: 大面积崩溃
    if dt_count >= 30:
        score = 0.0
        level_max = 5
        deductions.append("L5-大面积崩溃!!!")

    # 天地板超级警告
    if has_tiandiban:
        score = max(0, score - 3)
        deductions.append("⚠️天地板")

    # 保护下限
    score = round(max(0.0, min(10.0, score)), 2)

    warnings = []
    is_dangerous = score <= 4
    if is_dangerous:
        warnings.append("🔴 崩溃前兆信号链已触发！高度警惕")
    elif score <= 6:
        warnings.append("⚠️ 出现部分崩溃前兆信号")
    
    conf_base = 70 - level_max * 8
    if index_drop_3d is None:
        conf_base -= 10  # 数据不完整扣置信度
    
    return CollapseChainResult(
        score=score,
        level_triggered=level_max,
        deductions=deductions,
        is_dangerous=is_dangerous,
        warnings=warnings,
        confidence=max(25, min(95, conf_base)),
    )
