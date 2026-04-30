#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3 反弹三阶段策略引擎

反弹三阶段:
初期(强势反抽): 急跌后V型反弹，龙头率先反包 → 只做龙头反包/最强首板
中期(超跌反弹): 指数企稳，超跌板块轮动反弹 → 可做超跌首板，回避高位接力
末期(爆发力): 反弹加速，补涨扩散 → 可做补涨龙/弹性票，注意随时结束

识别依据:
- 初期: 指数大阳线(>2%) + 高位核按钮开始减少
- 中期: 指数横盘震荡 + 跌停家数稳定<10
- 末期: 涨停家数连续增加 + 连板高度突破前期压制
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class ReboundPhase(Enum):
    INITIAL = ("初期-强势反抽", "龙头率先反包", "只做龙头反包/最强首板")
    MID = ("中期-超跌反弹", "超跌板块轮动", "可做超跌首板，回避高位接力")
    LATE = ("末期-爆发力", "补涨扩散", "可做补涨龙/弹性票，注意随时结束")
    NONE = ("无反弹信号", "", "")


@dataclass
class ReboundResult:
    phase: ReboundPhase = ReboundPhase.NONE
    detail: Dict[str, Any] = field(default_factory=dict)
    strategy: Dict[str, Any] = field(default_factory=dict)
    confidence: int = 50


# 各阶段策略配置
REBOUND_STRATEGY = {
    ReboundPhase.INITIAL: {
        "what_to_do": "只做龙头(>=3板)反包板和最强题材首板",
        "position": "≤30%",
        "forbidden": ["跟风股", "无辨识度的首板", "非主线"],
        "tactics": "打板/半路（仅限龙头）",
        "duration": "通常1-3天",
    },
    ReboundPhase.MID: {
        "what_to_do": "可做超跌板块的首板，不做高位连板接力",
        "position": "20%-40%",
        "forbidden": [">=4板接力", "无业绩支撑的纯概念", "缩量加速板"],
        "tactics": "低吸/首板打板",
        "duration": "3-7天",
    },
    ReboundPhase.LATE: {
        "what_to_do": "可做补涨龙和弹性票，随时准备撤退",
        "position": "逐步从50%降至20%",
        "forbidden": ["新开仓追高", "满仓", "忽视退潮信号"],
        "tactics": "兑现利润为主，不新开重仓",
        "duration": "1-3天后可能转退潮",
    },
}


def identify_rebound_phase(market_data: Dict[str, Any]) -> ReboundResult:
    """识别当前处于反弹的哪个阶段"""
    
    # 提取关键数据
    index_chg = float(market_data.get("index_chg_today", 0) or 0)
    dt_count = int(market_data.get("dt_count", 0) or 0)
    zt_count = int(market_data.get("zt_count", 0) or 0)
    zt_yest = int(market_data.get("zt_count_yesterday", 0) or 0)
    nuclear_cnt = int(market_data.get("nuclear_count", 0) or 0)
    nuclear_yest = int(market_data.get("nuclear_count_yesterday", 0) or 0)
    sentiment_score = float(market_data.get("sentiment_score", 5) or 5)
    max_lb = int(market_data.get("max_lianban", 0) or 0)

    # 判断逻辑
    signals = []
    phase = ReboundPhase.NONE

    # 初期特征：大阳 + 核按钮减少
    if (index_chg >= 2.0 and nuclear_yest >= 3 and nuclear_cnt < nuclear_yest):
        phase = ReboundPhase.INITIAL
        signals.append(f"指数大阳+{index_chg:.1f}%且核按钮从{nuclear_yest}→{nuclear_cnt}")

    # 中期特征：指数企稳 + 跌停可控
    elif (abs(index_chg) < 1.5 and dt_count <= 10 and 2 <= zt_count <= 40 and sentiment_score < 6.5):
        # 进一步确认是否是中期（排除冰点）
        if zt_count >= 15 and max_lb <= 4:
            phase = ReboundPhase.MID
            signals.append(f"指数企稳(±{index_chg:.1f}%), 跌停{dt_count}家可控")

    # 末期特征：涨停增加 + 高度突破
    elif (zt_count > zt_yest * 1.15 and zt_count >= 35 and max_lb >= 4):
        phase = ReboundPhase.LATE
        signals.append(f"涨停扩散({zt_yest}→{zt_count}), 高度{max_lb}板突破压制")

    # 无反弹信号
    else:
        if sentiment_score < 4:
            signals.append("情绪冰点，暂无反弹迹象")
        elif sentiment_score > 7:
            signals.append("市场偏强，不属于反弹范畴")
        else:
            signals.append("无明显反弹特征，可能是震荡或下跌中继")

    strategy = REBOUND_STRATEGY.get(phase, {})
    conf_base = 60 if phase != ReboundPhase.NONE else 40
    conf = min(90, conf_base + len(signals) * 8)

    return ReboundResult(
        phase=phase,
        detail={
            "signals": signals,
            "index_chg": round(index_chg, 2),
            "dt_count": dt_count,
            "zt_change": f"{zt_yest}→{zt_count}",
            "nuclear_change": f"{nuclear_yest}→{nuclear_cnt}",
            "sentiment": round(sentiment_score, 1),
        },
        strategy=strategy,
        confidence=conf,
    )
