#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
短线规则表（可配置）

用途：
- 统一管理：情绪周期阶段阈值、阶段→策略模板、学习提醒卡片
- 让"经验"变成可计算、可迭代的系统能力（避免散落在各模块里）
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, TypedDict


CycleStage = Literal["ICE", "START", "FERMENT", "CLIMAX"]


class StageRule(TypedDict, total=False):
    # 仅保留核心阈值（先做最小可用版）
    max_lb_le: int
    max_lb_ge: int
    zt_count_lt: int
    zt_count_ge: int
    zb_rate_ge: float
    zb_rate_le: float
    dt_count_ge: int


STAGE_RULES: Dict[CycleStage, StageRule] = {
    # 冰点/退潮：高度压缩 + 涨停少 + 炸板高 + 跌停多
    "ICE": {"max_lb_le": 3, "zt_count_lt": 30, "zb_rate_ge": 40.0, "dt_count_ge": 10},
    # 启动/试错：2~4板，涨停回到 30~50 区间
    "START": {"max_lb_ge": 2, "max_lb_le": 4, "zt_count_ge": 30},
    # 发酵/加速：4~6板，涨停放大，炸板较低
    "FERMENT": {"max_lb_ge": 4, "max_lb_le": 6, "zt_count_ge": 50, "zb_rate_le": 30.0},
    # 高潮：高度>=6 且涨停极多 且炸板很低（更一致）
    "CLIMAX": {"max_lb_ge": 6, "zt_count_ge": 80, "zb_rate_le": 20.0},
}


STAGE_CN: Dict[CycleStage, str] = {
    "ICE": "冰点",
    "START": "启动",
    "FERMENT": "发酵",
    "CLIMAX": "高潮",
}


STAGE_TO_TYPE: Dict[CycleStage, str] = {
    # UI 三态：good/warn/fire
    "ICE": "fire",
    "START": "warn",
    "FERMENT": "good",
    "CLIMAX": "good",
}


ACTION_TEMPLATES: Dict[CycleStage, Dict[str, Any]] = {
    "ICE": {
        "stance": "防守",
        "mode": "休息",
        "core": ["不做接力", "只看首板确认", "亏钱扩散先保命"],
    },
    "START": {
        "stance": "试错",
        "mode": "低位试错",
        "core": ["关注首板确认", "围绕新题材", "不追高只做确认"],
    },
    "FERMENT": {
        "stance": "进攻",
        "mode": "接力",
        "core": ["聚焦主线核心", "分歧转一致可加仓", "做辨识度"],
    },
    "CLIMAX": {
        "stance": "兑现",
        "mode": "高位减仓",
        "core": ["不追一致末端", "警惕次日分化", "高位只卖不买"],
    },
}


NOTE_CARDS: List[Dict[str, Any]] = [
    {"id": "ice_001", "when": {"cycle": ["ICE"]}, "text": "冰点期：不做接力，盯首板→1进2的确认信号。"},
    {"id": "start_001", "when": {"cycle": ["START"]}, "text": "启动期：最重要是1→2筛选关口，不追高。"},
    {"id": "ferment_001", "when": {"cycle": ["FERMENT"]}, "text": "加速期：主线清晰后做核心辨识度，回封是加仓点。"},
    {"id": "climax_001", "when": {"cycle": ["CLIMAX"]}, "text": "高潮期：高手卖出龙头，不要追一致末端。"},
    {"id": "risk_spike_001", "when": {"risk_spike": [1]}, "text": "风险突刺：炸板/跌停共振时先保命。"},
    {"id": "tier_break_001", "when": {"tier_integrity_low": [1]}, "text": "梯队断层：龙头有高度但缺中军，仓位要降级。"},
]

