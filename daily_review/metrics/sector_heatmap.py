#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
sector_heatmap: PRD 3.7 多板块情绪热力图（按题材聚合）

约束：
- 数据以现有 marketData 为准（themePanels / leaders / mood）
- 输出字段为 marketData.sectorHeatmap（可由前端直接渲染）
- 评分逻辑保证“可复算”：只使用输入字段做确定性计算
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
        "hot": "强势题材，可做龙头与强分支",
        "warm": "可做但控制追高",
        "cool": "偏防守，低位试错",
        "cold": "回避，等待修复",
    }.get(lv, "观望")


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
    从现有字段派生“板块情绪热力图”。

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
        # 这里做“可复算的二次映射”，目的是统一到 0~100 的热度分。
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
            }
        )

    rows_out.sort(key=lambda x: int(x.get("score") or 0), reverse=True)
    rows_out = rows_out[:10]

    top = rows_out[0] if rows_out else None
    alpha = ""
    if top:
        if global_score < 50 and int(top.get("score") or 0) >= 75:
            alpha = f"全局偏冷（{global_score}），但「{top.get('name')}」偏热（{top.get('score')}）→ 可结构性做多该题材，其余方向防守。"
        elif global_score >= 60 and int(top.get("score") or 0) < 60:
            alpha = f"全局不弱（{global_score}），但题材扩散一般 → 注意“无主线”的轮动风险。"

    hint = alpha or "按题材聚合强弱：优先看高分题材的龙头与扩散，其次看跌停/炸板是否向主线穿透。"
    return {
        "globalScore": global_score,
        "rows": rows_out,
        "alpha": alpha,
        "hint": hint,
        "meta": {
            "precision": "strict_derived",
            "asOf": str((market_data or {}).get("meta", {}).get("tradeDate") or ""),
            "notes": [
                "题材热力图基于 themePanels.strengthRows（涨停/炸板/跌停 + 净强度/风险）二次映射到 0~100 分；可复算。",
                "龙头来自 leaders（若当日缺失则不展示龙头）。",
            ],
        },
    }
