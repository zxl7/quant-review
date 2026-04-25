#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
sector_heatmap: PRD 3.7 多板块情绪热力图（按题材聚合）

约束：
- 数据以现有 marketData 为准（themePanels / leaders / mood）
- 输出字段为 marketData.sectorHeatmap（可由前端直接渲染）
- 评分逻辑保证"可复算"：只使用输入字段做确定性计算
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


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


def _level(score: float) -> str:
    if score >= 80:
        return "hot"
    if score >= 60:
        return "warm"
    if score >= 40:
        return "cool"
    return "cold"


def _icon(lv: str) -> str:
    return {"hot": "🔥🔥🔥", "warm": "🔥🔥☆", "cool": "☆☆☆", "cold": "🧊"}.get(lv, "☆☆☆")


def _advice(lv: str) -> str:
    return {
        "hot": "强势，可做龙头",
        "warm": "可做但不追高",
        "cool": "偏弱，低位试错",
        "cold": "回避，等修复",
    }.get(lv, "观望")


# ===== 关注方向配置 =====
# 用户可修改此列表，匹配到的板块会自动置顶并标记
FOCUS_SECTORS = [
    "光通信", "CPO", "光模块",
    "航天", "军工", "卫星", "商业航天",
    "新材料", "碳纤维",
    "锂电池", "储能", "固态电池",
    "华为", "鸿蒙", "昇腾",
    "AI", "人工智能", "算力",
]


def _is_focus(name: str) -> bool:
    """判断板块名是否在关注方向内（模糊匹配）"""
    n = str(name or "").strip()
    if not n:
        return False
    for f in FOCUS_SECTORS:
        if f in n or n in f:
            return True
    return False


def _pick_leader(leaders: list[dict[str, Any]], theme: str) -> Optional[dict[str, Any]]:
    for it in leaders or []:
        if not isinstance(it, dict):
            continue
        if str(it.get("theme") or "") == theme:
            return it
        if str(((it.get("reason") or {}).get("explosion") or {}).get("theme") or "") == theme:
            return it
    return None


