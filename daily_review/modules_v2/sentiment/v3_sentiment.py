#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3_sentiment 模块：基于v3.0算法规格书的六维加权情绪评分

六维: 涨停热度(20%) / 赚钱效应(25%) / 连板健康度(20%) / 负反馈(15%) / 主线清晰度(10%) / 崩溃前兆链(10%)
输出: 综合分(0-10) + 周期阶段 + 各维分项 + 置信度 + 警告列表
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module
from daily_review.data.biying import normalize_stock_code


def _derive_inputs(ctx: Context) -> Dict[str, Any]:
    """从Context中提取情绪评分所需的所有输入数据，构造 SentimentInput"""
    md = ctx.market_data or {}

    # 1) 从 features.mood_inputs 获取基础字段
    mi = (md.get("features") or {}).get("mood_inputs") or {}
    mi = mi if isinstance(mi, dict) else {}

    zt_count = mi.get("zt_count")
    zb_count = mi.get("zb_count")
    dt_count = mi.get("dt_count")
    max_lb = mi.get("max_lb")
    yest_zt_avg_chg = mi.get("yest_zt_avg_chg")

    # 昨日涨停数：从 hist_zt 倒数第二位推断
    hist_zt = mi.get("hist_zt") or mi.get("hist_zt_count") or []
    zt_yest = None
    if isinstance(hist_zt, list) and len(hist_zt) >= 2:
        zt_yest = hist_zt[-2]
    if zt_yest is None:
        pools0 = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
        yest_ztgc0 = pools0.get("yest_ztgc") or []
        zt_yest = len(yest_ztgc0) if isinstance(yest_ztgc0, list) else None

    # 晋级率：用 jj_rate 作为 yesterday lianban promote rate 的近似口径
    jj_rate = mi.get("jj_rate")

    # 连板家数：用 raw.pools.ztgc 里 lbc>=2 统计
    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
    ztgc = pools.get("ztgc") or []
    lianban_count = 0
    if isinstance(ztgc, list):
        lianban_count = sum(
            1 for x in ztgc if isinstance(x, dict) and int(x.get("lbc", 1) or 1) >= 2
        )

    # 高度历史：用 hist_max_lb（近5日）
    height_history = mi.get("hist_max_lb") or []
    height_history = height_history if isinstance(height_history, list) else []

    # 主线清晰度/强弱/轮动：从 themePanels/styleRadar 推断
    style = md.get("styleRadar") or {}
    overlap = (md.get("themePanels") or {}).get("overlap") or {}
    from daily_review.utils.num import to_float as _to_float

    top3 = _to_float(style.get("top3ThemeRatio") or mi.get("top3_theme_ratio") or 0)
    ov = _to_float(overlap.get("score") or mi.get("overlap_score") or 0)
    main_clear = bool(top3 >= 55 and top3 <= 85 and ov < 75)
    main_strength = (
        "强" if (main_clear and top3 >= 65 and ov < 68)
        else ("中" if main_clear else "弱")
    )
    theme_rotation_freq = int((md.get("themeTrend") or {}).get("rotationFreq") or 0)

    # 昨日断板核按钮（yest_zbgc → 今日低开核按钮）
    nuclear = 0
    try:
        pools_y = pools.get("yest_zbgc") or []
        quotes = (ctx.raw.get("quotes") or {}) if isinstance(ctx.raw, dict) else {}
        quotes_items = quotes.get("items") if isinstance(quotes, dict) else {}
        quotes_items = quotes_items if isinstance(quotes_items, dict) else {}
        from daily_review.utils.num import to_float as _to_float

        for s in (pools_y if isinstance(pools_y, list) else []):
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
        "lianban_count": lianban_count,
        "max_lianban": max_lb,
        "zab_count": zb_count,
        "try_zt_total": (int(zt_count or 0) + int(zb_count or 0)),
        "zab_rate": mi.get("zb_rate"),
        "yest_zt_avg_chg": yest_zt_avg_chg,
        "yest_lianban_promote_rate": jj_rate,
        "yest_duanban_nuclear": nuclear,
        "dt_count": dt_count,
        "height_history": height_history,
        "main_theme_clear": main_clear,
        "main_theme_strength": main_strength,
        "theme_rotation_freq": theme_rotation_freq,
        "has_tiandiban": False,
        "has_ditianban": False,
        "has_waipan_shock": False,
        "is_weekend_ahead": False,
        "index_drop_3d": None,
        "has_trap_pattern": False,
        "loss": mi.get("loss") if mi.get("loss") is not None else (int(mi.get("bf_count") or 0) + int(mi.get("dt_count") or 0)),
    }


def _compute(ctx: Context) -> Dict[str, Any]:
    """v3 sentiment 计算主函数"""
    try:
        from daily_review.metrics.v3_validator import validate_and_clean
        from daily_review.metrics.v3_sentiment import calc_sentiment_score

        raw_inputs = _derive_inputs(ctx)
        sentiment_input, validation = validate_and_clean(raw_inputs)

        result = calc_sentiment_score(sentiment_input)

        return {
            "marketData.v3.sentiment": vars(result) if hasattr(result, "__dataclass_fields__") else result,
        }
    except Exception as e:
        return {
            "marketData.v3.sentiment": {"error": str(e), "confidence": 0},
        }


# 注册Module
V3_SENTIMENT_MODULE = Module(
    name="v3_sentiment",
    requires=[
        "features.mood_inputs",
        "raw.pools.ztgc",
        "raw.pools.yest_ztgc",
        "raw.pools.dtgc",
        "raw.pools.zbgc",
        "marketData.styleRadar",
        "marketData.themePanels",
        "marketData.themeTrend",
    ],
    provides=["marketData.v3.sentiment"],
    compute=_compute,
)
