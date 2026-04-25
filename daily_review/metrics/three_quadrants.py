#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
three_quadrants: PRD 3.3 盘面三象限（Market Three Quadrants）

要求：
- 必须“精准复算”：仅使用 raw.pools/现有字段做确定性计算
- 输出 marketData.threeQuadrants（供前端 ECharts Scatter + 轨迹渲染）

说明（v1 精准版口径）：
- 承接（X）：使用 features.mood_inputs.jj_rate_adj/jj_rate（0~1）
- 一致性（Y）：使用“早封率 earlySealRate”（从 raw.pools.ztgc[].fbt 分桶计算，0~1）
- 风险（Z）：使用“高位炸板压力”proxy（0~1）：
  - highOpenRate = 高位(>=5板)涨停股中，发生过炸板（zbc>0）的比例（只统计最终封住的 ztgc）
  - 由于 zbgc 无法提供连板高度，无法做“高位未回封炸板率”精确分层；因此 risk.z 采用 highOpenRate
  - 同时在 axes.risk.components 中给出 zbgc_ratio 作为系统性分歧补充（可复算）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _to_num(v: Any, d: float = 0.0) -> float:
    try:
        if v is None:
            return d
        if isinstance(v, str):
            s = v.replace("%", "").strip()
            return float(s) if s else d
        return float(v)
    except Exception:
        return d


def _time_to_min(s: Any) -> Optional[int]:
    """
    fbt/lbt: 'HHMMSS'（如 '092500'）
    """
    try:
        t = str(s or "").strip()
        if len(t) != 6 or not t.isdigit():
            return None
        hh = int(t[0:2])
        mm = int(t[2:4])
        ss = int(t[4:6])
        return hh * 60 + mm + (1 if ss >= 30 else 0)
    except Exception:
        return None


def _calc_early_seal_rate(ztgc: List[Dict[str, Any]]) -> float:
    """
    earlySealRate: 9:30~10:00 首封占比（基于 fbt）
    """
    if not ztgc:
        return 0.0
    a = 9 * 60 + 30
    b = 10 * 60
    ok = 0
    tot = 0
    for it in ztgc:
        if not isinstance(it, dict):
            continue
        tot += 1
        m = _time_to_min(it.get("fbt"))
        if m is not None and a <= m <= b:
            ok += 1
    return ok / tot if tot else 0.0


def _calc_high_open_rate(ztgc: List[Dict[str, Any]], *, min_board: int = 5) -> float:
    """
    高位炸板压力：在最终封住的涨停股中，高位(>=min_board)发生过炸板（zbc>0）的比例
    """
    highs = [it for it in ztgc if isinstance(it, dict) and int(_to_num(it.get("lbc"), 0)) >= min_board]
    if not highs:
        return 0.0
    opened = [it for it in highs if int(_to_num(it.get("zbc"), 0)) > 0]
    return len(opened) / len(highs) if highs else 0.0


def _calc_zbgc_ratio(zbgc: List[Dict[str, Any]], ztgc: List[Dict[str, Any]]) -> float:
    """
    系统性分歧补充：炸板池 / (炸板池 + 涨停池)
    """
    zb = len(zbgc) if isinstance(zbgc, list) else 0
    zt = len(ztgc) if isinstance(ztgc, list) else 0
    denom = zb + zt
    return zb / denom if denom else 0.0


def _calc_volume_size(md: dict[str, Any]) -> float:
    """
    气泡大小（0~1）：用 volume.values 归一化到最近5日区间。
    """
    vol = md.get("volume") or {}
    vals = vol.get("values") or []
    if not isinstance(vals, list) or len(vals) < 2:
        return 0.5
    xs = [float(x) for x in vals if _to_num(x, None) is not None]
    if not xs:
        return 0.5
    v = float(xs[-1])
    lo = min(xs)
    hi = max(xs)
    span = (hi - lo) or 1.0
    return max(0.0, min(1.0, (v - lo) / span))


