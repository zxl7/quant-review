#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
features.build_features：从 raw 提取可复用特征（供 modules 复用/partial 重算）

当前实现为"最小可用版"，覆盖：
- features.mood_inputs：情绪模块输入（mood）
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
    loss = int(bf_count) + int(dt_count)

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
        "loss": int(loss),
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


def default_chart_palette() -> list[str]:
    return ["#ef4444", "#f97316", "#f59e0b", "#fb7185"]


# === v3 扩展特征构建 ===

def build_v3_sentiment_inputs(*, pools, height_history=None, **kwargs) -> Dict[str, Any]:
    """v3 六维情绪评分所需的输入数据构建。

    基于现有的 build_mood_inputs() 输出，转换为 v3 SentimentInput 格式，
    并补充 v3 特有的字段（如高度趋势、主线判断等）。

    Args:
        pools: 三池数据映射 (ztgc/zbgc/dtgc/yest_ztgc/qsgc 等)
        height_history: 近期高度趋势序列 [(date, max_lb), ...]
        **kwargs: 额外字段：
            - main_theme_clear: 主线是否清晰
            - main_theme_strength: 主线强度描述
            - theme_rotation_freq: 板块轮动频率
            - has_tiandiban: 是否有天地板
            - has_ditianban: 是否有地天板
            - is_weekend_ahead: 是否临近周末

    Returns:
        v3 格式的情绪评分输入字典
    """
    base = build_mood_inputs(pools=pools)

    return {
        # 基础字段从base映射
        'zt_count': base['zt_count'],
        'zt_count_yesterday': len(pools.get('yest_ztgc') or []) if pools else 0,
        'lianban_count': base.get('lb_2', 0) + base.get('lb_3', 0) + base.get('lb_4p', 0) + base.get('lb_5p', 0),
        'max_lianban': base['max_lb'],
        'zab_count': base['zb_count'],
        'try_zt_total': base['zt_count'] + base['zb_count'],
        'zab_rate': base['zb_rate'],
        'yest_zt_avg_chg': base.get('yest_zt_avg_chg', 0.0),
        'yest_lianban_promote_rate': base.get('jj_rate', 0.0),
        'yest_duanban_nuclear': sum(
            1 for s in (pools.get("dtgc") or [])
            if isinstance(s, dict) and float(str(s.get('zf', 0) or 0)) < -5
        ),
        'dt_count': base['dt_count'],
        'height_history': height_history if height_history else [],
        'main_theme_clear': kwargs.get('main_theme_clear', False),
        'main_theme_strength': kwargs.get('main_theme_strength', '无'),
        'theme_rotation_freq': kwargs.get('theme_rotation_freq', 0),
        'has_tiandiban': kwargs.get('has_tiandiban', False),
        'has_ditianban': kwargs.get('has_ditianban', False),
        'has_waipan_shock': False,  # 需外部数据源
        'is_weekend_ahead': kwargs.get('is_weekend_ahead', False),
        # 同时保留原始base数据以兼容旧模块
        '_legacy_mood_inputs': base,
    }