def build_sector_heatmap(market_data: dict[str, Any]) -> dict[str, Any]:
    """
    从现有字段派生"板块情绪热力图"。

输入依赖（尽可能只用现有口径）：
- themePanels.strengthRows: [{name, zt, zb, dt, net, risk, netClass, riskClass}]
- leaders: [{name, code, theme, tags}]
- mood: {score, heat}

输出：
{
  globalScore: int,
  hint: str,
  alpha: str,
  rows: [{name, score, level, icon, zt, zb, dt, net, risk, netClass, riskClass, sub, leader, tags, advice}]
}
    """

    md = market_data or {}
    tp = md.get("themePanels") or {}
    rows_in = tp.get("strengthRows") or []
    if not isinstance(rows_in, list):
        rows_in = []

    # fallback：仅用 sectors（只有涨停count 等）
    if not rows_in:
        sectors = md.get("sectors") or []
        if isinstance(sectors, list):
            for s in sectors:
                if not isinstance(s, dict):
                    continue
                rows_in.append(
                    {
                        "name": s.get("name"),
                        "zt": s.get("count", 0),
                        "zb": 0,
                        "dt": 0,
                        "net": s.get("net", 0),
                        "risk": s.get("risk", 0),
                        "netClass": "red-text" if _to_num(s.get("net"), 0) >= 0 else "green-text",
                        "riskClass": "red-text" if _to_num(s.get("risk"), 0) >= 0 else "green-text",
                    }
                )

    leaders = md.get("leaders") or []
    leaders = leaders if isinstance(leaders, list) else []

    mood = md.get("mood") or {}
    global_score = int(round(_to_num(mood.get("score"), _to_num(mood.get("heat"), 50.0))))
    global_score = int(_clamp(global_score))

    def score_row(r: dict[str, Any]) -> int:
        zt = _to_num(r.get("zt"), 0)
        zb = _to_num(r.get("zb"), 0)
        dt = _to_num(r.get("dt"), 0)
        net = _to_num(r.get("net"), 0)
        risk = _to_num(r.get("risk"), 0)
        # 说明：strengthRows 的 net/risk 已是 pipeline 算出的衍生指标
        # 这里做"可复算的二次映射"，目的是统一到 0~100 的热度分。
        s = 50 + zt * 1.8 - zb * 1.2 - dt * 2.2 + net * 0.8 - risk * 0.6
        return int(round(_clamp(s)))

    rows_out: List[Dict[str, Any]] = []
    for r in rows_in[:]:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or "").strip()
        if not name:
            continue
        s = score_row(r)
        lv = _level(s)
        ld = _pick_leader(leaders, name)
        sub = (
            f"龙头：{ld.get('name')}｜{' / '.join(ld.get('tags') or [])}"
            if isinstance(ld, dict) and (ld.get("tags") or [])
            else f"涨停 {int(_to_num(r.get('zt'),0))} · 炸板 {int(_to_num(r.get('zb'),0))} · 跌停 {int(_to_num(r.get('dt'),0))}"
        )
    rows_out.append(
        {
            "name": name,
            "score": s,
            "level": lv,
            "icon": _icon(lv),
            "zt": int(_to_num(r.get("zt"), 0)),
            "zb": int(_to_num(r.get("zb"), 0)),
            "dt": int(_to_num(r.get("dt"), 0)),
            "net": f"{_to_num(r.get('net'),0):.1f}亿" if r.get("net") is not None else "-",
            "risk": f"{_to_num(r.get('risk'),0):.1f}%" if r.get("risk") is not None else "-",
            "netClass": r.get("netClass") or ("red-text" if _to_num(r.get("net"), 0) >= 0 else "green-text"),
            "riskClass": r.get("riskClass") or ("red-text" if _to_num(r.get("risk"), 0) >= 0 else "green-text"),
            "sub": sub,
            "leader": f"{ld.get('name')}（{ld.get('code')}）" if isinstance(ld, dict) and ld.get("name") else "",
            "tags": " / ".join(ld.get("tags") or []) if isinstance(ld, dict) else "—",
            "advice": _advice(lv),
            "isFocus": _is_focus(name),
        }
    )

    # 排序：关注方向优先 → 其余按分数排
    rows_out.sort(key=lambda x: (not x.get("isFocus", False), -int(x.get("score") or 0)))
    rows_out = rows_out[:12]  # 稍微放宽到12条（给关注方向留空间）

    # 关注方向统计
    focus_rows = [r for r in rows_out if r.get("isFocus")]
    other_rows = [r for r in rows_out if not r.get("isFocus")]

    top = rows_out[0] if rows_out else None
    # 关注方向摘要
    focus_top = focus_rows[0] if focus_rows else None
    focus_summary = ""
    if focus_rows:
        names = "、".join([r["name"] for r in focus_rows[:3]])
        best_focus_score = focus_rows[0].get("score", 0)
        focus_summary = f"关注方向({len(focus_rows)}个)：{names}，最强{best_focus_score}分"
    else:
        focus_summary = "关注方向今日无涨停"

    alpha = ""
    if top:
        if global_score < 50 and int(top.get("score") or 0) >= 75:
            alpha = f"整体偏冷（{global_score}），但「{top.get('name')}」偏热（{top.get('score')}）→ 可围绕该方向找机会"
        elif global_score >= 60 and int(top.get("score") or 0) < 60:
            alpha = f"整体不弱（{global_score}），但题材分散 → 注意轮动风险"

    hint = focus_summary + (" | " + alpha if alpha else "") or "按题材强弱排序，优先看高分板块的龙头与扩散"
    return {
        "globalScore": global_score,
        "rows": rows_out,
        "focusCount": len(focus_rows),
        "focusTopName": focus_top["name"] if focus_top else "",
        "focusTopScore": int(focus_top["score"]) if focus_top else 0,
        "alpha": alpha,
        "hint": hint,
        "meta": {
            "precision": "strict_derived",
            "asOf": str((market_data or {}).get("meta", {}).get("tradeDate") or ""),
            "notes": [
                f"热力图按「关注方向优先→分数排序」，FOCUS_SECTORS={FOCUS_SECTORS}",
                "龙头来自 leaders（若当日缺失则不展示）。",
                f"今日命中{len(focus_rows)}个关注方向板块",
            ],
        },
    }
