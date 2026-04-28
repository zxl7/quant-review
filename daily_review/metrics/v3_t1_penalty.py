#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3 T+1流动性惩罚因子

A股T+1制度意味着今天买的明天才能卖:
- 弱势阶段买错了当天无法纠错 → 应该更保守
- 周五买入要承受周末不确定性 → 小幅惩罚
- 高波动环境（高炸板率）→ 打板后被埋概率高 → 惩罚
- 冰点期额外20%惩罚（最危险时段）
"""

from __future__ import annotations
from typing import Any, Dict, Optional


def calc_t1_penalty(
    *,
    sentiment_score: float,
    phase: str = "",
    zab_rate: float = 0.0,
    is_friday: bool = False,
    rebound_phase: Optional[str] = None,
) -> Dict[str, Any]:
    """
    计算T+1流动性惩罚。

    返回: {
        penalty_ratio: float,      # 惩罚比例 0~0.35 (即0%~35%)
        penalty_pct: str,           # 可读格式 "15%"
        reasons: list[str],         # 惩罚原因列表
        adjusted_position: callable, # 接受原始仓位比例返回调整后仓位
    }
    """
    penalty = 0.0
    reasons = []

    # ─── 基础阶段惩罚 ───
    if sentiment_score <= 2.0:
        penalty += 0.20
        reasons.append(f"冰点期(评分{sentiment_score:.1f}): 多扣20%")
    elif sentiment_score <= 4.0:
        penalty += 0.12
        reasons.append(f"严冬期(评分{sentiment_score:.1f}): 扣12%")
    elif sentiment_score <= 5.5:
        penalty += 0.08
        reasons.append(f"僵持/弱修复(评分{sentiment_score:.1f}): 扣8%")

    # ─── 周末惩罚 ───
    if is_friday:
        penalty += 0.05
        reasons.append("周五买入承受周末不确定性: 扣5%")

    # ─── 高波动惩罚 ───
    if zab_rate > 45:
        penalty += 0.08
        reasons.append(f"炸板率极高({zab_rate:.0f}%): 扣8%")
    elif zab_rate > 35:
        penalty += 0.04
        reasons.append(f"炸板率高({zab_rate:.0f}%): 扣4%")

    # ─── 反弹中期额外保守 ───
    if rebound_phase and "MID" in str(rebound_phase).upper():
        penalty += 0.10
        reasons.append("反弹中期超跌反弹本身风险高: 扣10%")

    # 上限保护
    penalty = min(0.35, max(0.0, penalty))

    def adjust_position(raw_capital_pct: float) -> float:
        """接受原始仓位比例(0-1)，返回T+1调整后的仓位比例"""
        return max(0.0, round(raw_capital_pct * (1 - penalty), 2))

    return {
        "penalty_ratio": round(penalty, 2),
        "penalty_pct": f"{penalty*100:.0f}%",
        "reasons": reasons,
        "adjust_position": adjust_position,
        "is_significant": penalty >= 0.15,  # 是否值得特别提示用户
    }
