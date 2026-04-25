#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
features.build_features：从 raw 提取可复用特征（供 modules 复用/partial 重算）

当前实现为"最小可用版"，覆盖：
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
    qsgc = pools.get("qsgc") or []

    zt = zt if isinstance(zt, list) else []
    zb = zb if isinstance(zb, list) else []
    dt = dt if isinstance(dt, list) else []
    yest_zt = yest_zt if isinstance(yest_zt, list) else []
    qsgc = qsgc if isinstance(qsgc, list) else []

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

    # 梯队结构（2板/3板/4+ /5+）
    lb_2 = len([s for s in zt if _lbc_of(s) == 2])
    lb_3 = len([s for s in zt if _lbc_of(s) == 3])
    lb_4p = len([s for s in zt if _lbc_of(s) >= 4])
    lb_5p = len([s for s in zt if _lbc_of(s) >= 5])

    # 梯队完整性评分（0~100）：最小可用版
    # - 有高度锚（5+ 或 4+）加分
    # - 3板/2板梯队足够加分
    # - 极端"只有最高板、下面断层"会显著扣分
    tier_score = 0
    tier_score += 25 if lb_5p >= 1 else (15 if lb_4p >= 1 else 0)
    tier_score += 25 if (lb_3 >= 2) else (15 if lb_3 >= 1 else 0)
    tier_score += 25 if (lb_2 >= 4) else (15 if lb_2 >= 2 else 0)
    tier_score += 25 if zt_count >= 40 else (15 if zt_count >= 30 else 0)
    tier_integrity_score = max(0, min(100, tier_score))
    tier_integrity_low = 1 if tier_integrity_score < 50 else 0

    # ===== 昨日→今日：用"代码匹配"计算晋级/断板（对齐直觉口径）=====
    def _code6(s: Mapping[str, Any]) -> str:
        dm = str(s.get("dm") or s.get("code") or "")
        digits = "".join([c for c in dm if c.isdigit()])
        return digits[-6:] if len(digits) >= 6 else digits

    today_map = {_code6(s): _lbc_of(s) for s in zt if isinstance(s, dict) and _code6(s)}
    yest_map = {_code6(s): _lbc_of(s) for s in yest_zt if isinstance(s, dict) and _code6(s)}

    yest_lb_codes = [c for c, lb in yest_map.items() if lb >= 2]
    yest_2b_codes = [c for c, lb in yest_map.items() if lb == 2]
    yest_3b_codes = [c for c, lb in yest_map.items() if lb == 3]

    yest_lb_count = len(yest_lb_codes)
    yest_2b_count = len(yest_2b_codes)
    yest_3b_count = len(yest_3b_codes)

    succ_2to3 = sum(1 for c in yest_2b_codes if today_map.get(c, 0) >= 3)
    succ_3to4 = sum(1 for c in yest_3b_codes if today_map.get(c, 0) >= 4)
    rate_2to3 = (succ_2to3 / yest_2b_count * 100.0) if yest_2b_count else 0.0
    rate_3to4 = (succ_3to4 / yest_3b_count * 100.0) if yest_3b_count else 0.0

    duanban_count = sum(1 for c in yest_lb_codes if c not in today_map)
    broken_lb_rate = (duanban_count / yest_lb_count * 100.0) if yest_lb_count else 0.0
    jj_rate = ((yest_lb_count - duanban_count) / yest_lb_count * 100.0) if yest_lb_count else 0.0

    # 小票活跃度：lt<50亿
    smallcap = [s for s in zt if (_to_float(s.get("lt"), 0.0) / 1e8) < 50]
    smallcap_cnt = len(smallcap)
    smallcap_ratio = (smallcap_cnt / zt_count * 100.0) if zt_count else 0.0

    # bf_count（大面/负反馈）：对齐 gen_report_v4 口径（跌停池 + 强势股池中 <= -5%）
    big_face = []
    for s in dt:
        if not isinstance(s, dict):
            continue
        zf = _to_float(s.get("zf"), 0.0)
        if zf <= -5:
            big_face.append((_code6(s), str(s.get("mc") or "")))
    for s in qsgc:
        if not isinstance(s, dict):
            continue
        zf = _to_float(s.get("zf"), 0.0)
        if zf <= -5:
            big_face.append((_code6(s), str(s.get("mc") or "")))
    # 去重
    seen = set()
    big_face_names = []
    for c, n in big_face:
        if not c or c in seen:
            continue
        seen.add(c)
        if n:
            big_face_names.append(n)
    bf_count = len(seen)

    # 昨日强势反馈（qs_*）：如果 qsgc 提供 zf，则可直接统计
    qs_all = [s for s in qsgc if isinstance(s, dict)]
    qs_zfs = [(float(s.get("zf", 0) or 0), str(s.get("mc") or "")) for s in qs_all]
    qs_zfs.sort(key=lambda x: x[0], reverse=True)
    qs_avg_zf = (sum(z for z, _ in qs_zfs) / len(qs_zfs)) if qs_zfs else 0.0
    qs_best_zf, qs_best_name = (qs_zfs[0][0], qs_zfs[0][1]) if qs_zfs else (0.0, "—")
    qs_worst_zf, qs_worst_name = (qs_zfs[-1][0], qs_zfs[-1][1]) if qs_zfs else (0.0, "—")
    qs_extreme_up = len([1 for z, _ in qs_zfs if z >= 5])
    qs_positive = len([1 for z, _ in qs_zfs if 0 <= z < 5])
    qs_negative = len([1 for z, _ in qs_zfs if -5 < z < 0])
    qs_extreme_down = len([1 for z, _ in qs_zfs if z <= -5])

    # 风险突刺（最小可用版）：用于更快识别"转弱/退潮确认"
    # 注：后续若补齐 delta_*（昨日变化）可把规则改成"突刺=变化共振"
    risk_spike = 1 if (zb_rate >= 35.0 and dt_count >= 8 and broken_lb_rate >= 30.0) else 0

    # 昨日涨停今日平均涨跌幅：用于判断"真假修复"
    # 匹配逻辑：用代码找到昨天涨停的票 → 看今天涨跌
    yest_zt_chgs = []
    for s in yest_zt:
        if not isinstance(s, dict):
            continue
        code = _code6(s)
        if not code:
            continue
        # 从今天的涨停池/炸板池/强势池找这只票的今日涨跌幅
        found = False
        zf = _to_float(s.get("zf"), None)  # 有些数据源自带今日涨跌
        for pool in (zt, zb, dt, qsgc):
            for t in pool:
                if not isinstance(t, dict):
                    continue
                if _code6(t) == code:
                    z = _to_float(t.get("zf"), None)
                    if z is not None:
                        yest_zt_chgs.append(z)
                        found = True
                        break
            if found:
                break
        # 如果在所有池子里都找不到，但有自带zf就用自带的
        if not found and zf is not None:
            yest_zt_chgs.append(zf)

    yest_zt_avg_chg = (sum(yest_zt_chgs) / len(yest_zt_chgs)) if yest_zt_chgs else 0.0

    # 高位断板信息
    duanban_lbs = [(today_map.get(c, 0), c) for c in yest_lb_codes if c not in today_map]
    duanban_lbs.sort(reverse=True)
    top_duanban_name = ""
    top_duanban_lb = 0
    top_duanban_is_high = 0
    if duanban_lbs:
        top_duanban_lb = duanban_lbs[0][0]
        # 找断板股票名字
        for s in yest_zt:
            if _code6(s) == duanban_lbs[0][1]:
                top_duanban_name = str(s.get("mc") or "")[:4]
                break
        top_duanban_is_high = 1 if top_duanban_lb >= 5 else 0

    return {
        "fb_rate": round(fb_rate, 1),
        "jj_rate": round(jj_rate, 1),
        "zb_rate": round(zb_rate, 1),
        "dt_count": int(dt_count),
        "bf_count": int(bf_count),
        "bf_names": "、".join(big_face_names[:3]) if big_face_names else "无",
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
        "lb_2": int(lb_2),
        "lb_3": int(lb_3),
        "lb_4p": int(lb_4p),
        "lb_5p": int(lb_5p),
        "tier_integrity_score": int(tier_integrity_score),
        "tier_integrity_low": int(tier_integrity_low),
        "risk_spike": int(risk_spike),
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
        "qs_avg_zf": round(qs_avg_zf, 2),
        "qs_best_name": qs_best_name or "—",
        "qs_best_zf": round(qs_best_zf, 2),
        "qs_worst_name": qs_worst_name or "—",
        "qs_worst_zf": round(qs_worst_zf, 2),
        "qs_extreme_up": int(qs_extreme_up),
        "qs_positive": int(qs_positive),
        "qs_negative": int(qs_negative),
        "qs_extreme_down": int(qs_extreme_down),
        # 真假修复核心指标
        "yest_zt_avg_chg": round(yest_zt_avg_chg, 2),
        # 高位断板
        "top_duanban_name": top_duanban_name,
        "top_duanban_lb": top_duanban_lb,
        "top_duanban_is_high": top_duanban_is_high,
    }


