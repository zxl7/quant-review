#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模块④（v2 规格书，落地版）：板块梯队 & 主线判断（主流/支流/次主流）

数据来源（离线可跑）：
- market_data.ztgc（涨停池，含 lbc/zf/cje/hs/zbc）
- market_data.zt_code_themes / raw.themes.code2themes（个股→题材映射）
- cache/theme_trend_cache.json（by_day: 每日题材出现次数，用于持续性/活跃天数）

输出（v2）：
- mainline: {exists, top_sector, level, strength, conditions, strategy}
- sectors: 主题列表（topN），每个包含 ladder + health
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


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


THEME_LEVEL_STRATEGY = {
    "主流": {
        "hold_period": "中长线(1-4周)",
        "position_size": "可重仓(50-100%)",
        "tactics": "打板/半路/低吸均可",
        "key_rule": "主流不必等涨停也可随时买入，确认强度后加仓",
        "source": "养家心法",
    },
    "支流": {
        "hold_period": "中线(3-7天)",
        "position_size": "中等仓位(20-50%)",
        "tactics": "打板为主",
        "key_rule": "以龙头标杆品种走势为参考，逢高卖出套利",
        "source": "养家心法",
    },
    "次主流": {
        "hold_period": "超短(1-2天)",
        "position_size": "轻仓(10-20%)",
        "tactics": "只能打板",
        "key_rule": "隔日超短，不恋战",
        "source": "养家心法",
    },
    "无主题": {"hold_period": "-", "position_size": "轻仓/空仓", "tactics": "观望", "key_rule": "无明显主线，避免追逐轮动", "source": ""},
}


def _pick_primary_theme(code6: str, row: Dict[str, Any], code2themes: Dict[str, List[str]]) -> str:
    ths = code2themes.get(code6) or []
    if isinstance(ths, list) and ths:
        return str(ths[0] or "")
    # 兜底：行业字段
    return str(row.get("hy") or "")


