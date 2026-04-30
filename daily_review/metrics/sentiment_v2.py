#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模块①（v2 规格书）：情绪计分卡综合评分算法 + 崩溃前兆链

输出（贴近规格书）：
{
  "score": 0~10,
  "phase": "分歧期/修复期/亢奋期/冰点期/深冰点",
  "risk_level": "低/中/高",
  "dim_scores": {zt_heat, money_effect, lianban_health, negative, theme_clarity, collapse_chain},
  "warnings": [ ... ],
  "debug": { ... }  # 可选
}
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def _to_num(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


def _to_int(x: Any, default: int = 0) -> int:
    try:
        if x is None or x == "":
            return default
        return int(float(x))
    except Exception:
        return default


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _score_zt_heat(zt_today: int, zt_yest: int | None = None) -> float:
    # v2 规格书给的是“今日绝对量阈值”，先落地；后续再做动态阈值/分位数
    if zt_today >= 100:
        base = 10.0
    elif zt_today >= 70:
        base = 8.5
    elif zt_today >= 50:
        base = 7.0
    elif zt_today >= 35:
        base = 5.5
    elif zt_today >= 20:
        base = 4.0
    elif zt_today >= 10:
        base = 2.5
    else:
        base = 1.0

    # 增强：相对昨日的增减做微调（避免“同分不同势”）
    if zt_yest and zt_yest > 0:
        drop_ratio = (zt_yest - zt_today) / zt_yest
        if drop_ratio >= 0.30:
            base = max(0.0, base - 1.0)
        elif drop_ratio <= -0.25:
            base = min(10.0, base + 0.6)
    return base


def _score_zt_heat_dyn(zt_today: int, hist_zt: List[int]) -> float:
    """
    纯函数：涨停热度（动态版，0~10）。

    - 用近 N 日涨停数 hist_zt 做“相对强弱”，避免牛/熊市阈值漂移
    - 历史不足时回退到静态阈值
    """
    hs = [int(x) for x in (hist_zt or []) if isinstance(x, (int, float))]
    if len(hs) < 3:
        return _score_zt_heat(int(zt_today or 0), None)

    hs_sorted = sorted(hs)
    p20 = hs_sorted[max(0, int(len(hs_sorted) * 0.20) - 1)]
    p50 = hs_sorted[max(0, int(len(hs_sorted) * 0.50) - 1)]
    p80 = hs_sorted[max(0, int(len(hs_sorted) * 0.80) - 1)]
    x = int(zt_today or 0)

    if x >= p80:
        return 8.5 if x < p80 * 1.15 else 9.5
    if x >= p50:
        t = (x - p50) / max(1.0, float(p80 - p50))
        return round(5.5 + t * 3.0, 1)
    if x >= p20:
        t = (x - p20) / max(1.0, float(p50 - p20))
        return round(3.0 + t * 2.5, 1)
    return 1.5


def _score_carry_quality(
    *,
    fb_rate: float,
    jj_rate: float,
    broken_lb_rate: float,
    rate_2to3: float,
    rate_3to4: float,
) -> float:
    """
    纯函数：承接质量（0~10）。
    """
    fb = _clamp(_to_num(fb_rate, 0.0), 0.0, 100.0)
    s_fb = 10 if fb >= 75 else (8 if fb >= 65 else (6 if fb >= 55 else (4 if fb >= 45 else 2)))

    jj = _clamp(_to_num(jj_rate, 0.0), 0.0, 100.0)
    s_jj = 10 if jj >= 45 else (8 if jj >= 32 else (6 if jj >= 22 else (4 if jj >= 14 else 2)))

    br = _clamp(_to_num(broken_lb_rate, 0.0), 0.0, 100.0)
    s_br = 10 if br <= 18 else (8 if br <= 28 else (6 if br <= 38 else (4 if br <= 50 else 2)))

    r23 = _clamp(_to_num(rate_2to3, 0.0), 0.0, 100.0)
    r34 = _clamp(_to_num(rate_3to4, 0.0), 0.0, 100.0)
    s_r = ((r23 / 10.0) * 0.6 + (r34 / 10.0) * 0.4)  # 0~10

    return _clamp(round(s_fb * 0.30 + s_jj * 0.35 + s_br * 0.20 + s_r * 0.15, 1), 0, 10)


def _score_structure(tier_integrity_score: float, height_gap: float) -> float:
    """
    纯函数：结构完整（0~10）。
    """
    tier = _clamp(_to_num(tier_integrity_score, 0.0), 0.0, 100.0)
    gap = _clamp(_to_num(height_gap, 0.0), 0.0, 10.0)
    s_tier = tier / 10.0

    penalty = 0.0
    if gap >= 4:
        penalty = 2.5
    elif gap >= 3:
        penalty = 1.8
    elif gap >= 2:
        penalty = 1.0

    return _clamp(round(s_tier - penalty, 1), 0, 10)


def _score_crowding(overlap_score: float, top3_ratio: float, zb_high_ratio: float, max_lb: int) -> float:
    """
    纯函数：拥挤压力（0~10，返回“可控分”=10-压力）。
    """
    ov = _clamp(_to_num(overlap_score, 0.0), 0.0, 100.0)
    top3 = _clamp(_to_num(top3_ratio, 0.0), 0.0, 100.0)
    zbh = _clamp(_to_num(zb_high_ratio, 0.0), 0.0, 100.0)
    h = _clamp(float(max_lb or 0), 0.0, 10.0)

    p = (
        _clamp((ov - 55) / 35.0, 0.0, 1.0) * 0.40
        + _clamp((top3 - 60) / 25.0, 0.0, 1.0) * 0.25
        + _clamp((zbh - 25) / 25.0, 0.0, 1.0) * 0.20
        + _clamp((h - 5) / 3.0, 0.0, 1.0) * 0.15
    )
    return _clamp(round((1.0 - p) * 10.0, 1), 0, 10)


def _score_money_effect(avg_chg: float, promote_rate: float) -> float:
    # v2 给了 avg_chg 分段；晋级率分段按常识补齐
    if avg_chg >= 5:
        s_chg = 10
    elif avg_chg >= 3:
        s_chg = 8
    elif avg_chg >= 1:
        s_chg = 6
    elif avg_chg >= 0:
        s_chg = 4
    elif avg_chg >= -2:
        s_chg = 2
    else:
        s_chg = 0

    if promote_rate >= 60:
        s_pro = 10
    elif promote_rate >= 45:
        s_pro = 8
    elif promote_rate >= 30:
        s_pro = 6
    elif promote_rate >= 18:
        s_pro = 4
    elif promote_rate >= 8:
        s_pro = 2
    else:
        s_pro = 0

    return round((s_chg * 0.6 + s_pro * 0.4), 1)


def _score_lianban_health(lianban_cnt: int, max_lb: int, height_history: List[int]) -> float:
    """
    连板梯队健康度（简化落地版）：
    - 高度>4 且历史上升：加分
    - 高度<=3 且历史走弱：扣分
    """
    hh = [int(x) for x in height_history if isinstance(x, (int, float))] if height_history else []
    trend = 0
    if len(hh) >= 2:
        trend = hh[-1] - hh[0]

    s = 5.0
    if max_lb >= 6:
        s += 2.0
    elif max_lb >= 5:
        s += 1.2
    elif max_lb <= 2:
        s -= 2.0
    elif max_lb <= 3:
        s -= 0.8

    if lianban_cnt >= 12:
        s += 1.0
    elif lianban_cnt <= 4:
        s -= 0.8

    if trend >= 2:
        s += 1.0
    elif trend <= -2:
        s -= 1.2
    elif trend <= -1:
        s -= 0.6

    return _clamp(round(s, 1), 0, 10)


def _score_negative_feedback(zab_cnt: int, zab_rate: float, nuclear_cnt: int, dt_cnt: int) -> float:
    """
    负反馈强度（越低越好 → 分值越高）
    """
    # 基于 dt / 炸板率 / 核按钮 的扣分模型
    s = 10.0

    if dt_cnt >= 30:
        return 0.0
    if dt_cnt >= 15:
        s -= 4.0
    elif dt_cnt >= 10:
        s -= 3.0
    elif dt_cnt >= 6:
        s -= 1.8
    elif dt_cnt >= 3:
        s -= 0.8

    if zab_rate >= 45:
        s -= 3.0
    elif zab_rate >= 35:
        s -= 2.0
    elif zab_rate >= 28:
        s -= 1.2
    elif zab_rate >= 22:
        s -= 0.6

    if nuclear_cnt >= 6:
        s -= 2.2
    elif nuclear_cnt >= 3:
        s -= 1.2
    elif nuclear_cnt >= 1:
        s -= 0.6

    # 炸板家数作为次要修正（同炸板率下，家数更多说明生态更差）
    if zab_cnt >= 35:
        s -= 0.8
    elif zab_cnt >= 20:
        s -= 0.4

    return _clamp(round(s, 1), 0, 10)


def _score_theme(main_clear: bool, main_strength: str, rotation_freq: int) -> float:
    """
    主线清晰度（0~10）：
    - clear + 强：高
    - 轮动频繁：扣分
    """
    s = 5.0
    if main_clear:
        s += 1.5
    else:
        s -= 1.0

    st = (main_strength or "").strip()
    if st == "强":
        s += 2.0
    elif st == "中":
        s += 0.8
    elif st == "弱":
        s -= 0.8
    elif st == "无":
        s -= 1.5

    if rotation_freq >= 4:
        s -= 2.0
    elif rotation_freq >= 3:
        s -= 1.2
    elif rotation_freq >= 2:
        s -= 0.6

    return _clamp(round(s, 1), 0, 10)


def _score_collapse_chain(d: Dict[str, Any]) -> Tuple[float, List[str]]:
    """
    崩溃前兆链（满分10，逐级扣分；L5直接归零）
    """
    score = 10.0
    hits: List[str] = []

    yest_zt_avg_chg = _to_num(d.get("yest_zt_avg_chg"), 0.0)
    zt_today = _to_int(d.get("zt_count"), 0)
    zt_yest = _to_int(d.get("zt_count_yesterday"), 0)
    dt_cnt = _to_int(d.get("dt_count"), 0)
    max_lb = _to_int(d.get("max_lianban"), _to_int(d.get("max_lb"), 0))
    nuclear = _to_int(d.get("yest_duanban_nuclear"), 0)
    has_tiandiban = bool(d.get("has_tiandiban") or False)

    # L1 追涨者开始亏钱
    if yest_zt_avg_chg < 1.0:
        score -= 2.0
        hits.append(f"L1 追涨亏钱（昨涨今均幅{yest_zt_avg_chg:.2f}%）")

    # L2 活跃度骤降
    if zt_yest > 0:
        drop_ratio = (zt_yest - zt_today) / zt_yest
        if drop_ratio > 0.30:
            score -= 2.0
            hits.append(f"L2 活跃骤降（涨停减{drop_ratio*100:.0f}%）")

    # L3 抄底诱多：需要更细数据，先留接口位（不扣分）

    # L4 强势股补跌（用核按钮近似）
    if max_lb >= 5 and nuclear >= 2:
        score -= 2.0
        hits.append(f"L4 高位补跌（核按钮{nuclear}家）")

    # L5 大面积崩溃
    if dt_cnt >= 30:
        score = 0.0
        hits.append("L5 大面积崩溃（跌停≥30）")

    # 天地板超级警告
    if has_tiandiban:
        score = max(0.0, score - 3.0)
        hits.append("天地板出现")

    return max(0.0, round(score, 1)), hits


def _map_phase(score: float, dim_scores: Dict[str, float]) -> str:
    # v2：用分数区间映射；同时保留“弱修复=看戏”等特征交给策略引擎
    if score >= 7.5:
        return "亢奋期"
    if score >= 6.0:
        return "修复期"
    if score >= 4.0:
        return "分歧期"
    if score >= 2.0:
        return "冰点期"
    return "深冰点"


def _risk_level(d: Dict[str, Any]) -> str:
    dt = _to_int(d.get("dt_count"), 0)
    nuclear = _to_int(d.get("yest_duanban_nuclear"), 0)
    zab_rate = _to_num(d.get("zab_rate"), _to_num(d.get("zb_rate"), 0.0))
    # loss：你现有体系的“扩散”，可用于风险层语义
    loss = _to_num(d.get("loss"), 0.0)

    if dt >= 10 or nuclear >= 6 or zab_rate >= 35 or loss >= 12:
        return "高"
    if dt >= 6 or nuclear >= 3 or zab_rate >= 25 or loss >= 9:
        return "中"
    return "低"


def calc_sentiment_score(input_like: Dict[str, Any]) -> Dict[str, Any]:
    """
    入参尽量贴合 v2 SentimentInput，但允许缺字段（会进入 warnings）。
    """
    d = dict(input_like or {})
    warnings: List[str] = []

    zt_count = _to_int(d.get("zt_count"), 0)
    zt_yest = d.get("zt_count_yesterday")
    zt_count_yesterday = _to_int(zt_yest, 0) if zt_yest is not None else 0
    if zt_yest is None:
        warnings.append("缺少 zt_count_yesterday（用0兜底，涨停热度相对判断会变弱）")

    zab_count = _to_int(d.get("zab_count"), _to_int(d.get("zb_count"), 0))
    try_zt_total = _to_int(d.get("try_zt_total"), zt_count + zab_count)
    zab_rate = _to_num(d.get("zab_rate"), _to_num(d.get("zb_rate"), 0.0))
    if (d.get("zab_rate") is None) and try_zt_total > 0:
        # 若未提供炸板率，尝试用 现有 zb_count / (zt+zb) 估算（注意：口径可能不同）
        est = (zab_count / try_zt_total) * 100.0
        # 若已有 zb_rate（可能来自其它口径），则不覆盖
        if d.get("zb_rate") is None:
            zab_rate = est

    yest_zt_avg_chg = _to_num(d.get("yest_zt_avg_chg"), 0.0)
    promote_rate = _to_num(d.get("yest_lianban_promote_rate"), _to_num(d.get("jj_rate"), 0.0))
    nuclear = _to_int(d.get("yest_duanban_nuclear"), 0)
    if d.get("yest_duanban_nuclear") is None:
        warnings.append("缺少 yest_duanban_nuclear（核按钮数据），崩溃链/L4 与负反馈维度会偏乐观")

    dt_count = _to_int(d.get("dt_count"), 0)

    height_history = d.get("height_history") or []
    if not isinstance(height_history, list):
        height_history = []

    lianban_cnt = _to_int(d.get("lianban_count"), 0)
    max_lb = _to_int(d.get("max_lianban"), _to_int(d.get("max_lb"), 0))
    if lianban_cnt == 0 and isinstance(d.get("lianban_count"), type(None)):
        # 允许从 lb_2（>=2板数量）推断一个近似值
        lianban_cnt = _to_int(d.get("lb_2"), 0)

    main_clear = bool(d.get("main_theme_clear") or False)
    main_strength = str(d.get("main_theme_strength") or ("中" if main_clear else "弱"))
    rotation_freq = _to_int(d.get("theme_rotation_freq"), 0)

    # 动态口径：近 N 日涨停（用于热度相对化）
    hist_zt = d.get("hist_zt") or []
    if not isinstance(hist_zt, list):
        hist_zt = []

    # 承接/结构/拥挤（来自 features.mood_inputs + themePanels/styleRadar proxy）
    fb_rate = _to_num(d.get("fb_rate"), _to_num(d.get("fb", 0.0), 0.0))
    jj_rate = _to_num(d.get("jj_rate"), promote_rate)
    broken_lb_rate = _to_num(d.get("broken_lb_rate"), _to_num(d.get("broken_lb_rate_adj"), 0.0))
    rate_2to3 = _to_num(d.get("rate_2to3"), 0.0)
    rate_3to4 = _to_num(d.get("rate_3to4"), 0.0)
    tier_integrity_score = _to_num(d.get("tier_integrity_score"), 0.0)
    height_gap = _to_num(d.get("height_gap"), 0.0)
    overlap_score = _to_num(d.get("overlap_score"), 0.0)
    top3_ratio = _to_num(d.get("top3_theme_ratio"), 0.0)
    zb_high_ratio = _to_num(d.get("zb_high_ratio"), 0.0)

    # v2 新增：崩溃前兆链（扣分项）
    collapse_score, collapse_hits = _score_collapse_chain(
        {
            "yest_zt_avg_chg": yest_zt_avg_chg,
            "zt_count": zt_count,
            "zt_count_yesterday": zt_count_yesterday,
            "dt_count": dt_count,
            "max_lianban": max_lb,
            "yest_duanban_nuclear": nuclear,
            "has_tiandiban": bool(d.get("has_tiandiban") or False),
        }
    )

    dim_scores = {
        # 动态热度：使用历史分位（更抗周期漂移）
        "zt_heat": _score_zt_heat_dyn(zt_count, hist_zt),
        "money_effect": _score_money_effect(yest_zt_avg_chg, promote_rate),
        "carry_quality": _score_carry_quality(
            fb_rate=fb_rate,
            jj_rate=jj_rate,
            broken_lb_rate=broken_lb_rate,
            rate_2to3=rate_2to3,
            rate_3to4=rate_3to4,
        ),
        "lianban_health": _score_lianban_health(
            lianban_cnt,
            max_lb,
            [int(x) for x in height_history if isinstance(x, (int, float))],
        ),
        "negative": _score_negative_feedback(zab_count, zab_rate, nuclear, dt_count),
        "theme_clarity": _score_theme(main_clear, main_strength, rotation_freq),
        "structure": _score_structure(tier_integrity_score, height_gap),
        "crowding": _score_crowding(overlap_score, top3_ratio, zb_high_ratio, max_lb),
        "collapse_chain": collapse_score,
    }

    weights = {
        # 更贴近实战：把“承接/结构/拥挤”显式纳入总分（更稳定、更可解释）
        "zt_heat": 0.15,
        "money_effect": 0.18,
        "carry_quality": 0.15,
        "lianban_health": 0.15,
        "negative": 0.15,
        "theme_clarity": 0.08,
        "structure": 0.06,
        "crowding": 0.04,
        "collapse_chain": 0.04,
    }
    total = sum(dim_scores[k] * weights[k] for k in weights.keys())
    total = round(_clamp(total, 0.0, 10.0), 1)

    phase = _map_phase(total, dim_scores)
    risk_level = _risk_level(
        {
            "dt_count": dt_count,
            "yest_duanban_nuclear": nuclear,
            "zab_rate": zab_rate,
            "loss": _to_num(d.get("loss"), 0.0),
        }
    )

    if collapse_hits:
        warnings.append("崩溃前兆链触发：" + "；".join(collapse_hits))

    return {
        "score": total,
        "phase": phase,
        "risk_level": risk_level,
        "dim_scores": dim_scores,
        "warnings": warnings,
        "debug": {
            "zt_count": zt_count,
            "zt_count_yesterday": zt_count_yesterday,
            "try_zt_total": try_zt_total,
            "zab_count": zab_count,
            "zab_rate": round(zab_rate, 2),
            "promote_rate": round(promote_rate, 2),
            "max_lianban": max_lb,
            "lianban_count": lianban_cnt,
        },
    }
