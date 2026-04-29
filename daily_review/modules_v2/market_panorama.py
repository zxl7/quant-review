#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
market_panorama 模块（v2）：市场全景（赚钱效应 + 亏钱效应 + 图二KPI）

输出：
- marketData.marketPanorama

设计目标：
- 作为“市场全景”单一入口，承载赚钱/亏钱效应的关键结论与证据
- 复用 raw.pools 与 features.mood_inputs（不做网络请求）
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        if isinstance(v, str):
            v = v.replace("%", "").strip()
        return float(v)
    except Exception:
        return default


def _to_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(float(v))
    except Exception:
        return default


def _pick_max_lb_name(ztgc: list[dict[str, Any]]) -> tuple[int, str]:
    """从涨停池找最高连板与名称（用于图二“最高连板”）"""
    best_lb = 0
    best_name = ""
    for s in ztgc:
        if not isinstance(s, dict):
            continue
        lb = _to_int(s.get("lbc", 0), 0)
        if lb >= best_lb:
            best_lb = lb
            best_name = str(s.get("mc") or s.get("name") or best_name or "")
    return best_lb, best_name


def _index_summary(indices: list[dict[str, Any]]) -> tuple[str, str]:
    """返回（简述、明细行）"""
    if not isinstance(indices, list) or not indices:
        return ("—", "—")
    downs = 0
    parts = []
    for it in indices:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "")
        chg = str(it.get("chg") or "")
        parts.append(f"{name}{chg}")
        try:
            v = float(chg.replace("%", "").replace("+", "").strip())
            if v < 0:
                downs += 1
        except Exception:
            pass
    if downs >= 3:
        brief = "全线收跌"
    elif downs == 2:
        brief = "偏弱"
    elif downs == 1:
        brief = "分化"
    else:
        brief = "偏强"
    return brief, " | ".join(parts) if parts else "—"


