#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模块⑦（v2 规格书）：右侧交易确认框架（落地版 / 可降级）

规格书核心：
- 回答“什么时候买”：入场确认信号 + 止损铁律
- 输出：can_enter, signal_strength, signals, msg

落地说明：
你当前数据源并不保证“指数/板块/个股”所有细粒度字段齐全，
因此这里用现有 market_data 特征做 proxy，并保证：
- 有数据 → 更准确
- 无数据 → 不报错 + 降级为“谨慎/等待确认”
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.utils.num import to_float as _to_float


def _score01(cond: bool) -> int:
    return 10 if cond else 0


def build_rightside_confirmation(market_data: Dict[str, Any]) -> Dict[str, Any]:
    md = market_data or {}
    mi = (md.get("features") or {}).get("mood_inputs") or {}
    v2s = (md.get("v2") or {}).get("sentiment") if isinstance(md.get("v2"), dict) else None
    v2s = v2s if isinstance(v2s, dict) else {}
    sector_pack = (md.get("v2") or {}).get("sector") if isinstance(md.get("v2"), dict) else {}
    sector_pack = sector_pack if isinstance(sector_pack, dict) else {}
    mainline = sector_pack.get("mainline") if isinstance(sector_pack.get("mainline"), dict) else {}

    score = _to_float(v2s.get("score"), 5.0)  # 0~10
    phase = str(v2s.get("phase") or "")
    risk_level = str(v2s.get("risk_level") or "中")

    # 指数/量能 proxy：量能不缩 + 情绪不在冰点
    vol = md.get("volume") or {}
    vol_chg = _to_float(vol.get("change"), 0.0)  # -1.98%
    idx_ok = (vol_chg >= -2.0) and (score >= 4.0) and ("冰点" not in phase)

    # 板块共振：优先用 v2 主线判断（模块④）
    overlap = (md.get("themePanels") or {}).get("overlap") or {}
    ov = _to_float(overlap.get("score"), 0.0)
    top3 = _to_float((md.get("styleRadar") or {}).get("top3ThemeRatio"), _to_float(mi.get("top3_theme_ratio"), 0))
    sector_ok = bool(mainline.get("exists")) if isinstance(mainline, dict) and mainline else (top3 >= 55 and top3 <= 95 and ov < 75)

    # 个股共振 proxy：晋级/封板维持 + 高位没有崩（断板/跌停不极端）
    jj = _to_float(mi.get("jj_rate"), 0.0)
    fb = _to_float(mi.get("fb_rate"), 0.0)
    dt = int(_to_float(mi.get("dt_count"), 0))
    broken = _to_float(mi.get("broken_lb_rate"), 0.0)
    stock_ok = (jj >= 25 and fb >= 60) and (dt < 30) and (broken < 70)

    signals = [
        {
            "key": "index_resonance",
            "name": "指数共振",
            "passed": bool(idx_ok),
            "score": _score01(idx_ok),
            "detail": f"量能{vol.get('change','-')}，情绪{score:.1f}/{phase}",
        },
        {
            "key": "sector_resonance",
            "name": "板块共振",
            "passed": bool(sector_ok),
            "score": _score01(sector_ok),
            "detail": f"{('主线：'+str(mainline.get('top_sector'))+'·'+str(mainline.get('strength'))) if isinstance(mainline, dict) and mainline.get('top_sector') else ('主线集中'+str(int(top3))+'% · 重叠'+str(int(ov))+'%')}",
        },
        {
            "key": "stock_resonance",
            "name": "个股共振",
            "passed": bool(stock_ok),
            "score": _score01(stock_ok),
            "detail": f"封{fb:.0f}% · 晋{jj:.0f}% · 跌停{dt} · 断板{broken:.0f}%",
        },
    ]

    passed = sum(1 for s in signals if s["passed"])
    strength = round((passed / 3) * 10, 1)  # 0~10

    # 入场规则：至少 2/3 共振 + 风险非高位冰点
    can_enter = bool(passed >= 2 and risk_level != "高" and score >= 4.0)
    msg = "✅ 符合右侧交易入场条件" if can_enter else "❌ 不符合右侧交易条件，禁止入场（等待共振确认）"

    advice = ""
    if can_enter:
        advice = "多重信号共振：优先做主线核心的确认点（回封/分歧转一致），仓位按赢面模型执行。"
    else:
        if risk_level == "高" or score < 4:
            advice = "风险偏高/情绪偏弱：以防守为主，最多小仓保持盘感。"
        else:
            advice = "共振不足：等待指数/板块/个股出现至少两项确认后再出手。"

    return {
        "can_enter": can_enter,
        "signal_strength": strength,
        "passed_count": passed,
        "signals": signals,
        "msg": msg,
        "advice": advice,
    }