def _analyze_trend(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    从历史轨迹中分析趋势方向。

    返回：
    - supportTrend: 承接趋势 ("up"/"down"/"flat")
    - consistencyTrend: 一致性趋势
    - riskTrend: 风险趋势
    - verdict: 一句话总结
    - arrows: 各轴的箭头符号
    """
    if len(history) < 3:
        return {
            "supportTrend": "flat", "consistencyTrend": "flat", "riskTrend": "flat",
            "verdict": "数据不足，需积累更多交易日",
            "arrows": {"x": "→", "y": "→", "z": "→"},
        }

    # 取最近3天的变化方向
    recent = history[-3:]
    
    def _axis_trend(key: str) -> str:
        vals = [(h.get(key)) for h in recent if h.get(key) is not None]
        if len(vals) < 2:
            return "flat"
        # 简单判断：最近值 vs 最早值
        if vals[-1] > vals[0] * 1.03:
            return "up"
        elif vals[-1] < vals[0] * 0.97:
            return "down"
        return "flat"

    s_trend = _axis_trend("x")   # 承接
    c_trend = _axis_trend("y")   # 一致性
    r_trend = _axis_trend("z")   # 风险

    arrow_map = {"up": "↗", "down": "↘", "flat": "→"}
    arrows = {"x": arrow_map[s_trend], "y": arrow_map[c_trend], "z": arrow_map[r_trend]}

    # 综合判定
    parts = []
    if s_trend == "up":
        parts.append("承接在变好")
    elif s_trend == "down":
        parts.append("承接在走弱")

    if c_trend == "up":
        parts.append("一致性增强")
    elif c_trend == "down":
        parts.append("一致性下降")

    if r_trend == "up":
        parts.append("⚠️风险上升")
    elif r_trend == "down":
        parts.append("风险下降")

    verdict = "，".join(parts) if parts else "整体平稳"

    return {
        "supportTrend": s_trend,
        "consistencyTrend": c_trend,
        "riskTrend": r_trend,
        "verdict": verdict,
        "arrows": arrows,
    }


def build_three_quadrants(market_data: dict[str, Any]) -> dict[str, Any]:
    md = market_data or {}
    mi = (md.get("features") or {}).get("mood_inputs") or {}
    pools = ((md.get("raw") or {}).get("pools") or {}) if isinstance(md.get("raw"), dict) else {}
    ztgc = pools.get("ztgc") or md.get("ztgc") or []
    zbgc = pools.get("zbgc") or []
    dtgc = pools.get("dtgc") or []

    # X: 承接（晋级率）
    jj = _to_num(mi.get("jj_rate_adj", mi.get("jj_rate")), 0.0) / 100.0
    jj = max(0.0, min(1.0, jj))

    # Y: 一致性（早封率）
    early = _calc_early_seal_rate(ztgc if isinstance(ztgc, list) else [])
    early = max(0.0, min(1.0, early))

    # Z: 风险（高位炸板压力 proxy + 系统性炸板比补充）
    high_open = _calc_high_open_rate(ztgc if isinstance(ztgc, list) else [], min_board=5)
    zbgc_ratio = _calc_zbgc_ratio(zbgc if isinstance(zbgc, list) else [], ztgc if isinstance(ztgc, list) else [])
    z = max(0.0, min(1.0, high_open))

    # 轨迹点（近5日）：依赖 cli 注入的 hist_days 等；若缺则只输出今日点
    hist_days = mi.get("hist_days") if isinstance(mi, dict) else None
    history: List[Dict[str, Any]] = []
    if isinstance(hist_days, list) and len(hist_days) >= 2:
        # 仅填充日期占位；具体 x/y/z 在 cli 侧读取历史文件时填充（保持单日函数纯粹）
        for d in hist_days[-5:]:
            history.append({"date": str(d)[5:], "x": None, "y": None, "z": None})

    out = {
        "position": {
            "x": round(jj, 4),
            "y": round(early, 4),
            "z": round(z, 4),
            "quadrant": "",  # 由 interpret 填
        },
        "axes": {
            "support": {"value": round(jj, 4), "label": "承接", "components": {"jj_rate": _to_num(mi.get("jj_rate", 0), 0)}},
            "consistency": {"value": round(early, 4), "label": "早封率", "components": {"earlySealRate": round(early, 4)}},
            "risk": {
                "value": round(z, 4),
                "label": "高位炸板压力",
                "components": {
                    "highOpenRate_ge5": round(high_open, 4),
                    "zbgcRatio": round(zbgc_ratio, 4),
                    "dtCount": len(dtgc) if isinstance(dtgc, list) else 0,
                },
            },
        },
        "history": history,
        "bubble": {"size": round(_calc_volume_size(md), 4)},
        "interpretation": {},
    }

    # quadrant & interpretation（可复算的规则）
    # 规则：y 高且 x 高且 z 低 → 理想；y 低且 x 低且 z 高 → 杀戮
    if jj >= 0.28 and early >= 0.35 and z <= 0.15:
        zone = "理想区"
        action = "可参与接力"
        warn = "注意高位拥挤与尾盘回封"
    elif jj <= 0.18 and early <= 0.25 and z >= 0.25:
        zone = "杀戮区"
        action = "以防守为主"
        warn = "等待冰点后再试错"
    else:
        zone = "安全区边缘" if z <= 0.2 else "警戒区"
        action = "低位试错"
        warn = "承接偏弱，避免中高位接力" if jj < 0.25 else "关注分歧回封与主线扩散"

    out["position"]["quadrant"] = zone
    out["interpretation"] = {"zone": zone, "action": action, "warning": warn}

    # 趋势分析：从历史轨迹判断各轴方向
    trend = _analyze_trend(history)
    out["trend"] = trend

    # 简化 meta（去掉技术术语）
    out["meta"] = {
        "precision": "strict",
        "notes": [
            f"X轴=承接(晋级率){trend['arrows']['x']}  Y轴=一致性(早封率){trend['arrows']['y']}  Z轴=风险(高位炸板){trend['arrows']['z']}",
            f"趋势总结: {trend['verdict']}",
        ],
    }
    return out

