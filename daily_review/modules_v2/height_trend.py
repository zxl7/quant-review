#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
height_trend 模块（v2）：遵循 pipeline.Module 协议

输入：
- raw.height_trend_cache.days（来自 cache/height_trend_cache.json）

输出（供前端 renderHeightTrend 使用）：
marketData.heightTrend = {
  dates: [...],
  main: [...], sub: [...], gem: [...],
  labels: {main: [...], sub: [...], gem: [...]},
  palette: [...]
}
"""

from __future__ import annotations

from typing import Any, Dict, List

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _compute(ctx: Context) -> Dict[str, Any]:
    cache = (ctx.raw.get("height_trend_cache") or {}) if isinstance(ctx.raw, dict) else {}
    days = (cache.get("days") or {}) if isinstance(cache, dict) else {}
    if not isinstance(days, dict) or not days:
        cur = ctx.market_data.get("heightTrend") or {}
        return {"marketData.heightTrend": cur}

    keys = sorted([d for d in days.keys() if isinstance(d, str)])
    keys = keys[-7:]
    if len(keys) < 2:
        cur = ctx.market_data.get("heightTrend") or {}
        return {"marketData.heightTrend": cur}

    main = []
    sub = []
    gem = []
    label_main = []
    label_sub = []
    label_gem = []

    for d in keys:
        it = days.get(d) or {}
        main.append(_to_int(it.get("main"), 0))
        sub.append(_to_int(it.get("sub"), 0))
        gem.append(_to_int(it.get("gem"), 0))
        label_main.append(str(it.get("label_main") or ""))
        label_sub.append(str(it.get("label_sub") or ""))
        label_gem.append(str(it.get("label_gem") or ""))

    return {
        "marketData.heightTrend": {
            "dates": [d[5:] if len(d) >= 10 else d for d in keys],
            "main": main,
            "sub": sub,
            "gem": gem,
            "labels": {"main": label_main, "sub": label_sub, "gem": label_gem},
            "palette": ["#ef4444", "#f59e0b", "#94a3b8"],
        }
    }


HEIGHT_TREND_MODULE = Module(
    name="height_trend",
    requires=["raw.height_trend_cache.days"],
    provides=["marketData.heightTrend"],
    compute=_compute,
)