def build_v3_dujie_inputs(*, ztgc, yest_ztgc=None, zbgc=None) -> List[Dict]:
    """为渡劫识别准备个股级输入数据。

    从涨停池中提取每只连板股的关键信息，
    用于判断是否存在渡劫信号（高辨识度标的在分歧中存活）。

    Args:
        ztgc: 今日涨停池列表
        yest_ztgc: 昨日涨停池列表（用于计算晋级）
        zbgc: 今日炸板池列表（用于识别断板）

    Returns:
        个股级输入列表，每个元素包含该连板股的关键特征
    """
    ztgc = ztgc if isinstance(ztgc, list) else []
    yest_ztgc = yest_ztgc if isinstance(yest_ztgc, list) else []
    zbgc = zbgc if isinstance(zbgc, list) else []

    def _code6(s: Mapping[str, Any]) -> str:
        dm = str(s.get("dm") or s.get("code") or "")
        digits = "".join([c for c in dm if c.isdigit()])
        return digits[-6:] if len(digits) >= 6 else digits

    def _lbc(s: Mapping[str, Any]) -> int:
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

    results: List[Dict] = []
    for s in ztgc:
        if not isinstance(s, dict):
            continue
        c6 = _code6(s)
        if not c6:
            continue
        lbc = _lbc(s)
        if lbc < 2:  # 只关注连板股
            continue

        # 昨日的连板数
        yest_lbc = 0
        for ys in yest_ztgc:
            if _code6(ys) == c6:
                yest_lbc = _lbc(ys)
                break

        # 是否有炸板记录（今日）
        is_zab = any(_code6(zs) == c6 for zs in zbgc)

        item = {
            "code": c6,
            "name": str(s.get("mc") or ""),
            "lbc_today": lbc,
            "lbc_yesterday": yest_lbc,
            "promoted": (lbc > yest_lbc > 0),
            "zf": _to_float(s.get("zf"), 0.0),
            "zj": _to_float(s.get("zj"), 0.0),       # 封板资金
            "hs": _to_float(s.get("hs"), 0.0),         # 换手率
            "lt": _to_float(s.get("lt"), 0.0),         # 流通市值
            "fbt": str(s.get("fbt") or ""),             # 封板时间
            "zbc": _to_int(s.get("zbc"), 0),           # 炸板次数
            "is_zab": is_zab,
            "themes": s.get("themes", []),
        }
        results.append(item)

    return results


def build_v3_dragon_inputs(*, ztgc, market_context=None) -> List[Dict]:
    """为龙头三要素量化准备个股级输入。

    提取涨停池中高辨识度标的的详细数据，
    用于龙头三要素评估（带领性、突破性、唯一性）。

    Args:
        ztgc: 今日涨停池列表
        market_context: 市场上下文（指数涨跌、量能等），可选

    Returns:
        高辨识度标的的特征列表
    """
    ztgc = ztgc if isinstance(ztgc, list) else []

    def _code6(s: Mapping[str, Any]) -> str:
        dm = str(s.get("dm") or s.get("code") or "")
        digits = "".join([c for c in dm if c.isdigit()])
        return digits[-6:] if len(digits) >= 6 else digits

    def _lbc(s: Mapping[str, Any]) -> int:
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

    # 筛选高辨识度标的：连板 >= 2 或 封板资金靠前
    candidates: List[Tuple[int, Dict]] = []  # (priority_score, stock_dict)
    seal_funds = [(_to_float(s.get("zj"), 0.0), i, s) for i, s in enumerate(ztgc) if isinstance(s, dict)]
    seal_funds.sort(key=lambda x: x[0], reverse=True)

    top_seal_set = set()
    for _, idx, _ in seal_funds[:10]:  # 封板金额前10
        top_seal_set.add(idx)

    for i, s in enumerate(ztgc):
        if not isinstance(s, dict):
            continue
        c6 = _code6(s)
        lbc = _lbc(s)

        # 高辨识度条件：高连板 或 大封单 或 早封
        is_high_lbc = lbc >= 3
        is_top_seal = i in top_seal_set
        is_early_seal = _is_time_leq(str(s.get("fbt") or ""), "09:45:00")

        if not (is_high_lbc or is_top_seal or is_early_seal):
            continue

        priority = 0
        if lbc >= 5:
            priority += 50
        elif lbc >= 4:
            priority += 35
        elif lbc >= 3:
            priority += 20
        elif lbc >= 2:
            priority += 10
        if is_top_seal:
            priority += 15
        if is_early_seal:
            priority += 10

        candidates.append((priority, s))

    candidates.sort(key=lambda x: x[0], reverse=True)

    results: List[Dict] = []
    for priority, s in candidates[:20]:  # 取前20只高辨识度标的
        c6 = _code6(s)
        results.append({
            "code": c6,
            "name": str(s.get("mc") or ""),
            "lbc": _lbc(s),
            "zf": _to_float(s.get("zf"), 0.0),
            "zj": _to_float(s.get("zj"), 0.0),
            "hs": _to_float(s.get("hs"), 0.0),
            "lt": _to_float(s.get("lt"), 0.0),
            "fbt": str(s.get("fbt") or ""),
            "zbc": _to_int(s.get("zbc"), 0),
            "priority": priority,
            "themes": s.get("themes", []),
        })

    return results
