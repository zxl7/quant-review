#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""潮汐算法：退潮穿越 + 回光返照的统一纯计算模块。"""

from __future__ import annotations

from typing import Any, Iterable

from daily_review.features.sector_resolver import normalize_sector


TideStatus = str


def build_tide_signal(
    *,
    market_data: dict[str, Any] | None,
    theme_trend_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建统一 tideSignal。

    本函数只做纯计算，不读写文件、不请求网络。数据不足时保持保守输出，
    下游继续按原系统逻辑判断。
    """
    md = market_data if isinstance(market_data, dict) else {}
    cache = theme_trend_cache if isinstance(theme_trend_cache, dict) else {}
    date = str(md.get("date") or "")

    signal = _empty_signal(date)
    today_snap = _market_snapshot(md)
    prev_snap = _market_snapshot(md.get("prev") if isinstance(md.get("prev"), dict) else {})

    if today_snap["date"] and not date:
        signal["date"] = today_snap["date"]

    market = _build_market_tide(today_snap, prev_snap)
    signal["market"] = market
    strength_map = _build_strength_map(md)

    days = _resolve_theme_days(cache, signal["date"])
    if len(days) < 2:
        signal["summary"]["action_hint"] = _market_action_hint(market, [], [], [])
        return signal

    by_day = cache.get("by_day") or {}
    today_day = days[-1]
    prev_day = days[-2]
    pre_prev_day = days[-3] if len(days) >= 3 else ""
    today_map = _theme_day_map(by_day.get(today_day))
    prev_map = _theme_day_map(by_day.get(prev_day))
    pre_prev_map = _theme_day_map(by_day.get(pre_prev_day)) if pre_prev_day else {}

    names = sorted(set(today_map) | set(prev_map) | set(pre_prev_map))
    themes = []
    for name in names:
        today_zt = today_map.get(name, 0)
        prev_zt = prev_map.get(name)
        pre_prev_zt = pre_prev_map.get(name)
        if today_zt <= 0 and (prev_zt or 0) <= 0 and (pre_prev_zt or 0) <= 0:
            continue
        themes.append(
            _build_theme_tide(
                name=name,
                today_zt=today_zt,
                prev_zt=prev_zt,
                pre_prev_zt=pre_prev_zt,
                market=market,
                strength_info=_match_strength_info(name, strength_map),
            )
        )

    themes.sort(key=_theme_sort_key)
    signal["themes"] = themes

    candidates = [t["name"] for t in themes if t["status"] in {"traverse_candidate", "micro_traverse"}]
    confirmed = [t["name"] for t in themes if t["status"] == "confirmed_mainline"]
    risks = [t["name"] for t in themes if t["warning_level"] in {"risk", "danger"}]
    signal["summary"] = {
        "mainline_candidates": candidates[:6],
        "confirmed_mainlines": confirmed[:6],
        "risk_themes": risks[:6],
        "action_hint": _market_action_hint(market, candidates, confirmed, risks),
    }
    return signal


def _empty_signal(date: str = "") -> dict[str, Any]:
    return {
        "date": date,
        "market": {
            "is_ebb_day": False,
            "trigger_count": 0,
            "triggers": [],
            "sentiment_delta": None,
            "limit_up_delta_pct": None,
            "seal_rate_delta_pct": None,
            "volume_delta_pct": None,
            "loss_effect": {
                "score": None,
                "level": "unknown",
                "limit_down": None,
                "broken": None,
                "broken_rate": None,
                "negative_score": None,
                "risk": None,
                "reasons": [],
            },
        },
        "themes": [],
        "summary": {
            "mainline_candidates": [],
            "confirmed_mainlines": [],
            "risk_themes": [],
            "action_hint": "潮汐数据不足，按原系统判断",
        },
    }


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    text = str(v).strip().replace(",", "")
    if not text:
        return None
    for suffix in ("亿元", "亿", "%", "pct", "PCT"):
        text = text.replace(suffix, "")
    try:
        return float(text)
    except Exception:
        return None


def _to_int(v: Any, default: int = 0) -> int:
    n = _to_float(v)
    return default if n is None else int(round(n))


def _parse_pct(v: Any) -> float | None:
    return _to_float(v)


def _pct_change(today: float | None, prev: float | None) -> float | None:
    if today is None or prev is None or prev == 0:
        return None
    return (today - prev) / abs(prev) * 100.0


def _first_number(values: Iterable[Any]) -> float | None:
    for value in values:
        n = _to_float(value)
        if n is not None:
            return n
    return None


def _market_snapshot(md: dict[str, Any]) -> dict[str, float | str | None]:
    if not isinstance(md, dict):
        md = {}
    sentiment = md.get("sentiment") if isinstance(md.get("sentiment"), dict) else {}
    mood = md.get("mood") if isinstance(md.get("mood"), dict) else {}
    panorama = md.get("panorama") if isinstance(md.get("panorama"), dict) else {}
    volume = md.get("volume") if isinstance(md.get("volume"), dict) else {}
    volume_values = volume.get("values") if isinstance(volume.get("values"), list) else []
    sub_scores = sentiment.get("sub_scores") if isinstance(sentiment.get("sub_scores"), dict) else {}

    vol = _to_float(volume_values[-1]) if volume_values else None
    if vol is None:
        vol = _first_number([volume.get("total"), volume.get("amount"), md.get("volume_total")])

    return {
        "date": str(md.get("date") or ""),
        "sentiment": _first_number([sentiment.get("score"), mood.get("score"), md.get("sentiment_score")]),
        "limit_up": _first_number([panorama.get("limitUp"), panorama.get("limit_up"), md.get("limitUp")]),
        "limit_down": _first_number([panorama.get("limitDown"), panorama.get("limit_down"), md.get("limitDown")]),
        "broken": _first_number([panorama.get("broken"), panorama.get("zab"), panorama.get("zb")]),
        "seal_rate": _parse_pct(panorama.get("ratio") or panorama.get("sealRate") or panorama.get("seal_rate")),
        "volume": vol,
        "negative_score": _first_number([sub_scores.get("negative"), md.get("negative_score")]),
        "risk": _first_number([sentiment.get("risk"), mood.get("risk"), md.get("risk")]),
    }


def _build_market_tide(today: dict[str, Any], prev: dict[str, Any]) -> dict[str, Any]:
    sentiment_delta = _delta(today.get("sentiment"), prev.get("sentiment"))
    limit_up_delta_pct = _pct_change(_num(today.get("limit_up")), _num(prev.get("limit_up")))
    seal_rate_delta_pct = _delta(today.get("seal_rate"), prev.get("seal_rate"))
    volume_delta_pct = _pct_change(_num(today.get("volume")), _num(prev.get("volume")))
    loss_effect = _build_loss_effect(today, prev)

    triggers: list[str] = []
    if sentiment_delta is not None and sentiment_delta <= -15:
        triggers.append(f"情绪降温{sentiment_delta:.1f}")
    if limit_up_delta_pct is not None and limit_up_delta_pct <= -40:
        triggers.append(f"涨停降幅{limit_up_delta_pct:.1f}%")
    if seal_rate_delta_pct is not None and seal_rate_delta_pct <= -10:
        triggers.append(f"封板率下降{seal_rate_delta_pct:.1f}pct")
    if loss_effect["score"] is not None and loss_effect["score"] >= 65:
        triggers.append(f"亏钱扩散{loss_effect['score']:.1f}")
    elif loss_effect["delta"] is not None and loss_effect["delta"] >= 20:
        triggers.append(f"亏钱抬升{loss_effect['delta']:.1f}")

    loss_danger = loss_effect["score"] is not None and loss_effect["score"] >= 75
    return {
        # 亏钱效应是退潮的硬风控触发：跌停/炸板/负反馈极端时，不再等待第二个进攻端信号确认。
        "is_ebb_day": len(triggers) >= 2 or loss_danger,
        "trigger_count": len(triggers),
        "triggers": triggers,
        "sentiment_delta": _round_or_none(sentiment_delta),
        "limit_up_delta_pct": _round_or_none(limit_up_delta_pct),
        "seal_rate_delta_pct": _round_or_none(seal_rate_delta_pct),
        "volume_delta_pct": _round_or_none(volume_delta_pct),
        "loss_effect": loss_effect,
    }


def _build_loss_effect(today: dict[str, Any], prev: dict[str, Any]) -> dict[str, Any]:
    """亏钱效应：退潮模块的风险端，偏跌停/炸板/负反馈。"""
    limit_down = _num(today.get("limit_down"))
    broken = _num(today.get("broken"))
    limit_up = _num(today.get("limit_up"))
    negative_score = _num(today.get("negative_score"))
    risk = _num(today.get("risk"))
    broken_rate = None
    if broken is not None and limit_up is not None and (broken + limit_up) > 0:
        broken_rate = broken / (broken + limit_up) * 100.0

    score = _loss_effect_score(
        limit_down=limit_down,
        broken=broken,
        broken_rate=broken_rate,
        negative_score=negative_score,
        risk=risk,
    )
    prev_score = _loss_effect_score(
        limit_down=_num(prev.get("limit_down")),
        broken=_num(prev.get("broken")),
        broken_rate=_calc_broken_rate(prev),
        negative_score=_num(prev.get("negative_score")),
        risk=_num(prev.get("risk")),
    )
    delta = _delta(score, prev_score)
    return {
        "score": _round_or_none(score, 1),
        "level": _loss_effect_level(score),
        "delta": _round_or_none(delta, 1),
        "limit_down": _round_or_none(limit_down, 0),
        "broken": _round_or_none(broken, 0),
        "broken_rate": _round_or_none(broken_rate, 1),
        "negative_score": _round_or_none(negative_score, 1),
        "risk": _round_or_none(risk, 1),
        "reasons": _loss_effect_reasons(limit_down, broken, broken_rate, negative_score, risk),
    }


def _calc_broken_rate(snap: dict[str, Any]) -> float | None:
    broken = _num(snap.get("broken"))
    limit_up = _num(snap.get("limit_up"))
    if broken is None or limit_up is None or (broken + limit_up) <= 0:
        return None
    return broken / (broken + limit_up) * 100.0


def _loss_effect_score(
    *,
    limit_down: float | None,
    broken: float | None,
    broken_rate: float | None,
    negative_score: float | None,
    risk: float | None,
) -> float | None:
    if all(v is None for v in (limit_down, broken, broken_rate, negative_score, risk)):
        return None
    score = 0.0
    if limit_down is not None:
        score += min(45.0, limit_down / 30.0 * 45.0)
    if broken_rate is not None:
        score += min(25.0, broken_rate / 40.0 * 25.0)
    elif broken is not None:
        score += min(18.0, broken / 35.0 * 18.0)
    if negative_score is not None:
        # 上游 negative 是“负反馈健康分”：越低越危险，因此反向计入亏钱效应。
        score += min(20.0, max(0.0, 10.0 - negative_score) / 10.0 * 20.0)
    if risk is not None:
        score += min(10.0, risk / 80.0 * 10.0)
    return max(0.0, min(100.0, score))


def _loss_effect_level(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 75:
        return "danger"
    if score >= 60:
        return "risk"
    if score >= 40:
        return "watch"
    return "low"


def _loss_effect_reasons(
    limit_down: float | None,
    broken: float | None,
    broken_rate: float | None,
    negative_score: float | None,
    risk: float | None,
) -> list[str]:
    reasons: list[str] = []
    if limit_down is not None and limit_down >= 20:
        reasons.append(f"跌停{int(round(limit_down))}")
    if broken_rate is not None and broken_rate >= 30:
        reasons.append(f"炸板率{broken_rate:.1f}%")
    elif broken is not None and broken >= 30:
        reasons.append(f"炸板{int(round(broken))}")
    if negative_score is not None and negative_score <= 3:
        reasons.append(f"负反馈{negative_score:.1f}")
    if risk is not None and risk >= 60:
        reasons.append(f"风险{risk:.0f}")
    return reasons[:4]


def _num(v: Any) -> float | None:
    return v if isinstance(v, (int, float)) else _to_float(v)


def _delta(today: Any, prev: Any) -> float | None:
    t = _num(today)
    p = _num(prev)
    if t is None or p is None:
        return None
    return t - p


def _round_or_none(v: float | None, ndigits: int = 2) -> float | None:
    return None if v is None else round(v, ndigits)


def _resolve_theme_days(cache: dict[str, Any], date: str) -> list[str]:
    by_day = cache.get("by_day") if isinstance(cache, dict) else {}
    if not isinstance(by_day, dict) or not by_day:
        return []
    days = sorted([str(d) for d in by_day.keys() if isinstance(d, str) and d])
    if date:
        days = [d for d in days if d <= date]
    return days[-3:]


def _theme_day_map(day: Any) -> dict[str, int]:
    if not isinstance(day, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in day.items():
        name = str(k or "").strip()
        if not name:
            continue
        out[name] = _to_int(v, 0)
    return out


def _theme_key(name: Any) -> str:
    """题材匹配用 key：先复用板块归一化，再去掉常见修饰符。"""
    text = str(normalize_sector(str(name or "").strip()) or "").strip().lower()
    for ch in (" ", "\t", "\n", "·", "・", "-", "_", "/", "\\", "（", "）", "(", ")"):
        text = text.replace(ch, "")
    for suffix in ("概念", "板块", "产业链", "方向", "行情"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text


def _canonical_theme_name(name: Any) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    return str(normalize_sector(raw) or raw).strip()


def _build_strength_map(market_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """提取板块强度。

    强度只做“确认层”，不替代涨停数韧性。来源优先级：
    1. plateRankTop10 / plateRotateTop：更像全市场板块强度排名。
    2. sectorHeatmap.rows：细分题材的热力分，用于风能、核电等细分名称兜底。
    """
    out: dict[str, dict[str, Any]] = {}

    ranked_rows: list[dict[str, Any]] = []
    for key in ("plateRankTop10", "plateRotateTop"):
        rows = market_data.get(key)
        if isinstance(rows, list):
            ranked_rows.extend([r for r in rows if isinstance(r, dict)])

    max_strength = max((_to_float(r.get("strength")) or 0.0 for r in ranked_rows), default=0.0)
    for idx, row in enumerate(ranked_rows, 1):
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        raw_strength = _to_float(row.get("strength"))
        score = _to_float(row.get("barPct"))
        if score is None and raw_strength is not None and max_strength > 0:
            score = raw_strength / max_strength * 100.0
        rank = _to_int(row.get("rank"), idx)
        _merge_strength(
            out,
            name,
            {
                "strength": raw_strength,
                "strength_rank": rank,
                "strength_score": _round_or_none(score),
                "strength_source": "plate_rank",
            },
        )

    heatmap = market_data.get("sectorHeatmap")
    heat_rows = heatmap.get("rows") if isinstance(heatmap, dict) else None
    if isinstance(heat_rows, list):
        for row in heat_rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            score = _to_float(row.get("score"))
            _merge_strength(
                out,
                name,
                {
                    "strength": score,
                    "strength_rank": None,
                    "strength_score": _round_or_none(score),
                    "strength_source": "sector_heatmap",
                },
            )
    return out


def _merge_strength(out: dict[str, dict[str, Any]], name: str, info: dict[str, Any]) -> None:
    key = _theme_key(name)
    if not key:
        return
    prev = out.get(key)
    # 多个来源命中同一 canonical 时，保留更能说明市场认可度的一条。
    if prev is None or _strength_priority(info) > _strength_priority(prev):
        out[key] = info


def _strength_priority(info: dict[str, Any]) -> tuple[float, float]:
    rank = info.get("strength_rank")
    rank_score = 120.0 - float(rank) * 8.0 if isinstance(rank, (int, float)) and rank > 0 else 0.0
    score = float(info.get("strength_score") or 0.0)
    return (max(score, rank_score), score)


def _match_strength_info(name: str, strength_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    key = _theme_key(name)
    if not key or not strength_map:
        return {"strength": None, "strength_rank": None, "strength_score": None, "strength_source": ""}
    if key in strength_map:
        return strength_map[key]
    for strength_key, info in strength_map.items():
        if key in strength_key or strength_key in key:
            return info
    return {"strength": None, "strength_rank": None, "strength_score": None, "strength_source": ""}


def _is_strength_strong(info: dict[str, Any]) -> bool:
    rank = info.get("strength_rank")
    score = info.get("strength_score")
    return (
        (isinstance(rank, (int, float)) and rank <= 5)
        or (isinstance(score, (int, float)) and score >= 65)
    )


def _is_strength_weak(info: dict[str, Any]) -> bool:
    rank = info.get("strength_rank")
    score = info.get("strength_score")
    if isinstance(rank, (int, float)) and rank <= 10:
        return False
    return isinstance(score, (int, float)) and score < 45


def _build_theme_tide(
    *,
    name: str,
    today_zt: int,
    prev_zt: int | None,
    pre_prev_zt: int | None,
    market: dict[str, Any],
    strength_info: dict[str, Any],
) -> dict[str, Any]:
    canonical_name = _canonical_theme_name(name)
    prev_val = 0 if prev_zt is None else prev_zt
    pre_prev_val = 0 if pre_prev_zt is None else pre_prev_zt
    theme_delta_pct = _pct_change(float(today_zt), float(prev_val)) if prev_val > 0 else None
    market_delta_pct = market.get("limit_up_delta_pct")
    resilience = None
    if theme_delta_pct is not None and isinstance(market_delta_pct, (int, float)):
        resilience = theme_delta_pct - float(market_delta_pct)

    status: TideStatus = "neutral"
    warning_level = "none"
    action_hint = "潮汐中性，按梯队和辨识度判断"
    strength_score = strength_info.get("strength_score")
    strength_rank = strength_info.get("strength_rank")
    strength_strong = _is_strength_strong(strength_info)
    strength_weak = _is_strength_weak(strength_info)

    rebounded = theme_delta_pct is not None and theme_delta_pct >= 80
    shrunk = isinstance(market.get("volume_delta_pct"), (int, float)) and float(market["volume_delta_pct"]) <= -5
    two_day_decay = pre_prev_val >= 3 and prev_val <= max(1, int(pre_prev_val * 0.45))
    still_below_peak = pre_prev_val > 0 and today_zt <= max(1, int(pre_prev_val * 0.65))
    if two_day_decay and rebounded and shrunk and still_below_peak:
        status = "rebound_warning"
        warning_level = "danger"
        action_hint = "回光返照风险：只看辨识度兑现，不开新仓"
    elif pre_prev_val >= today_zt and rebounded and shrunk:
        status = "volume_rebound"
        warning_level = "risk"
        action_hint = "缩量反弹：降低追高权重，等待放量确认"
    elif market.get("is_ebb_day") and prev_val >= 8 and today_zt >= 5 and (resilience or 0) > 0:
        status = "traverse_candidate"
        warning_level = "watch"
        action_hint = "退潮穿越候选：次日观察是否继续抗跌"
        if strength_strong and (resilience or 0) >= 10:
            # 板块强度排名/热力同步靠前，说明抗跌不是孤立涨停数，优先升级为确认主线。
            status = "confirmed_mainline"
            warning_level = "none"
            action_hint = "韧性与板块强度共振，确认主线优先跟踪"
        elif strength_weak:
            # 只有涨停数相对抗跌，但板块强度没有得到市场确认，先降为微型穿越观察。
            status = "micro_traverse"
            action_hint = "涨停韧性尚可但板块强度不足，先按微型穿越观察"
    elif prev_val >= 5 and prev_val <= 7 and today_zt >= prev_val:
        status = "micro_traverse"
        warning_level = "watch"
        action_hint = "低基数微型穿越：可观察，不按大主线处理"
        if strength_strong and today_zt >= 5:
            # 低基数题材如果同步进入强度前排，保留观察但提高置信度。
            action_hint = "低基数微型穿越，板块强度同步改善，次日验证持续性"
    elif pre_prev_val >= 8 and prev_val >= 5 and today_zt >= prev_val and (resilience is None or resilience >= -10):
        status = "confirmed_mainline"
        action_hint = "穿越后确认主线：推荐线可提高优先级"
    elif resilience is not None and resilience < -10 and today_zt < prev_val:
        status = "weak"
        warning_level = "watch"
        action_hint = "弱于市场：降低主线权重"
    elif prev_zt is None and today_zt >= 3 and strength_strong:
        # 新题材没有历史韧性可比，但强度榜已经确认，避免简单显示“潮汐不足”。
        status = "micro_traverse"
        warning_level = "watch"
        action_hint = "新题材强度靠前，历史不足，先按微型穿越观察"

    confidence = _theme_confidence(resilience, strength_info)
    tide_score = _theme_tide_score(resilience, strength_info, status)

    return {
        "name": name,
        "canonical_name": canonical_name,
        "status": status,
        "today_zt": today_zt,
        "prev_zt": prev_zt,
        "pre_prev_zt": pre_prev_zt,
        "resilience": _round_or_none(resilience),
        "strength": _round_or_none(strength_info.get("strength")),
        "strength_rank": strength_rank,
        "strength_score": _round_or_none(strength_score),
        "strength_source": strength_info.get("strength_source") or "",
        "tide_score": tide_score,
        "confidence": confidence,
        "warning_level": warning_level,
        "action_hint": action_hint,
    }


def _theme_confidence(resilience: float | None, strength_info: dict[str, Any]) -> str:
    has_resilience = resilience is not None
    has_strength = strength_info.get("strength_score") is not None or strength_info.get("strength_rank") is not None
    if has_resilience and has_strength:
        return "high"
    if has_resilience or has_strength:
        return "medium"
    return "low"


def _theme_tide_score(resilience: float | None, strength_info: dict[str, Any], status: str) -> int:
    base = 50.0
    if resilience is not None:
        # 韧性仍是主因子：强弱相对市场表现直接决定潮汐底色。
        base += max(-35.0, min(35.0, resilience * 0.55))
    score = strength_info.get("strength_score")
    rank = strength_info.get("strength_rank")
    if isinstance(score, (int, float)):
        base += (float(score) - 50.0) * 0.25
    if isinstance(rank, (int, float)) and rank > 0:
        base += max(0.0, 12.0 - float(rank))
    if status in {"rebound_warning", "volume_rebound"}:
        base -= 18.0
    elif status == "confirmed_mainline":
        base += 8.0
    return max(0, min(100, round(base)))


def _theme_sort_key(theme: dict[str, Any]) -> tuple[int, int, float]:
    priority = {
        "confirmed_mainline": 0,
        "traverse_candidate": 1,
        "micro_traverse": 2,
        "rebound_warning": 3,
        "volume_rebound": 4,
        "weak": 5,
        "neutral": 6,
    }
    return (
        priority.get(str(theme.get("status") or "neutral"), 9),
        -int(theme.get("today_zt") or 0),
        -float(theme.get("resilience") or -999),
    )


def _market_action_hint(
    market: dict[str, Any],
    candidates: list[str],
    confirmed: list[str],
    risks: list[str],
) -> str:
    if risks:
        return f"出现回光返照/缩量反弹：{', '.join(risks[:3])}，不开新仓先看兑现。"
    if confirmed:
        return f"潮汐确认主线：{', '.join(confirmed[:3])}，推荐线可提高优先级。"
    if candidates:
        return f"退潮穿越候选：{', '.join(candidates[:3])}，次日继续验证。"
    if market.get("is_ebb_day"):
        return "退潮日确认，优先观察穿越题材，回避弱反抽。"
    if any(market.get(k) is not None for k in ("sentiment_delta", "limit_up_delta_pct", "seal_rate_delta_pct")):
        return "潮汐无极端信号，按原系统判断。"
    return "潮汐数据不足，按原系统判断"
