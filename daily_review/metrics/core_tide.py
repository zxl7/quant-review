#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""核心潮汐算法：情绪 + 板块 + 量能 + 消息面 + 大盘的统一纯计算层。"""

from __future__ import annotations

from typing import Any, Iterable

from daily_review.features.sector_resolver import normalize_sector


CoreAction = str
CoreStatus = str


def build_core_tide_signal(
    *,
    market_data: dict[str, Any] | None,
    tide_signal: dict[str, Any] | None = None,
    catalyst_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建 coreTideSignal。

    纯计算约束：
    - 不请求网络，不读写文件。
    - tide_signal 是上一层“退潮穿越/回光返照”的统一产物。
    - catalyst_data 由编排层读取缓存后传入，缺失时按中性消息面处理。
    """
    md = market_data if isinstance(market_data, dict) else {}
    tide = tide_signal if isinstance(tide_signal, dict) else {}
    catalysts = catalyst_data if isinstance(catalyst_data, dict) else {}
    date = str(md.get("date") or tide.get("date") or "")

    market_regime = _build_market_regime(md, tide)
    catalyst_map = _build_catalyst_map(catalysts)
    theme_rows = tide.get("themes") if isinstance(tide.get("themes"), list) else []

    themes = [
        _build_core_theme(
            theme=row,
            market_regime=market_regime,
            catalyst=_match_catalyst(str(row.get("name") or ""), catalyst_map),
        )
        for row in theme_rows
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    ]
    themes.sort(key=_theme_sort_key)

    confirmed = [t["name"] for t in themes if t["action"] == "confirm"]
    watch = [t["name"] for t in themes if t["action"] == "watch"]
    avoid = [t["name"] for t in themes if t["action"] in {"avoid", "no_new_position"}]
    rising = [t["name"] for t in themes if t.get("tide_phase") == "rising"]
    neutral = [t["name"] for t in themes if t.get("tide_phase") == "neutral"]
    ebbing = [t["name"] for t in themes if t.get("tide_phase") == "ebbing"]
    return {
        "date": date,
        "marketRegime": market_regime,
        "themes": themes,
        "summary": {
            "confirmed": confirmed[:6],
            "watch": watch[:8],
            "avoid": avoid[:8],
            "rising": rising[:6],
            "neutral": neutral[:8],
            "ebbing": ebbing[:8],
            "action_hint": _summary_action_hint(market_regime, rising, neutral, ebbing),
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
    if text.startswith("+"):
        text = text[1:]
    try:
        return float(text)
    except Exception:
        return None


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _round(v: float | None, ndigits: int = 2) -> float | None:
    return None if v is None else round(v, ndigits)


def _first_number(values: Iterable[Any]) -> float | None:
    for value in values:
        n = _to_float(value)
        if n is not None:
            return n
    return None


def _pct_change(today: float | None, prev: float | None) -> float | None:
    if today is None or prev is None or prev == 0:
        return None
    return (today - prev) / abs(prev) * 100.0


def _build_market_regime(md: dict[str, Any], tide: dict[str, Any]) -> dict[str, Any]:
    emotion_score, emotion_reasons = _calc_emotion_score(md)
    index_score, index_reasons = _calc_index_score(md)
    volume_score, volume_reasons = _calc_volume_score(md)
    breadth_score, breadth_reasons = _calc_breadth_score(md, tide)
    loss_score, loss_reasons = _calc_loss_score(md, tide)
    structure = _calc_structure_context(md)

    score = (
        emotion_score * 0.26
        + breadth_score * 0.20
        + index_score * 0.16
        + volume_score * 0.13
        + (100.0 - loss_score) * 0.13
        + float(structure.get("score") or 50.0) * 0.12
    )
    ebb = bool(((tide.get("market") or {}) if isinstance(tide, dict) else {}).get("is_ebb_day"))
    status = _market_status(score, ebb, breadth_score, loss_score)
    risk_level = "high" if status in {"ebb", "ice"} else ("mid" if status == "divergence" else "low")
    reasons = [
        *emotion_reasons,
        *loss_reasons,
        *[str(x) for x in structure.get("reasons", []) if str(x).strip()],
        *breadth_reasons,
        *volume_reasons,
        *index_reasons,
    ]
    if ebb and "基础潮汐退潮" not in reasons:
        reasons.insert(0, "基础潮汐退潮")

    return {
        "status": status,
        "score": round(_clamp(score)),
        "emotion_score": round(emotion_score),
        "index_score": round(index_score),
        "volume_score": round(volume_score),
        "breadth_score": round(breadth_score),
        "loss_score": round(loss_score),
        "structure_score": round(float(structure.get("score") or 50.0)),
        "high_risk_score": round(float(structure.get("high_risk_score") or 0.0)),
        "low_ladder_score": round(float(structure.get("low_ladder_score") or 0.0)),
        "structure": structure,
        "risk_level": risk_level,
        "reasons": reasons[:6],
    }


def _calc_emotion_score(md: dict[str, Any]) -> tuple[float, list[str]]:
    sentiment = md.get("sentiment") if isinstance(md.get("sentiment"), dict) else {}
    mood = md.get("mood") if isinstance(md.get("mood"), dict) else {}
    score = _first_number([sentiment.get("score"), mood.get("score"), md.get("sentiment_score")])
    risk = _first_number([sentiment.get("risk"), mood.get("risk")])
    out = 50.0 if score is None else score
    if risk is not None and risk >= 65:
        out -= min(15.0, (risk - 60.0) * 0.35)
    reasons: list[str] = []
    if score is not None:
        reasons.append(f"情绪{score:.0f}")
    if risk is not None and risk >= 60:
        reasons.append(f"风险{risk:.0f}")
    warnings = sentiment.get("warnings") if isinstance(sentiment.get("warnings"), list) else []
    if warnings:
        out -= 6.0
        reasons.append("情绪预警")
    return _clamp(out), reasons


def _calc_index_score(md: dict[str, Any]) -> tuple[float, list[str]]:
    rows = md.get("indices")
    if not isinstance(rows, list) or not rows:
        return 50.0, ["大盘数据中性"]

    changes: list[float] = []
    ma_bonus = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        chg = _to_float(row.get("chg"))
        if chg is not None:
            changes.append(chg)
        price = _to_float(row.get("price") or row.get("val"))
        ma5 = _to_float(row.get("ma5"))
        ma20 = _to_float(row.get("ma20"))
        if price is not None and ma5 is not None:
            ma_bonus += 3.0 if price >= ma5 else -3.0
        if price is not None and ma20 is not None:
            ma_bonus += 4.0 if price >= ma20 else -4.0

    avg_chg = sum(changes) / len(changes) if changes else 0.0
    score = 50.0 + avg_chg * 8.0 + ma_bonus / max(1, len(rows))
    reasons = [f"指数均涨{avg_chg:.2f}%"]
    if ma_bonus > 0:
        reasons.append("指数均线支撑")
    elif ma_bonus < 0:
        reasons.append("指数均线压制")
    return _clamp(score), reasons


def _calc_volume_score(md: dict[str, Any]) -> tuple[float, list[str]]:
    volume = md.get("volume") if isinstance(md.get("volume"), dict) else {}
    change = _to_float(volume.get("change"))
    if change is None:
        values = volume.get("values") if isinstance(volume.get("values"), list) else []
        if len(values) >= 2:
            change = _pct_change(_to_float(values[-1]), _to_float(values[-2]))
    if change is None:
        today = _first_number([volume.get("total"), volume.get("amount")])
        prev_volume = ((md.get("prev") or {}).get("volume") or {}) if isinstance(md.get("prev"), dict) else {}
        prev = _first_number([prev_volume.get("total"), prev_volume.get("amount")])
        change = _pct_change(today, prev)

    if change is None:
        return 50.0, ["量能数据中性"]
    # 放量温和支持主线，极端放量更偏分歧；缩量直接降低进攻权重。
    if change >= 25:
        score = 62.0
    elif change >= 8:
        score = 72.0
    elif change >= 0:
        score = 62.0
    elif change >= -8:
        score = 45.0
    else:
        score = 34.0
    return score, [f"量能{change:+.1f}%"]


def _calc_breadth_score(md: dict[str, Any], tide: dict[str, Any]) -> tuple[float, list[str]]:
    panorama = md.get("panorama") if isinstance(md.get("panorama"), dict) else {}
    limit_up = _to_float(panorama.get("limitUp") or panorama.get("limit_up"))
    broken = _to_float(panorama.get("broken"))
    limit_down = _to_float(panorama.get("limitDown") or panorama.get("limit_down"))
    seal_rate = _to_float(panorama.get("ratio") or panorama.get("sealRate") or panorama.get("seal_rate"))

    if limit_up is None and limit_down is None and seal_rate is None:
        return 50.0, ["涨跌停广度中性"]

    score = 48.0
    if limit_up is not None:
        score += min(24.0, limit_up * 0.28)
    if limit_down is not None:
        score -= min(28.0, limit_down * 0.45)
    if broken is not None:
        score -= min(12.0, broken * 0.12)
    if seal_rate is not None:
        score += (seal_rate - 55.0) * 0.22
    if bool(((tide.get("market") or {}) if isinstance(tide, dict) else {}).get("is_ebb_day")):
        score -= 8.0

    reasons = []
    if limit_up is not None:
        reasons.append(f"涨停{limit_up:.0f}")
    if limit_down is not None and limit_down >= 20:
        reasons.append(f"跌停{limit_down:.0f}")
    if seal_rate is not None:
        reasons.append(f"封板率{seal_rate:.0f}%")
    return _clamp(score), reasons


def _calc_loss_score(md: dict[str, Any], tide: dict[str, Any]) -> tuple[float, list[str]]:
    tide_market = tide.get("market") if isinstance(tide.get("market"), dict) else {}
    loss = tide_market.get("loss_effect") if isinstance(tide_market.get("loss_effect"), dict) else {}
    score = _to_float(loss.get("score"))
    if score is None:
        panorama = md.get("panorama") if isinstance(md.get("panorama"), dict) else {}
        sentiment = md.get("sentiment") if isinstance(md.get("sentiment"), dict) else {}
        sub_scores = sentiment.get("sub_scores") if isinstance(sentiment.get("sub_scores"), dict) else {}
        limit_down = _to_float(panorama.get("limitDown") or panorama.get("limit_down"))
        broken = _to_float(panorama.get("broken"))
        limit_up = _to_float(panorama.get("limitUp") or panorama.get("limit_up"))
        broken_rate = broken / (broken + limit_up) * 100.0 if broken is not None and limit_up is not None and (broken + limit_up) > 0 else None
        negative_score = _to_float(sub_scores.get("negative"))
        risk = _first_number([sentiment.get("risk"), (md.get("mood") or {}).get("risk") if isinstance(md.get("mood"), dict) else None])
        score = 0.0
        if limit_down is not None:
            score += min(45.0, limit_down / 30.0 * 45.0)
        if broken_rate is not None:
            score += min(25.0, broken_rate / 40.0 * 25.0)
        elif broken is not None:
            score += min(18.0, broken / 35.0 * 18.0)
        if negative_score is not None:
            score += min(20.0, max(0.0, 10.0 - negative_score) / 10.0 * 20.0)
        if risk is not None:
            score += min(10.0, risk / 80.0 * 10.0)
    reasons = loss.get("reasons") if isinstance(loss.get("reasons"), list) else []
    if not reasons and score is not None and score >= 60:
        reasons = [f"亏钱效应{score:.0f}"]
    return _clamp(float(score if score is not None else 50.0)), [str(x) for x in reasons[:3]]


def _calc_structure_context(md: dict[str, Any]) -> dict[str, Any]:
    """
    结构分专门回答两个问题：
    1. 高位负反馈有没有开始主导盘面；
    2. 低位连板梯队是否在承接、修复，足以支撑新一轮潮汐。
    """
    zt_meta = ((md.get("ztAnalysis") or {}).get("meta") or {}) if isinstance(md.get("ztAnalysis"), dict) else {}
    ladder_rows = md.get("ladder") if isinstance(md.get("ladder"), list) else []
    height_context = str(zt_meta.get("heightContext") or "")
    break_risk_base = _to_float(zt_meta.get("breakRiskBase"))
    tier_engagement = _to_float(((zt_meta.get("tierEngagement") or {}).get("score")))
    promo_ecology = _to_float(zt_meta.get("promoEcology"))

    badge_rows: list[tuple[int, dict[str, Any]]] = []
    for row in ladder_rows:
        if not isinstance(row, dict):
            continue
        badge = int(_to_float(row.get("badge")) or 0)
        if badge <= 0:
            continue
        badge_rows.append((badge, row))

    badge_rows.sort(key=lambda item: item[0], reverse=True)
    top_badge = badge_rows[0][0] if badge_rows else 0
    second_badge = badge_rows[1][0] if len(badge_rows) > 1 else 0
    top_gap = max(0, top_badge - second_badge)

    low_ladder_rows = [row for badge, row in badge_rows if badge in {2, 3}]
    low_ladder_count = len(low_ladder_rows)
    low_ladder_quality = sum(
        1
        for row in low_ladder_rows
        if str(row.get("status") or "") == "晋级"
        or any(flag in str(row.get("qualityLabel") or "") for flag in ("强", "稳", "良"))
    )
    low_badge_2_rows = [row for badge, row in badge_rows if badge == 2]
    low_badge_3_rows = [row for badge, row in badge_rows if badge == 3]
    low_badge_2_count = len(low_badge_2_rows)
    low_badge_3_count = len(low_badge_3_rows)
    low_promotion_count = sum(1 for row in low_ladder_rows if str(row.get("status") or "") == "晋级")
    low_turnover_confirm_count = sum(
        1
        for row in low_ladder_rows
        if any(flag in str(row.get("qualityLabel") or "") for flag in ("温和放量", "高换手承接", "加速确认"))
    )
    low_badge_3_quality = sum(
        1
        for row in low_badge_3_rows
        if str(row.get("status") or "") == "晋级"
        or any(flag in str(row.get("qualityLabel") or "") for flag in ("加速确认", "高换手承接", "温和放量"))
    )

    high_ladder_rows = [row for badge, row in badge_rows if badge >= 4]
    high_ladder_count = len(high_ladder_rows)
    high_break_rows = [row for row in high_ladder_rows if str(row.get("status") or "") != "晋级"]
    high_repeat_open_rows = [row for row in high_ladder_rows if float(_to_float(row.get("zbc")) or 0.0) >= 2.0]
    high_rotten_rows = [
        row
        for row in high_ladder_rows
        if any(flag in str(row.get("qualityLabel") or "") for flag in ("分歧烂板", "反复回封"))
    ]
    high_break_ratio = (len(high_break_rows) / high_ladder_count * 100.0) if high_ladder_count else 0.0
    high_repeat_open_ratio = (len(high_repeat_open_rows) / high_ladder_count * 100.0) if high_ladder_count else 0.0
    high_rotten_ratio = (len(high_rotten_rows) / high_ladder_count * 100.0) if high_ladder_count else 0.0

    high_risk_pressure = 0.0
    if break_risk_base is not None:
        high_risk_pressure += break_risk_base * 0.38
    if height_context == "pressure":
        high_risk_pressure += 15.0
    elif height_context == "repair":
        high_risk_pressure -= 6.0
    if top_badge >= 6:
        high_risk_pressure += 8.0 + min(10.0, top_gap * 3.5)
    elif top_badge >= 5 and top_gap >= 2:
        high_risk_pressure += 7.0

    high_break_pressure = min(28.0, high_break_ratio * 0.35)
    high_repeat_open_pressure = min(20.0, high_repeat_open_ratio * 0.28)
    high_rotten_pressure = min(18.0, high_rotten_ratio * 0.24)

    high_risk_score = (
        high_risk_pressure
        + high_break_pressure
        + high_repeat_open_pressure
        + high_rotten_pressure
    )

    low_count_support = min(18.0, low_ladder_count * 5.0)
    low_badge_2_support = min(14.0, low_badge_2_count * 4.5)
    low_badge_3_support = min(16.0, low_badge_3_count * 5.5)
    low_promotion_support = min(16.0, low_promotion_count * 5.5)
    low_turnover_support = min(12.0, low_turnover_confirm_count * 4.0)
    low_badge_3_quality_support = min(14.0, low_badge_3_quality * 6.0)

    low_ladder_score = (
        8.0
        + low_count_support
        + low_badge_2_support
        + low_badge_3_support
        + low_promotion_support
        + low_turnover_support
        + low_badge_3_quality_support
    )
    if tier_engagement is not None:
        low_ladder_score += min(18.0, max(0.0, tier_engagement) * 6.0)
    if promo_ecology is not None:
        low_ladder_score += min(12.0, max(0.0, promo_ecology) * 2.0)
    if height_context == "repair":
        low_ladder_score += 8.0

    high_risk_score = _clamp(high_risk_score)
    low_ladder_score = _clamp(low_ladder_score)
    score = _clamp(50.0 + (low_ladder_score - high_risk_score) * 0.35)

    reasons: list[str] = []
    if high_risk_score >= 70:
        reasons.append("高位负反馈偏强")
    elif high_risk_score >= 55:
        reasons.append("高位分歧累积")
    if low_ladder_score >= 68:
        reasons.append("低位连板承接良好")
    elif low_ladder_score <= 42:
        reasons.append("低位梯队承接偏弱")
    if low_badge_3_quality >= 2:
        reasons.append("3板晋级质量提升")
    elif low_turnover_confirm_count >= 2:
        reasons.append("低位换手确认增加")
    elif low_badge_2_count >= 3:
        reasons.append("2板承接扩散")
    if tier_engagement is not None and tier_engagement >= 2.5:
        reasons.append("梯队完整")
    elif tier_engagement is not None and tier_engagement < 1.0:
        reasons.append("梯队松散")
    if high_break_ratio >= 45:
        reasons.append("高位断板偏多")
    elif high_repeat_open_ratio >= 35:
        reasons.append("高位炸板回封差")
    elif high_rotten_ratio >= 35:
        reasons.append("高位烂板增多")

    return {
        "score": round(score, 2),
        "high_risk_score": round(high_risk_score, 2),
        "low_ladder_score": round(low_ladder_score, 2),
        "height_context": height_context or "neutral",
        "top_badge": top_badge,
        "top_gap": top_gap,
        "high_ladder_count": high_ladder_count,
        "high_break_ratio": round(high_break_ratio, 2),
        "high_repeat_open_ratio": round(high_repeat_open_ratio, 2),
        "high_rotten_ratio": round(high_rotten_ratio, 2),
        "high_risk_pressure": round(high_risk_pressure, 2),
        "high_break_pressure": round(high_break_pressure, 2),
        "high_repeat_open_pressure": round(high_repeat_open_pressure, 2),
        "high_rotten_pressure": round(high_rotten_pressure, 2),
        "low_ladder_count": low_ladder_count,
        "low_ladder_quality": low_ladder_quality,
        "low_badge_2_count": low_badge_2_count,
        "low_badge_3_count": low_badge_3_count,
        "low_promotion_count": low_promotion_count,
        "low_turnover_confirm_count": low_turnover_confirm_count,
        "low_badge_3_quality": low_badge_3_quality,
        "low_count_support": round(low_count_support, 2),
        "low_badge_2_support": round(low_badge_2_support, 2),
        "low_badge_3_support": round(low_badge_3_support, 2),
        "low_promotion_support": round(low_promotion_support, 2),
        "low_turnover_support": round(low_turnover_support, 2),
        "low_badge_3_quality_support": round(low_badge_3_quality_support, 2),
        "tier_engagement": _round(tier_engagement),
        "promo_ecology": _round(promo_ecology),
        "reasons": reasons[:4],
    }


def _market_status(score: float, is_ebb_day: bool, breadth_score: float, loss_score: float) -> str:
    if is_ebb_day and score < 38:
        return "ice"
    if loss_score >= 78 and (is_ebb_day or breadth_score < 45):
        return "ice"
    if is_ebb_day or breadth_score < 35 or score < 42 or loss_score >= 70:
        return "ebb"
    if score < 55:
        return "divergence"
    if score < 66:
        return "repair"
    return "attack"


def _theme_key(name: Any) -> str:
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


def _build_catalyst_map(catalyst_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    _ingest_surge_plates(catalyst_data.get("surge_plates"), out)
    _ingest_tomorrow_themes(catalyst_data.get("tomorrow_themes"), out)
    _ingest_abnormal_events(catalyst_data.get("abnormal"), out)
    return out


def _add_catalyst(out: dict[str, dict[str, Any]], name: Any, source: str, desc: str = "") -> None:
    key = _theme_key(name)
    if not key:
        return
    row = out.setdefault(key, {"score": 50.0, "sources": [], "descriptions": []})
    if source not in row["sources"]:
        row["sources"].append(source)
        row["score"] += {"xgb_surge": 16, "em_hot": 12, "em_theme": 8, "xgb_abnormal": 6}.get(source, 4)
    if desc and desc not in row["descriptions"]:
        row["descriptions"].append(desc[:80])
    row["score"] = _clamp(float(row["score"]), 0.0, 90.0)


def _ingest_surge_plates(surge_plates: Any, out: dict[str, dict[str, Any]]) -> None:
    layer1 = surge_plates.get("raw") if isinstance(surge_plates, dict) else None
    inner = layer1.get("data") if isinstance(layer1, dict) else None
    payload = inner.get("data") if isinstance(inner, dict) and isinstance(inner.get("data"), dict) else inner
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return
    for item in items:
        if isinstance(item, dict):
            _add_catalyst(out, item.get("name"), "xgb_surge", str(item.get("description") or ""))


def _ingest_tomorrow_themes(tomorrow_themes: Any, out: dict[str, dict[str, Any]]) -> None:
    layer1 = tomorrow_themes.get("raw") if isinstance(tomorrow_themes, dict) else None
    inner = layer1.get("raw") if isinstance(layer1, dict) else None
    data = inner.get("data") if isinstance(inner, dict) else None
    items = data if isinstance(data, list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        source = "em_hot" if str(item.get("isHot")) == "1" else "em_theme"
        desc = str(item.get("title") or item.get("summary") or "")
        _add_catalyst(out, item.get("themeName"), source, desc)


def _ingest_abnormal_events(abnormal: Any, out: dict[str, dict[str, Any]]) -> None:
    latest = abnormal.get("latest") if isinstance(abnormal, dict) and isinstance(abnormal.get("latest"), dict) else {}
    combined = latest.get("combined") if isinstance(latest.get("combined"), dict) else {}
    raw = combined.get("data") if isinstance(combined.get("data"), dict) else {}
    events = raw.get("data") if isinstance(raw.get("data"), list) else []
    for event in events:
        if not isinstance(event, dict):
            continue
        plate = event.get("plate_abnormal_event_data") or {}
        if isinstance(plate, dict) and plate.get("plate_name"):
            _add_catalyst(out, plate.get("plate_name"), "xgb_abnormal")
        stock = event.get("stock_abnormal_event_data") or {}
        related = stock.get("related_plates") if isinstance(stock, dict) else None
        if isinstance(related, list):
            for item in related[:3]:
                if isinstance(item, dict) and item.get("plate_name"):
                    _add_catalyst(out, item.get("plate_name"), "xgb_abnormal")


def _match_catalyst(name: str, catalyst_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    key = _theme_key(name)
    if not key:
        return {"score": 50, "sources": [], "descriptions": []}
    if key in catalyst_map:
        return catalyst_map[key]
    for cand_key, row in catalyst_map.items():
        if key in cand_key or cand_key in key:
            return row
    return {"score": 50, "sources": [], "descriptions": []}


def _build_core_theme(
    *,
    theme: dict[str, Any],
    market_regime: dict[str, Any],
    catalyst: dict[str, Any],
) -> dict[str, Any]:
    name = str(theme.get("name") or "")
    canonical_name = _canonical_theme_name(theme.get("canonical_name") or name)
    tide_score = float(theme.get("tide_score") or _status_base_score(str(theme.get("status") or "")))
    strength_score = _theme_strength_score(theme)
    news_score = float(catalyst.get("score") or 50.0)
    market_score = float(market_regime.get("score") or 50.0)
    volume_score = _theme_volume_score(theme, market_regime)
    structure_score = _theme_structure_score(theme, market_regime, catalyst)

    core_score = (
        tide_score * 0.35
        + strength_score * 0.25
        + news_score * 0.15
        + market_score * 0.10
        + volume_score * 0.10
        + structure_score * 0.05
    )
    status, action = _theme_status_action(core_score, theme, market_regime)
    tide_phase = _theme_tide_phase(
        status=status,
        action=action,
        base_status=str(theme.get("status") or ""),
        core_score=core_score,
    )
    ebb_score = _theme_ebb_score(
        core_score=core_score,
        tide_score=tide_score,
        strength_score=strength_score,
        status=status,
        action=action,
        base_status=str(theme.get("status") or ""),
    )
    reasons, cautions = _theme_reasons(theme, catalyst, market_regime, status)
    confirms = {
        "emotion": int(market_regime.get("emotion_score") or 0) >= 55,
        "strength": strength_score >= 62,
        "volume": volume_score >= 58,
        "news": news_score >= 62,
        "market": market_score >= 55 and market_regime.get("status") not in {"ebb", "ice"},
    }
    return {
        "name": name,
        "canonical_name": canonical_name,
        "status": status,
        "base_tide_status": str(theme.get("status") or ""),
        "action": action,
        "tide_zone": _theme_tide_zone(status, action),
        "tide_phase": tide_phase,
        "core_score": round(_clamp(core_score)),
        "ebb_score": round(_clamp(ebb_score)),
        "tide_score": round(_clamp(tide_score)),
        "emotion_score": int(market_regime.get("emotion_score") or 50),
        "strength_score": round(_clamp(strength_score)),
        "volume_score": round(_clamp(volume_score)),
        "news_score": round(_clamp(news_score)),
        "market_score": round(_clamp(market_score)),
        "structure_score": round(_clamp(structure_score)),
        "confidence": _confidence(confirms, theme, catalyst),
        "confirms": confirms,
        "reasons": reasons,
        "cautions": cautions,
        "action_hint": _theme_action_hint(status, action, name),
    }


def _status_base_score(status: str) -> float:
    return {
        "confirmed_mainline": 76.0,
        "traverse_candidate": 66.0,
        "micro_traverse": 58.0,
        "neutral": 50.0,
        "weak": 38.0,
        "volume_rebound": 34.0,
        "rebound_warning": 24.0,
    }.get(status, 50.0)


def _theme_strength_score(theme: dict[str, Any]) -> float:
    score = _to_float(theme.get("strength_score"))
    rank = _to_float(theme.get("strength_rank"))
    if score is None and rank is not None and rank > 0:
        score = max(35.0, 92.0 - rank * 6.0)
    if score is None:
        zt = _to_float(theme.get("today_zt")) or 0.0
        score = 44.0 + min(24.0, zt * 3.0)
    if rank is not None and rank <= 5:
        score += 6.0
    return _clamp(score)


def _theme_volume_score(theme: dict[str, Any], market_regime: dict[str, Any]) -> float:
    base = float(market_regime.get("volume_score") or 50.0)
    today_zt = _to_float(theme.get("today_zt")) or 0.0
    prev_zt = _to_float(theme.get("prev_zt")) or 0.0
    if today_zt >= prev_zt and today_zt >= 5:
        base += 8.0
    if str(theme.get("status") or "") == "volume_rebound":
        base -= 18.0
    if str(theme.get("status") or "") == "rebound_warning":
        base -= 24.0
    return _clamp(base)


def _theme_structure_score(theme: dict[str, Any], market_regime: dict[str, Any], catalyst: dict[str, Any]) -> float:
    structure = market_regime.get("structure") if isinstance(market_regime.get("structure"), dict) else {}
    high_risk = float(structure.get("high_risk_score") or 0.0)
    low_ladder = float(structure.get("low_ladder_score") or 0.0)
    base = 50.0 + (low_ladder - high_risk) * 0.30
    status = str(theme.get("status") or "")
    low_start = _is_low_start_theme(theme, catalyst, structure)
    if low_start:
        # 低位新启动方向不应该被“全市场高位退潮”一刀切压死；
        # 它们更多体现为观察/验证，而不是直接判成退潮。
        base += max(0.0, low_ladder - 50.0) * 0.16
        base += min(8.0, (_to_float(theme.get("today_zt")) or 0.0) * 2.0)
        base -= max(0.0, high_risk - 72.0) * 0.06
    if status in {"confirmed_mainline", "traverse_candidate", "micro_traverse"}:
        base += max(0.0, low_ladder - 55.0) * 0.15
    if status in {"weak", "volume_rebound", "rebound_warning"}:
        base -= max(0.0, high_risk - 45.0) * 0.20
    return _clamp(base)


def _theme_ebb_score(
    *,
    core_score: float,
    tide_score: float,
    strength_score: float,
    status: str,
    action: str,
    base_status: str,
) -> float:
    """退潮强度分：专门用于“谁退潮最猛”的排序，不等同于核心关注分。"""
    # 这里改成“可比较排序分”，避免所有弱势题材都被直接打到 90+。
    score = (
        22.0
        + (100.0 - tide_score) * 0.18
        + (100.0 - strength_score) * 0.12
        + (100.0 - core_score) * 0.10
    )
    if action == "avoid":
        score += 8.0
    elif action == "no_new_position":
        score += 11.0
    if status in {"avoid_weak", "afterglow_risk", "shrinking_rebound"}:
        score += 6.0
    if base_status in {"weak", "rebound_warning", "volume_rebound"}:
        score += 5.0
    return _clamp(score, 0.0, 100.0)


def _theme_tide_zone(status: str, action: str) -> str:
    if action == "confirm" or status in {"core_mainline", "resonance_traverse"}:
        return "rising"
    if action in {"avoid", "no_new_position"} or status in {"avoid_weak", "afterglow_risk", "shrinking_rebound"}:
        return "ebbing"
    return "neutral"


def _theme_tide_phase(status: str, action: str, base_status: str, core_score: float) -> str:
    """
    给前端提供更稳定的三段式阶段语义：
    - rising: 进入涨潮区，优先聚焦核心
    - neutral: 位于中性过渡区，仍需确认持续性
    - ebbing: 进入退潮/反抽/弱势阶段
    """
    if action in {"avoid", "no_new_position"} or status in {"avoid_weak", "afterglow_risk", "shrinking_rebound"}:
        return "ebbing"
    if action == "confirm" or status in {"core_mainline", "resonance_traverse"}:
        return "rising"
    if base_status in {"confirmed_mainline", "traverse_candidate", "micro_traverse"} or core_score >= 55:
        return "neutral"
    return "neutral"


def _is_low_start_theme(theme: dict[str, Any], catalyst: dict[str, Any] | None = None, structure: dict[str, Any] | None = None) -> bool:
    """
    识别“低位新启动/底部转强”题材。

    这类方向常见特征：
    - 本身是微穿越/穿越候选，而不是高位反抽
    - 今日涨停数不弱于昨日，且历史基数不高
    - 板块强度没有明显掉队
    - 若有消息催化、2板开始扩散、或结构承接偏好，则进一步确认
    """
    status = str(theme.get("status") or "")
    today_zt = _to_float(theme.get("today_zt")) or 0.0
    prev_zt = _to_float(theme.get("prev_zt"))
    pre_prev_zt = _to_float(theme.get("pre_prev_zt"))
    strength_score = _to_float(theme.get("strength_score"))
    strength_rank = _to_float(theme.get("strength_rank"))
    catalyst_sources = (catalyst or {}).get("sources") if isinstance(catalyst, dict) else []
    structure = structure if isinstance(structure, dict) else {}
    low_badge_2_count = _to_float(structure.get("low_badge_2_count")) or 0.0
    low_promotion_count = _to_float(structure.get("low_promotion_count")) or 0.0

    if status not in {"micro_traverse", "traverse_candidate", "neutral"}:
        return False
    if today_zt < 2:
        return False

    prev_low_base = prev_zt is None or prev_zt <= 2.0
    pre_prev_low_base = pre_prev_zt is None or pre_prev_zt <= 3.0
    today_not_weaker = prev_zt is None or today_zt >= prev_zt
    strength_ok = (
        (strength_score is not None and strength_score >= 50.0)
        or (strength_rank is not None and strength_rank <= 12.0)
    )
    catalyst_ok = isinstance(catalyst_sources, list) and len(catalyst_sources) > 0
    low_expand_ok = low_badge_2_count >= 3 or low_promotion_count >= 2
    strong_front_ok = (
        (strength_score is not None and strength_score >= 58.0)
        or (strength_rank is not None and strength_rank <= 8.0)
    )
    return bool(
        prev_low_base
        and pre_prev_low_base
        and today_not_weaker
        and strength_ok
        and (catalyst_ok or low_expand_ok or strong_front_ok)
    )


def _theme_status_action(
    core_score: float,
    theme: dict[str, Any],
    market_regime: dict[str, Any],
) -> tuple[CoreStatus, CoreAction]:
    base_status = str(theme.get("status") or "")
    market_status = str(market_regime.get("status") or "")
    structure = market_regime.get("structure") if isinstance(market_regime.get("structure"), dict) else {}
    high_risk = float(structure.get("high_risk_score") or 0.0)
    low_ladder = float(structure.get("low_ladder_score") or 0.0)
    low_start = _is_low_start_theme(theme, None, structure)
    strength_score = _to_float(theme.get("strength_score")) or 0.0
    today_zt = _to_float(theme.get("today_zt")) or 0.0
    prev_zt = _to_float(theme.get("prev_zt")) or 0.0
    resilience = _to_float(theme.get("resilience"))
    self_is_weak = (
        base_status in {"weak", "rebound_warning", "volume_rebound"}
        or core_score < 42
        or (strength_score < 45.0 and today_zt < max(2.0, prev_zt))
        or (resilience is not None and resilience <= -15.0 and today_zt < prev_zt)
    )
    if base_status == "rebound_warning":
        return "afterglow_risk", "no_new_position"
    if base_status == "volume_rebound":
        return "shrinking_rebound", "no_new_position"
    if self_is_weak:
        return "avoid_weak", "avoid"
    # 高位负反馈过强时，只压“自身也弱/拥挤”的方向，不再一刀切打全市场。
    if (
        high_risk >= 76
        and core_score < 66
        and base_status not in {"confirmed_mainline"}
        and not low_start
        and (strength_score < 52.0 or today_zt < prev_zt or (resilience is not None and resilience < -8.0))
    ):
        return "avoid_weak", "avoid"
    if core_score >= 70 and base_status == "confirmed_mainline":
        return "core_mainline", "confirm"
    if core_score >= 64 and base_status in {"confirmed_mainline", "traverse_candidate"}:
        confirm = market_status in {"attack", "repair"} and high_risk < 72 and low_ladder >= 52
        return "resonance_traverse", "confirm" if confirm else "watch"
    if low_start and core_score >= 56:
        # 低位启动先落到观察层，等次日确认，不直接被高位退潮带偏。
        return "observe_candidate", "watch"
    if core_score >= 58 and base_status in {"traverse_candidate", "micro_traverse"} and low_ladder >= 60 and high_risk < 65:
        return "observe_candidate", "watch"
    if core_score >= 55:
        return "observe_candidate", "watch"
    return "neutral_wait", "watch"


def _theme_reasons(
    theme: dict[str, Any],
    catalyst: dict[str, Any],
    market_regime: dict[str, Any],
    status: str,
) -> tuple[list[str], list[str]]:
    reasons: list[str] = []
    cautions: list[str] = []
    tide_label = {
        "confirmed_mainline": "潮汐确认",
        "traverse_candidate": "退潮穿越",
        "micro_traverse": "微型穿越",
        "weak": "潮汐偏弱",
        "volume_rebound": "缩量反弹",
        "rebound_warning": "回光返照",
    }.get(str(theme.get("status") or ""))
    if tide_label:
        (cautions if tide_label in {"潮汐偏弱", "缩量反弹", "回光返照"} else reasons).append(tide_label)
    strength_rank = theme.get("strength_rank")
    strength_score = theme.get("strength_score")
    if isinstance(strength_rank, (int, float)) and strength_rank <= 5:
        reasons.append(f"板块强度第{int(strength_rank)}")
    elif isinstance(strength_score, (int, float)) and strength_score >= 65:
        reasons.append(f"板块强度{strength_score:.0f}")
    sources = catalyst.get("sources") if isinstance(catalyst.get("sources"), list) else []
    if sources:
        reasons.append("消息催化")
    market_status = str(market_regime.get("status") or "")
    structure = market_regime.get("structure") if isinstance(market_regime.get("structure"), dict) else {}
    high_risk = float(structure.get("high_risk_score") or 0.0)
    low_ladder = float(structure.get("low_ladder_score") or 0.0)
    if _is_low_start_theme(theme, catalyst, structure):
        reasons.append("低位新启动")
    if low_ladder >= 60:
        reasons.append("低位连板承接")
    if market_status in {"ebb", "ice"}:
        cautions.append("市场退潮")
    elif market_status == "divergence":
        cautions.append("市场分歧")
    if high_risk >= 65:
        cautions.append("高位负反馈")
    if status in {"afterglow_risk", "shrinking_rebound"}:
        cautions.append("不开新仓")
    return list(dict.fromkeys(reasons))[:4], list(dict.fromkeys(cautions))[:4]


def _confidence(confirms: dict[str, bool], theme: dict[str, Any], catalyst: dict[str, Any]) -> str:
    hit = sum(1 for ok in confirms.values() if ok)
    if str(theme.get("confidence") or "") == "high":
        hit += 1
    if catalyst.get("sources"):
        hit += 1
    if hit >= 5:
        return "high"
    if hit >= 3:
        return "medium"
    return "low"


def _theme_action_hint(status: str, action: str, name: str) -> str:
    if action == "confirm":
        return f"{name}进入核心潮汐确认区，推荐线可提高优先级。"
    if action == "no_new_position":
        return f"{name}属于反抽/回光类信号，不开新仓，只看兑现和辨识度。"
    if action == "avoid":
        return f"{name}核心潮汐偏弱，降低权重，避免追高。"
    if status == "observe_candidate":
        return f"{name}有观察价值，等待情绪/量能/消息继续共振。"
    return f"{name}核心潮汐中性，按梯队和个股辨识度处理。"


def _theme_sort_key(theme: dict[str, Any]) -> tuple[int, int]:
    action_rank = {"confirm": 0, "watch": 1, "no_new_position": 2, "avoid": 3}
    return (action_rank.get(str(theme.get("action") or ""), 9), -int(theme.get("core_score") or 0))


def _summary_action_hint(market: dict[str, Any], rising: list[str], neutral: list[str], ebbing: list[str]) -> str:
    status = str(market.get("status") or "")
    if rising:
        return f"涨潮方向：{', '.join(rising[:3])}，优先围绕最强核心做节奏。"
    if status in {"ebb", "ice"}:
        return "市场处于退潮阶段，优先防守，只看逆势走强和确认信号。"
    if neutral:
        return f"中性方向：{', '.join(neutral[:3])}，等待情绪/量能/消息继续共振。"
    if ebbing:
        return f"退潮方向：{', '.join(ebbing[:3])}，反抽不开新仓，优先看兑现。"
    return "核心潮汐数据不足，按原系统判断。"
