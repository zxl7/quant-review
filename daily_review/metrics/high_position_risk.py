#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
high_position_risk: PRD 3.5 高位风险预警（High-Position Risk Alert）

目标：
- 口径可复算：以 raw.pools（ztgc/zbgc/dtgc）+ raw.themes（code6->themes）为主
- 当天高度未达到触发阈值（默认 >=4板）时，仍输出结构化结果，但标记 triggered=false
"""

from __future__ import annotations

from typing import Any, Optional

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
    "央企改革",
    "国资改革",
    "中字头",
    "年度强势",
    "历史新高",
}


def _pick_primary_theme(code6: str, theme_map: dict[str, list[str]]) -> str:
    arr = theme_map.get(code6) or []
    for t in arr:
        t = str(t or "").strip()
        if not t or t in _THEME_BLACKLIST:
            continue
        return t
    return (arr[0] if arr else "其他")


def _net_big_order_flow_yi(client: HttpClient, *, date8: str, code6: str) -> Optional[float]:
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


def build_high_position_risk(
    market_data: dict[str, Any],
    *,
    date: str,
    client: Optional[HttpClient] = None,
    trigger_lb: int = 4,
) -> dict[str, Any]:
    md = market_data or {}
    pools = ((md.get("raw") or {}).get("pools") or {}) if isinstance(md.get("raw"), dict) else {}
    ztgc = pools.get("ztgc") or []
    zbgc = pools.get("zbgc") or []
    dtgc = pools.get("dtgc") or []

    raw_themes = (md.get("raw") or {}).get("themes") or {}
    theme_map = raw_themes if isinstance(raw_themes, dict) else {}

    # 最高板
    max_lb = 0
    if isinstance(ztgc, list) and ztgc:
        max_lb = max(int(_to_num(x.get("lbc"), 0)) for x in ztgc if isinstance(x, dict))

    triggered = max_lb >= trigger_lb
    if not triggered:
        return {
            "triggered": False,
            "maxHeight": max_lb,
            "triggerHeight": trigger_lb,
            "score": 0,
            "level": "off",
            "signals": [{"k": "高度", "v": f"最高 {max_lb} 板，未触发高位预警"}],
            "alerts": [],
            "meta": {"precision": "strict", "asOf": date, "note": "未达到触发高度阈值，模块不展示或仅提示未触发。"},
        }

    # 高位集合：>= trigger_lb
    highs = [it for it in ztgc if isinstance(ztgc, list) and isinstance(it, dict) and int(_to_num(it.get("lbc"), 0)) >= trigger_lb]
    # 高位开板压力：高位中 zbc>0 的占比
    high_open = len([it for it in highs if int(_to_num(it.get("zbc"), 0)) > 0]) / len(highs) if highs else 0.0
    # 高位平均炸板次数（仅对最终封住的高位）
    avg_zbc = sum(_to_num(it.get("zbc"), 0) for it in highs) / len(highs) if highs else 0.0
    # 市场系统分歧：炸板池/(涨停池+炸板池)
    zbgc_ratio = (len(zbgc) / (len(zbgc) + len(ztgc))) if (isinstance(zbgc, list) and isinstance(ztgc, list) and (len(zbgc) + len(ztgc)) > 0) else 0.0
    # 亏钱压强：跌停数量
    dt_cnt = len(dtgc) if isinstance(dtgc, list) else 0

    # 高位题材集中度（在高位集合中统计 primary theme）
    theme_count: dict[str, int] = {}
    for it in highs:
        c6 = _norm_code6(str(it.get("dm") or ""))
        th = _pick_primary_theme(c6, theme_map)
        theme_count[th] = theme_count.get(th, 0) + 1
    top_theme = max(theme_count.items(), key=lambda x: x[1])[0] if theme_count else "—"
    top_theme_ratio = (max(theme_count.values()) / len(highs)) if (highs and theme_count) else 0.0

    # 高位资金（精确）：取高位集合成交额 Top3 的大单净流之和（亿）
    high_flow = None
    flow_meta = {"precision": "missing"}
    if client is not None and highs:
        date8 = date.replace("-", "")
        highs_sorted = sorted(highs, key=lambda x: _to_num(x.get("cje"), 0), reverse=True)
        codes = []
        seen = set()
        for it in highs_sorted:
            c6 = _norm_code6(str(it.get("dm") or ""))
            if not c6 or c6 in seen:
                continue
            seen.add(c6)
            codes.append(c6)
            if len(codes) >= 3:
                break
        vals = []
        for c6 in codes:
            v = _net_big_order_flow_yi(client, date8=date8, code6=c6)
            if v is not None:
                vals.append(v)
        if vals:
            high_flow = round(sum(vals), 2)
            flow_meta = {"precision": "strict_sample_top3_high_cje", "sampleSize": len(vals), "codes": codes}

    # score（越高越危险）
    # 经验组合：高位开板压力 + 平均炸板次数 + 系统分歧 + 跌停压强 + 高位集中度 + 高位资金流出
    flow_penalty = 0.0
    if isinstance(high_flow, (int, float)) and high_flow < 0:
        flow_penalty = min(20.0, -high_flow * 1.5)
    score = (
        15.0
        + high_open * 35.0
        + _clamp(avg_zbc / 3.0, 0, 1) * 15.0
        + zbgc_ratio * 20.0
        + _clamp(dt_cnt / 30.0, 0, 1) * 10.0
        + top_theme_ratio * 10.0
        + flow_penalty
    )
    score = int(round(_clamp(score, 0, 100)))
    if score >= 70:
        level = "danger"
    elif score >= 45:
        level = "warning"
    else:
        level = "watch"

    signals = [
        {"k": "高度", "v": f"最高 {max_lb} 板（高位>= {trigger_lb} 板：{len(highs)} 只）"},
        {"k": "高位开板压力", "v": f"{high_open*100:.1f}%"},
        {"k": "高位题材集中", "v": f"{top_theme} · {top_theme_ratio*100:.0f}%"},
        {"k": "系统分歧（炸板比）", "v": f"{zbgc_ratio*100:.1f}%"},
        {"k": "跌停压强", "v": f"{dt_cnt} 只"},
    ]
    if high_flow is not None:
        signals.append({"k": "高位大单净流", "v": f"{high_flow:+.2f} 亿"})

    alerts = []
    if high_open >= 0.35:
        alerts.append({"type": "high_open", "severity": "danger", "msg": "高位频繁开板：谨慎接力，优先等分歧转一致的回封确认。"})
    if top_theme_ratio >= 0.6:
        alerts.append({"type": "crowded", "severity": "warning", "msg": "高位过度集中：一旦分歧，容易形成瀑布式退潮。"})
    if isinstance(high_flow, (int, float)) and high_flow < -5:
        alerts.append({"type": "flow_out", "severity": "danger", "msg": "高位资金流出明显：避免中高位硬接力。"})

    return {
        "triggered": True,
        "maxHeight": max_lb,
        "triggerHeight": trigger_lb,
        "score": score,
        "level": level,
        "topTheme": top_theme,
        "signals": signals,
        "alerts": alerts,
        "fund": {"highNetBigOrderFlowYi": high_flow, "meta": flow_meta},
        "meta": {"precision": "strict_with_sample_fund", "asOf": date},
    }

