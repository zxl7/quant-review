#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模块②③（v2 规格书，落地版）：连板高度&龙头诊断 + 龙头三要素（含渡劫、神形简化）

注意：
- 你目前的缓存数据以涨停池（ztgc）为主，缺少完整 OHLC/涨停价 等字段；
- 本实现使用“可从现有数据推断”的 proxy，保证系统可跑，并为后续接入券商接口/OHLC 做好接口位。
"""

from __future__ import annotations

from typing import Any, Dict


def _to_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        if isinstance(v, str) and v.endswith("%"):
            v = v[:-1]
        return float(v)
    except Exception:
        return default


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _pattern_from_ztgc_row(row: Dict[str, Any]) -> str:
    """
    五态分类（尽量贴近 v2 文档）：
    - 一字板 / T字板 / 实体板 / 烂板 / 断板（断板不在涨停池内，此处不会产生）
    """
    zbc = _to_int(row.get("zbc"), 0)  # 开板次数
    hs = _to_float(row.get("hs"), 0.0)  # 换手
    fbt = str(row.get("fbt") or "")
    lbt = str(row.get("lbt") or "")

    # 一字：开板=0 且基本在 09:25 封死，且换手极低
    if zbc == 0 and fbt == lbt and fbt.startswith("0925") and hs <= 2.0:
        return "一字板"
    # T字：9:25 封板后打开再回封
    if fbt.startswith("0925") and zbc >= 1:
        return "T字板"
    # 烂板：开板次数多或换手过大（分歧极大）
    if zbc >= 3 or hs >= 15.0:
        return "烂板"
    return "实体板"


def diagnose_doujie(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    渡劫识别（落地版）
    目前主要利用：zbc（开板次数）、hs（换手）做 proxy。
    """
    zbc = _to_int(row.get("zbc"), 0)
    hs = _to_float(row.get("hs"), 0.0)
    boards = _to_int(row.get("lbc"), 1)

    is_doujie = False
    doujie_type = ""
    level = 0
    survival = 1.0
    advice = "持有/观察"

    # 类型1：炸板渡劫
    if zbc >= 3:
        is_doujie = True
        doujie_type = "炸板渡劫"
        level = min(5, zbc)
        survival = 0.70
        advice = "回封确认后可轻仓介入（分歧转一致买点）"

    # 类型2：巨量渡劫（用换手 proxy）
    if hs >= 25:
        is_doujie = True
        doujie_type = "巨量渡劫"
        level = max(level, 4)
        survival = min(survival, 0.65)
        advice = "放量换手充分：能封住=健康；若次日低开走弱则撤退"

    # 高位打折
    if boards >= 7:
        survival *= 0.70
    elif boards >= 5:
        survival *= 0.85

    return {
        "is_doujie": is_doujie,
        "doujie_type": doujie_type,
        "doujie_level": int(level),
        "survival_prob": round(float(_clamp(survival, 0, 1)), 2),
        "advice": advice,
    }


def identify_life_cycle(row: Dict[str, Any]) -> Dict[str, Any]:
    boards = _to_int(row.get("lbc"), 1)
    pattern = _pattern_from_ztgc_row(row)
    doujie = diagnose_doujie(row)

    if boards <= 2:
        phase = "startup"
        phase_name = "启动期"
        detail = f"{boards}板启动中，观察是否有带动性"
    elif boards <= 4:
        phase = "acceleration"
        phase_name = "加速期"
        detail = f"{boards}板加速期，{('缩量一致' if pattern in ('一字板','T字板') else '注意换手')}"
    else:
        if pattern == "一字板":
            phase = "climax"
            phase_name = "见顶期"
            detail = f"{boards}板一字加速赶顶，警惕突然死亡"
        else:
            phase = "divergence"
            phase_name = "分歧期"
            extra = f"（渡劫：{doujie.get('doujie_type')} 存活率{int(doujie.get('survival_prob',1)*100)}%）" if doujie.get("is_doujie") else ""
            detail = f"{boards}板高位分歧{extra}"

    return {"phase": phase, "phase_name": phase_name, "detail": detail}


def build_height_module(market_data: Dict[str, Any]) -> Dict[str, Any]:
    ztgc = (market_data.get("ztgc") or []) if isinstance(market_data.get("ztgc"), list) else []
    if not ztgc:
        return {"max_board": 0, "trend": "➡️ 震荡", "top_stock": {}, "state_label": "", "life_cycle": {}}

    top = max((x for x in ztgc if isinstance(x, dict)), key=lambda x: _to_int(x.get("lbc"), 1), default={})
    boards = _to_int(top.get("lbc"), 1)
    pattern = _pattern_from_ztgc_row(top)
    doujie = diagnose_doujie(top)
    life = identify_life_cycle(top)

    state_label = "⚡ 烂板分歧" if pattern == "烂板" else ("🧊 一字加速" if pattern == "一字板" else "✅ 实体健康")

    return {
        "max_board": boards,
        "trend": "",  # 趋势沿用现有 heightTrend（v2 后续可统一）
        "top_stock": {"name": str(top.get("mc") or ""), "board": boards, "state": pattern},
        "state_label": state_label,
        "life_cycle": life,
        "doujie_result": doujie,
    }


def _grade(overall: float) -> str:
    if overall >= 8:
        return "S"
    if overall >= 7:
        return "A"
    if overall >= 6:
        return "B"
    if overall >= 4:
        return "C"
    return "D"


