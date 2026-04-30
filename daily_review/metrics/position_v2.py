#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模块⑧（v2 规格书）：养家仓位-赢面量化模型

说明（落地版）：
- 严格按规格书结构输出（win_rate / factors / space_ratio / tier / quote / full_position_check）
- 由于部分模块（③龙头、⑥交易性质、④主线强弱）尚在重构中，这里允许输入缺失并降级兜底
"""

from __future__ import annotations

from typing import Any, Dict


def _to_num(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


POSITION_TIERS = {
    (0, 60): {"max_position": 0.00, "action": "观望", "desc": "赢面不足，不操作"},
    (60, 70): {"max_position": 0.20, "action": "小仓出击", "desc": "赢面一般，试探性参与"},
    (70, 80): {"max_position": 0.40, "action": "中仓出击", "desc": "赢面较好，适度参与"},
    (80, 90): {"max_position": 0.70, "action": "大仓出击", "desc": "赢面很好，积极参与"},
    (90, 101): {"max_position": 1.00, "action": "满仓出击", "desc": "赢面极佳，重拳出击"},
}


def _match_position_tier(win_rate: float) -> Dict[str, Any]:
    for (lo, hi), tier in POSITION_TIERS.items():
        if lo <= win_rate < hi:
            return {**tier, "range": [lo, hi]}
    return {**POSITION_TIERS[(0, 60)], "range": [0, 60]}


def _validate_full_position(win_rate: float, upside: float, downside: float) -> Dict[str, Any]:
    condition1 = win_rate >= 90
    condition2 = (upside >= 0.30) and (downside <= 0.05)
    if condition1 and condition2:
        return {"passed": True, "msg": "✅ 通过养家满仓双条件校验"}
    if condition1 and not condition2:
        return {
            "passed": False,
            "msg": f"⚠️ 胜率达标({win_rate:.1f}%≥90%)但盈亏比不足（上行{upside*100:.0f}%需≥30%, 下行{downside*100:.0f}%需≤5%）",
        }
    if (not condition1) and condition2:
        return {"passed": False, "msg": f"⚠️ 盈亏比达标但胜率不足({win_rate:.1f}%<90%)"}
    return {"passed": False, "msg": "❌ 双条件均不满足，禁止满仓"}


def _yangjia_quote(win_rate: float) -> str:
    if win_rate >= 90:
        return '"满仓出击时，胜率必须90%+，上涨空间至少看到30-50%，下跌空间控制在3-5%。胜负的事情交给概率。"'
    if win_rate >= 80:
        return '"大仓出击，力求更大限度博取利润。"'
    if win_rate >= 70:
        return '"中仓出击，市场有一定机会。"'
    if win_rate >= 60:
        return '"小仓出击，试探性参与。"'
    return '"赢面60%以下——观望。看看天气，如果觉得要下雨了，就早点回家。"'


def calc_win_rate(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    context（建议字段）：
    - sentiment_score: 0~10（模块①）
    - mainline: {exists: bool, strength: str}
    - dragon_overall_score: 0~10（模块③，暂无则用5）
    - nature_compatible: bool（模块⑥，暂无则用False）
    - upside_potential: 0~1（预期上涨空间，默认0.10）
    - downside_risk: 0~1（预期下跌风险，默认0.05）
    """
    ctx = context or {}

    sentiment_score = _to_num(ctx.get("sentiment_score"), 5.0)
    factor_sentiment = _clamp(sentiment_score * 10.0, 0, 100)

    mainline = ctx.get("mainline") or {}
    exists = bool(mainline.get("exists") or False)
    strength = str(mainline.get("strength") or "")
    factor_mainline = 100 if exists else (60 if "弱" in strength else 20)

    dragon_score = _to_num(ctx.get("dragon_overall_score"), 5.0)
    factor_dragon = _clamp(dragon_score * 10.0, 0, 100)

    nature_compat = bool(ctx.get("nature_compatible") or False)
    factor_nature = 80 if nature_compat else 30

    win_rate = (
        factor_sentiment * 0.40
        + factor_mainline * 0.20
        + factor_dragon * 0.20
        + factor_nature * 0.20
    )

    upside = _to_num(ctx.get("upside_potential"), 0.10)
    downside = _to_num(ctx.get("downside_risk"), 0.05)
    space_ratio = upside / max(downside, 0.01)

    if space_ratio >= 8:
        space_adj = 1.15
    elif space_ratio >= 5:
        space_adj = 1.08
    elif space_ratio >= 3:
        space_adj = 1.0
    elif space_ratio >= 2:
        space_adj = 0.90
    else:
        space_adj = 0.75

    final_win_rate = _clamp(win_rate * space_adj, 0, 100)
    tier = _match_position_tier(final_win_rate)

    full_position_check = None
    if tier.get("max_position", 0) >= 1.0:
        full_position_check = _validate_full_position(final_win_rate, upside, downside)

    return {
        "win_rate": round(final_win_rate, 1),
        "factors": {
            "情绪周期": round(factor_sentiment, 1),
            "主线清晰": round(float(factor_mainline), 1),
            "龙头地位": round(factor_dragon, 1),
            "性质适配": round(float(factor_nature), 1),
        },
        "space_ratio": round(space_ratio, 1),
        "tier": tier,
        "quote": _yangjia_quote(final_win_rate),
        "full_position_check": full_position_check,
        "inputs": {
            "upside_potential": upside,
            "downside_risk": downside,
        },
    }

