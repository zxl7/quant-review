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

from typing import Any, Dict

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _calc_height_trend_row(day: str, day_data: list[dict[str, Any]]) -> dict[str, Any]:
    """
    纯函数：复刻 gen_report_v4 的单日高度趋势口径。
    - main: 当日最高连板高度
    - sub: 次高高度（去重后的第二名）
    - gem: 创业板最高高度（300*）
    """
    data = day_data or []
    lbs = [_to_int(s.get("lbc", 1) or 1, 1) for s in data if isinstance(s, dict)]
    main_max = max(lbs) if lbs else 0

    gem_data = [s for s in data if str((s or {}).get("dm", "")).startswith("300")]
    gem_max = max((_to_int(s.get("lbc", 1) or 1, 1) for s in gem_data), default=0)

    sorted_lb = sorted(set(lbs), reverse=True)
    sub_max = sorted_lb[1] if len(sorted_lb) > 1 else 0

    top_stock = max(data, key=lambda x: _to_int((x or {}).get("lbc", 0) or 0, 0), default={})
    top_name = (str((top_stock or {}).get("mc", "") or "")[:4]).strip()

    sub_stock = next((s for s in data if _to_int((s or {}).get("lbc", 0) or 0, 0) == sub_max), {})
    sub_name = (str((sub_stock or {}).get("mc", "") or "")[:4]).strip()

    gem_stock = max(gem_data, key=lambda x: _to_int((x or {}).get("lbc", 0) or 0, 0), default={}) if gem_data else {}
    gem_name = (str((gem_stock or {}).get("mc", "") or "")[:4]).strip()

    return {
        "day": day,
        "main": main_max,
        "sub": sub_max,
        "gem": gem_max,
        "label_main": top_name if main_max >= 3 else "",
        "label_sub": sub_name if sub_max >= 2 else "",
        "label_gem": gem_name if gem_max >= 1 else "",
    }


def _compute(ctx: Context) -> Dict[str, Any]:
    cache = (ctx.raw.get("height_trend_cache") or {}) if isinstance(ctx.raw, dict) else {}
    days = (cache.get("days") or {}) if isinstance(cache, dict) else {}
    report_day = str((ctx.meta.get("date") if isinstance(ctx.meta, dict) else "") or ctx.market_data.get("date") or "")

    # 允许 cache 缺失：尽量保持旧值
    if (not isinstance(days, dict)) or (not report_day):
        cur = ctx.market_data.get("heightTrend") or {}
        return {"marketData.heightTrend": cur}

    keys_all = sorted([d for d in days.keys() if isinstance(d, str)])
    prev = [d for d in keys_all if d < report_day][-6:]

    # 当日高度：用 raw.pools.ztgc 现算（与旧脚本一致：不写入 cache，但展示在图里）
    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
    zt_today = pools.get("ztgc") or []
    zt_today = zt_today if isinstance(zt_today, list) else []
    today_row = _calc_height_trend_row(report_day, [x for x in zt_today if isinstance(x, dict)])

    # 组合序列：历史最多 6 天 + 今日 1 天（共 7 点）
    keys = prev + [report_day]

    main = []
    sub = []
    gem = []
    label_main = []
    label_sub = []
    label_gem = []

    for d in keys:
        if d == report_day:
            it = today_row
        else:
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
