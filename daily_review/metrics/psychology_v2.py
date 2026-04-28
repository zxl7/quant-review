#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模块⑪（v2 规格书，落地版）：人性博弈层 / 反身性分析

输出：
- reflexivity_cycle: position(early/mid/late), summary, warning
- behavior_chains: 追高链/抄底链/止损链（触发与建议）
- psychology_game: 市场两类参与者心理（持有者/观望者）+ 应对
"""

from __future__ import annotations

from typing import Any, Dict, List

from daily_review.utils.num import to_float, to_int


def analyze_reflexivity_cycle(market_data: Dict[str, Any]) -> Dict[str, Any]:
    md = market_data or {}
    v2 = md.get("v2") if isinstance(md.get("v2"), dict) else {}
    sent = v2.get("sentiment") if isinstance(v2.get("sentiment"), dict) else {}
    mi = (md.get("features") or {}).get("mood_inputs") or {}

    score = to_float(sent.get("score"), 5.0)
    phase = str(sent.get("phase") or "")
    zt = to_int(mi.get("zt_count"), 0)
    dt = to_int(mi.get("dt_count"), 0)
    yest = to_float(mi.get("yest_zt_avg_chg"), 0.0)

    # 简化：用“赚钱效应（yest）+ 活跃度（zt）+ 风险（dt/phase）”推断反身性位置
    if "亢奋" in phase and zt >= 70 and yest >= 2:
        pos = "late"
        summary = "反身性末期：一致性极强，容易出现‘强更强→突然崩’。"
        warning = "减少追高，开始兑现，防止‘高潮死’。"
    elif "修复" in phase and score >= 6 and dt <= 10:
        pos = "mid"
        summary = "反身性中期：赚钱效应逐步强化，资金开始正反馈。"
        warning = "以主线核心为主，分歧转一致买点优先。"
    elif "分歧" in phase or score < 6:
        pos = "early"
        summary = "反身性早期：分歧大，正反馈未建立，试错为主。"
        warning = "仓位控制，先等两项共振确认再加仓。"
    else:
        pos = "early"
        summary = "反身性未确认：以风控为先。"
        warning = "不做模式外冲动交易。"

    return {
        "position": pos,
        "position_name": {"early": "早期", "mid": "中期", "late": "末期"}.get(pos, pos),
        "summary": summary,
        "warning": warning,
        "inputs": {"score": score, "phase": phase, "zt": zt, "dt": dt, "yest": yest},
    }


def behavior_chain_monitor(market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    md = market_data or {}
    v2 = md.get("v2") if isinstance(md.get("v2"), dict) else {}
    sent = v2.get("sentiment") if isinstance(v2.get("sentiment"), dict) else {}
    mi = (md.get("features") or {}).get("mood_inputs") or {}

    score = to_float(sent.get("score"), 5.0)
    dt = to_int(mi.get("dt_count"), 0)
    yest = to_float(mi.get("yest_zt_avg_chg"), 0.0)
    fb = to_float(mi.get("fb_rate"), 0.0)
    jj = to_float(mi.get("jj_rate"), 0.0)

    chains = []

    # 追高链：情绪强 + 封板好，但昨日反馈开始走弱 → 很容易“追高→补跌”
    chase_trigger = bool(score >= 7 and fb >= 70 and yest < 1.0)
    chains.append(
        {
            "name": "追高链（追涨—回撤—补跌）",
            "triggered": chase_trigger,
            "hint": "当你想追高时，先问自己：这是主流核心的确认点，还是情绪末端一致？",
            "rule": "追高只做主线核心的回封确认；不做尾盘一致追涨。",
        }
    )

    # 抄底链：跌停多/情绪弱但晋级还没崩 → 容易“抄底—反抽—再杀”
    dip_trigger = bool(dt >= 15 and score <= 4 and jj >= 20)
    chains.append(
        {
            "name": "抄底链（抄底—反抽—再杀）",
            "triggered": dip_trigger,
            "hint": "恐慌期反抽不等于趋势反转。",
            "rule": "抄底只允许小仓‘最后一跌’试错，-3%止损，不补仓。",
        }
    )

    # 止损链：昨反馈差 + 跌停升温 → 连续止损期
    stop_trigger = bool(yest < 0 and dt >= 10)
    chains.append(
        {
            "name": "止损链（亏损—加码—再亏）",
            "triggered": stop_trigger,
            "hint": "连续止损期，最该做的是减少交易次数。",
            "rule": "日内亏损2%停止交易；第二天只做一笔小仓验证。",
        }
    )

    return chains


def psychological_game_analysis(market_data: Dict[str, Any], reflexivity: Dict[str, Any]) -> Dict[str, Any]:
    md = market_data or {}
    v2 = md.get("v2") if isinstance(md.get("v2"), dict) else {}
    sent = v2.get("sentiment") if isinstance(v2.get("sentiment"), dict) else {}
    score = to_float(sent.get("score"), 5.0)
    phase = str(sent.get("phase") or "")

    # 观望者/持有者博弈（市场级别的简化表述）
    if reflexivity.get("position") == "late":
        holders = "持有者极度自信，觉得会继续新高。"
        watchers = "观望者FOMO，害怕错过而追高入场。"
        advice = "你要站在更冷静的一侧：开始兑现，等分歧给低风险机会。"
    elif reflexivity.get("position") == "mid":
        holders = "持有者开始赚钱，愿意持股等待更大趋势。"
        watchers = "观望者逐渐入场，形成正反馈。"
        advice = "顺势做主线核心，分歧转一致点加仓。"
    else:
        holders = "持有者焦虑，随时想走，抛压大。"
        watchers = "观望者不信反弹，买盘不足。"
        advice = "以试错/等待为主，先等共振出现再加仓。"

    return {"holders": holders, "watchers": watchers, "advice": advice, "context": f"{phase}/{score:.1f}"}


def build_psychology_layer(market_data: Dict[str, Any]) -> Dict[str, Any]:
    ref = analyze_reflexivity_cycle(market_data)
    chains = behavior_chain_monitor(market_data)
    game = psychological_game_analysis(market_data, ref)
    return {"reflexivity_cycle": ref, "behavior_chains": chains, "psychology_game": game}

