#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
sentiment_v2 模块：按 v2 规格书输出 marketData.v2.summary

并做兼容：
- 覆盖 marketData.sentiment / dual_dimension 的核心字段（让 UI 先跑起来）
- 覆盖 marketData.moodStage.title 为 v2.phase（用于情绪温度标题）
"""

from __future__ import annotations

from typing import Any, Dict, List

from daily_review.metrics.sentiment_v2 import calc_sentiment_score
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _derive_inputs(ctx: Context) -> Dict[str, Any]:
    md = ctx.market_data or {}
    mi = (md.get("features") or {}).get("mood_inputs") or {}
    mi = mi if isinstance(mi, dict) else {}

    # 基础字段（来自现有 mood_inputs）
    zt_count = mi.get("zt_count")
    zb_count = mi.get("zb_count")
    dt_count = mi.get("dt_count")
    max_lb = mi.get("max_lb")
    yest_zt_avg_chg = mi.get("yest_zt_avg_chg")

    # 1) 昨日涨停数：从 hist_zt 倒数第二位推断
    hist_zt = mi.get("hist_zt") or mi.get("hist_zt_count") or []
    zt_yest = None
    if isinstance(hist_zt, list) and len(hist_zt) >= 2:
        zt_yest = hist_zt[-2]

    # 2) 晋级率：用 jj_rate 作为 yesterday lianban promote rate 的近似口径
    jj_rate = mi.get("jj_rate")

    # 3) 连板家数：用 raw.pools.ztgc 里 lbc>=2 统计（比 lb_2 更稳）
    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
    ztgc = pools.get("ztgc") or []
    lianban_count = 0
    if isinstance(ztgc, list):
        lianban_count = sum(1 for x in ztgc if isinstance(x, dict) and int(x.get("lbc", 1) or 1) >= 2)

    # 4) 高度历史：用 hist_max_lb（近5日）
    height_history = mi.get("hist_max_lb") or []
    height_history = height_history if isinstance(height_history, list) else []

    # 5) 主线清晰度/强弱/轮动：先用现有 themePanels/styleRadar 的 proxy
    # 规则（可改）：top3ThemeRatio 过高或 overlap 过高 → 不清晰/拥挤
    style = md.get("styleRadar") or {}
    overlap = (md.get("themePanels") or {}).get("overlap") or {}
    def _to_float(v: Any, default: float = 0.0) -> float:
        try:
            if v is None or v == "":
                return default
            if isinstance(v, str) and v.endswith("%"):
                v = v[:-1]
            return float(v)
        except Exception:
            return default

    top3 = _to_float(style.get("top3ThemeRatio") or mi.get("top3_theme_ratio") or 0)
    ov = _to_float(overlap.get("score") or mi.get("overlap_score") or 0)
    main_clear = bool(top3 >= 55 and top3 <= 85 and ov < 75)
    main_strength = "强" if (main_clear and top3 >= 65 and ov < 68) else ("中" if main_clear else "弱")
    theme_rotation_freq = int((md.get("themeTrend") or {}).get("rotationFreq") or 0)

    return {
        "zt_count": zt_count,
        "zt_count_yesterday": zt_yest,
        "lianban_count": lianban_count,
        "max_lianban": max_lb,
        "zab_count": zb_count,  # 现有口径 zb_count≈炸板家数
        "try_zt_total": (int(zt_count or 0) + int(zb_count or 0)),
        "zab_rate": mi.get("zb_rate"),  # 直接沿用现有
        "yest_zt_avg_chg": yest_zt_avg_chg,
        "yest_lianban_promote_rate": jj_rate,
        "yest_duanban_nuclear": None,  # 暂缺：后续接入昨日断板/核按钮数据源
        "dt_count": dt_count,
        "height_history": height_history,
        "main_theme_clear": main_clear,
        "main_theme_strength": main_strength,
        "theme_rotation_freq": theme_rotation_freq,
        "has_tiandiban": False,
        "loss": mi.get("loss"),
    }


def _compute(ctx: Context) -> Dict[str, Any]:
    md = ctx.market_data or {}
    inputs = _derive_inputs(ctx)
    s = calc_sentiment_score(inputs)

    # v2 收口输出
    v2 = {"sentiment": s}

    # 兼容旧字段（逐步替换）
    compat_sentiment = {
        "score": s.get("score"),
        "phase": s.get("phase"),
        "risk_level": s.get("risk_level"),
        "sub_scores": s.get("dim_scores"),
        "warnings": s.get("warnings"),
    }

    # moodStage：让标题与 phase 对齐（你现在 UI 依赖它）
    mood_stage = {**(md.get("moodStage") or {}), "title": s.get("phase") or "-", "detail": "；".join(s.get("warnings") or [])}
    # mood：heat/risk 保留 0~100 语义
    score10 = float(s.get("score") or 0)
    heat = round(score10 * 10.0, 1)
    risk = {"低": 40, "中": 60, "高": 80}.get(str(s.get("risk_level") or "中"), 60)
    mood = {**(md.get("mood") or {}), "heat": heat, "risk": risk}

    return {
        "marketData.v2": v2,
        "marketData.sentiment": compat_sentiment,
        "marketData.moodStage": mood_stage,
        "marketData.mood": mood,
    }


SENTIMENT_V2_MODULE = Module(
    name="sentiment_v2",
    requires=[
        "features.mood_inputs",
        "raw.pools.ztgc",
        "marketData.styleRadar",
        "marketData.themePanels",
        "marketData.themeTrend",
    ],
    provides=["marketData.v2", "marketData.sentiment", "marketData.moodStage", "marketData.mood"],
    compute=_compute,
)
