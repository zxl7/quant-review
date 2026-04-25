#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
divergence: PRD 3.2 分歧与承接（Divergence & Support Engine）

要求：口径可复算 + 尽量使用 raw.pools（封板时间、炸板次数）与资金流向接口（大单）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from daily_review.http import HttpClient


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


def _code_with_market(code6: str) -> str:
    if not code6:
        return ""
    return f"{code6}.SH" if code6.startswith("6") else f"{code6}.SZ"


def _time_to_min(s: Any) -> Optional[int]:
    # HHMMSS
    try:
        t = str(s or "").strip()
        if len(t) != 6 or not t.isdigit():
            return None
        hh = int(t[0:2])
        mm = int(t[2:4])
        ss = int(t[4:6])
        return hh * 60 + mm + (1 if ss >= 30 else 0)
    except Exception:
        return None


def _bucket_rates(ztgc: list[dict[str, Any]]) -> tuple[float, float, float]:
    # early: 9:30-10:00, mid: 10:00-13:00, late: 13:00-15:00 (按 fbt)
    if not ztgc:
        return 0.0, 0.0, 0.0
    a0 = 9 * 60 + 30
    a1 = 10 * 60
    b1 = 13 * 60
    c1 = 15 * 60
    e = m = l = 0
    tot = 0
    for it in ztgc:
        if not isinstance(it, dict):
            continue
        tot += 1
        t = _time_to_min(it.get("fbt"))
        if t is None:
            continue
        if a0 <= t <= a1:
            e += 1
        elif a1 < t <= b1:
            m += 1
        elif b1 < t <= c1:
            l += 1
    if tot <= 0:
        return 0.0, 0.0, 0.0
    return e / tot, m / tot, l / tot


def _open_rate(ztgc: list[dict[str, Any]], *, min_lb: int, max_lb: int | None) -> float:
    """
    “炸板率”在当前数据下无法精确按高度分层（zbgc 无 lbc）。
    这里使用 ztgc 中 zbc>0 作为“经历炸板仍最终封住”的可复算指标（openRateInSealed）。
    """
    arr = []
    for it in ztgc:
        if not isinstance(it, dict):
            continue
        lb = int(_to_num(it.get("lbc"), 0))
        if lb < min_lb:
            continue
        if max_lb is not None and lb > max_lb:
            continue
        arr.append(it)
    if not arr:
        return 0.0
    opened = [it for it in arr if int(_to_num(it.get("zbc"), 0)) > 0]
    return len(opened) / len(arr) if arr else 0.0


def _reseal_metrics(*, ztgc: list[dict[str, Any]], zbgc: list[dict[str, Any]]) -> tuple[float, float, float]:
    """
    炸板回封率：回封 = 在 ztgc 中 zbc>0（经历炸板且最终封住）
    未回封 = zbgc（炸板池：最终未封住）
    avgResealMinutes：使用 (lbt - fbt)（仅对经历炸板的 ztgc）作为“回封耗时 proxy”，可复算
    lateResealRatio：回封中，lbt >= 14:30 的比例
    """
    resealed = [it for it in ztgc if isinstance(it, dict) and int(_to_num(it.get("zbc"), 0)) > 0]
    unre = zbgc if isinstance(zbgc, list) else []
    denom = len(resealed) + len(unre)
    reseal_rate = (len(resealed) / denom) if denom else 0.0

    minutes = []
    late = 0
    for it in resealed:
        f = _time_to_min(it.get("fbt"))
        l = _time_to_min(it.get("lbt"))
        if f is not None and l is not None and l >= f:
            minutes.append(l - f)
        if l is not None and l >= (14 * 60 + 30):
            late += 1
    avg_min = (sum(minutes) / len(minutes)) if minutes else 0.0
    late_ratio = (late / len(resealed)) if resealed else 0.0
    return reseal_rate, avg_min, late_ratio


def _parse_percent_from_mood_cards(md: dict[str, Any], label: str) -> Optional[float]:
    for it in (md.get("moodCards") or []):
        if not isinstance(it, dict):
            continue
        if str(it.get("label") or "") != label:
            continue
        v = str(it.get("value") or "").replace("%", "").strip()
        try:
            return float(v) / 100.0
        except Exception:
            return None
    return None


def _net_big_order_flow_yi(client: HttpClient, *, date8: str, code6: str) -> Optional[float]:
    """
    使用资金流向接口：hsstock/history/transaction/{code}.{SZ|SH}
    返回：特大单+大单 的 主买 - 主卖（单位：亿）
    """
    code = _code_with_market(code6)
    if not code:
        return None
    url = f"{client.base_url}/hsstock/history/transaction/{code}/{client.token}?st={date8}&et={date8}&lt=1"
    data = client.get_json(url)
    if not isinstance(data, list) or not data:
        return None
    it = data[-1] if isinstance(data[-1], dict) else {}
    buy = _to_num(it.get("zmbtdcje"), 0) + _to_num(it.get("zmbddcje"), 0)
    sell = _to_num(it.get("zmstdcje"), 0) + _to_num(it.get("zmsddcje"), 0)
    return round((buy - sell) / 1e8, 2)  # 元 -> 亿


