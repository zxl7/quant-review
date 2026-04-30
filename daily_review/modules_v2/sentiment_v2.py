#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
sentiment_v2 模块：按 v2 规格书输出 marketData.v2.summary

并做兼容：
- 覆盖 marketData.sentiment / dual_dimension 的核心字段（让 UI 先跑起来）
- 覆盖 marketData.moodStage.title 为 v2.phase（用于情绪温度标题）
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.sentiment_v2 import calc_sentiment_score
from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module
from daily_review.data.biying import normalize_stock_code


def _clamp(x: float, lo: float, hi: float) -> float:
    """
    纯函数：数值裁剪到区间 [lo, hi]。
    """
    return max(lo, min(hi, x))


def _scale01(x: float, x0: float, x1: float) -> float:
    """
    纯函数：把 x 映射到 0~1（线性），并做裁剪。

    - x<=x0 → 0
    - x>=x1 → 1
    """
    if x1 == x0:
        return 0.0
    return _clamp((x - x0) / (x1 - x0), 0.0, 1.0)


def _risk_level_from_score(risk: float) -> str:
    """
    纯函数：把风险分（0~100，越高越危险）映射为“低/中/高”。
    """
    if risk >= 70:
        return "高"
    if risk >= 45:
        return "中"
    return "低"


def _calc_risk100(inputs: Dict[str, Any]) -> int:
    """
    纯函数：计算风险分（0~100，越高越危险）。

    设计目标：
    - 不依赖单一标签（低/中/高），而是把“高度/拥挤/核按钮/亏钱扩散/炸板”量化合成。
    - 与 UI 颜色映射对齐：风险从 黄→绿（高风险偏黄，低风险偏绿）。
    """
    # 1) 高度风险：高度越高，兑现/分歧概率越高
    max_lb = float(inputs.get("max_lianban") or 0)
    height_risk = _scale01(max_lb, 3.0, 8.0) * 100.0

    # 2) 拥挤度（重叠度）：越高越危险（越接近退潮/分歧）
    overlap = float(inputs.get("overlap_score") or 0)
    overlap_risk = _scale01(overlap, 55.0, 90.0) * 100.0

    # 3) 核按钮：强势股补跌/断板负反馈
    nuclear = float(inputs.get("yest_duanban_nuclear") or 0)
    nuclear_risk = _scale01(nuclear, 0.0, 6.0) * 100.0

    # 4) 亏钱扩散：跌停 + 大面（loss 口径已在 inputs 里聚合）
    loss = float(inputs.get("loss") or 0)
    loss_risk = _scale01(loss, 2.0, 18.0) * 100.0

    # 5) 炸板率：高分歧 → 生态变差
    zab_rate = float(inputs.get("zab_rate") or 0)
    zab_risk = _scale01(zab_rate, 18.0, 45.0) * 100.0

    # 加权合成（总权重=1）
    risk = (
        0.28 * overlap_risk
        + 0.26 * height_risk
        + 0.20 * nuclear_risk
        + 0.16 * loss_risk
        + 0.10 * zab_risk
    )
    return int(round(_clamp(risk, 0.0, 100.0)))


