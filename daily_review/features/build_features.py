#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
features.build_features：从 raw 提取可复用特征（供 modules 复用/partial 重算）

当前实现为“最小可用版”，覆盖：
- features.mood_inputs：情绪模块输入（mood）
- features.style_inputs：风格雷达输入（style_radar）
- features.chart_palette：图表配色

原则：
- 不做网络请求
- 尽量纯函数（除依赖传入的 raw/market_data）
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _to_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(float(v))
    except Exception:
        return default


def _quantile(xs: Sequence[float], q: float, default: float = 0.0) -> float:
    if not xs:
        return default
    ys = sorted(xs)
    q = max(0.0, min(1.0, q))
    pos = (len(ys) - 1) * q
    lo = int(pos)
    hi = min(len(ys) - 1, lo + 1)
    if lo == hi:
        return ys[lo]
    w = pos - lo
    return ys[lo] * (1.0 - w) + ys[hi] * w


def _is_time_leq(hms: str, threshold: str) -> bool:
    s = str(hms or "").strip()
    if not s:
        return False
    if len(s) == 6 and s.isdigit():
        s = f"{s[0:2]}:{s[2:4]}:{s[4:6]}"
    # HH:MM:SS 固定格式可直接比较
    return s <= threshold


def _lbc_of(s: Mapping[str, Any]) -> int:
    lb = s.get("lbc", None)
    if lb is not None:
        return max(1, _to_int(lb, 1))
    tj = str(s.get("tj", "") or "")
    try:
        parts = tj.split("/")
        if len(parts) == 2:
            return max(1, int(parts[1]))
    except Exception:
        pass
    return 1