def build_dragon_three_elements(market_data: Dict[str, Any], height_module: Dict[str, Any]) -> Dict[str, Any]:
    """
    三要素（简化落地）：
    - 带领性：该股所在题材在涨停池中的扩散程度（数量）
    - 突破性：是否突破近5日最高连板（hist_max_lb）
    - 唯一性：题材内是否明显最高标（与次高板差距）
    - 神/形：用“周期阶段 + 主线拥挤度 + 是否高标”近似
    """
    ztgc = (market_data.get("ztgc") or []) if isinstance(market_data.get("ztgc"), list) else []
    top = height_module.get("top_stock") or {}
    stock_name = str(top.get("name") or "")
    boards = _to_int(top.get("board"), 0)

    if not stock_name or boards <= 0:
        return {"stock_name": "", "overall": 0, "grade": "D", "is_real_dragon": False, "elements": {}, "god_form_analysis": {}}

    # 找到 top 的代码行（通过名称匹配兜底）
    top_row = next((x for x in ztgc if isinstance(x, dict) and str(x.get("mc") or "") == stock_name), None) or {}
    code = str(top_row.get("dm") or "")

    zt_code_themes = market_data.get("zt_code_themes") or {}
    themes = zt_code_themes.get(code) if isinstance(zt_code_themes, dict) else None
    themes = themes if isinstance(themes, list) else []
    main_theme = str(themes[0]) if themes else str(top_row.get("hy") or "")

    # 题材扩散：同题材涨停数量
    theme_cnt = 0
    theme_top = boards
    theme_second = 0
    for r in ztgc:
        if not isinstance(r, dict):
            continue
        c = str(r.get("dm") or "")
        ths = (zt_code_themes.get(c) if isinstance(zt_code_themes, dict) else None) or []
        th0 = str(ths[0]) if isinstance(ths, list) and ths else str(r.get("hy") or "")
        if th0 == main_theme and th0:
            theme_cnt += 1
            b = _to_int(r.get("lbc"), 1)
            if b > theme_top:
                theme_second = theme_top
                theme_top = b
            elif b > theme_second and b <= theme_top:
                theme_second = b

    # 带领性：题材越多人封板，越像“带动”
    leading = _clamp(4.5 + min(5.0, theme_cnt * 0.9) + (1.0 if boards >= 4 else 0.0), 0, 10)

    # 突破性：是否创新高（对比 hist_max_lb）
    mi = (market_data.get("features") or {}).get("mood_inputs") or {}
    hist_max = mi.get("hist_max_lb") or []
    hist_max = hist_max if isinstance(hist_max, list) else []
    prev_max = max([_to_int(x, 0) for x in hist_max[:-1]], default=0) if len(hist_max) >= 2 else max([_to_int(x, 0) for x in hist_max], default=0)
    if boards >= prev_max + 1 and boards >= 3:
        breakthrough = 8.0
    elif boards == prev_max and boards >= 3:
        breakthrough = 6.5
    else:
        breakthrough = 5.0

    # 唯一性：题材内与次高的差距
    gap = max(0, theme_top - theme_second)
    if gap >= 2:
        uniqueness = 8.0
    elif gap >= 1:
        uniqueness = 6.8
    else:
        uniqueness = 5.2

    overall = round(min(leading, breakthrough, uniqueness), 1)

    # 神/形（简化）：相同形态在不同周期意义不同
    v2s = (market_data.get("v2") or {}).get("sentiment") if isinstance(market_data.get("v2"), dict) else None
    v2s = v2s if isinstance(v2s, dict) else {}
    phase = str(v2s.get("phase") or "")
    score = _to_float(v2s.get("score"), 5.0)
    overlap = (market_data.get("themePanels") or {}).get("overlap") or {}
    ov = _to_float(overlap.get("score"), 0.0)
    god_score = 5.0
    if score >= 6.0 and ("冰点" not in phase) and main_theme:
        god_score += 1.0
    if boards >= max(_to_int(mi.get("max_lb"), 0), 3):
        god_score += 1.0
    if ov >= 75:
        god_score -= 1.5  # 拥挤末端，神弱
    god_score = _clamp(god_score, 0, 10)

    is_real = bool(overall >= 6.0 and god_score >= 6.0)

    return {
        "stock_name": stock_name,
        "stock_code": code,
        "main_theme": main_theme,
        "leading_score": round(leading, 1),
        "breakthrough_score": round(breakthrough, 1),
        "uniqueness_score": round(uniqueness, 1),
        "overall": overall,
        "grade": _grade(overall),
        "is_real_dragon": is_real,
        "elements": {
            "带领性": {"score": round(leading, 1), "evidence": f"同题材涨停{theme_cnt}只"},
            "突破性": {"score": round(breakthrough, 1), "evidence": f"对比近5日最高板{prev_max}"},
            "唯一性": {"score": round(uniqueness, 1), "evidence": f"题材内高度差{gap}"},
        },
        "god_form_analysis": {
            "god_score": round(god_score, 1),
            "verdict": "神形俱备" if is_real else ("形似神不似" if overall >= 6 and god_score < 6 else "未确认为龙头"),
            "note": f"周期{phase}·情绪{score:.1f}·拥挤{ov:.0f}%",
        },
    }

