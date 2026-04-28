#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3 Y=F(X)反身性模型 + 人性博弈分析层

反身性循环:
- 正向加强晚期(评分>=8.5, 涨停>=80): 过热区，F'(Y)即将反转 → 减仓
- 正向加强中期(评分>=7, 涨停>=50): 资金自我强化 → 持股/加仓
- 过冷区(评分4-6): 转折临界点 → 开始做多
- 反向加强中(评分<4): 恐慌蔓延 → 空仓等待

心理博弈:
- 持筹者心态(按浮盈程度): >30%丰厚浮盈 / >10%有浮盈 / 微利 / 小套 / 深套
- 持币者行为: 下跌时敢不敢买? 上涨时追不追?
- 行为链条监控: 追涨者效应 + 抄底者成功率
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def analyze_reflexivity_cycle(market_state: Dict[str, Any]) -> Dict[str, Any]:
    """反身性循环分析。返回 {cycle_position, risk_level, reflexivity_warning, suggested_action, insight}"""
    
    sentiment_score = float(market_state.get("sentiment_score", 5) or 5)
    zt_count = int(market_state.get("zt_count", 0) or 0)
    risk_spike = bool(market_state.get("risk_spike", False))
    
    # 判定位置
    if sentiment_score >= 8.5 and zt_count >= 80:
        position = "正向加强晚期（过热区）"
        risk = "极高"
        warning = "市场已被推向高潮，F'(Y)即将反转"
        action = "逐步减仓"
    elif sentiment_score >= 7 and zt_count >= 50:
        position = "正向加强中期"
        risk = "中"
        warning = "资金不断进入，赚钱效应自我强化"
        action = "持股/择机加仓"
    elif 4 <= sentiment_score < 6:
        position = "过冷区/转折临界点"
        risk = "中"
        warning = "情绪已达冰点附近，F'(Y)可能转向正面"
        action = "开始积极做多"
    elif sentiment_score < 4:
        position = "反向加强中（恐慌蔓延）"
        risk = "高"
        warning = "亏钱效应扩散导致恐慌宣泄"
        action = "空仓等待"
    else:
        if sentiment_score >= 6:
            position = "过渡区-偏强"
            risk = "中低"
            warning = "市场在选择方向，偏乐观"
            action = "积极但不激进"
        else:
            position = "过渡区-偏弱"
            risk = "中"
            warning = "市场在选择方向，偏谨慎"
            action = "观望为主"

    # 风险突刺修正
    if risk_spike and risk != "极高":
        risk = "高"
        warning += " | ⚠️检测到风险突刺信号!"

    return {
        "cycle_position": position,
        "risk_level": risk,
        "reflexivity_warning": warning,
        "suggested_action": action,
        "insight": "你是要做主流Y里面的F(X)，不要做别的X。",
        "_meta": {
            "score": round(sentiment_score, 1),
            "zt_count": zt_count,
        },
        "confidence": 70 + (10 - abs(sentiment_score - 6)) * 2,
    }