def build_mood_inputs(*, pools: Mapping[str, Any]) -> Dict[str, Any]:
    zt = pools.get("ztgc") or []
    zb = pools.get("zbgc") or []
    dt = pools.get("dtgc") or []
    yest_zt = pools.get("yest_ztgc") or []

    zt = zt if isinstance(zt, list) else []
    zb = zb if isinstance(zb, list) else []
    dt = dt if isinstance(dt, list) else []
    yest_zt = yest_zt if isinstance(yest_zt, list) else []

    zt_count = len(zt)
    zb_count = len(zb)
    dt_count = len(dt)

    fb_rate = (zt_count / (zt_count + zb_count) * 100.0) if (zt_count + zb_count) else 0.0
    zb_rate = (zb_count / (zt_count + zb_count) * 100.0) if (zt_count + zb_count) else 0.0

    # 高位炸板占比（4板+）
    zb_high = [s for s in zb if _lbc_of(s) >= 4]
    zb_high_count = len(zb_high)
    zb_high_ratio = (zb_high_count / zb_count * 100.0) if zb_count else 0.0
    zb_high_names = "、".join([str(s.get("mc") or "") for s in sorted(zb_high, key=lambda x: _lbc_of(x), reverse=True)[:3] if str(s.get("mc") or "").strip()])

    # 早封占比（<=10:00）
    zt_early = [s for s in zt if _is_time_leq(str(s.get("fbt") or ""), "10:00:00")]
    zt_early_count = len(zt_early)
    zt_early_ratio = (zt_early_count / zt_count * 100.0) if zt_count else 0.0

    # 涨停炸板次数均值 + 高炸板占比
    zbc_list = [_to_int(s.get("zbc"), 0) for s in zt]
    avg_zt_zbc = (sum(zbc_list) / len(zbc_list)) if zbc_list else 0.0
    zt_zbc_ge3_ratio = (len([x for x in zbc_list if x >= 3]) / len(zbc_list) * 100.0) if zbc_list else 0.0

    # 封板资金（用 zj 近似）
    seal_list = [_to_float(s.get("zj"), 0.0) for s in zt if _to_float(s.get("zj"), 0.0) > 0]
    avg_seal_fund_yi = (sum(seal_list) / len(seal_list) / 1e8) if seal_list else 0.0
    top3 = sorted([( _to_float(s.get("zj"), 0.0), str(s.get("mc") or "")) for s in zt], reverse=True)[:3]
    top_seal_names = "、".join([f"{n}{(amt/1e8):.0f}亿" for amt, n in top3 if n and amt > 0])

    # 换手中位数
    hs_list = [_to_float(s.get("hs"), 0.0) for s in zt if _to_float(s.get("hs"), 0.0) > 0]
    hs_median = float(_quantile(hs_list, 0.5, 0.0))
    hs_ge15_ratio = (len([x for x in hs_list if x >= 15]) / len(hs_list) * 100.0) if hs_list else 0.0

    # 高度 max/second/gap（基于涨停池）
    lbs = sorted([_lbc_of(s) for s in zt], reverse=True)
    max_lb = int(lbs[0]) if lbs else 0
    second_lb = int(lbs[1]) if len(lbs) >= 2 else int(lbs[0]) if lbs else 0
    height_gap = int(max(0, max_lb - second_lb))

    # 昨日连板结构（用于晋级率/断板率）
    yest_lbs = [_lbc_of(s) for s in yest_zt]
    yest_lb_count = len([lb for lb in yest_lbs if lb >= 2])
    yest_2b_count = len([lb for lb in yest_lbs if lb == 2])
    yest_3b_count = len([lb for lb in yest_lbs if lb == 3])

    # 今日晋级：昨日2板 -> 今日3板+；昨日3板 -> 今日4板+
    today_3p = len([_lbc_of(s) for s in zt if _lbc_of(s) >= 3])
    today_4p = len([_lbc_of(s) for s in zt if _lbc_of(s) >= 4])
    succ_2to3 = len([s for s in zt if _lbc_of(s) >= 3 and _lbc_of(s) - 1 == 2])
    succ_3to4 = len([s for s in zt if _lbc_of(s) >= 4 and _lbc_of(s) - 1 == 3])
    rate_2to3 = (succ_2to3 / yest_2b_count * 100.0) if yest_2b_count else 0.0
    rate_3to4 = (succ_3to4 / yest_3b_count * 100.0) if yest_3b_count else 0.0

    # 简化版晋级率：晋级 = 今日连板且昨日存在（粗略）
    jj_rate = (len([s for s in zt if _lbc_of(s) >= 2]) / max(yest_lb_count, 1) * 100.0) if yest_lb_count else 0.0
    duanban_count = max(0, yest_lb_count - len([s for s in zt if _lbc_of(s) >= 2 and (_lbc_of(s) - 1) >= 1]))
    broken_lb_rate = (duanban_count / yest_lb_count * 100.0) if yest_lb_count else 0.0

    # 小票活跃度：lt<50亿
    smallcap = [s for s in zt if (_to_float(s.get("lt"), 0.0) / 1e8) < 50]
    smallcap_cnt = len(smallcap)
    smallcap_ratio = (smallcap_cnt / zt_count * 100.0) if zt_count else 0.0

    # bf_count（大面/负反馈）数据源不稳定：先用 dt_count 近似兜底
    bf_count = dt_count

    return {
        "fb_rate": round(fb_rate, 1),
        "jj_rate": round(jj_rate, 1),
        "zb_rate": round(zb_rate, 1),
        "dt_count": int(dt_count),
        "bf_count": int(bf_count),
        "zt_count": int(zt_count),
        "zb_count": int(zb_count),
        "zt_early_ratio": round(zt_early_ratio, 1),
        "zt_early_count": int(zt_early_count),
        "avg_seal_fund_yi": round(avg_seal_fund_yi, 2),
        "top_seal_names": top_seal_names,
        "hs_median": round(hs_median, 2),
        "hs_ge15_ratio": round(hs_ge15_ratio, 1),
        "rate_2to3": round(rate_2to3, 1),
        "rate_3to4": round(rate_3to4, 1),
        "yest_2b_count": int(yest_2b_count),
        "yest_3b_count": int(yest_3b_count),
        "succ_2to3": int(succ_2to3),
        "succ_3to4": int(succ_3to4),
        "max_lb": int(max_lb),
        "second_lb": int(second_lb),
        "height_gap": int(height_gap),
        "zb_high_ratio": round(zb_high_ratio, 1),
        "zb_high_count": int(zb_high_count),
        "zb_high_names": zb_high_names,
        "avg_zt_zbc": round(avg_zt_zbc, 2),
        "zt_zbc_ge3_ratio": round(zt_zbc_ge3_ratio, 1),
        "smallcap_ratio": round(smallcap_ratio, 1),
        "smallcap_cnt": int(smallcap_cnt),
        "broken_lb_rate": round(broken_lb_rate, 1),
        "yest_lb_count": int(yest_lb_count),
        "duanban_count": int(duanban_count),
        # 先给默认值，避免阶段判定里出现 KeyError/空值
        "broken_lb_rate_adj": round(broken_lb_rate, 1),
        "jj_rate_adj": round(jj_rate, 1),
        "effect_verdict_type": "",
        "mood_mode": "aggressive",
        "trend_max_lb": 0,
        "trend_fb_rate": 0,
        "trend_jj_rate": 0,
        "trend_broken_lb_rate": 0,
        "hist_days": [],
        "hist_max_lb": [],
        "hist_fb_rate": [],
        "hist_jj_rate": [],
        "hist_broken_lb_rate": [],
    }


def build_style_inputs(*, mood_inputs: Mapping[str, Any], theme_panels: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """
    尽量对齐 gen_report_v4 的 style_inputs，但只依赖现有数据。
    """
    zt_count = int(mood_inputs.get("zt_count", 0) or 0)
    max_lb = int(mood_inputs.get("max_lb", 0) or 0)
    top3_ratio = 0.0
    if theme_panels and isinstance(theme_panels, dict):
        try:
            top3 = (theme_panels.get("ztTop") or [])[:3]
            top3_cnt = sum([int(x.get("count", 0) or 0) for x in top3 if isinstance(x, dict)])
            top3_ratio = (top3_cnt / zt_count * 100.0) if zt_count else 0.0
        except Exception:
            top3_ratio = 0.0
    return {
        "jj_rate": float(mood_inputs.get("jj_rate", 0) or 0),
        "first_board_count": 0,
        "zt_count": zt_count,
        "gem_today_count": 0,
        "gem_height": 0,
        "top3_theme_ratio": round(top3_ratio, 1),
        "top10_concentration": 0,
        "high_level_ratio": 0,
        "max_lb": max_lb,
    }


def default_chart_palette() -> list[str]:
    return ["#ef4444", "#f97316", "#f59e0b", "#fb7185"]

