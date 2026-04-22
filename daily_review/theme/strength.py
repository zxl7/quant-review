#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
题材强度：分三列（涨停/炸板/跌停）+ 净强度
"""

from __future__ import annotations

from typing import Dict, List


def build_strength_rows(
    *,
    zt_cnt: Dict[str, int],
    zb_cnt: Dict[str, int],
    dt_cnt: Dict[str, int],
    topn: int = 12,
    w_zt: float = 1.0,
    w_zb: float = 0.7,
    w_dt: float = 1.2,
) -> List[dict]:
    names = set(zt_cnt.keys()) | set(zb_cnt.keys()) | set(dt_cnt.keys())
    rows = []
    for name in names:
        zt = int(zt_cnt.get(name, 0) or 0)
        zb = int(zb_cnt.get(name, 0) or 0)
        dt = int(dt_cnt.get(name, 0) or 0)
        net = zt * w_zt - zb * w_zb - dt * w_dt
        risk = zb * w_zb + dt * w_dt
        rows.append(
            {
                "name": name,
                "zt": zt,
                "zb": zb,
                "dt": dt,
                "net": round(net, 1),
                "risk": round(risk, 1),
                "netClass": "red-text" if net >= 3 else ("orange-text" if net >= 1 else "green-text"),
                "riskClass": "red-text" if risk >= 3 else ("orange-text" if risk >= 1 else "green-text"),
            }
        )
    rows.sort(key=lambda r: (-r["net"], -r["zt"], r["risk"]))
    return rows[:topn]

