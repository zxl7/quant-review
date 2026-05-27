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

    # 实时行情融合
    quotes_raw = (ctx.raw.get("quotes") or {}) if isinstance(ctx.raw, dict) else {}
    quotes_map = quotes_raw.get("items") or {}

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

        # 归一化代码，用于匹配实时行情
        code6 = _norm_code6(dm)
        q = quotes_map.get(code6) if isinstance(quotes_map, dict) else None

        # 融合逻辑：优先使用实时行情（quotes），缺失时回退到池数据（pools）
        # 注意：实时行情中的字段名可能与池数据不一致，需做映射
        def _get_val(pool_key: str, quote_key: str, default: Any) -> Any:
            if isinstance(q, dict) and q.get(quote_key) not in (None, "", 0, 0.0):
                return q.get(quote_key)
            return s.get(pool_key, default)

        p_val = _get_val("p", "p", 0.0)
        zf_val = _get_val("zf", "pc", 0.0)
        cje_val = _get_val("cje", "cje", 0.0)
        hs_val = _get_val("hs", "hs", 0.0)
        zsz_val = _get_val("zsz", "zsz", 0.0)
        lt_val = _get_val("lt", "lt", 0.0)

        ztgc.append(
            {
                "dm": dm,
                "mc": mc,
                "p": _to_float(p_val, 0.0),
                "lbc": _to_int(s.get("lbc"), 1) or 1,
                "zf": _to_float(zf_val, 0.0),
                "cje": _to_float(cje_val, 0.0),
                "lt": _to_float(lt_val, 0.0),
                "zsz": _to_float(zsz_val, 0.0),
                "zj": _to_float(s.get("zj"), 0.0),
                "zbc": _to_int(s.get("zbc"), 0),
                "hs": _to_float(hs_val, 0.0),
                "fbt": str(s.get("fbt", "") or ""),
                "lbt": str(s.get("lbt", "") or ""),
                "tj": str(s.get("tj", "") or ""),
                "hy": str(s.get("hy", "") or ""),
            }
        )

        # 题材映射：key 使用原 dm（与前端匹配），value 使用缓存 code6->themes
        if code6 and isinstance(code2themes, dict):
            zt_code_themes[dm] = list(code2themes.get(code6) or [])

    return {
        "marketData.ztgc": ztgc,
        "marketData.zt_code_themes": zt_code_themes,
    }


ZTGC_MODULE = Module(
    name="ztgc",
    requires=["raw.pools.ztgc", "raw.themes.code2themes", "raw.quotes"],
    provides=["marketData.ztgc", "marketData.zt_code_themes"],
    compute=_compute,
)

