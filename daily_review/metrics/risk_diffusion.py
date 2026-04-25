#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
risk_diffusion: PRD 3.1 风险与亏钱扩散（Risk & Loss Diffusion Engine）

约束：
- 口径必须可复算：仅使用 marketData 已有字段（raw.pools + raw.themes + features.mood_inputs + prev）
- 对于“明细名单”若无法覆盖全市场，则明确标注数据口径（sample），但不伪造全量数据
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


def _to_num(v: Any, d: float = 0.0) -> float:
    try:
        if v is None:
            return d
        if isinstance(v, str):
            s = v.replace("%", "").replace("亿", "").strip()
            return float(s) if s else d
        return float(v)
    except Exception:
        return d


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _norm_code6(code: str) -> str:
    digits = "".join([c for c in str(code or "") if c.isdigit()])
    return digits[-6:] if len(digits) >= 6 else digits


_THEME_BLACKLIST = {
    "小盘",
    "中盘",
    "大盘",
    "微盘股",
    "低价",
    "融资融券",
    "MSCI中国",
    "证金汇金",
    "基金重仓",
    "社保重仓",
    "QFII持股",
    "养老金概念",
    "央企改革",
    "国资改革",
    "中字头",
    "年度强势",
    "历史新高",
}


def _pick_primary_theme(code6: str, theme_map: dict[str, list[str]], *, fallback: str = "") -> str:
    arr = theme_map.get(code6) or []
    for t in arr:
        t = str(t or "").strip()
        if not t or t in _THEME_BLACKLIST:
            continue
        return t
    return fallback or (arr[0] if arr else "其他")