def _build_ladder(stocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    梯队：龙头/龙二/龙三/补涨
    由于缺少完整历史，这里用：
    - 连板数 lbc
    - 成交额 cje
    - 今日涨幅 zf
    组合排序。
    """
    def key(x: Dict[str, Any]) -> Tuple[int, float, float]:
        return (_to_int(x.get("lbc"), 1), _to_float(x.get("zf"), 0.0), _to_float(x.get("cje"), 0.0))

    ss = sorted([s for s in stocks if isinstance(s, dict)], key=key, reverse=True)
    dragon = ss[0] if len(ss) > 0 else None
    d2 = ss[1] if len(ss) > 1 else None
    d3 = ss[2] if len(ss) > 2 else None
    followers = ss[3:] if len(ss) > 3 else []

    health = _calc_ladder_health(dragon, d2, d3, followers)
    return {
        "dragon": _compact_stock(dragon),
        "dragon_2": _compact_stock(d2),
        "dragon_3": _compact_stock(d3),
        "followers": [_compact_stock(x) for x in followers[:8]],
        "health_score": round(health, 1),
        "health_grade": _grade_health(health),
        "follower_cnt": len(followers),
    }


def _compact_stock(x: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not x:
        return None
    return {
        "code": str(x.get("dm") or x.get("code") or ""),
        "name": str(x.get("mc") or x.get("name") or ""),
        "boards": _to_int(x.get("lbc"), 1),
        "pct": round(_to_float(x.get("zf"), 0.0), 2),
        "amount": _to_float(x.get("cje"), 0.0),
        "open_times": _to_int(x.get("zbc"), 0),
        "turnover": _to_float(x.get("hs"), 0.0),
    }


def _calc_ladder_health(dragon: Optional[Dict[str, Any]], d2: Optional[Dict[str, Any]], d3: Optional[Dict[str, Any]], followers: List[Dict[str, Any]]) -> float:
    score = 0.0
    if dragon:
        score += 3
        score += min(2.0, _to_int(dragon.get("lbc"), 1) * 0.4)
    if d2:
        score += 2
    if d3:
        score += 1

    n = len(followers)
    if n >= 5:
        score += 2
    elif n >= 3:
        score += 1.5
    elif n >= 1:
        score += 1

    # 联动性 proxy：龙头涨幅高时，龙二是否也偏强
    if dragon and d2:
        dragon_chg = _to_float(dragon.get("zf"), 0.0)
        d2_chg = _to_float(d2.get("zf"), 0.0)
        if dragon_chg > 5 and d2_chg > 3:
            score += 1
        elif dragon_chg > 5 and d2_chg < 0:
            score -= 1
    return _clamp(score, 0, 10)


def _grade_health(health: float) -> str:
    if health >= 8:
        return "A"
    if health >= 6:
        return "B"
    if health >= 4:
        return "C"
    return "D"


def _duration_days(by_day: Dict[str, Dict[str, int]], theme: str, days: List[str]) -> int:
    """过去 N 个交易日内出现的天数。"""
    cnt = 0
    for d in days:
        day_map = by_day.get(d) or {}
        if int(day_map.get(theme, 0) or 0) > 0:
            cnt += 1
    return cnt


def _active_days_consecutive(by_day: Dict[str, Dict[str, int]], theme: str, days: List[str], th: int = 2) -> int:
    """连续活跃天数：从最近往前数，单日出现次数>=th 算活跃。"""
    streak = 0
    for d in reversed(days):
        day_map = by_day.get(d) or {}
        if int(day_map.get(theme, 0) or 0) >= th:
            streak += 1
        else:
            break
    return streak


def classify_theme_level(*, policy_level: str = "", duration_days: int = 0, volume_ratio: float = 0.0, has_complete_ladder: bool = False) -> str:
    """
    v2 规格书：主流判定满足任意 2 个信号
    由于 policy_level 目前缺数据，默认走“持续+占比+梯队”。
    """
    mainstream_signals = 0
    if policy_level == "national":
        mainstream_signals += 1
    if duration_days >= 10:
        mainstream_signals += 1
    if volume_ratio >= 0.15:
        mainstream_signals += 1
    if has_complete_ladder:
        mainstream_signals += 1

    if mainstream_signals >= 2:
        return "主流"
    if duration_days >= 3 and volume_ratio >= 0.05:
        return "支流"
    if duration_days >= 1:
        return "次主流"
    return "无主题"


def build_sector_ladders(market_data: Dict[str, Any], theme_trend_cache: Dict[str, Any] | None = None) -> Dict[str, Any]:
    md = market_data or {}
    ztgc = md.get("ztgc") if isinstance(md.get("ztgc"), list) else []
    zt_cnt = len(ztgc)

    code2themes = md.get("zt_code_themes") or (((md.get("raw") or {}).get("themes") or {}).get("code2themes") if isinstance(md.get("raw"), dict) else {})
    code2themes = code2themes if isinstance(code2themes, dict) else {}

    by_day = (theme_trend_cache or {}).get("by_day") or {}
    by_day = by_day if isinstance(by_day, dict) else {}

    # 取近 12 个交易日作为“持续性观察窗”
    # 若 tradeDays 不可用，退化为 by_day 的 key 排序
    days = sorted([d for d in by_day.keys() if isinstance(d, str)])[-12:]

    # 统计主题 -> 股票列表（用第一主题作为主类，避免“多标签虚胖”）
    theme_map: Dict[str, List[Dict[str, Any]]] = {}
    for r in ztgc:
        if not isinstance(r, dict):
            continue
        code6 = "".join([c for c in str(r.get("dm") or "") if c.isdigit()])[-6:]
        th = _pick_primary_theme(code6, r, code2themes)
        if not th:
            continue
        theme_map.setdefault(th, []).append(r)

    sectors = []
    for th, arr in theme_map.items():
        ladder = _build_ladder(arr)
        zt_ratio = (len(arr) / max(1, zt_cnt))
        duration = _duration_days(by_day, th, days) if days else 0
        active_days = _active_days_consecutive(by_day, th, days, th=2) if days else 1
        has_complete = bool(ladder.get("dragon") and ladder.get("dragon_2") and ladder.get("dragon_3") and ladder.get("follower_cnt", 0) >= 3)
        level = classify_theme_level(duration_days=duration, volume_ratio=zt_ratio, has_complete_ladder=has_complete)
        sectors.append(
            {
                "name": th,
                "zt_count": len(arr),
                "zt_ratio": round(zt_ratio, 3),
                "active_days": int(active_days),
                "duration_days": int(duration),
                "level": level,
                "ladder": ladder,
            }
        )

    # 排序：先按涨停数量，再按梯队健康
    sectors.sort(key=lambda x: (x.get("zt_count", 0), x.get("ladder", {}).get("health_score", 0)), reverse=True)
    return {"sectors": sectors[:12], "all_count": len(sectors)}


def judge_mainline(sectors: List[Dict[str, Any]], sentiment_score: float) -> Dict[str, Any]:
    if not sectors:
        return {"exists": False, "reason": "无活跃板块"}
    top = sectors[0]

    cond1 = float(top.get("zt_ratio") or 0) >= 0.20
    cond2 = float((top.get("ladder") or {}).get("health_score") or 0) >= 3.0
    cond3 = int(top.get("active_days") or 1) >= 2
    exists = bool(cond1 and cond2 and cond3)

    level = str(top.get("level") or "无主题")
    strength = ("主线极强" if sentiment_score >= 8 and exists else "主线存在" if sentiment_score >= 5 and exists else "主线偏弱" if exists else "无明显主线")

    return {
        "exists": exists,
        "top_sector": str(top.get("name") or ""),
        "level": level if exists else None,
        "conditions": {"c1_占比达标": cond1, "c2_梯队健康": cond2, "c3_持续活跃": cond3},
        "strength": strength,
        "strategy": THEME_LEVEL_STRATEGY.get(level, {}) if exists else {},
    }

