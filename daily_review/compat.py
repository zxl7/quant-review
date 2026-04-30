#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
compat：统一输出层（v1/v2/v3 → 单一口径）

目标：
- 前端/模板只依赖 marketData.compat.*，避免到处写 v1/v2/v3 判断
- 算法可以逐步迁移：v3 做唯一真源；v2/v1 仅做兼容映射
"""

from __future__ import annotations

from typing import Any, Dict, Literal


Algo = Literal["auto", "v1", "v2", "v3"]


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        if isinstance(v, str) and v.endswith("%"):
            v = v[:-1]
        return float(v)
    except Exception:
        return default


def _get(d: Dict[str, Any], path: str) -> Any:
    cur: Any = d
    for p in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _pick_algo(market_data: Dict[str, Any], prefer: Algo) -> str:
    if prefer in ("v1", "v2", "v3"):
        return prefer
    # auto：优先 v3 -> v2 -> v1
    if isinstance(market_data.get("v3"), dict) and market_data["v3"]:
        return "v3"
    if isinstance(market_data.get("v2"), dict) and market_data["v2"]:
        return "v2"
    return "v1"


def _map_v3(md: Dict[str, Any]) -> Dict[str, Any]:
    v3 = md.get("v3") if isinstance(md.get("v3"), dict) else {}
    out: Dict[str, Any] = {"algo": "v3"}

    # v3 没有显式 risk_level：用崩溃链等级/情绪分做一个可解释的 proxy
    cc_level = str(_get(v3, "collapseChain.level") or "")
    s_score = _to_float(_get(v3, "sentiment.score"), 5.0)
    if "CRITICAL" in cc_level or "HIGH" in cc_level:
        risk_level = "高"
    elif s_score >= 8:
        risk_level = "中"
    elif s_score >= 5:
        risk_level = "中低"
    else:
        risk_level = "低"

    out["sentiment"] = {
        "score": _get(v3, "sentiment.score"),
        "phase": _get(v3, "sentiment.phase"),
        "warnings": _get(v3, "sentiment.warnings") or [],
        "risk_level": risk_level,
        "confidence": _get(v3, "sentiment.confidence"),
    }
    out["mainline"] = {
        "exists": _get(v3, "mainstream.mainline.exists"),
        "top_sector": _get(v3, "mainstream.mainline.top_sector"),
        "level": _get(v3, "mainstream.mainline.level"),
        "strength": _get(v3, "mainstream.mainline.strength"),
    }
    out["rightside"] = {
        "allowed": _get(v3, "rightside.allowed"),
        "score": _get(v3, "rightside.score"),
        "advice": _get(v3, "rightside.advice"),
        "confidence": _get(v3, "rightside.confidence"),
    }
    out["position"] = {
        "capital_pct": _get(v3, "positionV3.capital_pct_adjusted"),
        "win_rate": _get(v3, "positionV3.win_rate"),
        "tier": _get(v3, "positionV3.tier"),
        "confidence": _get(v3, "positionV3.confidence"),
    }
    out["full_position"] = {
        "passed_count": _get(v3, "fullPosition.passed_count"),
        "max_recommended_position": _get(v3, "fullPosition.max_recommended_position"),
        "confidence": _get(v3, "fullPosition.confidence"),
    }
    out["rebound"] = {
        "phase": _get(v3, "rebound.phase.label") or _get(v3, "rebound.phase"),
        "confidence": _get(v3, "rebound.confidence"),
    }
    out["trading_nature"] = {
        "label": _get(v3, "tradingNature.nature.label"),
        "risk_level": _get(v3, "tradingNature.nature.risk_level"),
        "max_position": _get(v3, "tradingNature.nature.max_position"),
        "stop_loss": _get(v3, "tradingNature.nature.stop_loss"),
        "confidence": _get(v3, "tradingNature.confidence"),
    }
    out["reflexivity"] = {
        "cycle_position": _get(v3, "reflexivity.cycle.cycle_position"),
        "risk_level": _get(v3, "reflexivity.cycle.risk_level"),
        "warning": _get(v3, "reflexivity.cycle.reflexivity_warning"),
        "confidence": _get(v3, "reflexivity.cycle.confidence"),
    }
    out["collapse_chain"] = {
        "level": _get(v3, "collapseChain.level"),
        "score": _get(v3, "collapseChain.score"),
        "advice": _get(v3, "collapseChain.advice"),
    }

    return out


def _map_v2(md: Dict[str, Any]) -> Dict[str, Any]:
    v2 = md.get("v2") if isinstance(md.get("v2"), dict) else {}
    out: Dict[str, Any] = {"algo": "v2"}
    out["sentiment"] = {
        "score": _get(v2, "sentiment.score"),
        "phase": _get(v2, "sentiment.phase"),
        "warnings": _get(v2, "sentiment.warnings") or [],
        "risk_level": _get(v2, "sentiment.risk_level"),
        "confidence": _get(v2, "sentiment.confidence"),
    }
    out["mainline"] = {
        "exists": _get(v2, "sector.mainline.exists"),
        "top_sector": _get(v2, "sector.mainline.top_sector"),
        "level": _get(v2, "sector.mainline.level"),
        "strength": _get(v2, "sector.mainline.strength"),
    }
    out["rightside"] = {
        "allowed": _get(v2, "rightside.can_enter"),
        "score": _get(v2, "rightside.signal_strength"),
        "advice": _get(v2, "rightside.advice"),
        "confidence": None,
    }
    out["position"] = {
        "capital_pct": _get(v2, "position_model.tier.max_position"),
        "win_rate": _get(v2, "position_model.win_rate"),
        "tier": _get(v2, "position_model.tier.action"),
        "confidence": None,
    }
    out["full_position"] = {
        "passed_count": _get(v2, "resonance.passed_count"),
        "max_recommended_position": _get(v2, "resonance.max_recommended_position"),
        "confidence": None,
    }
    out["rebound"] = {
        "phase": _get(v2, "rebound.phase_name"),
        "confidence": None,
    }
    out["trading_nature"] = {
        "label": _get(v2, "trade_nature.label"),
        "risk_level": None,
        "max_position": _get(v2, "strategy.trade_nature.position_limit"),
        "stop_loss": _get(v2, "strategy.trade_nature.stop_loss"),
        "confidence": None,
    }
    out["reflexivity"] = {
        "cycle_position": _get(v2, "psychology.reflexivity_cycle.position_name"),
        "risk_level": None,
        "warning": _get(v2, "psychology.reflexivity_cycle.warning"),
        "confidence": None,
    }
    out["collapse_chain"] = {"level": None, "score": None, "advice": None}
    return out


def _map_v1(md: Dict[str, Any]) -> Dict[str, Any]:
    # v1 主要字段在顶层（sentiment/moodStage 等），能映射多少算多少
    out: Dict[str, Any] = {"algo": "v1"}
    out["sentiment"] = {
        "score": _get(md, "sentiment.score"),
        "phase": _get(md, "moodStage.title"),
        "warnings": [],
        "confidence": None,
    }
    out["mainline"] = {
        "exists": None,
        "top_sector": _get(md, "themePanels.strengthRows.0.name") or _get(md, "themePanels.ztTop.0.name"),
        "level": None,
        "strength": None,
    }
    out["rightside"] = {"allowed": None, "score": None, "advice": None, "confidence": None}
    out["position"] = {"capital_pct": None, "win_rate": None, "tier": None, "confidence": None}
    out["full_position"] = {"passed_count": None, "max_recommended_position": None, "confidence": None}
    out["rebound"] = {"phase": None, "confidence": None}
    out["trading_nature"] = {"label": None, "risk_level": None, "max_position": None, "stop_loss": None, "confidence": None}
    out["reflexivity"] = {"cycle_position": None, "risk_level": None, "warning": None, "confidence": None}
    out["collapse_chain"] = {"level": None, "score": None, "advice": None}
    return out


def build_compat(market_data: Dict[str, Any], *, prefer: Algo = "auto") -> Dict[str, Any]:
    algo = _pick_algo(market_data, prefer)
    if algo == "v3":
        compat = _map_v3(market_data)
    elif algo == "v2":
        compat = _map_v2(market_data)
    else:
        compat = _map_v1(market_data)

    # 通用附加：生成时间/日期
    compat["date"] = market_data.get("date")
    compat["generatedAt"] = _get(market_data, "meta.generatedAt")
    return compat
