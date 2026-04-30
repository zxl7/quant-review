#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模块⑥（v2 规格书，落地版）：交易性质六分类系统

目标：
- 输出一个“交易性质判定”，给策略引擎做：
  1) 允许战术（allowed_tactics）
  2) 单票/总仓位上限（position_limit）
  3) 止损规则（stop_loss）
- 由于当前数据源偏“市场级 + 涨停池”，个股级细颗粒信号不足，
  本实现先给出可落地的默认判定与兜底路径：
  - 有主线/有真龙/右侧允许 → 更偏“连板接力/回封”
  - 无主线/右侧不允许/冰点 → “观望/超短试错”
"""

from __future__ import annotations

from typing import Any, Dict


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        if isinstance(v, str) and v.endswith("%"):
            v = v[:-1]
        return float(v)
    except Exception:
        return default


TRADE_NATURES = {
    "RELAY_BOARD": {
        "label": "连板接力",
        "best_phase": ["亢奋期", "修复期"],
        "forbidden_phase": ["冰点期", "深冰点"],
        "min_dragon_score": 8.0,
        "position_limit": 0.30,
        "stop_loss": "次日低开≥3%不接；盘中走弱立即撤",
        "target": "连板加速",
        "hold_days": "1-2",
        "risk_level": "中高风险",
        "allowed_tactics": ["打板", "回封", "竞价"],
    },
    "RESEAL_CONFIRM": {
        "label": "回封确认",
        "best_phase": ["分歧期", "修复期"],
        "forbidden_phase": ["深冰点"],
        "min_dragon_score": 6.0,
        "position_limit": 0.20,
        "stop_loss": "次日若低开>5%直接走；不回封不接力",
        "target": "分歧转一致",
        "hold_days": "1",
        "risk_level": "中风险",
        "allowed_tactics": ["回封", "半路"],
    },
    "LOW_TRIAL": {
        "label": "低位试错",
        "best_phase": ["冰点期", "分歧期"],
        "forbidden_phase": ["亢奋期"],
        "min_dragon_score": 0.0,
        "position_limit": 0.10,
        "stop_loss": "单票-3%止损；不补仓",
        "target": "抢修复",
        "hold_days": "1",
        "risk_level": "低风险",
        "allowed_tactics": ["低吸", "尾盘"],
    },
    "WATCH_ONLY": {
        "label": "观望",
        "best_phase": [],
        "forbidden_phase": [],
        "min_dragon_score": 0.0,
        "position_limit": 0.00,
        "stop_loss": "-",
        "target": "-",
        "hold_days": "0",
        "risk_level": "最低风险",
        "allowed_tactics": [],
    },
}


def decide_trade_nature(market_data: Dict[str, Any]) -> Dict[str, Any]:
    md = market_data or {}
    v2 = md.get("v2") if isinstance(md.get("v2"), dict) else {}

    sent = v2.get("sentiment") if isinstance(v2.get("sentiment"), dict) else {}
    phase = str(sent.get("phase") or "")
    score = _to_float(sent.get("score"), 5.0)
    risk_level = str(sent.get("risk_level") or "中")

    sector = v2.get("sector") if isinstance(v2.get("sector"), dict) else {}
    mainline = sector.get("mainline") if isinstance(sector.get("mainline"), dict) else {}
    main_exists = bool(mainline.get("exists")) if isinstance(mainline, dict) else False

    dragon = v2.get("dragon") if isinstance(v2.get("dragon"), dict) else {}
    dragon_score = _to_float(dragon.get("overall"), 0.0)
    is_real_dragon = bool(dragon.get("is_real_dragon"))

    rs = v2.get("rightside") if isinstance(v2.get("rightside"), dict) else {}
    can_enter = bool(rs.get("can_enter")) if isinstance(rs, dict) and rs else False

    # 判定优先级（先排除）
    if (not can_enter) or (risk_level == "高") or ("深冰点" in phase):
        chosen = "WATCH_ONLY"
        compatible = False
        warning = "右侧不满足/风险偏高：禁止入场，等待确认。"
    elif ("冰点" in phase) or score <= 4.0:
        chosen = "LOW_TRIAL"
        compatible = True
        warning = "弱势环境：只允许小仓低位试错，不做接力。"
    else:
        # 有主线 + 真龙分数够 → 接力；否则走回封确认
        if main_exists and dragon_score >= 8.0 and (is_real_dragon or dragon_score >= 8.5):
            chosen = "RELAY_BOARD"
            compatible = True
            warning = ""
        else:
            chosen = "RESEAL_CONFIRM"
            compatible = True
            warning = "主线/龙头未完全确认：以回封确认/分歧转一致为主，避免情绪硬接力。"

    rule = TRADE_NATURES.get(chosen) or TRADE_NATURES["WATCH_ONLY"]
    return {
        "nature": chosen,
        "label": rule.get("label"),
        "compatible": bool(compatible),
        "warning": warning,
        "rule": rule,
        "inputs": {
            "phase": phase,
            "score": score,
            "risk_level": risk_level,
            "mainline_exists": main_exists,
            "dragon_score": dragon_score,
            "rightside_can_enter": can_enter,
        },
    }

