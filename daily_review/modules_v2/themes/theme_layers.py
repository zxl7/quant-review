#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
theme_layers 模块（v2）：主线/支线/轮动线（marketData.themeLayers）

最小可用版：
- 基于 themePanels.ztTop / strengthRows 输出 3 层：
  主线：ztTop[0]
  支线：ztTop[1:3]
  轮动：strengthRows 中净强靠前但不在 ztTop 的前几名
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _compute(ctx: Context) -> Dict[str, Any]:
    tp = ctx.market_data.get("themePanels") or {}
    zt_top = tp.get("ztTop") or []
    rows = tp.get("strengthRows") or []
    zt_top = zt_top if isinstance(zt_top, list) else []
    rows = rows if isinstance(rows, list) else []

    main = zt_top[0] if len(zt_top) >= 1 and isinstance(zt_top[0], dict) else {}
    sup = [x for x in zt_top[1:3] if isinstance(x, dict)]

    zt_names = set([str(x.get("name") or "") for x in zt_top if isinstance(x, dict)])
    rot = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or "")
        if not name or name in zt_names:
            continue
        rot.append(r)
        if len(rot) >= 2:
            break

    def pack(label: str, it: dict) -> dict:
        return {
            "label": label,
            "names": str(it.get("name") or "-"),
            "count": int(float(it.get("count", it.get("zt", 0)) or 0)),
            "stocks": str(it.get("examples") or ""),
        }

    layers = []
    if main:
        layers.append(pack("主线", main))
    for s in sup:
        layers.append(pack("支线", s))
    for r in rot:
        layers.append(pack("轮动", r))

    return {"marketData.themeLayers": layers}


THEME_LAYERS_MODULE = Module(
    name="theme_layers",
    requires=["marketData.themePanels"],
    provides=["marketData.themeLayers"],
    compute=_compute,
)

