#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ladder 模块（v2）：遵循 pipeline.Module 协议

职责：
- 从 raw.pools.ztgc 生成“连板天梯”marketData.ladder（2板及以上）
- 为后续（可选）情绪模块提供 yest 相关输入，本模块暂只输出 ladder

说明：
- 该模块只做“结构数据”生产，不做主观结论（结论交给 mood/action_guide）
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


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


def _parse_lbc_from_tj(tj: str) -> int:
    """
    纯函数：从涨停统计 tj（x天/y板）中提取 y（连板数）。
    """
    if not tj:
        return 1
    try:
        parts = str(tj).split("/")
        if len(parts) != 2:
            return 1
        return int(parts[1])
    except Exception:
        return 1


def _normalize_hms(hms: str) -> str:
    """
    纯函数：兼容 "092500" / "09:25:00"。
    """
    s = str(hms or "").strip()
    if not s:
        return ""
    if ":" in s:
        return s
    if len(s) == 6 and s.isdigit():
        return f"{s[0:2]}:{s[2:4]}:{s[4:6]}"
    return s


def _as_list(v: Any) -> List[Dict[str, Any]]:
    return v if isinstance(v, list) else []


def _compute(ctx: Context) -> Dict[str, Any]:
    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
    zt = _as_list(pools.get("ztgc"))
    yest_zt = _as_list(pools.get("yest_ztgc"))
    if not zt:
        # 兜底：不改动，避免 partial 时因为 raw 缺失导致天梯变空
        cur = ctx.market_data.get("ladder") or []
        return {"marketData.ladder": cur}

    # 昨日连板映射：用于标注“晋级/新晋”（避免前端显示 undefined）
    # 规则：
    # - 若今日 lbc>=2 且昨日同 code 存在且昨日 lbc == 今日 lbc-1 -> 晋级
    # - 否则 -> 新晋
    yest_lb: Dict[str, int] = {}
    for s in yest_zt:
        code = str(s.get("dm") or "").strip()
        if not code:
            continue
        lb = s.get("lbc", None)
        lbc = _to_int(lb, 0) if lb is not None else _parse_lbc_from_tj(str(s.get("tj", "") or ""))
        if lbc <= 0:
            lbc = 1
        yest_lb[code] = lbc

    by_lbc: Dict[int, List[Dict[str, Any]]] = {}
    for s in zt:
        lb = s.get("lbc", None)
        lbc = _to_int(lb, 0) if lb is not None else _parse_lbc_from_tj(str(s.get("tj", "") or ""))
        if lbc <= 0:
            lbc = 1
        by_lbc.setdefault(lbc, []).append(s)

    for k in list(by_lbc.keys()):
        by_lbc[k].sort(key=lambda x: _to_float(x.get("zf"), 0.0), reverse=True)

    ladder_rows: List[Dict[str, Any]] = []
    for lb in sorted(by_lbc.keys(), reverse=True):
        if lb <= 1:
            continue
        for s in by_lbc[lb]:
            code = str(s.get("dm") or "").strip()
            ylb = yest_lb.get(code, 0)
            status = "晋级" if (ylb == lb - 1 and ylb >= 1) else "新晋"
            ladder_rows.append(
                {
                    "badge": lb,
                    "name": str(s.get("mc") or ""),
                    "code": code,
                    "zf": _to_float(s.get("zf"), 0.0),
                    "zbc": _to_int(s.get("zbc"), 0),
                    "zj": _to_float(s.get("zj"), 0.0),
                    "hs": _to_float(s.get("hs"), 0.0),
                    "cje": _to_float(s.get("cje"), 0.0),
                    "fbt": _normalize_hms(str(s.get("fbt") or "")),
                    "status": status,
                    "note": "",
                }
            )

    # 最高板标记（保持与 gen_report_v4 一致的体验）
    if ladder_rows:
        ladder_rows[0]["name"] = f"👑 {ladder_rows[0]['name']}"

    return {"marketData.ladder": ladder_rows}


LADDER_MODULE = Module(
    name="ladder",
    requires=["raw.pools.ztgc", "raw.pools.yest_ztgc"],
    provides=["marketData.ladder"],
    compute=_compute,
)
