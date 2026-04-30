#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
按《a-stock-sentiment-algo-spec.md》落地的“短线情绪”核心输出（最小可用版）。

说明：
- 你现有系统已经有丰富的中间特征（features.mood_inputs / heightTrend / styleRadar 等）
- 这里先按“规范书的结构”产出 sentiment / dual_dimension / height_analysis，并同时做向后兼容：
  - marketData.mood.heat / marketData.mood.risk 仍保留，便于现有前端组件继续工作
  - marketData.moodStage.title 使用 phase（分歧期/修复期…）
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


def _slope(xs: List[float]) -> float:
    """简单斜率：末值-首值（用于判断高度趋势方向）。"""
    if not xs or len(xs) < 2:
        return 0.0
    return float(xs[-1]) - float(xs[0])


# === 六维评分（0~10）===
def score_yest_feedback(yest_zt_avg_chg: float) -> float:
    # 昨日涨停今日平均表现（%）
    if yest_zt_avg_chg >= 2:
        return 9.0
    if yest_zt_avg_chg >= 0:
        return 7.0
    if yest_zt_avg_chg >= -2:
        return 4.0
    return 1.5


def score_height_trend(height_main: List[int]) -> float:
    s = _slope([float(x) for x in height_main if isinstance(x, (int, float))])
    if s >= 2:
        return 8.5
    if s >= 1:
        return 7.0
    if s <= -2:
        return 2.0
    if s <= -1:
        return 3.5
    return 5.5


def score_zab_rate(zb_rate: float) -> float:
    # 炸板率（%）越低越好
    if zb_rate <= 18:
        return 8.5
    if zb_rate <= 25:
        return 7.0
    if zb_rate <= 32:
        return 5.0
    if zb_rate <= 40:
        return 3.0
    return 1.5


def score_nuclear(*, nuclear_cnt: int, broken_lb_cnt: int) -> float:
    # 核按钮：用“昨日断板核按钮比例”近似（数据源不足时的可落地版本）
    denom = max(1, broken_lb_cnt)
    r = nuclear_cnt / denom
    if r <= 0.10:
        return 8.0
    if r <= 0.20:
        return 6.0
    if r <= 0.35:
        return 4.0
    if r <= 0.50:
        return 2.5
    return 1.5


def score_main_theme(*, top3_ratio: float, overlap_score: float) -> float:
    # 主线清晰度：top3 占比越低越“分散”，但过低又代表没有主线；结合重叠度（拥挤）
    # 这里给一个可用的启发式：
    # - 拥挤高（overlap>=75）直接扣分
    if overlap_score >= 75:
        return 3.0
    if top3_ratio >= 80:
        return 4.0
    if 65 <= top3_ratio < 80:
        return 6.0
    if 50 <= top3_ratio < 65:
        return 7.5
    return 6.0


def score_dt_count(dt_count: int) -> float:
    if dt_count <= 2:
        return 9.0
    if dt_count <= 5:
        return 7.0
    if dt_count <= 9:
        return 5.0
    if dt_count <= 14:
        return 3.0
    return 1.5


def infer_phase(score: float) -> str:
    if score >= 7.5:
        return "亢奋期"
    if score >= 6.0:
        return "修复期"
    if score >= 4.0:
        return "分歧期"
    if score >= 2.0:
        return "冰点期"
    return "深冰点"


def infer_risk_level(*, dt_count: int, nuclear_cnt: int, zb_rate: float, loss: float) -> str:
    # 仅返回 低/中/高（与规范一致）
    if dt_count >= 10 or nuclear_cnt >= 6 or zb_rate >= 35 or loss >= 12:
        return "高"
    if dt_count >= 6 or nuclear_cnt >= 3 or zb_rate >= 25 or loss >= 9:
        return "中"
    return "低"


def build_sentiment(market_data: Dict[str, Any]) -> Dict[str, Any]:
    mi = (market_data.get("features") or {}).get("mood_inputs") or {}
    height = market_data.get("heightTrend") or {}
    style = market_data.get("styleRadar") or {}
    overlap = (market_data.get("themePanels") or {}).get("overlap") or {}

    yest_zt_avg_chg = _to_num(mi.get("yest_zt_avg_chg"), 0.0)
    zb_rate = _to_num(mi.get("zb_rate"), 0.0)
    dt_count = _to_int(mi.get("dt_count"), 0)
    loss = _to_num(mi.get("loss"), 0.0)
    broken_lb_cnt = _to_int(mi.get("broken_lb_count"), 0)
    nuclear_cnt = _to_int(mi.get("yest_duanban_nuclear"), 0)

    top3_ratio = _to_num(style.get("top3ThemeRatio"), _to_num(mi.get("top3_theme_ratio"), 0.0))
    overlap_score = _to_num(overlap.get("score"), _to_num(mi.get("overlap_score"), 0.0))

    h_main = height.get("main") or []
    if not isinstance(h_main, list):
        h_main = []

    sub = {
        "yest_feedback": score_yest_feedback(yest_zt_avg_chg),
        "height_trend": score_height_trend([_to_int(x, 0) for x in h_main]),
        "zab_rate": score_zab_rate(zb_rate),
        "nuclear": score_nuclear(nuclear_cnt=nuclear_cnt, broken_lb_cnt=broken_lb_cnt),
        "main_theme": score_main_theme(top3_ratio=top3_ratio, overlap_score=overlap_score),
        "dt_count": score_dt_count(dt_count),
    }

    # 权重（与规范书精神一致：昨日反馈权重大）
    w = {
        "yest_feedback": 0.25,
        "height_trend": 0.15,
        "zab_rate": 0.15,
        "nuclear": 0.15,
        "main_theme": 0.15,
        "dt_count": 0.15,
    }
    total = sum(sub[k] * w[k] for k in w.keys())
    total = round(_clamp(total, 0.0, 10.0), 1)

    phase = infer_phase(total)
    risk_level = infer_risk_level(dt_count=dt_count, nuclear_cnt=nuclear_cnt, zb_rate=zb_rate, loss=loss)
    sub_round = {k: round(float(v), 1) for k, v in sub.items()}

    return {
        "score": total,
        "phase": phase,
        "risk_level": risk_level,
        "sub_scores": sub_round,
    }


