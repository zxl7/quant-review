#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
volume 模块（v2）：遵循 pipeline.Module 协议

目标：
- 离线情况下也能重算 marketData.volume（趋势 dates/values + total/change）

输入：
- raw.index_klines.codes（来自 cache/index_kline_cache.json）
  其中 items[*].a 为成交额（元）

输出：
- marketData.volume: {total, change, increase, dates, values}

注意：
- FULL（gen_report_v4）盘中用 real/time 计算 total，更实时。
- PARTIAL 离线重算用日K成交额 a 做近似（更稳定、可复现）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _extract_date(t: str) -> str:
    s = str(t or "")
    return s[:10] if len(s) >= 10 else s


def _compute(ctx: Context) -> Dict[str, Any]:
    # 兜底：如果缺少 kline cache，就保持原值（避免 partial 清空）
    codes = ((ctx.raw.get("index_klines") or {}).get("codes") or {}) if isinstance(ctx.raw, dict) else {}
    if not isinstance(codes, dict) or not codes:
        cur = ctx.market_data.get("volume") or {}
        return {"marketData.volume": cur}

    sh = (codes.get("000001.SH") or {}).get("items") or []
    sz = (codes.get("399001.SZ") or {}).get("items") or []
    if not (isinstance(sh, list) and isinstance(sz, list) and sh and sz):
        cur = ctx.market_data.get("volume") or {}
        return {"marketData.volume": cur}

    report_day = str((ctx.meta.get("date") if isinstance(ctx.meta, dict) else "") or ctx.market_data.get("date") or "")

    # 对齐日期：取两边交集的最后 5 天（且不超过报告日）
    sh_map = {_extract_date(it.get("t", "")): _to_float(it.get("a", 0.0)) for it in sh if isinstance(it, dict)}
    sz_map = {_extract_date(it.get("t", "")): _to_float(it.get("a", 0.0)) for it in sz if isinstance(it, dict)}
    days = sorted(set(sh_map.keys()) & set(sz_map.keys()))
    days = [d for d in days if d]
    if report_day:
        days = [d for d in days if d <= report_day]

    # 过滤“占位日/未收盘日”：
    # - 某些缓存会包含下一交易日的占位条目（a=0 或 sf=1）
    # - 不过滤会导致 total=0、change=-100% 这类明显异常
    sh_sf = {_extract_date(it.get("t", "")): int(it.get("sf", 0) or 0) for it in sh if isinstance(it, dict)}
    sz_sf = {_extract_date(it.get("t", "")): int(it.get("sf", 0) or 0) for it in sz if isinstance(it, dict)}
    days = [
        d
        for d in days
        if (sh_map.get(d, 0.0) > 0 and sz_map.get(d, 0.0) > 0 and sh_sf.get(d, 0) != 1 and sz_sf.get(d, 0) != 1)
    ]
    days = days[-5:]
    if len(days) < 2:
        cur = ctx.market_data.get("volume") or {}
        return {"marketData.volume": cur}

    vals_yi = [round((sh_map[d] + sz_map[d]) / 1e8, 2) for d in days]  # 亿
    total = vals_yi[-1]
    prev = vals_yi[-2]
    chg_pct = ((total - prev) / prev * 100.0) if prev else 0.0
    diff = total - prev

    direction_text = "放量" if diff >= 0 else "缩量"
    magnitude_text = "大幅" if abs(chg_pct) >= 5 else "小幅"
    increase = f"{magnitude_text}{direction_text} {abs(diff):.2f}亿"

    return {
        "marketData.volume": {
            "total": f"{total:.2f}亿",
            "change": f"{chg_pct:+.2f}%",
            "increase": increase,
            "dates": [d[5:] if len(d) >= 10 else d for d in days],
            "values": vals_yi,
        }
    }


VOLUME_MODULE = Module(
    name="volume",
    requires=["raw.index_klines.codes"],
    provides=["marketData.volume"],
    compute=_compute,
)
