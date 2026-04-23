#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
top10 模块（v2）：成交额 TOP10（marketData.top10 + marketData.top10Summary）

说明：
- 旧实现是在 gen_report_v4 里“合并涨停池 + 强势股池”按成交额排序，并为每只股补题材。
- v2 版本保持相同口径，但完全离线：只依赖 raw.pools + raw.themes.code2themes。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _as_list(v: Any) -> List[Dict[str, Any]]:
    return v if isinstance(v, list) else []

def _norm_code6(dm: Any) -> str:
    s = "".join([c for c in str(dm or "") if c.isdigit()])
    return s[-6:] if len(s) >= 6 else s


def _parse_yi(s: Any) -> float:
    """
    把 "123亿" / "123.4亿" 解析为 float(亿)。
    """
    t = str(s or "").strip().replace("亿", "")
    try:
        return float(t)
    except Exception:
        return 0.0


def _pct_class(zf: float) -> str:
    return "red-text" if zf > 0 else ("green-text" if zf < 0 else "")


def _weight_of_rank(rank: int) -> int:
    # 模板里用 weight 控制字体粗细（对齐旧版）
    if rank <= 1:
        return 900
    if rank <= 3:
        return 800
    return 700


def _compute(ctx: Context) -> Dict[str, Any]:
    # 若已有（例如从历史缓存带入）则复用；否则从 raw 离线重算
    top10 = _as_list(ctx.market_data.get("top10"))
    if not top10:
        pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
        zt = _as_list(pools.get("ztgc"))
        qs = _as_list(pools.get("qsgc"))
        code2themes = ((ctx.raw.get("themes") or {}).get("code2themes") or {}) if isinstance(ctx.raw, dict) else {}
        code2themes = code2themes if isinstance(code2themes, dict) else {}

        merged: Dict[str, Dict[str, Any]] = {}
        for s in (zt + qs):
            if not isinstance(s, dict):
                continue
            code = str(s.get("dm") or s.get("code") or "").strip()
            if not code:
                continue
            cje = float(s.get("cje", 0) or 0)
            if cje <= 0:
                continue
            # 去重：同 code 取成交额更大的一条（通常涨停池更完整）
            prev = merged.get(code)
            if (prev is None) or (float(prev.get("cje", 0) or 0) < cje):
                merged[code] = s

        rows = sorted(merged.values(), key=lambda x: float(x.get("cje", 0) or 0), reverse=True)[:10]

        built = []
        for i, s in enumerate(rows, start=1):
            mc = str(s.get("mc") or s.get("name") or "").strip()
            zf = float(s.get("zf", 0) or 0)
            cje = float(s.get("cje", 0) or 0)
            hy = str(s.get("hy") or "").strip()
            code6 = _norm_code6(s.get("dm") or s.get("code") or "")
            themes = code2themes.get(code6) or []
            sector = str(themes[0]) if isinstance(themes, list) and themes else (hy or "其他")
            built.append(
                {
                    "rank": i,
                    "mc": mc or code6,
                    "zf_str": f"{zf:+.2f}%",
                    "pct_class": _pct_class(zf),
                    "cje_yi": f"{cje/1e8:.0f}亿",
                    "weight": _weight_of_rank(i),
                    "sector": sector,
                }
            )
        top10 = built

    top5 = top10[:5]
    top5_sum = sum(_parse_yi(r.get("cje_yi")) for r in top5)
    top5_sectors = []
    for r in top5:
        sec = str(r.get("sector") or "").strip()
        if sec and sec not in top5_sectors:
            top5_sectors.append(sec)

    summary = {
        "top5_sum_yi": f"{top5_sum:.0f}亿",
        "top5_sectors": ", ".join(top5_sectors) if top5_sectors else "-",
    }
    return {
        "marketData.top10": top10,
        "marketData.top10Summary": summary,
    }


TOP10_MODULE = Module(
    name="top10",
    requires=["raw.pools.ztgc", "raw.pools.qsgc", "raw.themes.code2themes"],
    provides=["marketData.top10", "marketData.top10Summary"],
    compute=_compute,
)