def build_dual_dimension(market_data: Dict[str, Any], sentiment: Dict[str, Any]) -> Dict[str, Any]:
    mi = (market_data.get("features") or {}).get("mood_inputs") or {}
    yest_zt_avg_chg = _to_num(mi.get("yest_zt_avg_chg"), 0.0)
    jj_rate = _to_num(mi.get("jj_rate"), 0.0)
    fb_rate = _to_num(mi.get("fb_rate"), 0.0)
    zb_rate = _to_num(mi.get("zb_rate"), 0.0)
    dt_count = _to_int(mi.get("dt_count"), 0)
    bf_count = _to_int(mi.get("bf_count"), 0)
    loss = _to_num(mi.get("loss"), 0.0)
    zbc_ge3 = _to_num(mi.get("zbc_ge3_ratio"), 0.0)

    # 赚钱效应（1~5 星）：用“昨日反馈 + 晋级承接 + 封板一致性”融合（语义化）
    star_raw = (
        score_yest_feedback(yest_zt_avg_chg) * 0.45
        + _clamp(jj_rate / 6.0, 0, 10) * 0.35
        + _clamp((fb_rate - 50) / 5.0, 0, 10) * 0.20
    )
    stars = int(round(_clamp(star_raw / 2.0, 1.0, 5.0)))  # 0~10 → 1~5
    earning_effect = f"{'⭐'*stars}{'☆'*(5-stars)} ({stars}/5)"

    # 亏钱效应：用 dt/bf/loss 给语义等级
    if dt_count >= 10 or bf_count >= 12 or loss >= 12:
        loss_effect = "🔴偏大"
    elif dt_count >= 6 or bf_count >= 8 or loss >= 9:
        loss_effect = "🟡中等"
    else:
        loss_effect = "🟢可控"

    divergence_warning = bool(zb_rate >= 30 or zbc_ge3 >= 18)

    return {
        "earning_effect": earning_effect,
        "loss_effect": loss_effect,
        "divergence_warning": divergence_warning,
    }


def build_height_analysis(market_data: Dict[str, Any]) -> Dict[str, Any]:
    mi = (market_data.get("features") or {}).get("mood_inputs") or {}
    max_lb = _to_int(mi.get("max_lb"), 0)

    # 趋势：用 heightTrend.main 最近 7 点斜率
    height = market_data.get("heightTrend") or {}
    main = height.get("main") or []
    main = [_to_int(x, 0) for x in main] if isinstance(main, list) else []
    s = _slope([float(x) for x in main])
    if s >= 2:
        trend = "📈 明显上升"
    elif s >= 1:
        trend = "📈 温和上升"
    elif s <= -2:
        trend = "📉 明显下降"
    elif s <= -1:
        trend = "📉 温和下降"
    else:
        trend = "➡️ 震荡"

    # 顶部标的：从 ztgc 里找最高连板
    ztgc = market_data.get("ztgc") or []
    top = {}
    if isinstance(ztgc, list) and ztgc:
        top = max((x for x in ztgc if isinstance(x, dict)), key=lambda x: _to_int(x.get("lbc", 1), 1), default={})
    top_stock = {
        "name": str(top.get("mc") or top.get("name") or ""),
        "board": _to_int(top.get("lbc", 1), 1),
        "state": str(top.get("zt_style") or top.get("state") or ""),
    }

    # 生命周期（按规范 phase 输出）
    phase_name = "divergence" if max_lb >= 5 else ("start" if max_lb >= 3 else "ice")
    phase_cn = "分歧期" if phase_name == "divergence" else ("修复期" if phase_name == "start" else "冰点期")

    return {
        "max_board": max_lb,
        "trend": trend,
        "top_stock": top_stock,
        "state_label": "",
        "life_cycle": {"phase": phase_name, "phase_name": phase_cn},
    }


def apply_compat_to_mood(sentiment: Dict[str, Any], dual: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    给前端兼容字段：
    - mood.heat/risk 仍为 0~100
    - moodStage.title/type 用 phase/risk_level 映射
    """
    score10 = float(sentiment.get("score") or 0)
    phase = str(sentiment.get("phase") or "-")
    risk_level = str(sentiment.get("risk_level") or "中")

    heat = round(_clamp(score10 * 10.0, 0, 100), 1)
    risk = {"低": 40, "中": 60, "高": 80}.get(risk_level, 60)

    # phase -> type（用于 UI 颜色）
    if phase in ("深冰点", "冰点期"):
        t = "fire"
    elif phase in ("分歧期",):
        t = "warn"
    else:
        t = "good"

    mood = {
        "heat": heat,
        "risk": risk,
        "score10": score10,
        "phase": phase,
        "earning_effect": dual.get("earning_effect"),
        "loss_effect": dual.get("loss_effect"),
    }
    mood_stage = {"title": phase, "type": t, "detail": f"风险：{risk_level}｜{dual.get('earning_effect','')}/{dual.get('loss_effect','')}"}
    return mood, mood_stage

