#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
structure_v2: PRD 3.4/3.5/3.6 的“结构拆解 v2”（产品化降噪版）

输出目标：
- 首屏仅给 3 张“结论卡”：结构 / 高度 / 穿透
- 其余细节作为 evidence（证据链）供前端折叠展示

约束：
- 全部可复算：只用 marketData 现有字段（raw.pools/themePanels/features/riskEngine）
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


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


def _norm_code6(code: str) -> str:
    digits = "".join([c for c in str(code or "") if c.isdigit()])
    return digits[-6:] if len(digits) >= 6 else digits


def _status(score: float) -> str:
    if score >= 70:
        return "good"
    if score >= 45:
        return "warn"
    return "bad"


def build_structure_v2(market_data: dict[str, Any], *, date: str) -> dict[str, Any]:
    md = market_data or {}
    pools = ((md.get("raw") or {}).get("pools") or {}) if isinstance(md.get("raw"), dict) else {}
    ztgc = pools.get("ztgc") or []
    zbgc = pools.get("zbgc") or []
    dtgc = pools.get("dtgc") or []
    qsgc = pools.get("qsgc") or []
    yest_ztgc = pools.get("yest_ztgc") or []

    # ===== ladder stats from ztgc.lbc（精确复算）
    lb_counts: dict[int, int] = {}
    max_lb = 0
    for it in ztgc if isinstance(ztgc, list) else []:
        if not isinstance(it, dict):
            continue
        lb = int(_to_num(it.get("lbc"), 0))
        if lb <= 0:
            continue
        lb_counts[lb] = lb_counts.get(lb, 0) + 1
        max_lb = max(max_lb, lb)

    # gaps: 1..max_lb 中缺失的档位
    gaps = [k for k in range(2, max(2, max_lb + 1)) if lb_counts.get(k, 0) == 0]
    integrity = 100.0
    if max_lb <= 1:
        integrity = 35.0
    else:
        integrity = 85.0 - len(gaps) * 18.0 - max(0, 2 - lb_counts.get(2, 0)) * 8.0
        if max_lb >= 3 and lb_counts.get(3, 0) == 0:
            integrity -= 12.0
    integrity = max(0.0, min(100.0, integrity))

    # ===== height trend vs yest (from yest_ztgc)
    y_max = 0
    for it in yest_ztgc if isinstance(yest_ztgc, list) else []:
        if not isinstance(it, dict):
            continue
        y_max = max(y_max, int(_to_num(it.get("lbc"), 0)))
    height_delta = max_lb - y_max

    # ===== penetration: dt in yest_zt ratio (can reuse riskEngine if present)
    risk_engine = md.get("riskEngine") or {}
    dt_in_zt_ratio = _to_num((risk_engine.get("penetration") or {}).get("dtInZbRatio"), None)
    if dt_in_zt_ratio is None:
        # fallback recompute
        yest_zt = {_norm_code6(str(it.get("dm") or "")) for it in yest_ztgc if isinstance(it, dict)}
        dt_set = {_norm_code6(str(it.get("dm") or "")) for it in dtgc if isinstance(it, dict)}
        hit = len([c for c in dt_set if c and c in yest_zt])
        dt_in_zt_ratio = (hit / len(dt_set)) if dt_set else 0.0

    # ===== simple market pressures
    dt_cnt = len(dtgc) if isinstance(dtgc, list) else 0
    zb_cnt = len(zbgc) if isinstance(zbgc, list) else 0
    zt_cnt = len(ztgc) if isinstance(ztgc, list) else 0

    # qsgc negative sample (not full market, but repeatable)
    neg_cnt = 0
    if isinstance(qsgc, list):
        for it in qsgc:
            if not isinstance(it, dict):
                continue
            if _to_num(it.get("zf"), 0) <= -5:
                neg_cnt += 1

    # theme overlap (existing)
    overlap = (md.get("themePanels") or {}).get("overlap") or {}

    # ===== build 3 conclusion cards
    # 1) structure card
    st_score = integrity
    st_status = _status(st_score)
    if max_lb <= 1:
        st_note = "结构偏低位：高度尚未打开，适合小仓试错。"
        st_action = "只做首板/低位确认"
    elif gaps:
        st_note = f"结构有断层：{('、'.join(str(x)+'板' for x in gaps[:3]))}缺位，接力不顺。"
        st_action = "优先做回封/分歧转一致"
    else:
        st_note = "结构相对完整：梯队承接更顺，利于主线延续。"
        st_action = "围绕主线核心做确认点"

    # 2) height card
    # height score: higher is not always better; but here treat "是否打开空间"
    height_score = 30.0 + min(70.0, max_lb * 18.0)
    if max_lb >= 5:
        height_note = "高度较高：容易出现分化/兑现，重点看高位开板与资金。"
        height_action = "高位不追，等换手回封"
    elif max_lb >= 3:
        height_note = "高度已打开：具备主线延续的基础，关注承接质量。"
        height_action = "做 2→3 / 3→4 的确定性"
    else:
        height_note = "高度不高：情绪难走主升，更像轮动/震荡。"
        height_action = "轻仓快进快出"
    height_status = _status(height_score)

    # 3) penetration card
    pen_score = 100.0 - min(100.0, dt_in_zt_ratio * 140.0) - min(30.0, dt_cnt * 1.0)
    pen_score = max(0.0, min(100.0, pen_score))
    pen_status = _status(pen_score)
    if dt_in_zt_ratio >= 0.35:
        pen_note = "穿透偏高：主线出现“回撤深”，次日更看风控。"
        pen_action = "优先保命，避免硬接力"
    elif dt_in_zt_ratio >= 0.20:
        pen_note = "穿透中等：注意主线分歧，选择性参与。"
        pen_action = "只做最强/回封确认"
    else:
        pen_note = "穿透较低：主线回撤浅，修复空间更大。"
        pen_action = "可围绕核心做弱转强"

    summary = [
        {
            "key": "structure",
            "title": "结构",
            "value": f"{int(round(st_score))}分",
            "status": st_status,
            "note": st_note,
            "action": st_action,
        },
        {
            "key": "height",
            "title": "高度",
            "value": f"{max_lb}板",
            "status": height_status,
            "note": height_note + (f"（较昨{height_delta:+d}）" if height_delta != 0 else ""),
            "action": height_action,
        },
        {
            "key": "penetration",
            "title": "穿透",
            "value": f"{dt_in_zt_ratio*100:.1f}%",
            "status": pen_status,
            "note": pen_note,
            "action": pen_action,
        },
    ]

    evidence = {
        "counts": {"zt": zt_cnt, "zb": zb_cnt, "dt": dt_cnt, "negSample": neg_cnt},
        "ladder": {
            "maxHeight": max_lb,
            "countsByHeight": {str(k): lb_counts.get(k, 0) for k in sorted(lb_counts.keys())},
            "gaps": gaps,
        },
        "penetration": {
            "dtInYestZtRatio": round(float(dt_in_zt_ratio), 4),
            "dtCount": dt_cnt,
        },
        "overlap": overlap,
    }

    return {
        "summary": summary,
        "evidence": evidence,
        "meta": {"precision": "strict", "asOf": date},
    }