def _derive_inputs(ctx: Context) -> Dict[str, Any]:
    md = ctx.market_data or {}
    mi = (md.get("features") or {}).get("mood_inputs") or {}
    mi = mi if isinstance(mi, dict) else {}

    # 基础字段（来自 mood_inputs）
    zt_count = mi.get("zt_count")
    zb_count = mi.get("zb_count")
    dt_count = mi.get("dt_count")
    max_lb = mi.get("max_lb")
    yest_zt_avg_chg = mi.get("yest_zt_avg_chg")
    fb_rate = mi.get("fb_rate")
    jj_rate = mi.get("jj_rate_adj") if mi.get("jj_rate_adj") is not None else mi.get("jj_rate")
    broken_lb_rate = mi.get("broken_lb_rate_adj") if mi.get("broken_lb_rate_adj") is not None else mi.get("broken_lb_rate")

    # 1) 昨日涨停数：从 hist_zt 倒数第二位推断
    hist_zt = mi.get("hist_zt") or mi.get("hist_zt_count") or []
    zt_yest = None
    if isinstance(hist_zt, list) and len(hist_zt) >= 2:
        zt_yest = hist_zt[-2]
    if zt_yest is None:
        pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
        yest_ztgc = pools.get("yest_ztgc") or []
        zt_yest = len(yest_ztgc) if isinstance(yest_ztgc, list) else None

    # 2) 晋级率：用 jj_rate 作为 yesterday lianban promote rate 的近似口径

    # 3) 连板家数：用 raw.pools.ztgc 里 lbc>=2 统计（比 lb_2 更稳）
    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
    ztgc = pools.get("ztgc") or []
    lianban_count = 0
    if isinstance(ztgc, list):
        lianban_count = sum(1 for x in ztgc if isinstance(x, dict) and int(x.get("lbc", 1) or 1) >= 2)

    # 4) 高度历史：用 hist_max_lb（近5日）
    height_history = mi.get("hist_max_lb") or []
    height_history = height_history if isinstance(height_history, list) else []

    # 4.5) 其它结构/生态输入（用于更精细的情绪分项）
    tier_integrity_score = mi.get("tier_integrity_score")
    height_gap = mi.get("height_gap")
    rate_2to3 = mi.get("rate_2to3")
    rate_3to4 = mi.get("rate_3to4")
    bf_count = mi.get("bf_count")
    risk_spike = mi.get("risk_spike")
    qs_avg_zf = mi.get("qs_avg_zf")
    zt_early_ratio = mi.get("zt_early_ratio")
    avg_seal_fund_yi = mi.get("avg_seal_fund_yi")
    avg_zt_zbc = mi.get("avg_zt_zbc")
    zt_zbc_ge3_ratio = mi.get("zt_zbc_ge3_ratio")
    hs_median = mi.get("hs_median")
    zb_high_ratio = mi.get("zb_high_ratio")

    # 5) 主线清晰度/强弱/轮动：先用现有 themePanels/styleRadar 的 proxy
    # 规则（可改）：top3ThemeRatio 过高或 overlap 过高 → 不清晰/拥挤
    style = md.get("styleRadar") or {}
    overlap = (md.get("themePanels") or {}).get("overlap") or {}
    from daily_review.utils.num import to_float as _to_float

    top3 = _to_float(style.get("top3ThemeRatio") or mi.get("top3_theme_ratio") or 0)
    ov = _to_float(overlap.get("score") or mi.get("overlap_score") or 0)
    main_clear = bool(top3 >= 55 and top3 <= 85 and ov < 75)
    main_strength = "强" if (main_clear and top3 >= 65 and ov < 68) else ("中" if main_clear else "弱")
    theme_rotation_freq = int((md.get("themeTrend") or {}).get("rotationFreq") or 0)

    # 6) 昨日断板核按钮（yest_zbgc → 今日低开核按钮）
    # 口径：昨日炸板池个股，若今日“低开<=-5%”记为核按钮；缺口数据不足则 fallback 到今日涨跌幅<=-5%。
    nuclear = 0
    try:
        quotes = (ctx.raw.get("quotes") or {}) if isinstance(ctx.raw, dict) else {}
        quotes_items = quotes.get("items") if isinstance(quotes, dict) else {}
        quotes_items = quotes_items if isinstance(quotes_items, dict) else {}
        yest_zbgc = pools.get("yest_zbgc") or []
        from daily_review.utils.num import to_float as _to_float

        for s in (yest_zbgc if isinstance(yest_zbgc, list) else []):
            if not isinstance(s, dict):
                continue
            c6 = normalize_stock_code(s.get("dm") or s.get("code") or "")
            if not c6:
                continue
            q = quotes_items.get(c6)
            if not isinstance(q, dict):
                continue
            yc = _to_float(q.get("yc") or 0)
            o = _to_float(q.get("o") or 0)
            if yc > 0 and o > 0:
                gap = (o - yc) / yc * 100.0
                if gap <= -5.0:
                    nuclear += 1
            else:
                zf = _to_float(q.get("zf") or 0)
                if zf <= -5.0:
                    nuclear += 1
    except Exception:
        nuclear = 0

    return {
        "zt_count": zt_count,
        "zt_count_yesterday": zt_yest,
        "hist_zt": hist_zt if isinstance(hist_zt, list) else [],
        "lianban_count": lianban_count,
        "max_lianban": max_lb,
        "zab_count": zb_count,  # 现有口径 zb_count≈炸板家数
        "try_zt_total": (int(zt_count or 0) + int(zb_count or 0)),
        "zab_rate": mi.get("zb_rate"),  # 直接沿用现有
        "fb_rate": fb_rate,
        "jj_rate": jj_rate,
        "broken_lb_rate": broken_lb_rate,
        "rate_2to3": rate_2to3,
        "rate_3to4": rate_3to4,
        "tier_integrity_score": tier_integrity_score,
        "height_gap": height_gap,
        "bf_count": bf_count,
        "risk_spike": risk_spike,
        "qs_avg_zf": qs_avg_zf,
        "zt_early_ratio": zt_early_ratio,
        "avg_seal_fund_yi": avg_seal_fund_yi,
        "avg_zt_zbc": avg_zt_zbc,
        "zt_zbc_ge3_ratio": zt_zbc_ge3_ratio,
        "hs_median": hs_median,
        "zb_high_ratio": zb_high_ratio,
        "yest_zt_avg_chg": yest_zt_avg_chg,
        "yest_lianban_promote_rate": jj_rate,
        "yest_duanban_nuclear": nuclear,
        "dt_count": dt_count,
        "height_history": height_history,
        "main_theme_clear": main_clear,
        "main_theme_strength": main_strength,
        "theme_rotation_freq": theme_rotation_freq,
        # 风险量化输入（用于 risk100）
        "top3_theme_ratio": top3,
        "overlap_score": ov,
        "has_tiandiban": False,
        "loss": mi.get("loss") if mi.get("loss") is not None else (int(mi.get("bf_count") or 0) + int(mi.get("dt_count") or 0)),
    }


