#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
实时盯盘/情绪触发器（短线）：把“数据 → 结论 → 动作”收口到后端输出，前端只展示。

输出：
- moodSignals: {updatedAt, headline, pos: [...], risk: [...]}
- hm2Compare: 赚钱效应左右对比（与前端 hm2 展示口径一致）
"""

from __future__ import annotations

from statistics import median
from typing import Any, Dict, List


def _to_num(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


def _last_n(arr: Any, n: int) -> List[float]:
    if not isinstance(arr, list):
        return []
    xs = [_to_num(v, None) for v in arr]
    xs = [v for v in xs if v is not None]
    return xs[-n:] if len(xs) > n else xs


def _roll_median(arr: Any, n: int, fallback: float) -> float:
    xs = _last_n(arr, n)
    return float(median(xs)) if xs else fallback


def _fmt_pp(x: float) -> str:
    # pp：保留 1 位
    return f"{x:+.1f}pp"


def _fmt_pct(x: float) -> str:
    return f"{x:.1f}%"


def _fmt_int(x: float) -> str:
    return f"{int(round(x))}"


def _status(cur: float, base: float, up: float, down: float) -> str:
    """
    状态三段：
    - on：明显优/明显差
    - watch：略优/略差
    - off：中性
    """
    if cur >= base + up:
        return "on"
    if cur <= base - down:
        return "on"
    if cur >= base + up * 0.5:
        return "watch"
    if cur <= base - down * 0.5:
        return "watch"
    return "off"


def build_mood_signals(market_data: Dict[str, Any]) -> Dict[str, Any]:
    mi = (market_data.get("features") or {}).get("mood_inputs") or {}
    d = market_data.get("delta") or {}
    meta = market_data.get("meta") or {}

    fb = _to_num(mi.get("fb_rate"), 0.0)
    jj = _to_num(mi.get("jj_rate"), 0.0)
    zb = _to_num(mi.get("zb_rate"), 0.0)
    early = _to_num(mi.get("zt_early_ratio"), 0.0)
    avg_zbc = _to_num(mi.get("avg_zt_zbc"), 0.0)
    ge3 = _to_num(mi.get("zt_zbc_ge3_ratio", mi.get("zbc_ge3_ratio")), 0.0)
    loss = _to_num(mi.get("loss"), 0.0)

    # 拥挤/集中（来自 style_radar/theme_panels，若不存在则兜底）
    top3_ratio = _to_num((market_data.get("styleRadar") or {}).get("top3ThemeRatio"), _to_num(mi.get("top3_theme_ratio"), 0.0))
    overlap = _to_num((market_data.get("themePanels") or {}).get("overlap", {}).get("score"), _to_num(mi.get("overlap_score"), 0.0))

    # rolling baseline（用 hist_*，不存在则退化为当前值）
    base_fb = _roll_median(mi.get("hist_fb_rate"), 20, fb)
    base_jj = _roll_median(mi.get("hist_jj_rate"), 20, jj)
    base_zb = _roll_median(mi.get("hist_zb_rate"), 20, zb)
    base_early = _roll_median(mi.get("hist_zt_early_ratio"), 20, early)
    base_loss = _roll_median(mi.get("hist_loss"), 20, loss)

    # Δ（用于“盯盘确认”）
    d_fb = _to_num(d.get("fb_rate"), 0.0)
    d_jj = _to_num(d.get("jj_rate"), 0.0)
    d_zb = _to_num(d.get("zb_rate"), 0.0)
    d_loss = _to_num(d.get("loss"), 0.0)

    pos: List[Dict[str, Any]] = []
    risk_signals: List[Dict[str, Any]] = []

    # 正面 1：承接是否回暖（晋级率）
    pos.append(
        {
            "key": "support",
            "title": "承接是否回暖",
            "value": f"晋级 {jj:.1f}%",
            "delta": _fmt_pp(d_jj) if d_jj else "",
            "status": "on" if (jj >= base_jj + 3 and d_jj >= 0) else ("watch" if jj >= base_jj + 1.5 else "off"),
            "why": f"对比近20日中位数 {base_jj:.1f}%",
            "action": "承接强→可做回封/换手接力；承接弱→降低出手频次",
        }
    )

    # 正面 2：一致性（封板率+早封）
    pos.append(
        {
            "key": "consistency",
            "title": "一致性（封板/早封）",
            "value": f"封 {_fmt_pct(fb)} · 早 {_fmt_pct(early)}",
            "delta": _fmt_pp(d_fb) if d_fb else "",
            "status": "on" if (fb >= base_fb + 3 and early >= base_early + 3) else ("watch" if fb >= base_fb + 1.5 else "off"),
            "why": f"对比近20日中位数 封{base_fb:.1f}%/早{base_early:.1f}%",
            "action": "一致性强→优先做主线辨识度；一致性弱→只做确认点/低位试错",
        }
    )

    # 正面 3：亏钱是否收敛
    pos.append(
        {
            "key": "loss_converge",
            "title": "亏钱是否收敛",
            "value": f"扩散 {_fmt_int(loss)}",
            "delta": _fmt_int(d_loss) if d_loss else "",
            "status": "on" if (loss <= base_loss - 2 or d_loss < 0) else ("watch" if loss <= base_loss - 1 else "off"),
            "why": f"对比近20日中位数 {base_loss:.0f}",
            "action": "扩散收敛→可提高仓位上限；扩散走高→只做低位/快进快出",
        }
    )

    # 风险 1：分歧升级（炸板/多开板）
    risk_signals.append(
        {
            "key": "diverge",
            "title": "分歧是否升级",
            "value": f"炸 {_fmt_pct(zb)} · ≥3开 {_fmt_pct(ge3)} · 均开 {avg_zbc:.2f}",
            "delta": _fmt_pp(d_zb) if d_zb else "",
            "status": "on" if (zb >= base_zb + 4 or ge3 >= 18 or avg_zbc >= 2.2) else ("watch" if zb >= base_zb + 2 else "off"),
            "why": f"对比近20日中位数 炸{base_zb:.1f}%",
            "action": "分歧大→只做回封确认；不追一致；优先低位",
        }
    )

    # 风险 2：亏钱扩散突刺
    risk_signals.append(
        {
            "key": "loss_spike",
            "title": "亏钱扩散是否突刺",
            "value": f"扩散 {_fmt_int(loss)}",
            "delta": _fmt_int(d_loss) if d_loss else "",
            "status": "on" if (loss >= base_loss + 4 or d_loss >= 3) else ("watch" if loss >= base_loss + 2 else "off"),
            "why": f"对比近20日中位数 {base_loss:.0f}",
            "action": "突刺出现→减仓/撤退；只保留最强辨识度",
        }
    )

    # 风险 3：拥挤/集中度过高
    risk_signals.append(
        {
            "key": "crowd",
            "title": "题材集中/拥挤",
            "value": f"TOP3占比 {_fmt_pct(top3_ratio)} · 重叠 {_fmt_pct(overlap)}",
            "delta": "",
            "status": "on" if (top3_ratio >= 80 or overlap >= 75) else ("watch" if top3_ratio >= 72 else "off"),
            "why": "集中度过高时更容易走向一致末端 → 分歧加速",
            "action": "拥挤高→只做主线核心/回封；避免高位跟风扩散",
        }
    )

    # headline：一眼看到当天“盯盘重点”
    key_takeaways: List[str] = []
    if pos[0]["status"] == "on" and pos[2]["status"] == "on":
        key_takeaways.append("承接回暖且亏钱收敛，可适度进攻")
    elif risk_signals[1]["status"] == "on" or risk_signals[0]["status"] == "on":
        key_takeaways.append("分歧/扩散偏大，优先防守")
    else:
        key_takeaways.append("震荡中性，等待确认点")

    updated_at = meta.get("generatedAt") or meta.get("asOf", {}).get("pools") or ""
    return {
        "updatedAt": updated_at,
        "headline": "；".join(key_takeaways),
        "pos": pos,
        "risk": risk_signals,
    }


def build_hm2_compare(market_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    赚钱效应（左右对比）数据结构：
    - score/hint/pointerLeft 用于顶部与温度条
    - cells：6 个维度，供前端分组展示（profit/strength/cons vs loss/diverge/crowd）
    """
    mi = (market_data.get("features") or {}).get("mood_inputs") or {}
    mood = market_data.get("mood") or {}
    stage = market_data.get("moodStage") or {}
    style = market_data.get("styleRadar") or {}
    theme_panels = market_data.get("themePanels") or {}

    heat = _to_num(mood.get("heat"), 0.0)
    risk = _to_num(mood.get("risk"), 0.0)
    score = round((heat * 0.55 + (100 - risk) * 0.45), 1)

    # 温度条：0~100 → 0~100%
    pointer_left = f"{max(0, min(100, score)):.1f}%"

    stage_type = str(stage.get("type") or "")
    if stage_type == "fire":
        hint = "退潮/冰点：先看修复信号，避免高位一致"
    elif risk >= heat + 10:
        hint = "风险压过热度：轻仓等待，优先回封确认"
    elif heat >= risk + 10:
        hint = "热度占优：围绕主线辨识度进攻，避免跟风扩散"
    else:
        hint = "震荡均衡：先确认承接，再决定是否进攻"

    jj = _to_num(mi.get("jj_rate"), 0.0)
    fb = _to_num(mi.get("fb_rate"), 0.0)
    early = _to_num(mi.get("zt_early_ratio"), 0.0)
    zb = _to_num(mi.get("zb_rate"), 0.0)
    loss = _to_num(mi.get("loss"), 0.0)
    ge3 = _to_num(mi.get("zt_zbc_ge3_ratio", mi.get("zbc_ge3_ratio")), 0.0)
    avg_zbc = _to_num(mi.get("avg_zt_zbc"), 0.0)
    top3 = _to_num(style.get("top3ThemeRatio"), _to_num(mi.get("top3_theme_ratio"), 0.0))
    overlap = _to_num((theme_panels.get("overlap") or {}).get("score"), _to_num(mi.get("overlap_score"), 0.0))

    def _cls(kind: str) -> str:
        # 与现有 CSS 兼容：good/warn/bad
        return "good" if kind == "good" else ("warn" if kind == "warn" else "bad")

    cells = [
        {
            "key": "profit",
            "accent": "profit",
            "title": "赚钱效应",
            "tag": "热度 vs 风险",
            "value": f"{score:.1f}",
            "statusIcon": "▲" if heat >= risk else "■",
            "statusText": "偏强" if heat >= risk + 8 else ("均衡" if abs(heat - risk) < 8 else "偏弱"),
            "statusClass": _cls("good" if heat >= risk + 8 else ("warn" if abs(heat - risk) < 8 else "bad")),
            "brief": hint,
            "driver": f"热{heat:.0f}/险{risk:.0f}（score={score:.1f}）",
        },
        {
            "key": "strength",
            "accent": "strength",
            "title": "承接强度",
            "tag": "晋级/换手",
            "value": f"{jj:.1f}%",
            "statusIcon": "✓" if jj >= 30 else "!",
            "statusText": "可做" if jj >= 30 else ("观察" if jj >= 22 else "谨慎"),
            "statusClass": _cls("good" if jj >= 30 else ("warn" if jj >= 22 else "bad")),
            "brief": "看晋级率是否持续走强",
            "driver": f"晋级{jj:.1f}%",
        },
        {
            "key": "cons",
            "accent": "cons",
            "title": "一致性",
            "tag": "封板/早封",
            "value": f"{fb:.1f}%",
            "statusIcon": "✓" if fb >= 70 and early >= 45 else "!",
            "statusText": "顺" if fb >= 70 and early >= 45 else ("一般" if fb >= 62 else "弱"),
            "statusClass": _cls("good" if fb >= 70 and early >= 45 else ("warn" if fb >= 62 else "bad")),
            "brief": "一致性强更利于回封与接力",
            "driver": f"封{fb:.1f}% · 早{early:.1f}%",
        },
        {
            "key": "loss",
            "accent": "crowd",
            "title": "亏钱扩散",
            "tag": "跌停+负反馈",
            "value": f"{loss:.0f}",
            "statusIcon": "!" if loss >= 10 else "✓",
            "statusText": "走高" if loss >= 10 else ("一般" if loss >= 7 else "收敛"),
            "statusClass": _cls("bad" if loss >= 10 else ("warn" if loss >= 7 else "good")),
            "brief": "扩散走高时要降级出手",
            "driver": f"扩散{loss:.0f}",
        },
        {
            "key": "diverge",
            "accent": "diverge",
            "title": "分歧强度",
            "tag": "炸板/开板",
            "value": f"{zb:.1f}%",
            "statusIcon": "!" if zb >= 30 or ge3 >= 18 else "✓",
            "statusText": "偏大" if zb >= 30 or ge3 >= 18 else ("一般" if zb >= 22 else "可控"),
            "statusClass": _cls("bad" if zb >= 30 or ge3 >= 18 else ("warn" if zb >= 22 else "good")),
            "brief": "分歧大时只做回封确认",
            "driver": f"炸{zb:.1f}% · ≥3开{ge3:.1f}% · 均开{avg_zbc:.2f}",
        },
        {
            "key": "crowd",
            "accent": "risk",
            "title": "题材集中度",
            "tag": "拥挤/重叠",
            "value": f"{top3:.1f}%",
            "statusIcon": "!" if top3 >= 80 or overlap >= 75 else "✓",
            "statusText": "拥挤" if top3 >= 80 or overlap >= 75 else ("一般" if top3 >= 72 else "舒适"),
            "statusClass": _cls("bad" if top3 >= 80 or overlap >= 75 else ("warn" if top3 >= 72 else "good")),
            "brief": "集中度过高更容易一致末端",
            "driver": f"TOP3{top3:.1f}% · 重叠{overlap:.1f}%",
        },
    ]

    return {"score": score, "hint": hint, "pointerLeft": pointer_left, "cells": cells}
