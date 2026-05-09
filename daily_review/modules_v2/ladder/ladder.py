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

from typing import Any, Dict, List

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


def _parse_minutes(hms: str) -> int:
    s = _normalize_hms(hms)
    if not s or ":" not in s:
        return -1
    try:
        hh, mm = s.split(":")[0:2]
        return int(hh) * 60 + int(mm)
    except Exception:
        return -1


def _chip(text: str, cls: str) -> Dict[str, str]:
    return {"text": text, "cls": cls}


def _quality_profile(*, lbc: int, status: str, zbc: int, hs: float, zj: float, cje: float, fbt: str) -> Dict[str, Any]:
    """
    连板质量标签：
    - 分歧烂板：开板次数非常多，且换手/承接压力明显
    - 加速确认：晋级板早盘快速确认，几乎不给分歧
    - 温和放量：有一定换手，但开板少，量价结构健康
    - 高换手承接：分歧充分，靠承接完成封板
    - 午后确认：确认时间偏后，更像后手修复
    """
    minute = _parse_minutes(fbt)
    seal_ratio = (zj / cje) if cje > 0 else 0.0

    quality_label = "常规封板"
    quality_tags: List[Dict[str, str]] = []
    quality_note = "质量中性，需结合位阶与次日承接再看。"
    quality_score = 68.0

    if zbc >= 8 or (zbc >= 5 and hs >= 10):
        quality_label = "分歧烂板"
        quality_score = 36.0
        quality_tags = [
            _chip("分歧烂板", "ladder-chip-warn orange-text"),
            _chip("高波动", "ladder-chip-warn orange-text"),
        ]
        quality_note = f"开板 {zbc} 次、换手 {hs:.1f}%，封板过程反复，次日承接压力偏大。"
    elif status == "晋级" and zbc == 0 and 0 < minute <= 570 and hs <= 6:
        quality_label = "加速确认"
        quality_score = 96.0
        quality_tags = [
            _chip("加速确认", "ladder-chip-strong red-text"),
            _chip("早盘强封", "ladder-chip-cool blue-text"),
        ]
        quality_note = "晋级板早盘直接确认，几乎不给分歧，属于一致性较强的加速板。"
    elif zbc <= 1 and 4 <= hs <= 16:
        quality_label = "温和放量"
        quality_score = 84.0
        quality_tags = [
            _chip("温和放量", "ladder-chip-cool blue-text"),
        ]
        quality_note = f"换手 {hs:.1f}% 且开板不多，量能释放适中，承接结构相对健康。"
    elif zbc <= 2 and hs >= 16:
        quality_label = "高换手承接"
        quality_score = 78.0
        quality_tags = [
            _chip("高换手承接", "ladder-chip-cool blue-text"),
        ]
        quality_note = f"换手 {hs:.1f}% 较高，但仍能封住，说明承接充分、筹码交换完成。"
    elif zbc >= 3:
        quality_label = "反复回封"
        quality_score = 54.0
        quality_tags = [
            _chip("反复回封", "ladder-chip-warn orange-text"),
        ]
        quality_note = f"开板 {zbc} 次后完成回封，分歧明显，质量强弱取决于次日是否有承接。"
    elif zbc == 0 and 0 < minute <= 575 and seal_ratio >= 0.18:
        quality_label = "封单充足"
        quality_score = 90.0
        quality_tags = [
            _chip("封单充足", "ladder-chip-strong red-text"),
        ]
        quality_note = "早盘封单相对充足，全天一致性较强，属于偏强质量板。"
    elif zbc <= 1 and minute >= 780:
        quality_label = "午后确认"
        quality_score = 66.0
        quality_tags = [
            _chip("午后确认", "ladder-chip-cool blue-text"),
        ]
        quality_note = "午后才完成封板，偏修复确认型，次日更要看情绪是否延续。"
    elif lbc >= 4 and zbc <= 1:
        quality_label = "高位确认"
        quality_score = 88.0
        quality_tags = [
            _chip("高位确认", "ladder-chip-strong red-text"),
        ]
        quality_note = "高位板仍能较顺畅封住，说明当前高度压制不算明显。"

    return {
        "quality_label": quality_label,
        "quality_score": quality_score,
        "quality_tags": quality_tags,
        "quality_note": quality_note,
    }


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

    ladder_rows: List[Dict[str, Any]] = []
    for lb in sorted(by_lbc.keys(), reverse=True):
        if lb <= 1:
            continue
        rows_for_lb: List[Dict[str, Any]] = []
        for s in by_lbc[lb]:
            code = str(s.get("dm") or "").strip()
            ylb = yest_lb.get(code, 0)
            status = "晋级" if (ylb == lb - 1 and ylb >= 1) else "新晋"
            zbc = _to_int(s.get("zbc"), 0)
            zj = _to_float(s.get("zj"), 0.0)
            hs = _to_float(s.get("hs"), 0.0)
            cje = _to_float(s.get("cje"), 0.0)
            fbt = _normalize_hms(str(s.get("fbt") or ""))
            q = _quality_profile(
                lbc=lb,
                status=status,
                zbc=zbc,
                hs=hs,
                zj=zj,
                cje=cje,
                fbt=fbt,
            )
            rows_for_lb.append(
                {
                    "badge": lb,
                    "name": str(s.get("mc") or ""),
                    "code": code,
                    "zf": _to_float(s.get("zf"), 0.0),
                    "zbc": zbc,
                    "zj": zj,
                    "hs": hs,
                    "cje": cje,
                    "fbt": fbt,
                    "status": status,
                    "note": q["quality_note"],
                    "qualityLabel": q["quality_label"],
                    "qualityScore": q["quality_score"],
                    "qualityTags": q["quality_tags"],
                }
            )
        rows_for_lb.sort(
            key=lambda x: (
                _to_float(x.get("qualityScore"), 0.0),
                _to_float(x.get("zj"), 0.0),
                -_parse_minutes(str(x.get("fbt") or "")) if _parse_minutes(str(x.get("fbt") or "")) > 0 else -9999,
                -_to_int(x.get("zbc"), 0),
                _to_float(x.get("zf"), 0.0),
            ),
            reverse=True,
        )
        ladder_rows.extend(rows_for_lb)

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
