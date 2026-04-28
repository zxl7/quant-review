#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3 交易性质六分类系统

六种交易性质:
1. 龙头首阴 — 龙头股第一次收阴(未跌停)，博弈反包
2. 反包板 — 昨日断板/大跌今日涨停反包
3. 连板接力 — 买入连板股博继续涨停
4. 低位首板 — 第一板，位置低(非连板)
5. 趋势中继 — 趋势股的日常回调后买点
6. 超跌反弹 — 大幅下跌后的反弹买点
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TradeNature(Enum):
    """六种交易性质。value = (名称, 风险等级, 最大仓位, 止损线, 目标收益)"""
    DRAGON_FIRST_YIN = ("龙头首阴", "高风险高回报", "30%", "-5%", "8~15%")
    REBOUND_BOARD = ("反包板", "中高风险", "25%", "-4%", "6~12%")
    RELAY_BOARD = ("连板接力", "高风险", "20%", "-3%", "5~10%")
    LOW_FIRST_BOARD = ("低位首板", "中低风险", "40%", "-3%", "3~8%")
    TREND_CONTINUE = ("趋势中继", "中风险", "35%", "-4%", "5~10%")
    OVERSOLD_REBOUND = ("超跌反弹", "中风险", "25%", "-5%", "6~15%")

    @property
    def name(self) -> str:
        return self.value[0]

    @property
    def risk_level(self) -> str:
        return self.value[1]

    @property
    def max_position(self) -> str:
        return self.value[2]

    @property
    def stop_loss(self) -> str:
        return self.value[3]

    @property
    def target_gain(self) -> str:
        return self.value[4]


# 每种交易性质的详细规则
TRADE_NATURE_RULES: Dict[TradeNature, Dict[str, Any]] = {
    TradeNature.DRAGON_FIRST_YIN: {
        "valid_phases": ["修复期", "亢奋前期"],
        "min_sentiment": 5.5,
        "tactics": "低吸为主",
        "forbidden_phases": ["冰点", "弱修复", "退潮"],
        "key_condition": "龙头股(>=3板)首次收阴且未跌停",
    },
    TradeNature.REBOUND_BOARD: {
        "valid_phases": ["修复期", "亢奋前期", "弱修复"],
        "min_sentiment": 4.0,
        "tactics": "打板/半路",
        "forbidden_phases": ["冰点", "退潮确认"],
        "key_condition": "昨日断板或大跌(> -5%)今日强势涨停",
    },
    TradeNature.RELAY_BOARD: {
        "valid_phases": ["修复期", "亢奋前期"],
        "min_sentiment": 6.0,
        "tactics": "打板/竞价/回封",
        "forbidden_phases": ["冰点", "弱修复", "分歧", "退潮"],
        "key_condition": "连板股(>=2板)博弈继续涨停",
    },
    TradeNature.LOW_FIRST_BOARD: {
        "valid_phases": ["冰点边缘", "弱修复", "修复期", "亢奋前期"],
        "min_sentiment": 3.0,
        "tactics": "打板/半路",
        "forbidden_phases": ["退潮确认"],
        "key_condition": "第一板，非连板，有板块支撑",
    },
    TradeNature.TREND_CONTINUE: {
        "valid_phases": ["修复期", "亢奋前期", "亢奋高潮"],
        "min_sentiment": 5.5,
        "tactics": "低吸/回踩均线",
        "forbidden_phases": ["冰点", "弱修复", "退潮"],
        "key_condition": "趋势股缩量回调至关键均线",
    },
    TradeNature.OVERSOLD_REBOUND: {
        "valid_phases": ["冰点边缘", "弱修复", "修复期"],
        "min_sentiment": 3.0,
        "tactics": "低吸/首板",
        "forbidden_phases": ["退潮确认"],
        "key_condition": "短期跌幅>20%后出现止跌信号",
    },
}


@dataclass
class TradeNatureResult:
    nature: Optional[TradeNature] = None
    compatible: bool = False
    warning: str = ""
    rules: Dict[str, Any] = field(default_factory=dict)
    confidence: int = 50


def determine_trade_nature(
    stock_info: Dict[str, Any],
    market_context: Dict[str, Any],
) -> TradeNatureResult:
    """
    判断给定股票的交易性质。

    Args:
        stock_info: 个股数据（需含 consecutive_boards, chg_pct, yest_chg_pct 等）
        market_context: 市场上下文（需含 sentiment_score, phase 等）
    """
    boards = int(stock_info.get("consecutive_boards", 0) or 0)
    chg_pct = float(stock_info.get("chg_pct", 0) or 0)
    yest_chg = float(stock_info.get("yest_chg_pct", 0) or 0)
    is_zt = bool(stock_info.get("is_zt", False))
    sentiment = float(market_context.get("sentiment_score", 5) or 5)
    phase = str(market_context.get("phase", ""))

    nature = None
    warning = ""
    conf = 50

    # 判断逻辑
    if boards >= 3 and not is_zt and chg_pct > -9.5:
        nature = TradeNature.DRAGON_FIRST_YIN
        warning = f"{boards}板龙头首阴" if chg_pct < 0 else f"{boards}板假阴(实际收阳)"
        conf = 75 if boards >= 5 else 60
    elif yest_chg <= -5 and is_zt:
        nature = TradeNature.REBOUND_BOARD
        warning = f"反包板(昨{yest_chg:.0f}%今涨停)"
        conf = 70
    elif boards >= 2 and is_zt:
        nature = TradeNature.RELAY_BOARD
        warning = f"{boards}板连板接力"
        conf = 65 if boards >= 4 else 55
    elif boards <= 1 and is_zt:
        nature = TradeNature.LOW_FIRST_BOARD
        warning = "低位首板"
        conf = 60
    elif not is_zt and -3 < chg_pct < 3 and stock_info.get("is_trend", False):
        nature = TradeNature.TREND_CONTINUE
        warning = "趋势中继"
        conf = 55
    elif float(stock_info.get("drawdown_5d", 0) or 0) > 20 and chg_pct > 3:
        nature = TradeNature.OVERSOLD_REBOUND
        warning = f"超跌反弹({stock_info.get('drawdown_5d', 0):.0f}%回调)"
        conf = 58

    # 兼容性检查
    compatible = True
    rules = {}
    if nature:
        rules = TRADE_NATURE_RULES.get(nature, {})
        # 检查阶段是否允许
        forbidden = rules.get("forbidden_phases", [])
        for fp in forbidden:
            if fp in phase:
                compatible = False
                warning += f" [⚠️当前阶段'{phase}'不建议此性质]"
                conf -= 15
                break

        # 检查情绪分数是否达标
        min_sent = rules.get("min_sentiment", 0)
        if sentiment < min_sent:
            compatible = False if sentiment < min_sent - 1.5 else compatible
            warning += f" [情绪{sentiment:.1f}<要求{min_sent}]"

    conf = max(20, min(100, conf))

    return TradeNatureResult(
        nature=nature,
        compatible=compatible,
        warning=warning,
        rules=rules,
        confidence=conf,
    )


def batch_classify_trade_nature(
    stocks: List[Dict[str, Any]],
    market_context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """批量判断多只股票的交易性质"""
    results = []
    for s in stocks:
        r = determine_trade_nature(s, market_context)
        results.append({
            **s,
            "_v3_nature": r.nature.name if r.nature else None,
            "_v3_compatible": r.compatible,
            "_v3_warning": r.warning,
            "_v3_confidence": r.confidence,
        })
    return results
