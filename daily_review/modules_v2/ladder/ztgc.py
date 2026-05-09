#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ztgc 模块（v2）：遵循 pipeline.Module 协议

职责：
- 将 raw.pools.ztgc（涨停池）裁剪为前端需要的字段，输出 marketData.ztgc
- 根据 raw.themes.code2themes（题材缓存）构建 marketData.zt_code_themes

说明：
- 不做任何网络请求（完全离线可重算）
- 这样你改“前端个股分析/龙头识别”的字段口径时，不需要全量 fetch
"""

from __future__ import annotations

from typing import Any, Dict, List

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _as_list(v: Any) -> List[Dict[str, Any]]:
    return v if isinstance(v, list) else []


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _norm_code6(dm: Any) -> str:
    s = "".join([c for c in str(dm or "") if c.isdigit()])
    return s[-6:] if len(s) >= 6 else s


def _compute(ctx: Context) -> Dict[str, Any]:
    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
    zt_all = _as_list(pools.get("ztgc"))

    themes = (ctx.raw.get("themes") or {}) if isinstance(ctx.raw, dict) else {}
    code2themes = (themes.get("code2themes") or {}) if isinstance(themes, dict) else {}

    if not zt_all:
        # 兜底：保持旧值
        patch: Dict[str, Any] = {}
        if "ztgc" in ctx.market_data:
            patch["marketData.ztgc"] = ctx.market_data.get("ztgc") or []
        if "zt_code_themes" in ctx.market_data:
            patch["marketData.zt_code_themes"] = ctx.market_data.get("zt_code_themes") or {}
        return patch

    # 裁剪字段（保持与 gen_report_v4 输出一致）
    ztgc = []
    zt_code_themes: Dict[str, List[str]] = {}
    for s in zt_all:
        dm = str(s.get("dm", "") or s.get("code", "") or "").strip()
        mc = str(s.get("mc", "") or s.get("name", "") or "").strip()
        if not dm:
            continue

        ztgc.append(
            {
                "dm": dm,
                "mc": mc,
                "p": _to_float(s.get("p"), 0.0),
                "lbc": _to_int(s.get("lbc"), 1) or 1,
                "zf": _to_float(s.get("zf"), 0.0),
                "cje": _to_float(s.get("cje"), 0.0),
                "lt": _to_float(s.get("lt"), 0.0),
                "zsz": _to_float(s.get("zsz"), 0.0),
                "zj": _to_float(s.get("zj"), 0.0),
                "zbc": _to_int(s.get("zbc"), 0),
                "hs": _to_float(s.get("hs"), 0.0),
                "fbt": str(s.get("fbt", "") or ""),
                "lbt": str(s.get("lbt", "") or ""),
                "tj": str(s.get("tj", "") or ""),
                "hy": str(s.get("hy", "") or ""),
            }
        )

        # 题材映射：key 使用原 dm（与前端匹配），value 使用缓存 code6->themes
        code6 = _norm_code6(dm)
        if code6 and isinstance(code2themes, dict):
            zt_code_themes[dm] = list(code2themes.get(code6) or [])

    return {
        "marketData.ztgc": ztgc,
        "marketData.zt_code_themes": zt_code_themes,
    }


ZTGC_MODULE = Module(
    name="ztgc",
    requires=["raw.pools.ztgc", "raw.themes.code2themes"],
    provides=["marketData.ztgc", "marketData.zt_code_themes"],
    compute=_compute,
)