def build_divergence_engine(market_data: dict[str, Any], *, date: str, client: Optional[HttpClient] = None) -> dict[str, Any]:
    md = market_data or {}
    pools = ((md.get("raw") or {}).get("pools") or {}) if isinstance(md.get("raw"), dict) else {}
    ztgc = pools.get("ztgc") or []
    zbgc = pools.get("zbgc") or []

    # timeDim
    early, mid, late = _bucket_rates(ztgc if isinstance(ztgc, list) else [])
    if early >= 0.35:
        time_judge = "early_dominant"
    elif late >= 0.45:
        time_judge = "late_dominant"
    else:
        time_judge = "balanced"

    # spaceDim（严格可复算 proxy）
    high = _open_rate(ztgc, min_lb=5, max_lb=None)
    midr = _open_rate(ztgc, min_lb=2, max_lb=4)
    low = _open_rate(ztgc, min_lb=1, max_lb=1)
    if high <= 0.2:
        space_judge = "safe_at_high"
    elif high >= 0.4:
        space_judge = "danger_at_high"
    else:
        space_judge = "mixed"

    # support quality
    pr_2_3 = _parse_percent_from_mood_cards(md, "2进3成功率")
    pr_3_4 = _parse_percent_from_mood_cards(md, "3进4成功率")
    reseal_rate, avg_min, late_reseal = _reseal_metrics(ztgc=ztgc if isinstance(ztgc, list) else [], zbgc=zbgc if isinstance(zbgc, list) else [])

    # fundDim（必须精确：使用资金流向接口；样本口径：三池+强势池成交额TopN）
    fund_dim = {"netBigOrderFlow": None, "judgment": "unknown", "meta": {"precision": "missing"}}
    if client is not None:
        date8 = date.replace("-", "")
        pools_today = []
        for pn in ("ztgc", "dtgc", "zbgc", "qsgc"):
            arr = pools.get(pn) or []
            if isinstance(arr, list):
                pools_today.extend([x for x in arr if isinstance(x, dict)])
        # 取成交额Top10（可复算，且有 code）
        pools_today.sort(key=lambda x: _to_num(x.get("cje"), 0), reverse=True)
        top_codes = []
        seen = set()
        for it in pools_today:
            c6 = _norm_code6(str(it.get("dm") or ""))
            if not c6 or c6 in seen:
                continue
            seen.add(c6)
            top_codes.append(c6)
            if len(top_codes) >= 10:
                break
        flows = []
        for c6 in top_codes:
            v = _net_big_order_flow_yi(client, date8=date8, code6=c6)
            if v is None:
                continue
            flows.append(v)
        net = round(sum(flows), 2) if flows else None
        if net is not None:
            judge = "money_in" if net >= 0 else "money_out"
            fund_dim = {
                "netBigOrderFlow": net,
                "judgment": judge,
                "meta": {"precision": "strict_sample_top10_pools_cje", "sampleSize": len(flows)},
            }

    # overallScore：0~100（越高=分歧越强）
    # 规则：晚封越高越分歧；高位经历炸板越多越分歧；大单净流出越多越分歧；回封率越低越分歧
    net_flow = fund_dim.get("netBigOrderFlow")
    flow_penalty = 0.0
    if isinstance(net_flow, (int, float)):
        flow_penalty = min(25.0, max(0.0, -float(net_flow) * 1.8))  # -12亿 ≈ 21.6
    score = (
        20.0
        + late * 45.0
        + high * 25.0
        + (1.0 - reseal_rate) * 25.0
        + flow_penalty
    )
    score = int(round(_clamp(score, 0, 100)))

    # verdict（PRD 决策树）
    if early > 0.35 and high < 0.2 and reseal_rate > 0.55:
        verdict = "healthy_divergence"
    elif late > 0.45 or high > 0.4 or reseal_rate < 0.35:
        verdict = "dangerous_divergence"
    else:
        verdict = "neutral_divergence"

    return {
        "overallScore": score,
        "verdict": verdict,
        "timeDim": {"earlySealRate": round(early, 4), "midSealRate": round(mid, 4), "lateSealRate": round(late, 4), "judgment": time_judge},
        "spaceDim": {
            "highBoardExplodeRate": round(high, 4),
            "midBoardExplodeRate": round(midr, 4),
            "lowBoardExplodeRate": round(low, 4),
            "judgment": space_judge,
            "meta": {"precision": "strict_proxy_openRateInSealed", "note": "zbgc 无 lbc，无法按高度分层未回封炸板率；此处用 ztgc(zbc>0) 作为可复算 proxy。"},
        },
        "fundDim": fund_dim,
        "supportQuality": {
            "promotionRate": {
                "overallJjRate": round(_to_num(((md.get('features') or {}).get('mood_inputs') or {}).get('jj_rate_adj', ((md.get('features') or {}).get('mood_inputs') or {}).get('jj_rate')), 0) / 100.0, 4),
                "2to3": pr_2_3,
                "3to4": pr_3_4,
            },
            "resealRate": round(reseal_rate, 4),
            "avgResealMinutes": round(avg_min, 1),
            "lateResealRatio": round(late_reseal, 4),
        },
        "meta": {"precision": "strict_with_sample_fund", "asOf": date},
    }