def psychological_game_analysis(stock: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    人性博弈分析。返回 {holders: {...}, watchers: {...}, conclusion: str}
    """
    profit_pct = float(stock.get("profit_pct", 0) or 0)
    
    # 持筹者心态
    if profit_pct > 30:
        holder_mindset = "浮盈丰厚 — 部分想落袋，龙头可能有锁仓"
    elif profit_pct > 10:
        holder_mindset = "有浮盈 — 多数不急于卖"
    elif profit_pct > 0:
        holder_mindset = "微利 — 波动即触发止盈"
    elif profit_pct > -5:
        holder_mindset = "小套 — '解套就走'心态主导"
    elif profit_pct > -15:
        holder_mindset = "深套 — 分化：死扛或割肉"
    else:
        holder_mindset = "重度深套 — 抛压很大"
    
    # 持筹者下跌时的行为预判
    on_decline = _infer_holder_on_decline(stock, context)
    
    # 持币者行为预判
    buy_on_decline = _infer_watcher_buy_on_decline(stock, context)
    buy_on_rally = _infer_watcher_buy_on_rally(stock, context)
    
    # 综合结论
    wants_exit = "exit" in str(on_decline).lower()
    watchers_buy = buy_on_decline or buy_on_rally
    
    if wants_exit and not watchers_buy:
        conclusion = "危险：持筹集中出逃+买盘不足 → 可能大跌"
    elif not wants_exit and watchers_buy:
        conclusion = "安全：筹码锁定+外部资金想买 → 易涨难跌"
    else:
        conclusion = "博弈中：多空不一 → 取决于明日催化剂"
    
    return {
        "holders": {
            "current_mindset": holder_mindset,
            "on_decline_action": on_decline,
            "key_insight": "持筹者怎么想？'给反弹就走'→你先走；'解套就走'→你提前走",
        },
        "watchers": {
            "buy_on_decline": buy_on_decline,
            "buy_on_rally": buy_on_rally,
            "key_insight": "没人接盘→无抵抗下跌；反弹有大量买盘→外部看好",
        },
        "conclusion": conclusion,
        "confidence": 65,
    }


def behavior_chain_monitor(data: Dict[str, Any]) -> List[str]:
    """行为链条监控。返回alerts列表"""
    alerts = []
    avg = float(data.get("yest_zt_avg_chg", 0) or 0)
    
    if avg >= 5:
        alerts.append("追涨者: 赚钱效应强 → 模仿资金可能进场")
    elif 1 <= avg < 5:
        alerts.append("追涨者: 有效应 → 热情维持中")
    elif -2 <= avg < 1:
        alerts.append("⚠️ 追涨者: 效应减弱 → 趋于谨慎")
    else:
        alerts.append("🔴 追涨者: 追涨亏钱 → 活跃度将进一步下降")

    reb_rate = float(data.get("rebound_success_rate", 50) or 50)
    if reb_rate >= 70:
        alerts.append("抄底者: 能赚 → 继续抄底 → 有支撑")
    elif reb_rate >= 40:
        alerts.append("抄底者: 盈亏不一 → 部分人犹豫")
    elif reb_rate >= 20:
        alerts.append("⚠️ 抄底者: 开始亏钱 → ⚠️ 崩溃前兆!")
    else:
        alerts.append("🔴 抄底者: 大面积亏损 → 无抵抗下跌风险!!")
    
    return alerts


def _infer_holder_on_decline(stock: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    """推断持筹者在下跌时会怎么做"""
    profit_pct = float(stock.get("profit_pct", 0) or 0)
    is_dragon = bool(stock.get("is_dragon", False))
    
    if is_dragon and profit_pct > 10:
        return "多数锁仓等待更高，少数止盈盘会在-3%左右出局"
    if profit_pct > 20:
        return "丰厚获利盘 → 会有不少止盈抛压，但不会恐慌"
    if profit_pct > 5:
        return "小幅获利 → 微利盘见利就跑，-2%附近开始有卖压"
    if profit_pct > -5:
        return "浅套盘 → '再给机会就解套走'，反弹至成本价有压力"
    if profit_pct > -15:
        return "中度套牢 → 分化：割肉派(-3%止损)和死扛派各半"
    return "深度套牢 → 割肉盘+死扛盘并存，继续下跌会引发更多割肉"


def _infer_watcher_buy_on_decline(stock: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """持币者会不会在下跌时买入"""
    sentiment_score = float(ctx.get("sentiment_score", 5) or 5)
    is_dragon = bool(stock.get("is_dragon", False))
    discount = float(stock.get("discount_from_high", 0) or 0)
    
    if is_dragon and discount > 15 and sentiment_score >= 5:
        return True
    if sentiment_score >= 7:
        return discount > 10
    return False


def _infer_watcher_buy_on_rally(stock: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """持币者会不会在反弹/上涨时追入"""
    sentiment_score = float(ctx.get("sentiment_score", 5) or 5)
    is_dragon = bool(stock.get("is_dragon", False))
    vol_rank = int(stock.get("volume_rank", 999) or 999)
    
    if is_dragon and sentiment_score >= 7 and vol_rank <= 10:
        return True
    if sentiment_score >= 8:
        return True
    return False
