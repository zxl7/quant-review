#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模块⑤（v2 规格书）：明日策略生成引擎（落地最小可用版）

目标：
- 输出结构尽量贴合规格书的 generate_strategy
- 未落地模块用占位/降级，不影响页面展示与后续迭代
"""

from __future__ import annotations

from typing import Any, Dict, List


def _to_num(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


def _tone(score: float) -> tuple[str, str]:
    if score <= 2:
        return "🧊 极寒 — 空仓保命", "空仓为主，用1/10仓位保持盘感。不要因为“跌多了”就想抄底（左侧禁区）。"
    if score <= 4:
        return "❄️ 严冬 — 试错为主", "极小仓试错首板，只做最强。大部分时间看戏。"
    if score <= 5.5:
        return "🔄 僵持 — 看戏为宜", "看戏为主，每天最多1只小仓试单。禁止追高/打板/半路/满仓。"
    if score <= 7:
        return "☀️ 春暖 — 积极做多", "积极做多主线龙头，仓位可提升至30-50%。"
    if score <= 8.5:
        return "🔥 盛夏 — 重仓出击", "赚钱效应良好，重仓参与主线核心，但单票不超过30%。"
    return "🚀 酷暑 — 兑现时刻", "市场亢奋，开始兑现利润。不追新开的重仓仓位。"


def select_tactics(*, phase: str, resonance_passed: int = 0) -> Dict[str, Any]:
    base = {"打板": 0, "半路": 0, "低吸": 0, "回封": 0, "竞价": 0, "尾盘": 0}
    p = phase or ""

    # 简化矩阵（后续可按 v2 文档补全）
    if "深冰点" in p or "冰点" in p:
        base.update({"低吸": 3, "回封": 2, "尾盘": 2})
    elif "分歧" in p:
        base.update({"回封": 4, "低吸": 3, "尾盘": 2, "半路": 1})
    elif "修复" in p:
        base.update({"回封": 4, "半路": 3, "打板": 2, "竞价": 2})
    else:  # 亢奋
        base.update({"打板": 4, "竞价": 3, "半路": 3, "回封": 2})

    # 共振约束：打板至少双共振
    if resonance_passed < 2:
        base["打板"] = min(base.get("打板", 0), 2)

    sorted_t = sorted(base.items(), key=lambda x: x[1], reverse=True)
    best = sorted_t[0][0] if sorted_t else "-"
    best_score = sorted_t[0][1] if sorted_t else 0
    return {"recommendations": dict(sorted_t), "best_tactic": best, "best_score": best_score, "notes": ""}


def generate_iron_rules(*, phase: str, score: float) -> List[str]:
    rules = [
        "① 单票仓位不得超过总仓位的30%",
        "② 日内亏损达到总资产2%时停止所有操作",
        "③ 禁止临时起意，只做计划内的操作",
        "④ 手风不顺时第二天赚钱就走，不管是否卖飞",
        "⑤ 杜绝“成本思维/仓位思维”，做纯粹的交易员",
    ]
    if score <= 2:
        rules += ["⑥ 冰点期：最多1只股票，总仓位上限10%", "⑦ 冰点期：禁止追高/打板/半路"]
    if score <= 5.5:
        rules += ["⑧ 僵持/弱修复：看戏为主，每天最多1只小仓试单", "⑨ 不追一致，不做模式外"]
    if score >= 8.5:
        rules += ["⑥ 亢奋高潮：开始减仓，不新开重仓", "⑦ 大胜当日/次日保持克制，防止乐极生悲"]
    return rules


def generate_strategy(
    *,
    v2_sentiment: Dict[str, Any],
    position_model: Dict[str, Any],
    resonance: Dict[str, Any] | None = None,
    rightside: Dict[str, Any] | None = None,
    trade_nature: Dict[str, Any] | None = None,
    rebound: Dict[str, Any] | None = None,
    psychology: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    s = v2_sentiment or {}
    score = _to_num(s.get("score"), 5.0)
    phase = str(s.get("phase") or "")

    tone, overall_advice = _tone(score)

    pos_from_win = _to_num((position_model or {}).get("tier", {}).get("max_position"), 0.0)
    pos_from_res = _to_num((resonance or {}).get("max_recommended_position"), 1.0)
    final_cap = min(pos_from_win, pos_from_res)

    # 右侧交易：不满足则进一步收紧（避免“算法给仓位但右侧不允许出手”）
    rs = rightside or {}
    can_enter = bool(rs.get("can_enter")) if rs else True
    if not can_enter:
        final_cap = min(final_cap, 0.10)

    passed_count = int((resonance or {}).get("passed_count") or 0)
    tactics = select_tactics(phase=phase, resonance_passed=passed_count)
    if not can_enter:
        tactics["notes"] = "右侧交易不满足：禁止入场，只能观察/等确认。"
        # 降级战术推荐
        tactics["best_tactic"] = "等待确认"
        tactics["best_score"] = 0

    # 交易性质约束：过滤允许战术 + 追加仓位上限
    tn = trade_nature or {}
    if isinstance(tn, dict) and tn.get("rule"):
        rule = tn.get("rule") or {}
        allowed = set(rule.get("allowed_tactics") or [])
        pos_limit = _to_num(rule.get("position_limit"), 1.0)
        if allowed:
            tactics["recommendations"] = {k: v for k, v in (tactics.get("recommendations") or {}).items() if k in allowed}
            # 重新选 best
            items = list((tactics.get("recommendations") or {}).items())
            items.sort(key=lambda x: x[1], reverse=True)
            tactics["best_tactic"] = items[0][0] if items else "等待确认"
            tactics["best_score"] = items[0][1] if items else 0
        final_cap = min(final_cap, pos_limit)

    strategy = {
        "tone": tone,
        "overall_advice": overall_advice,
        "position": {
            "recommended_max": f"{final_cap*100:.0f}%",
            "from_winrate_model": f"{pos_from_win*100:.0f}%",
            "from_resonance": f"{pos_from_res*100:.0f}%",
            "conservative_reason": "取两者较小值（保守原则）" if abs(pos_from_win - pos_from_res) > 1e-6 else "",
            "full_position_validated": bool((position_model or {}).get("full_position_check", {}) and (position_model or {}).get("full_position_check", {}).get("passed")),
        },
        "tactics": tactics,
        "iron_rules": generate_iron_rules(phase=phase, score=score),
        "warnings": s.get("warnings") or [],
    }
    if tn:
        strategy["trade_nature"] = {
            "nature": tn.get("nature"),
            "label": tn.get("label"),
            "compatible": tn.get("compatible"),
            "warning": tn.get("warning"),
            "position_limit": (tn.get("rule") or {}).get("position_limit"),
            "allowed_tactics": (tn.get("rule") or {}).get("allowed_tactics") or [],
            "stop_loss": (tn.get("rule") or {}).get("stop_loss"),
        }
    if rs:
        strategy["rightside"] = {
            "can_enter": bool(rs.get("can_enter")),
            "signal_strength": rs.get("signal_strength"),
            "passed_count": rs.get("passed_count"),
            "msg": rs.get("msg"),
        }
    if resonance:
        strategy["resonance"] = {
            "passed_count": passed_count,
            "level": (resonance or {}).get("level"),
            "missing": (resonance or {}).get("missing") or [],
        }

    rb = rebound or {}
    if isinstance(rb, dict) and rb:
        strategy["rebound"] = {
            "phase": rb.get("phase"),
            "phase_name": rb.get("phase_name"),
            "reason": rb.get("reason"),
            "strategy": rb.get("strategy") or {},
        }

    psy = psychology or {}
    if isinstance(psy, dict) and psy:
        ref = (psy.get("reflexivity_cycle") or {}) if isinstance(psy.get("reflexivity_cycle"), dict) else {}
        strategy["mindset"] = {
            "reflexivity_position": ref.get("position_name"),
            "reflexivity_summary": ref.get("summary"),
            "reflexivity_warning": ref.get("warning"),
            "behavior_chains": psy.get("behavior_chains") or [],
            "game": psy.get("psychology_game") or {},
        }
    return strategy
