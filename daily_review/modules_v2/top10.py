#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
top10 模块（v2）：遵循 pipeline.Module 协议

说明：
- 成交额 TOP10 属于“重 IO/重数据”的模块，当前 FULL 仍由 gen_report_v4 负责抓取与构建。
- 这个 v2 模块当前目标是：
  1) partial 时保证字段结构稳定（不因缺失而页面报错）
  2) 允许你后续只改“top10Summary 口径/展示”并离线重算

输入：
- marketData.top10（若存在则复用）

输出：
- marketData.top10（保持不变或置空）
- marketData.top10Summary（从 top10 推导）
"""

from __future__ import annotations

from typing import Any, Dict, List

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _as_list(v: Any) -> List[Dict[str, Any]]:
    return v if isinstance(v, list) else []


def _parse_yi(s: Any) -> float:
    """
    把 "123亿" / "123.4亿" 解析为 float(亿)。
    """
    t = str(s or "").strip().replace("亿", "")
    try:
        return float(t)
    except Exception:
        return 0.0


def _compute(ctx: Context) -> Dict[str, Any]:
    top10 = _as_list(ctx.market_data.get("top10"))
    if not top10:
        # 兜底：保持旧 summary 或置空
        return {
            "marketData.top10": ctx.market_data.get("top10") or [],
            "marketData.top10Summary": ctx.market_data.get("top10Summary") or {"top5_sum_yi": "-", "top5_sectors": "-"},
        }

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
    requires=["marketData.top10"],
    provides=["marketData.top10", "marketData.top10Summary"],
    compute=_compute,
)

