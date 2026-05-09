#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
effect 模块（v2）：赚钱效应综合判断（marketData.effect）

目的：补齐模板中用于展示的 effect 字段：
- verdictType / verdict / verdictDetail
- prop：低位/连板比（首板:连板）
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _to_num(v: Any, d: float = 0.0) -> float:
    try:
        if v is None:
            return d
        if isinstance(v, str):
            v = v.replace("%", "").strip()
        return float(v)
    except Exception:
        return d


def _compute(ctx: Context) -> Dict[str, Any]:
    mi = (ctx.features.get("mood_inputs") or {}) if isinstance(ctx.features, dict) else {}
    panorama = ctx.market_data.get("panorama") or {}

    zt_count = int(mi.get("zt_count", 0) or panorama.get("limitUp", 0) or 0)
    dt_count = int(mi.get("dt_count", 0) or panorama.get("limitDown", 0) or 0)
    fb_rate = float(mi.get("fb_rate", 0) or 0)
    jj_rate = float(mi.get("jj_rate_adj", mi.get("jj_rate", 0)) or 0)
    max_lb = int(mi.get("max_lb", 0) or 0)

    # 低位/连板比：首板 : 连板（>=2）
    first_board = int(mi.get("lb_2", 0) or 0)  # 这里只是占位，下面会从 ztgc 统计
    link_board = 0
    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
    zt = pools.get("ztgc") or []
    if isinstance(zt, list) and zt:
        try:
            first_board = len([s for s in zt if isinstance(s, dict) and int(s.get("lbc", 1) or 1) == 1])
            link_board = len([s for s in zt if isinstance(s, dict) and int(s.get("lbc", 1) or 1) >= 2])
        except Exception:
            pass

    prop = f"{first_board}:{link_board}" if link_board > 0 else f"{first_board}:0"

    # verdict（复刻 gen_report_v4 的三档逻辑，先保证“有内容”）
    if zt_count >= 70 and fb_rate >= 75 and jj_rate >= 40:
        verdict_type = "good"
        verdict = "📋 综合判断：大涨高潮日，赚钱效应极好。"
        verdict_detail = f"涨停{zt_count}只，封板率{fb_rate:.1f}%，晋级率{jj_rate:.1f}%，空间{max_lb}板；注意高潮次日分化风险。"
    elif zt_count >= 50 and fb_rate >= 65:
        verdict_type = "warn"
        verdict = "📋 综合判断：修复/发酵期，结构性机会存在。"
        verdict_detail = f"涨停{zt_count}只，封板率{fb_rate:.1f}%，空间{max_lb}板；以主线核心与低位确认为主，高位接力谨慎。"
    else:
        verdict_type = "fire"
        verdict = "📋 综合判断：退潮/冰点期，亏钱效应更显著。"
        verdict_detail = f"涨停{zt_count}只，封板率{fb_rate:.1f}%，跌停{dt_count}只；建议轻仓试错或观望，等待修复信号。"

    return {
        "marketData.effect": {
            "verdictType": verdict_type,
            "verdict": verdict,
            "verdictDetail": verdict_detail,
            "prop": prop,
        }
    }


EFFECT_MODULE = Module(
    name="effect",
    requires=["features.mood_inputs", "marketData.panorama", "raw.pools.ztgc"],
    provides=["marketData.effect"],
    compute=_compute,
)