def _compute(ctx: Context) -> Dict[str, Any]:
    md = ctx.market_data or {}
    inputs = _derive_inputs(ctx)
    s = calc_sentiment_score(inputs)

    # v2 收口输出
    v2 = {"sentiment": s}

    # moodStage：让标题与 phase 对齐（你现在 UI 依赖它）
    mood_stage = {**(md.get("moodStage") or {}), "title": s.get("phase") or "-", "detail": "；".join(s.get("warnings") or [])}

    # ─────────────────────────────────────────────────────────────
    # 情绪/风险合并为 100 分制（UI 口径）
    # - heat：情绪热度（0~100，越高越强）
    # - risk：风险分（0~100，越高越危险）
    # - score：综合分（0~100），把“强度”和“风险”合并成一个总分
    # ─────────────────────────────────────────────────────────────
    score10 = float(s.get("score") or 0)  # 保留 0~10 给算法/调试
    heat100 = int(round(_clamp(score10 * 10.0, 0.0, 100.0)))
    risk100 = _calc_risk100(inputs)
    # 总分：强度占主导，风险做扣分项（高风险会明显拉低总分）
    total100 = int(round(_clamp(0.70 * heat100 + 0.30 * (100 - risk100), 0.0, 100.0)))
    risk_level = _risk_level_from_score(risk100)

    # 兼容旧字段（逐步替换）
    compat_sentiment = {
        # UI 展示口径：0~100
        "score": total100,
        "score10": round(score10, 2),
        "heat": heat100,
        "risk": risk100,
        "phase": s.get("phase"),
        "risk_level": risk_level,
        "sub_scores": s.get("dim_scores"),
        "warnings": s.get("warnings"),
    }

    mood = {**(md.get("mood") or {}), "heat": heat100, "risk": risk100, "score": total100}

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
