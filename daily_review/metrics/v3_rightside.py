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
from typing import Dict, List, Optional


@dataclass
class RightSideResult:
    score: int = 0                    # 信号得分 0-5
    allowed: bool = False              # 是否允许右侧交易
    decision: str = "wait"             # allow / wait / forbid
    mainline_name: str = ""
    signals: Dict[str, bool] = field(default_factory=dict)  # 各信号是否满足
    violations: List[str] = field(default_factory=list)       # 左侧禁区违规列表
    pending: List[str] = field(default_factory=list)           # 需要等待确认的软条件
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
    planned: Optional[bool] = None,
) -> RightSideResult:
    """检查右侧交易5信号，返回完整判定结果"""
    signals_hit = {}
    score = 0
    violations = []
    pending = []
    mainline_name = ""

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
        mainstream = sector_data if isinstance(sector_data, dict) else {}
        mainline = mainstream.get("mainline") if isinstance(mainstream.get("mainline"), dict) else {}
        sector_ladder = mainstream.get("sector_ladder") if isinstance(mainstream.get("sector_ladder"), dict) else {}
        top_theme = mainstream.get("top_theme") if isinstance(mainstream.get("top_theme"), dict) else {}

        ladder_health = float(
            sector_data.get("ladder_health")
            or sector_ladder.get("health_score")
            or ((sector_data.get("ladder") or {}) if isinstance(sector_data.get("ladder"), dict) else {}).get("health_score")
            or 0
        )
        zt_count = int(
            sector_data.get("zt_count")
            or sector_ladder.get("total_count")
            or top_theme.get("count")
            or 0
        )
        mainline_name = str(
            mainline.get("top_sector")
            or top_theme.get("name")
            or sector_data.get("top_sector")
            or ""
        )
        mainline_exists = bool(mainline.get("exists")) if mainline else bool(mainline_name and zt_count >= 5)
        sector_has_ladder = (ladder_health >= 3 and zt_count >= 3) or zt_count >= 5
        if mainline_exists and zt_count >= 3:
            sector_has_ladder = True
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
    has_catalyst = len(str(catalyst_text).strip()) > 2 or bool(mainline_name)
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
        if rotation_freq >= 4 and not theme_clear:
            violations.append("no_clear_theme")
        else:
            pending.append("主线梯队还不够清晰")

    if stock_data and not stock_volume_up:
        amount = float(stock_data.get("amount", 0) or 0)
        if amount < 5e7:  # 成交额<5000万
            violations.append("low_volume")

    if sentiment_score <= 4.0:
        violations.append("weak_phase_boarding")
    if planned is False:
        violations.append("impulse_trade")
    elif not has_catalyst:
        pending.append("缺少明确催化/主线证据")

    allowed = score >= 4 and len(violations) == 0
    decision = "allow" if allowed else ("forbid" if violations else "wait")
    conf_base = 66 + score * 6 - len(violations) * 14 - len(pending) * 5

    # 生成建议
    if allowed:
        advice = f"✅ 右侧条件较完整（{score}/5）。按计划做主线核心确认点，优先回封/弱转强，仓位不超过{30 if score <=4 else 50}%。"
    elif violations:
        label_map = {k: v for k, v in LEFT_SIDE_FORBIDDEN}
        vtxt = "；".join([label_map.get(v, v).split(" — ")[0] for v in violations[:2]])
        advice = f"⛔ 硬风控触发（{vtxt}）。明日不做接力，只观察主线是否修复。"
    elif score >= 3:
        wait_txt = "；".join(pending[:2]) if pending else "仍需开盘承接确认"
        advice = f"⚠️ {score}/5信号进入观察。{wait_txt}，只做计划内候选的回封/弱转强，未确认就等。"
    else:
        advice = f"⏳ {score}/5信号不足。等待指数、主线、个股量能至少补齐两项后再考虑。"

    return RightSideResult(
        score=score,
        allowed=allowed,
        decision=decision,
        mainline_name=mainline_name,
        signals={k: v for k, v in zip([s[0] for s in RIGHT_SIDE_SIGNALS], [signals_hit.get(s[0], False) for s in RIGHT_SIDE_SIGNALS])},
        violations=violations,
        pending=pending,
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