def build_style_inputs(
    *,
    mood_inputs: Mapping[str, Any],
    theme_panels: Mapping[str, Any] | None = None,
    ztgc: list[dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """
    尽量对齐 gen_report_v4 的 style_inputs，但只依赖现有数据。
    """
    zt_count = int(mood_inputs.get("zt_count", 0) or 0)
    max_lb = int(mood_inputs.get("max_lb", 0) or 0)
    ztgc = ztgc if isinstance(ztgc, list) else []

    def _lbc(s: Mapping[str, Any]) -> int:
        try:
            return int(s.get("lbc", 1) or 1)
        except Exception:
            return 1

    first_board_count = len([s for s in ztgc if isinstance(s, dict) and _lbc(s) == 1])
    gem_today = [s for s in ztgc if isinstance(s, dict) and str(s.get("dm", "")).startswith("300")]
    gem_today_count = len(gem_today)
    gem_height = max((_lbc(s) for s in gem_today), default=0)

    high_level_ratio = 0.0
    if zt_count:
        high_level_ratio = len([s for s in ztgc if isinstance(s, dict) and _lbc(s) >= 5]) / zt_count * 100.0
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
        "first_board_count": int(first_board_count),
        "zt_count": zt_count,
        "gem_today_count": int(gem_today_count),
        "gem_height": int(gem_height),
        "top3_theme_ratio": round(top3_ratio, 1),
        "top10_concentration": 0,
        "high_level_ratio": round(high_level_ratio, 1),
        "max_lb": max_lb,
    }


def default_chart_palette() -> list[str]:
    return ["#ef4444", "#f97316", "#f59e0b", "#fb7185"]
