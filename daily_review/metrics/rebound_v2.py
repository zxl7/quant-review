#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模块⑨（v2 规格书，落地版）：反弹三阶段策略引擎

规格书输入（理想）：
- drop_days / drop_pct / has_panicked / new_theme_emerging / chi_next_flat_days

现实落地（当前数据条件）：
- 很多字段缺失，因此用“情绪/风险/跌停/量能/主线是否形成”做 proxy 推断；
- 保证输出结构稳定，便于 UI 与后续接券商接口后提升精度。
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from daily_review.utils.num import to_float, to_int


REBOUND_STRATEGY = {
    "EARLY": {
        "what_to_do": "强势股回调反抽 OR 新热点首板",
        "what_NOT_to_do": "不要去做超跌股（初期超跌还没到位）",
        "why": "下跌初期市场仍期待新高；超跌股抛压还很重",
        "position": "20-40%",
        "risk": "中",
        "source": "养家心法-反弹初期",
    },
    "MID": {
        "what_to_do": "超跌股（重点在时机！）",
        "what_NOT_to_do": "不要追前期强势股（反弹遭更强抛压）",
        "why": "已出现恐慌杀跌，超跌股抛压缓解，少量买盘即可推动反弹",
        "timing_rule": "连续下跌一段后，再度猛跌时（最后一跌）",
        "position": "20-30%",
        "risk": "中高（时机很重要）",
        "source": "养家心法-反弹中期",
    },
    "LATE": {
        "what_to_do": "符合主流热点、有爆发力的强势股",
        "what_NOT_to_do": "不要做纯超跌（末期超跌反弹已结束）",
        "why": "外部资金观望，赚钱效应出现后会在个别股票上爆发",
        "position": "40-60%（如有明确主线可加大）",
        "risk": "中",
        "source": "养家心法-反弹末期",
    },
    "NO_REBOUND": {"what_to_do": "非反弹框架", "what_NOT_to_do": "-", "why": "-", "position": "-", "risk": "-", "source": ""},
}


def _infer_inputs_from_market(market_data: Dict[str, Any]) -> Dict[str, Any]:
    md = market_data or {}
    mi = (md.get("features") or {}).get("mood_inputs") or {}
    v2 = md.get("v2") if isinstance(md.get("v2"), dict) else {}
    sent = v2.get("sentiment") if isinstance(v2.get("sentiment"), dict) else {}
    sector = v2.get("sector") if isinstance(v2.get("sector"), dict) else {}
    mainline = sector.get("mainline") if isinstance(sector.get("mainline"), dict) else {}

    score = to_float(sent.get("score"), 5.0)  # 0~10
    risk_level = str(sent.get("risk_level") or "中")
    dt = to_int(mi.get("dt_count"), 0)
    zt = to_int(mi.get("zt_count"), 0)
    vol_chg = to_float((md.get("volume") or {}).get("change"), 0.0)
    hist_dt = mi.get("hist_dt") if isinstance(mi.get("hist_dt"), list) else []
    prev_dt = to_int(hist_dt[-2], 0) if len(hist_dt) >= 2 else None

    # 恐慌杀跌 proxy：跌停暴增 or 风险为高 or 崩溃链触发较多（目前在 warnings 里）
    has_panicked = bool(dt >= 20 or risk_level == "高" or (prev_dt is not None and dt >= prev_dt + 8))

    # 新主线萌芽：主线 exists 或者 zt 回暖 + dt 下降（修复的常见组合）
    new_theme = bool(mainline.get("exists")) if isinstance(mainline, dict) else False
    if not new_theme and prev_dt is not None:
        new_theme = bool(zt >= 50 and dt <= max(0, prev_dt - 5) and score >= 5.0)

    # 创业板横盘天数 proxy：量能不再缩 + 跌停不再恶化（极简）
    chi_next_flat_days = 10 if (abs(vol_chg) <= 1.5 and (prev_dt is None or dt <= prev_dt)) else 0

    # 回落天数/幅度：当前无指数高点数据，只能用阶段 proxy
    if has_panicked and score <= 4:
        drop_days = 12
        drop_pct = 18
    elif score <= 5.5:
        drop_days = 8
        drop_pct = 10
    else:
        drop_days = 5
        drop_pct = 6

    return {
        "drop_days": drop_days,
        "drop_pct": float(drop_pct),
        "has_panicked": has_panicked,
        "new_theme_emerging": new_theme,
        "chi_next_flat_days": chi_next_flat_days,
    }


def identify_rebound_phase(market_data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    # 允许外部传入更精确字段，否则用 proxy
    raw = market_data or {}
    inputs = {
        "drop_days": raw.get("drop_days"),
        "drop_pct": raw.get("drop_pct"),
        "has_panicked": raw.get("has_panicked"),
        "new_theme_emerging": raw.get("new_theme_emerging"),
        "chi_next_flat_days": raw.get("chi_next_flat_days"),
    }
    if any(v is None for v in inputs.values()):
        inputs = _infer_inputs_from_market(market_data)

    drop_days = to_int(inputs.get("drop_days"), 0)
    drop_pct = to_float(inputs.get("drop_pct"), 0.0)
    has_panicked = bool(inputs.get("has_panicked"))
    new_theme = bool(inputs.get("new_theme_emerging"))
    flat_days = to_int(inputs.get("chi_next_flat_days"), 0)

    if drop_days <= 3:
        phase = "NO_REBOUND"
        reason = "回落时间太短，尚未进入反弹框架"
    elif drop_days <= 8 and drop_pct < 10 and not has_panicked:
        phase = "EARLY"
        reason = f"回落{drop_days}天/{drop_pct:.1f}%，尚无恐慌杀跌=初期"
    elif has_panicked and drop_pct >= 15 and not new_theme:
        phase = "MID"
        reason = "已出现恐慌杀跌+尚无新主线=中期（超跌模式窗口期）"
    elif (flat_days >= 10 or new_theme) and drop_days >= 10:
        phase = "LATE"
        reason = "企稳横盘/新主线萌芽=末期（寻找爆发力品种）"
    else:
        phase = "NO_REBOUND"
        reason = "不符合任一反弹阶段特征"

    return phase, {
        "phase": phase,
        "phase_name": {"EARLY": "反弹初期", "MID": "反弹中期", "LATE": "反弹末期", "NO_REBOUND": "非反弹阶段"}.get(phase, phase),
        "reason": reason,
        "strategy": REBOUND_STRATEGY.get(phase, {}),
        "key_metrics": {
            "drop_days": drop_days,
            "drop_pct": round(drop_pct, 1),
            "panicked": bool(has_panicked),
            "new_theme": bool(new_theme),
            "chi_next_flat": int(flat_days),
        },
    }

