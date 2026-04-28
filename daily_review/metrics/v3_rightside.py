#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3 右侧交易确认框架

右侧入场5信号(每信号1分):
1. 指数站上5日线 (+1)
2. 板块有涨停梯队(+1)
3. 目标股放量(+1)
4. 有明确催化剂(+1)
5. 情绪评分>=5.5(+1)

得分>=3 → 允许右侧交易; <3 → 禁止

左侧禁区(绝对不做):
- 指数在20日均线下方
- 主线不明或快轮动
- 目标股无成交量支撑
- 弱修复/冰点期打板
- 无计划临时起意
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RightSideResult:
    score: int = 0                    # 信号得分 0-5
    allowed: bool = False              # 是否允许右侧交易
    signals: Dict[str, bool] = field(default_factory=dict)  # 各信号是否满足
    violations: List[str] = field(default_factory=list)       # 左侧禁区违规列表
    advice: str = ""
    confidence: int = 50


# 右侧入场5个信号定义
RIGHT_SIDE_SIGNALS = [
    ("index_above_ma5", "指数站上5日线"),
    ("sector_has_ladder", "板块有涨停梯队"),
    ("stock_volume_up", "目标股放量"),
    ("has_catalyst", "有明确催化剂"),
    ("sentiment_ok", "情绪评分>=5.5"),
]

# 左侧禁区规则
LEFT_SIDE_FORBIDDEN = [
    ("index_below_ma20", "指数在20日均线下方 — 绝对不参与"),
    ("no_clear_theme", "主线不明或快速轮动 — 等待方向明确"),
    ("low_volume", "目标股无成交量支撑 — 容易被埋"),
    ("weak_phase_boarding", "弱修复/冰点期打板 — T+1无法纠错"),
    ("impulse_trade", "无计划临时起意 — 禁止一切临时操作"),
]

# 风控4铁律
IRON_RULES = [
    "① 单票仓位 ≤ 总资产30%",
    "② 日内亏损达总资产2% → 停止操作",
    "③ 禁止临时起意，只做计划内操作",
    "④ 手风不顺 → 第二天赚钱就走",
]


def check_right_side_signals(
    *,
    index_data: Optional[Dict] = None,
    sector_data: Optional[Dict] = None,
    stock_data: Optional[Dict] = None,
    sentiment_score: float = 5.0,
    catalyst_text: str = "",
) -> RightSideResult:
    """检查右侧交易5信号，返回完整判定结果"""
    signals_hit = {}
    score = 0
    violations = []

    # 信号1：指数站上5日线
    idx_above_ma5 = True  # 默认允许（无数据时不扣分）
    if index_data:
        ma5_val = float(index_data.get("ma5", 0) or 0)
        idx_price = float(index_data.get("price", 0) or 0)
        if ma5_val > 0 and idx_price > 0:
            idx_above_ma5 = idx_price >= ma5_val
        elif not ma5_val:
            idx_above_ma5 = True  # 无MA数据默认通过
    signals_hit["index_above_ma5"] = idx_above_ma5
    if idx_above_ma5:
        score += 1

    # 信号2：板块有涨停梯队
    sector_has_ladder = True
    if sector_data:
        ladder_health = float(sector_data.get("ladder_health", 0) or 0)
        zt_count = int(sector_data.get("zt_count", 0) or 0)
        sector_has_ladder = (ladder_health >= 3 and zt_count >= 3) or zt_count >= 5
    signals_hit["sector_has_ladder"] = sector_has_ladder
    if sector_has_ladder:
        score += 1

    # 信号3：目标股放量
    stock_volume_up = True
    if stock_data:
        vol_ratio = float(stock_data.get("volume_ratio", 1) or 1)
        amount = float(stock_data.get("amount", 0) or 0)
        stock_volume_up = vol_ratio >= 1.2 or amount >= 3e8  # 放量或成交额>=3亿
    signals_hit["stock_volume_up"] = stock_volume_up
    if stock_volume_up:
        score += 1

    # 信号4：有催化剂
    has_catalyst = len(str(catalyst_text).strip()) > 2
    signals_hit["has_catalyst"] = has_catalyst
    if has_catalyst:
        score += 1

    # 信号5：情绪评分OK
    sent_ok = sentiment_score >= 5.5
    signals_hit["sentiment_ok"] = sent_ok
    if sent_ok:
        score += 1

    # 左侧禁区检查
    if index_data and not idx_above_ma5:
        ma20_val = float(index_data.get("ma20", 0) or 0)
        idx_price = float(index_data.get("price", 0) or 0)
        if ma20_val > 0 and idx_price < ma20_val:
            violations.append("index_below_ma20")

    if sector_data and not sector_has_ladder:
        theme_clear = bool(sector_data.get("main_theme_clear", False))
        rotation_freq = int(sector_data.get("theme_rotation_freq", 0) or 0)
        if not theme_clear or rotation_freq >= 3:
            violations.append("no_clear_theme")

    if stock_data and not stock_volume_up:
        amount = float(stock_data.get("amount", 0) or 0)
        if amount < 5e7:  # 成交额<5000万
            violations.append("low_volume")

    if sentiment_score <= 4.0:
        violations.append("weak_phase_boarding")
    if not has_catalyst:
        violations.append("impulse_trade")

    allowed = score >= 3 and len(violations) == 0
    conf_base = 70 + score * 6 - len(violations) * 10

    # 生成建议
    if allowed:
        advice = f"✅ 右侧交易许可({score}/5信号)。建议按计划执行，仓位不超过{30 if score <=3 else 50}%。"
    elif score >= 3 and violations:
        advice = f"⚠️ {score}/5信号达标但有{len(violations)}条左侧违规: {'; '.join(violations[:2])}。建议降低仓位或等待。"
    else:
        advice = f"❌ 右侧交易禁止({score}/5信号不足或有严重违规)。建议观望或仅极小仓试错。"

    return RightSideResult(
        score=score,
        allowed=allowed,
        signals={k: v for k, v in zip([s[0] for s in RIGHT_SIDE_SIGNALS], [signals_hit.get(s[0], False) for s in RIGHT_SIDE_SIGNALS])},
        violations=violations,
        advice=advice,
        confidence=max(25, min(100, conf_base)),
    )


def right_side_decision(stock_info, market_context) -> RightSideResult:
    """
    便捷函数：从市场上下文中提取参数后调用check_right_side_signals。
    兼容旧接口风格。
    """
    idx = market_context.get("indices")
    # 兼容：indices 可能是 list[dict] 或 dict
    if isinstance(idx, list):
        idx = idx[0] if idx and isinstance(idx[0], dict) else None
    elif not isinstance(idx, dict):
        idx = None

    return check_right_side_signals(
        index_data=idx,
        sector_data=market_context.get("mainline") or market_context.get("themePanels"),
        stock_data=stock_info,
        sentiment_score=float(market_context.get("sentiment_score", market_context.get("score", 5)) or 5),
        catalyst_text=str(market_context.get("catalyst", "") or ""),
    )
