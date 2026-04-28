#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模块⑩（v2 规格书）：满仓三条件共振系统（落地版）

输出：
- passed_count: 0~3
- level: 文案等级
- max_recommended_position: 0~1
- missing: 缺失条件说明
"""

from __future__ import annotations

from typing import Any, Dict, List


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        if isinstance(v, str) and v.endswith("%"):
            v = v[:-1]
        return float(v)
    except Exception:
        return default


def check_resonance(market_data: Dict[str, Any]) -> Dict[str, Any]:
    md = market_data or {}
    mi = (md.get("features") or {}).get("mood_inputs") or {}
    v2s = (md.get("v2") or {}).get("sentiment") if isinstance(md.get("v2"), dict) else None
    v2s = v2s if isinstance(v2s, dict) else {}

    score = _to_float(v2s.get("score"), 5.0)
    phase = str(v2s.get("phase") or "")

    # 条件① 指数大势：用“情绪不在冰点 + 量能不极端缩”做 proxy
    vol = md.get("volume") or {}
    vol_chg = _to_float(vol.get("change"), 0.0)
    cond_index = bool(score >= 5.5 and "冰点" not in phase and vol_chg >= -1.5)

    # 条件② 板块核心：有主线且不拥挤极端（overlap < 75）
    overlap = (md.get("themePanels") or {}).get("overlap") or {}
    ov = _to_float(overlap.get("score"), 0.0)
    top3 = _to_float((md.get("styleRadar") or {}).get("top3ThemeRatio"), _to_float(mi.get("top3_theme_ratio"), 0))
    cond_sector = bool(top3 >= 65 and top3 <= 90 and ov < 75)

    # 条件③ 个股核心：最高连板≥3 且 承接不差
    max_lb = int(_to_float(mi.get("max_lb"), 0))
    jj = _to_float(mi.get("jj_rate"), 0.0)
    cond_stock = bool(max_lb >= 3 and jj >= 30)

    missing: List[str] = []
    passed = 0
    for ok, name in [(cond_index, "指数趋势"), (cond_sector, "板块主线"), (cond_stock, "个股核心")]:
        if ok:
            passed += 1
        else:
            missing.append(name)

    if passed == 3:
        level = "🔥🔥🔥 三共振 — 可满仓出击"
        max_pos = 1.00
    elif passed == 2:
        level = "🔥🔥 双共振 — 可中仓出击"
        max_pos = 0.50
    elif passed == 1:
        level = "🔥 单共振 — 仅小仓试探"
        max_pos = 0.20
    else:
        level = "❌ 零共振 — 禁止重仓"
        max_pos = 0.10

    return {
        "passed_count": passed,
        "level": level,
        "max_recommended_position": max_pos,
        "missing": missing,
        "conditions": {
            "index": {"passed": cond_index, "detail": f"量能{vol.get('change','-')}，情绪{score:.1f}/{phase}"},
            "sector": {"passed": cond_sector, "detail": f"主线集中{top3:.0f}% · 重叠{ov:.0f}%"},
            "stock": {"passed": cond_stock, "detail": f"高度{max_lb}板 · 晋级{jj:.0f}%"},
        },
    }