def _compute(ctx: Context) -> Dict[str, Any]:
    mi = (ctx.features.get("mood_inputs") or {}) if isinstance(ctx.features, dict) else {}
    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}

    ztgc = [x for x in (pools.get("ztgc") or []) if isinstance(x, dict)]
    dtgc = [x for x in (pools.get("dtgc") or []) if isinstance(x, dict)]
    zbgc = [x for x in (pools.get("zbgc") or []) if isinstance(x, dict)]
    qsgc = [x for x in (pools.get("qsgc") or []) if isinstance(x, dict)]

    zt_count = _to_int(mi.get("zt_count"), len(ztgc))
    dt_count = _to_int(mi.get("dt_count"), len(dtgc))
    zb_count = _to_int(mi.get("zb_count"), len(zbgc))
    zb_rate = _to_float(mi.get("zb_rate"), 0.0)

    # 首板 / 连板
    first_board = len([s for s in ztgc if _to_int(s.get("lbc", 1), 1) == 1])
    link_board = len([s for s in ztgc if _to_int(s.get("lbc", 1), 1) >= 2])

    max_lb = _to_int(mi.get("max_lb"), 0)
    max_lb2, max_name = _pick_max_lb_name(ztgc)
    if not max_lb:
        max_lb = max_lb2
    if not max_name:
        max_name = str((ctx.market_data.get("ladder") or [{}])[0].get("name") or "").replace("👑", "").strip()

    # 20cm 近似：300/301/688
    cm20 = 0
    for s in ztgc:
        dm = str(s.get("dm") or "")
        if dm.startswith("300") or dm.startswith("301") or dm.startswith("688"):
            cm20 += 1

    indices = ctx.market_data.get("indices") or []
    idx_brief, idx_line = _index_summary(indices if isinstance(indices, list) else [])

    bf_count = _to_int(mi.get("bf_count"), 0)
    bf_names = str(mi.get("bf_names") or "").strip()

    # 赚钱效应评分：偏“机会数量+封板质量+强势反馈”
    fb_rate = _to_float(mi.get("fb_rate"), 0.0)
    qs_avg = _to_float(mi.get("qs_avg_zf"), None)  # 可能缺失
    earn_score = 0.0
    earn_score += min(40.0, zt_count / 70.0 * 40.0) if zt_count else 0.0
    earn_score += min(25.0, fb_rate / 85.0 * 25.0) if fb_rate else 0.0
    earn_score += min(20.0, max_lb * 4.0)
    if qs_avg is not None:
        earn_score += max(0.0, min(15.0, (qs_avg + 2.0) / 7.0 * 15.0))
    earn_score = max(0.0, min(100.0, earn_score))

    # 亏钱效应评分：偏“跌停+大面+炸板”
    loss_score = 0.0
    loss_score += min(45.0, dt_count / 25.0 * 45.0) if dt_count else 0.0
    loss_score += min(35.0, bf_count / 10.0 * 35.0) if bf_count else 0.0
    loss_score += min(20.0, zb_rate / 40.0 * 20.0) if zb_rate else 0.0
    loss_score = max(0.0, min(100.0, loss_score))

    def _stars(score100: float) -> float:
        # 0~100 → 0~5（允许半星）
        return round((score100 / 100.0) * 5.0 * 2) / 2.0

    def _stars_text(stars: float) -> str:
        full = int(stars)
        half = 1 if abs(stars - full - 0.5) < 1e-9 else 0
        empty = max(0, 5 - full - half)
        return ("★" * full) + ("½" if half else "") + ("☆" * empty)

    out = {
        "kpis": {
            "zt_count": zt_count,
            "first_board": first_board,
            "link_board": link_board,
            "dt_count": dt_count,
            "zb_rate": round(zb_rate, 1),
            "zb_count": zb_count,
            "max_lb": max_lb,
            "max_lb_name": max_name or "—",
        },
        "earning": {
            "items": [
                {"k": "涨停家数", "v": f"{zt_count}家", "note": f"首板{first_board}｜连板{link_board}"},
                {"k": "炸板率", "v": f"{zb_rate:.1f}%", "note": f"炸板{zb_count}家"},
                {"k": "20cm涨停", "v": f"{cm20}家", "note": "创业板/科创弹性"},
                {"k": "强势池", "v": f"{len(qsgc)}家", "note": "用于观察次日反馈"},
                {"k": "最高连板", "v": f"{max_lb}板", "note": max_name or "—"},
            ],
            "stars": _stars(earn_score),
            "stars_text": _stars_text(_stars(earn_score)),
            "score": round(earn_score, 1),
            "comment": "有赚钱机会但需精选" if earn_score >= 60 else ("机会一般，谨慎试错" if earn_score >= 40 else "机会稀少，偏防守"),
        },
        "loss": {
            "items": [
                {"k": "跌停家数", "v": f"{dt_count}家", "note": "剔除ST口径见“风险”页"},
                {"k": "大面扩散", "v": f"{bf_count}只", "note": (bf_names[:26] + "…" if len(bf_names) > 26 else (bf_names or "无"))},
                {"k": "指数表现", "v": idx_brief, "note": idx_line},
            ],
            "stars": _stars(loss_score),
            "stars_text": _stars_text(_stars(loss_score)),
            "score": round(loss_score, 1),
            "comment": "分化加剧，有核按钮风险" if loss_score >= 60 else ("中等风险，控制仓位" if loss_score >= 40 else "风险可控"),
        },
    }

    return {"marketData.marketPanorama": out}


MARKET_PANORAMA_MODULE = Module(
    name="market_panorama",
    requires=[
        "features.mood_inputs",
        "marketData.indices",
        "marketData.ladder",
        "raw.pools.ztgc",
        "raw.pools.dtgc",
        "raw.pools.zbgc",
        "raw.pools.qsgc",
    ],
    provides=["marketData.marketPanorama"],
    compute=_compute,
)