def build_risk_engine(market_data: dict[str, Any], *, date: str) -> dict[str, Any]:
    md = market_data or {}
    pools = ((md.get("raw") or {}).get("pools") or {}) if isinstance(md.get("raw"), dict) else {}
    ztgc = pools.get("ztgc") or []
    dtgc = pools.get("dtgc") or []
    qsgc = pools.get("qsgc") or []
    yest_ztgc = pools.get("yest_ztgc") or []
    yest_dtgc = pools.get("yest_dtgc") or []

    # themes：code6 -> [themeName...]
    raw_themes = (md.get("raw") or {}).get("themes") or {}
    # cli 写入的是 dict(code6 -> list[str])
    theme_map = raw_themes if isinstance(raw_themes, dict) else {}

    mi = (md.get("features") or {}).get("mood_inputs") or {}
    prev_mi = ((md.get("prev") or {}).get("features") or {}).get("mood_inputs") or {}

    big_face_count = int(round(_to_num(mi.get("bf_count"), 0)))
    dt_count = len(dtgc) if isinstance(dtgc, list) else int(round(_to_num(mi.get("dt_count"), 0)))

    # 明细 faceList：使用 qsgc 中跌幅<=-5%的样本（可复算但非全市场）
    face_candidates = []
    if isinstance(qsgc, list):
        for it in qsgc:
            if not isinstance(it, dict):
                continue
            zf = _to_num(it.get("zf"), 0)
            if zf <= -5:
                face_candidates.append(it)

    # 也把跌停加入（更符合风控语义）
    dt_map = {str(it.get("dm")): it for it in dtgc if isinstance(it, dict)} if isinstance(dtgc, list) else {}
    for code, it in dt_map.items():
        face_candidates.append({"dm": it.get("dm"), "mc": it.get("mc"), "zf": _to_num(it.get("zf"), -10), "hy": it.get("hy"), "lbc": it.get("lbc")})

    # 去重（按 code6）
    seen = set()
    faces = []
    for it in sorted(face_candidates, key=lambda x: _to_num((x or {}).get("zf"), 0)):
        if not isinstance(it, dict):
            continue
        code6 = _norm_code6(str(it.get("dm") or it.get("code") or ""))
        if not code6 or code6 in seen:
            continue
        seen.add(code6)
        faces.append(it)

    yest_zt_set = {_norm_code6(str(it.get("dm") or "")) for it in yest_ztgc if isinstance(it, dict)}
    # 统计 diffusionMap：按“题材(优先) / 行业(兜底)”聚合
    sector_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for it in faces:
        code6 = _norm_code6(str(it.get("dm") or ""))
        hy = str(it.get("hy") or "").strip()
        sector = _pick_primary_theme(code6, theme_map, fallback=hy or "其他")
        sector_buckets[sector].append(it)

    diffusion_map = []
    for sec, arr in sector_buckets.items():
        drops = [_to_num(x.get("zf"), 0) for x in arr if isinstance(x, dict)]
        avg_drop = sum(drops) / len(drops) if drops else 0.0
        diffusion_map.append(
            {
                "sector": sec,
                "bigFaceCount": len(arr),
                "avgDrop": round(avg_drop, 2),
                "subSectors": [],  # 现有数据缺二级子行业，保持空（不伪造）
            }
        )
    diffusion_map.sort(key=lambda x: (x.get("bigFaceCount", 0), abs(_to_num(x.get("avgDrop"), 0))), reverse=True)

    # penetration：跌停穿透（跌停中有多少是昨日涨停）
    dt_set = {_norm_code6(str(it.get("dm") or "")) for it in dtgc if isinstance(it, dict)}
    dt_in_yzt = len([c for c in dt_set if c and c in yest_zt_set])
    dt_in_zt_ratio = (dt_in_yzt / len(dt_set)) if dt_set else 0.0

    # 昨日跌停修复（精确）：昨日跌停中，今日未继续跌停的数量
    yest_dt_set = {_norm_code6(str(it.get("dm") or "")) for it in yest_dtgc if isinstance(it, dict)}
    recovery_cnt = len([c for c in yest_dt_set if c and c not in dt_set])
    recovery_ratio = (recovery_cnt / len(yest_dt_set)) if yest_dt_set else 0.0

    diffusion_sector_count = len(diffusion_map)

    # score（PRD 给出的线性公式做“可复算实现”）
    base = 100.0
    score = (
        base
        - big_face_count * 2.0
        - dt_count * 3.0
        - diffusion_sector_count * 5.0
        - dt_in_zt_ratio * 20.0
        + recovery_ratio * 10.0
    )
    score = int(round(_clamp(score, 0, 100)))

    # level
    if score < 40:
        level = "safe"
    elif score < 60:
        level = "warning"
    else:
        level = "danger"

    # trend：对比昨日（用 prev 的 bf/dt 复算一个 yesterdayScore，保证可复算）
    prev_bf = int(round(_to_num(prev_mi.get("bf_count"), big_face_count)))
    prev_dt = int(round(_to_num(prev_mi.get("dt_count"), dt_count)))
    # 昨日扩散板块数量：用昨日跌停的题材分布（可复算）
    prev_diff_sectors = set()
    raw_themes_prev = ((md.get("prev") or {}).get("raw") or {}).get("themes") or theme_map
    theme_map_prev = raw_themes_prev if isinstance(raw_themes_prev, dict) else theme_map
    for it in (pools.get("yest_dtgc") or []):
        if not isinstance(it, dict):
            continue
        code6 = _norm_code6(str(it.get("dm") or ""))
        prev_diff_sectors.add(_pick_primary_theme(code6, theme_map_prev, fallback=str(it.get("hy") or "")))
    prev_diff_cnt = len([x for x in prev_diff_sectors if x])
    prev_dt_in_zt = 0.0  # 缺“前天涨停”缓存，无法精确；置 0 并在 meta 标注
    y_score = (
        100.0
        - prev_bf * 2.0
        - prev_dt * 3.0
        - prev_diff_cnt * 5.0
        - prev_dt_in_zt * 20.0
        + 0.0
    )
    y_score = int(round(_clamp(y_score, 0, 100)))
    if score < y_score:
        trend = "up"  # 风险加剧
    elif score > y_score:
        trend = "down"  # 风险缓解
    else:
        trend = "flat"

    # faceList（最多 20 条）
    zt_height = {_norm_code6(str(it.get("dm") or "")): int(_to_num(it.get("lbc"), 0)) for it in ztgc if isinstance(ztgc, list) and isinstance(it, dict)}
    dt_height = {_norm_code6(str(it.get("dm") or "")): int(_to_num(it.get("lbc"), 0)) for it in dtgc if isinstance(dtgc, list) and isinstance(it, dict)}

    face_list = []
    for rank, it in enumerate(sorted(faces, key=lambda x: _to_num(x.get("zf"), 0))[:20], start=1):
        code6 = _norm_code6(str(it.get("dm") or ""))
        hy = str(it.get("hy") or "").strip()
        sector = _pick_primary_theme(code6, theme_map, fallback=hy or "其他")
        lb = zt_height.get(code6) or dt_height.get(code6) or int(_to_num(it.get("lbc"), 0))
        face_list.append(
            {
                "rank": rank,
                "code": code6,
                "name": str(it.get("mc") or ""),
                "pct": round(_to_num(it.get("zf"), 0), 2),
                "sector": sector,
                "wasZt": code6 in yest_zt_set,
                "lbHeight": lb,
            }
        )

    return {
        "score": score,
        "level": level,
        "trend": trend,
        "diffusionMap": diffusion_map[:8],
        "penetration": {
            "dtInZbRatio": round(dt_in_zt_ratio, 4),
            "dtInZbCount": dt_in_yzt,
            "dtCount": len(dt_set),
            # consecutiveDrop：需要个股历史K线才能精确计算；这里先不输出，避免伪造
            "consecutiveDrop": None,
        },
        "faceList": face_list,
        "meta": {
            "precision": "strict_with_sample_list",
            "asOf": date,
            "notes": [
                "score 使用 features.mood_inputs.bf_count/dt_count 做全市场计数；diffusionMap/faceList 使用 raw.pools.qsgc（跌幅<=-5）+ dtgc 构建样本明细。",
                "trend 的昨日对比无法精确计算“昨日跌停中昨日涨停占比”（缺前天涨停缓存），已按 0 处理并保留说明。",
            ],
        },
    }

