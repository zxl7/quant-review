#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daily_review.config import load_config_from_env
from daily_review.data.biying import fetch_stock_history_k, fetch_stocks_realtime, normalize_stock_code
from daily_review.http import HttpClient


CACHE_DIR = ROOT / "cache"
ONLINE_CACHE_DIR = ROOT / "cache_online"
OUT_DIR = ROOT / "html" / "recommendation-preview"
OUT_JSON = OUT_DIR / "stock_research_backtest.json"
OUT_JS = OUT_DIR / "stock_research_backtest.js"
PRICE_CACHE = ROOT / "cache_online" / "recommendation_price_history.json"
TZ_BJ = timezone(timedelta(hours=8))

STRATEGIES = (
    ("next_day", "隔日收益", 1),
    ("hold_2d", "2日收益", 2),
    ("hold_3d", "3日收益", 3),
)

CAUTION_GAP_PCT = 5.0
FORCED_QUERY_TAGS = {"fore"}
SOURCE_HISTORY_SCHEMA = "stock_research_backtest_source_v1"
SOURCE_HISTORY_CLOSE_PUSH = "ztAnalysis.relay/watch.close_push"
MARKET_CLOSE_SECONDS = 15 * 3600
REALTIME_HTTP_RETRIES = 2


def _now_bj() -> datetime:
    return datetime.now(TZ_BJ)


def _normalize_query_tag(query_tag: str | None = None) -> str:
    raw = query_tag
    if raw in (None, ""):
        raw = os.environ.get("STOCK_RESEARCH_QUERY_TAG", "")
    return str(raw or "").strip().lower()


def _is_forced_query_tag(query_tag: str | None = None) -> bool:
    return _normalize_query_tag(query_tag) in FORCED_QUERY_TAGS


def _history_fetch_disabled() -> bool:
    return str(os.environ.get("QR_DISABLE_STOCK_RESEARCH_HISTORY_FETCH") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(part / total * 100.0, 1)


def _avg(values: list[float], digits: int = 2) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), digits)


def _strip_html(text: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", str(text or ""))
    return re.sub(r"\s+", " ", plain).strip()


def _code_with_suffix(code: str) -> str:
    c = str(code or "").strip()
    if "." in c:
        return c
    if c.startswith(("60", "68", "51", "56", "58", "11")):
        return f"{c}.SH"
    if c.startswith(("00", "20", "30", "12")):
        return f"{c}.SZ"
    if c.startswith(("4", "8", "9")):
        return f"{c}.BJ"
    return f"{c}.SZ"


def _normalize_bar(row: dict[str, Any]) -> dict[str, Any] | None:
    try:
        date10 = str(row.get("t") or "")[:10]
        open_price = float(row.get("o") or 0.0)
        close_price = float(row.get("c") or 0.0)
        high_price = float(row.get("h") or 0.0)
        low_price = float(row.get("l") or 0.0)
        prev_close = float(row.get("pc") or 0.0)
        suspended = int(float(row.get("sf") or 0)) == 1
    except Exception:
        return None
    if len(date10) != 10 or suspended or open_price <= 0 or close_price <= 0:
        return None
    return {
        "date": date10,
        "open": round(open_price, 2),
        "close": round(close_price, 2),
        "high": round(high_price, 2),
        "low": round(low_price, 2),
        "prev_close": round(prev_close, 2),
    }


def _load_price_cache() -> dict[str, Any]:
    data = _load_json(PRICE_CACHE, default={})
    if not isinstance(data, dict):
        return {"schema": "recommendation_price_history_v1", "codes": {}}
    data.setdefault("schema", "recommendation_price_history_v1")
    data.setdefault("codes", {})
    return data


def _save_price_cache(payload: dict[str, Any]) -> None:
    payload["updated_at_bj"] = _now_bj().strftime("%Y-%m-%d %H:%M:%S")
    _write_json(PRICE_CACHE, payload)


def _source_history_path() -> Path:
    return CACHE_DIR / "stock_research_backtest_source.json"


def _parse_bj_datetime(text: Any) -> datetime | None:
    raw = str(text or "").strip().replace("T", " ")
    if not raw:
        return None
    if len(raw) == 16:
        raw = f"{raw}:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=TZ_BJ)
    return parsed.astimezone(TZ_BJ)


def _seconds_of_day(current: datetime) -> int:
    return current.hour * 3600 + current.minute * 60 + current.second


def _is_after_close(current: datetime | None = None) -> bool:
    return _seconds_of_day(current or _now_bj()) >= MARKET_CLOSE_SECONDS


def _is_same_day_pre_close(timestamp_text: Any, date10: str) -> bool:
    if len(date10) != 10:
        return False
    parsed = _parse_bj_datetime(timestamp_text)
    if not parsed:
        return False
    return parsed.strftime("%Y-%m-%d") == date10 and _seconds_of_day(parsed) < MARKET_CLOSE_SECONDS


def _recommendation_date_from_source_item(item: dict[str, Any]) -> str:
    recommendation_date = str(item.get("recommendation_date") or "").strip()
    if len(recommendation_date) == 10:
        return recommendation_date
    rows = item.get("rows") if isinstance(item.get("rows"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_date10 = str(row.get("date10") or "").strip()
        if len(row_date10) == 10:
            return row_date10
    return ""


def _is_invalid_close_push_source_item(*, item: dict[str, Any]) -> bool:
    source = str(item.get("source") or "").strip()
    if source != SOURCE_HISTORY_CLOSE_PUSH:
        return False
    recommendation_date = _recommendation_date_from_source_item(item)
    if len(recommendation_date) != 10:
        return False
    generated_at_bj = str(item.get("generated_at_bj") or "").strip()
    pushed_at_bj = str(item.get("pushed_at_bj") or "").strip()
    if _is_same_day_pre_close(generated_at_bj, recommendation_date):
        return True
    if not generated_at_bj and _is_same_day_pre_close(pushed_at_bj, recommendation_date):
        return True
    return False


def _is_close_ready_market_data(market_data: dict[str, Any]) -> bool:
    if not isinstance(market_data, dict):
        return False
    date10 = str(market_data.get("date") or "").strip()
    if len(date10) != 10:
        return False
    current = _now_bj()
    today10 = current.strftime("%Y-%m-%d")
    if date10 != today10:
        return True
    meta = market_data.get("meta") if isinstance(market_data.get("meta"), dict) else {}
    asof = meta.get("asOf") if isinstance(meta.get("asOf"), dict) else {}
    generated_at = str(meta.get("generatedAt") or "").strip()
    generated_dt = _parse_bj_datetime(generated_at)
    if generated_dt and generated_dt.strftime("%Y-%m-%d") == date10 and _is_after_close(generated_dt):
        return True
    if isinstance(asof, dict):
        for key in ("indices", "pools", "themes"):
            if str(asof.get(key) or "").strip() == "收盘":
                return True
    return False


def _trade_days_cache_path_candidates() -> list[Path]:
    online_cache_dir = CACHE_DIR.parent / "cache_online"
    return [
        CACHE_DIR / "trade_days_cache.json",
        online_cache_dir / "trade_days_cache.json",
    ]


def _trade_day_dir_candidates() -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    online_cache_dir = CACHE_DIR.parent / "cache_online"
    for path in (CACHE_DIR, online_cache_dir):
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _clean_trade_days(days: list[Any]) -> list[str]:
    cleaned = [str(day).strip() for day in days if re.match(r"^\d{4}-\d{2}-\d{2}$", str(day).strip())]
    return sorted(dict.fromkeys(cleaned))


def _load_trade_days_from_payload(path: Path) -> list[str]:
    data = _load_json(path, default={})
    if isinstance(data, dict):
        days = data.get("days")
        if isinstance(days, list):
            return _clean_trade_days(days)
    if isinstance(data, list):
        return _clean_trade_days(data)
    return []


def _load_trade_days_from_pools_cache(path: Path) -> list[str]:
    data = _load_json(path, default={})
    if not isinstance(data, dict):
        return []
    pools = data.get("pools") if isinstance(data.get("pools"), dict) else {}
    if not isinstance(pools, dict):
        return []
    days: list[Any] = []
    for pool_name in ("ztgc", "dtgc", "zbgc", "qsgc"):
        rows = pools.get(pool_name)
        if isinstance(rows, dict):
            days.extend(rows.keys())
    return _clean_trade_days(days)


def _load_trade_days_from_market_data_dir(path: Path) -> list[str]:
    out: list[str] = []
    try:
        for fp in path.glob("market_data-*.json"):
            m = re.match(r"market_data-(\d{8})\.json$", fp.name)
            if not m:
                continue
            d8 = m.group(1)
            out.append(f"{d8[:4]}-{d8[4:6]}-{d8[6:8]}")
    except Exception:
        return []
    return _clean_trade_days(out)


def _load_trade_days() -> list[str]:
    merged: set[str] = set()
    for path in _trade_days_cache_path_candidates():
        merged.update(_load_trade_days_from_payload(path))
    for path in _trade_day_dir_candidates():
        merged.update(_load_trade_days_from_pools_cache(path / "pools_cache.json"))
        merged.update(_load_trade_days_from_market_data_dir(path))
    return sorted(merged)


def _next_weekday(date10: str) -> str:
    current = datetime.strptime(date10, "%Y-%m-%d")
    probe = current + timedelta(days=1)
    while probe.weekday() >= 5:
        probe += timedelta(days=1)
    return probe.strftime("%Y-%m-%d")


def _resolve_next_trade_date(date10: str, *, trade_days: list[str] | None = None) -> str:
    days = trade_days if trade_days is not None else _load_trade_days()
    if days:
        future = [day for day in days if day > date10]
        if future:
            return future[0]
    return _next_weekday(date10)


def _resolve_trade_date10_for_reference_date(
    reference_date10: str,
    current_trade_date10: str = "",
    *,
    trade_days: list[str] | None = None,
) -> str:
    if len(reference_date10) != 10:
        return str(current_trade_date10 or "").strip()
    known_trade_days = trade_days if trade_days is not None else _load_trade_days()
    trade_day_set = set(known_trade_days)
    existing = str(current_trade_date10 or "").strip()
    resolved = _resolve_next_trade_date(reference_date10, trade_days=known_trade_days) if known_trade_days else ""
    if len(existing) == 10 and existing > reference_date10:
        if not trade_day_set:
            return existing
        if existing in trade_day_set:
            return existing
        if resolved and resolved != existing:
            return resolved
        return existing
    if resolved:
        return resolved
    return existing or _next_weekday(reference_date10)


def _upgrade_rows_trade_dates(rows: list[dict[str, Any]], *, trade_days: list[str] | None = None) -> list[dict[str, Any]]:
    upgraded: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        record = dict(row)
        reference_date10 = str(record.get("date10") or "").strip()
        current_trade_date10 = str(record.get("trade_date10") or record.get("trade_date") or "").strip()
        resolved_trade_date10 = _resolve_trade_date10_for_reference_date(
            reference_date10,
            current_trade_date10,
            trade_days=trade_days,
        )
        if resolved_trade_date10:
            record["trade_date10"] = resolved_trade_date10
            if "trade_date" in record:
                record["trade_date"] = resolved_trade_date10
        upgraded.append(record)
    return upgraded


def _upgrade_realtime_buy_trade_date(
    realtime_buy: dict[str, Any],
    *,
    trade_days: list[str] | None = None,
) -> dict[str, Any]:
    upgraded = dict(realtime_buy)
    reference_date10 = str(upgraded.get("reference_date") or "").strip()
    current_trade_date10 = str(upgraded.get("trade_date") or "").strip()
    resolved_trade_date10 = _resolve_trade_date10_for_reference_date(
        reference_date10,
        current_trade_date10,
        trade_days=trade_days,
    )
    if resolved_trade_date10:
        upgraded["trade_date"] = resolved_trade_date10
    for bucket in ("buy_list", "pending_list", "rejected_list", "unavailable_list"):
        rows = upgraded.get(bucket)
        if isinstance(rows, list):
            upgraded[bucket] = _upgrade_rows_trade_dates(rows, trade_days=trade_days)
    return upgraded


def _upgrade_historical_snapshots(
    historical_snapshots: list[dict[str, Any]],
    backtest_rows: list[dict[str, Any]],
    *,
    trade_days: list[str] | None = None,
) -> list[dict[str, Any]]:
    if not historical_snapshots:
        return _build_historical_snapshots(backtest_rows) if backtest_rows else []

    trade_date_by_reference: dict[str, str] = {}
    for row in backtest_rows:
        if not isinstance(row, dict):
            continue
        reference_date10 = str(row.get("date10") or "").strip()
        trade_date10 = str(row.get("trade_date10") or "").strip()
        if len(reference_date10) == 10 and len(trade_date10) == 10:
            trade_date_by_reference[reference_date10] = trade_date10

    upgraded: list[dict[str, Any]] = []
    for item in historical_snapshots:
        if not isinstance(item, dict):
            continue
        snapshot = dict(item)
        reference_date10 = str(snapshot.get("reference_date") or "").strip()
        for bucket in ("buy_list", "pending_list", "rejected_list", "unavailable_list"):
            rows = snapshot.get(bucket)
            if isinstance(rows, list):
                snapshot[bucket] = _upgrade_rows_trade_dates(rows, trade_days=trade_days)
        resolved_trade_date10 = trade_date_by_reference.get(reference_date10)
        if not resolved_trade_date10 and len(reference_date10) == 10:
            resolved_trade_date10 = _resolve_trade_date10_for_reference_date(
                reference_date10,
                str(snapshot.get("trade_date") or snapshot.get("trade_date10") or "").strip(),
                trade_days=trade_days,
            )
        if resolved_trade_date10:
            snapshot["trade_date"] = resolved_trade_date10
            snapshot["trade_date10"] = resolved_trade_date10
        upgraded.append(snapshot)
    return upgraded


def _is_open_session(now: datetime | None = None) -> bool:
    current = now or _now_bj()
    total = current.hour * 3600 + current.minute * 60 + current.second
    return 9 * 3600 + 30 * 60 <= total < 15 * 3600


def _get_price_histories(codes: list[str], *, st8: str, et8: str) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    cache = _load_price_cache()
    code_cache = cache.setdefault("codes", {})
    histories: dict[str, list[dict[str, Any]]] = {}
    history_fetch_disabled = _history_fetch_disabled()
    diagnostics: dict[str, Any] = {
        "source": "cache_only" if history_fetch_disabled else "cache+api",
        "fetched": 0,
        "cached": 0,
        "missing": [],
        "history_fetch_disabled": history_fetch_disabled,
    }

    client = None
    if not history_fetch_disabled:
        cfg = load_config_from_env()
        client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=12, retries=0)

    for code in codes:
        cached = code_cache.get(code) if isinstance(code_cache.get(code), dict) else {}
        cached_bars = cached.get("bars") if isinstance(cached.get("bars"), list) else []
        earliest = cached_bars[0]["date"].replace("-", "") if cached_bars else ""
        latest = cached_bars[-1]["date"].replace("-", "") if cached_bars else ""
        if cached_bars and earliest <= st8 and latest >= et8:
            histories[code] = cached_bars
            diagnostics["cached"] += 1
            continue

        if history_fetch_disabled:
            if cached_bars:
                histories[code] = cached_bars
                diagnostics["cached"] += 1
            else:
                diagnostics["missing"].append(code)
            continue

        rows = fetch_stock_history_k(client, code=_code_with_suffix(code), st=st8, et=et8)
        bars = [bar for bar in (_normalize_bar(row) for row in rows if isinstance(row, dict)) if bar]
        bars.sort(key=lambda x: x["date"])
        if bars:
            histories[code] = bars
            code_cache[code] = {"code": code, "bars": bars}
            diagnostics["fetched"] += 1
        elif cached_bars:
            histories[code] = cached_bars
            diagnostics["cached"] += 1
        else:
            diagnostics["missing"].append(code)

    cache["requested_range"] = {"st": st8, "et": et8}
    _save_price_cache(cache)
    return histories, diagnostics


def _parse_expected_range(text: str) -> tuple[float, float] | None:
    m = re.search(r"([+-]?\d+(?:\.\d+)?)%\s*~\s*([+-]?\d+(?:\.\d+)?)%", text)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def _parse_super_open_threshold(text: str) -> float | None:
    m = re.search(r"高开≥\+?([+-]?\d+(?:\.\d+)?)%", text)
    if m:
        return float(m.group(1))
    m = re.search(r"高开≥([+-]?\d+(?:\.\d+)?)%", text)
    if m:
        return float(m.group(1))
    return None


def _parse_amount_threshold_yi(text: str, pattern: str) -> float | None:
    m = re.search(pattern, text)
    if not m:
        return None
    return round(float(m.group(1)), 2)


def _parse_open_board_limit(text: str) -> int | None:
    m = re.search(r"开板≤\s*(\d+)", text)
    if not m:
        return None
    return int(m.group(1))


def _parse_surge_threshold(text: str) -> float | None:
    m = re.search(r"盘中冲高确认（竞价价\+≥([\d.]+)%）", text)
    if not m:
        return None
    return float(m.group(1))


def _parse_volume_expand_ratio(text: str) -> float | None:
    m = re.search(r"量能.*≥竞价量×([\d.]+)", text)
    if not m:
        return None
    return float(m.group(1))


def _extract_expectation(reason_html: str) -> dict[str, Any]:
    flat = _strip_html(reason_html)
    expected_match = re.search(r"预期\s*(.+?)(?=\s*超预期|\s*低预期|$)", flat)
    super_match = re.search(r"超预期\s*(.+?)(?=\s*低预期|$)", flat)
    low_match = re.search(r"低预期\s*(.+?)$", flat)
    expected_text = expected_match.group(1).strip(" ：:;") if expected_match else ""
    super_text = super_match.group(1).strip(" ：:;") if super_match else ""
    low_text = low_match.group(1).strip(" ：:;") if low_match else ""
    # 新版条件（冲高/量能）优先；旧版（回封/封单/开板）向后兼容
    has_new_conditions = "冲高确认" in super_text or "量能" in super_text
    return {
        "expected_text": expected_text,
        "super_text": super_text,
        "low_text": low_text,
        "expected_range": _parse_expected_range(expected_text),
        "super_gap_min": _parse_super_open_threshold(super_text),
        "auction_amount_min_yi": _parse_amount_threshold_yi(super_text, r"竞价成交额≥\s*([0-9]+(?:\.[0-9]+)?)亿"),
        # 新版：冲高/量能确认条件
        "surge_pct_min": _parse_surge_threshold(super_text) if has_new_conditions else None,
        "volume_expand_ratio": _parse_volume_expand_ratio(super_text) if has_new_conditions else None,
        # 旧版兼容：回封/封单/开板
        "super_requires_reseal": "回封" in super_text if not has_new_conditions else False,
        "super_requires_open_board_limit": _parse_open_board_limit(super_text) if not has_new_conditions else None,
        "seal_amount_min_yi": _parse_amount_threshold_yi(super_text, r"(?:封单回补|回封后封单)≥\s*([0-9]+(?:\.[0-9]+)?)亿") if not has_new_conditions else None,
        "raw_text": flat,
    }


def _row_from_item(item: dict[str, Any], *, date10: str, bucket: str) -> dict[str, Any]:
    market_gate = item.get("marketGate") if isinstance(item.get("marketGate"), dict) else {}
    expectation = _extract_expectation(str(item.get("reason") or ""))
    theme_ladder = item.get("themeLadderProfile") if isinstance(item.get("themeLadderProfile"), dict) else {}
    hit_rules = [str(x).strip() for x in (item.get("hitRules") or []) if str(x).strip()]
    block_reasons = [str(x).strip() for x in (item.get("blockReasons") or []) if str(x).strip()]
    return {
        "date": date10.replace("-", ""),
        "date10": date10,
        "code": str(item.get("code") or "").strip(),
        "name": str(item.get("name") or "").strip(),
        "bucket": bucket,
        "bucket_label": "接力候选" if bucket == "relay" else "观察池",
        "score": int(round(float(item.get("factorScore") or item.get("score") or 0))),
        "score_band": str(item.get("scoreBand") or "").strip(),
        "score_sub_label": str(item.get("scoreSubLabel") or "").strip(),
        "main_line": str(item.get("predTheme") or "").strip(),
        "style_tag": str(item.get("qualityLabel") or "").strip(),
        "lbc": int(round(float(item.get("lbc") or 0))),
        "cje_yi": round(float(item.get("cjeYi") or 0.0), 2),
        "turnover": round(float(item.get("capacityFactorScore") or 0.0), 2),
        "tide_status": str(market_gate.get("label") or "").strip(),
        "next_step": str(item.get("nextStep") or "").strip(),
        "plate_name": str(item.get("plateName") or "").strip(),
        "hy": str(item.get("hy") or "").strip(),
        "factor_hint": str(item.get("factorHint") or "").strip(),
        "relay_rank": int(round(float(item.get("relayRank") or 0))) if item.get("relayRank") not in (None, "") else 0,
        "watch_rank": int(round(float(item.get("watchRank") or 0))) if item.get("watchRank") not in (None, "") else 0,
        "relay_selection_mode": str(item.get("relaySelectionMode") or "").strip(),
        "watch_group": str(item.get("watchGroup") or "").strip(),
        "score_label": str(item.get("scoreLabel") or "").strip(),
        "placement_label": "接力候选" if bucket == "relay" else "观察池",
        "leader_factor_score": round(float(item.get("leaderFactorScore") or 0.0), 2),
        "relay_factor_score": round(float(item.get("relayFactorScore") or 0.0), 2),
        "leader_philosophy_score": round(float(item.get("leaderPhilosophyScore") or 0.0), 2),
        "break_risk": round(float(item.get("breakRisk") or 0.0), 2),
        "environment_score": round(float(item.get("environmentScore") or 0.0), 2),
        "capacity_factor_score": round(float(item.get("capacityFactorScore") or 0.0), 2),
        "step_context_score": round(float(item.get("stepContextScore") or 0.0), 2),
        "tide_relay_gate": round(float(item.get("tideRelayGate") or 0.0), 2),
        "theme_ladder_profile": {
            "label": str(theme_ladder.get("label") or "").strip(),
            "score": round(float(theme_ladder.get("score") or 0.0), 2),
            "gap_count": int(round(float(theme_ladder.get("gapCount") or 0))) if theme_ladder.get("gapCount") not in (None, "") else 0,
            "front_count": int(round(float(theme_ladder.get("frontCount") or 0))) if theme_ladder.get("frontCount") not in (None, "") else 0,
            "leader_boards": int(round(float(theme_ladder.get("leaderBoards") or 0))) if theme_ladder.get("leaderBoards") not in (None, "") else 0,
            "has_carry": bool(theme_ladder.get("hasCarry")),
        },
        "hit_rules": hit_rules,
        "block_reasons": block_reasons,
        "reason_html": str(item.get("reason") or ""),
        "reason_text": _strip_html(item.get("reason") or ""),
        "expectation": expectation,
    }


def _load_source_history() -> dict[str, Any]:
    data = _load_json(_source_history_path(), default={})
    if not isinstance(data, dict):
        return {"schema": SOURCE_HISTORY_SCHEMA, "dates": {}}
    data.setdefault("schema", SOURCE_HISTORY_SCHEMA)
    data.setdefault("dates", {})
    return data


def _save_source_history(payload: dict[str, Any]) -> None:
    payload["updated_at_bj"] = _now_bj().strftime("%Y-%m-%d %H:%M:%S")
    _write_json(_source_history_path(), payload)


def sync_stock_research_backtest_source(*, market_data: dict[str, Any]) -> bool:
    if not isinstance(market_data, dict):
        return False
    date10 = str(market_data.get("date") or "").strip()
    if len(date10) != 10:
        return False
    meta = market_data.get("meta") if isinstance(market_data.get("meta"), dict) else {}
    if str(meta.get("mode") or "").strip() == "intraday":
        return False
    if not _is_close_ready_market_data(market_data):
        return False
    zt = market_data.get("ztAnalysis") if isinstance(market_data.get("ztAnalysis"), dict) else {}
    relay = zt.get("relay") if isinstance(zt.get("relay"), list) else []
    watch = zt.get("watch") if isinstance(zt.get("watch"), list) else []
    if not relay and not watch:
        return False

    rows = [_row_from_item(item, date10=date10, bucket="relay") for item in relay if isinstance(item, dict)]
    rows.extend(_row_from_item(item, date10=date10, bucket="watch") for item in watch if isinstance(item, dict))
    if not rows:
        return False
    trade_days = _load_trade_days()
    trade_date10 = _resolve_next_trade_date(date10, trade_days=trade_days)
    for row in rows:
        row["trade_date10"] = trade_date10

    history = _load_source_history()
    dates = history.setdefault("dates", {})
    dates[trade_date10] = {
        "date": trade_date10,
        "recommendation_date": date10,
        "source": SOURCE_HISTORY_CLOSE_PUSH,
        "generated_at_bj": str(meta.get("generatedAt") or "").strip(),
        "pushed_at_bj": _now_bj().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": rows,
    }
    _save_source_history(history)
    return True


def _iter_valid_source_history_items(history: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    dates = history.get("dates") if isinstance(history.get("dates"), dict) else {}
    trade_days = _load_trade_days()
    items: list[tuple[str, dict[str, Any]]] = []
    for trade_date10 in sorted(dates.keys()):
        item = dates.get(trade_date10)
        if not isinstance(item, dict):
            continue
        day_rows = item.get("rows") if isinstance(item.get("rows"), list) else []
        upgraded_rows = _upgrade_rows_trade_dates(day_rows, trade_days=trade_days)
        if not day_rows:
            continue
        if _is_invalid_close_push_source_item(item=item):
            continue
        resolved_trade_date10 = ""
        if upgraded_rows:
            resolved_trade_date10 = str(upgraded_rows[0].get("trade_date10") or "").strip()
        if not resolved_trade_date10:
            resolved_trade_date10 = _resolve_trade_date10_for_reference_date(
                _recommendation_date_from_source_item(item),
                trade_date10,
                trade_days=trade_days,
            )
        upgraded_item = dict(item)
        upgraded_item["rows"] = upgraded_rows
        if resolved_trade_date10:
            upgraded_item["date"] = resolved_trade_date10
        items.append((resolved_trade_date10 or trade_date10, upgraded_item))
    items.sort(key=lambda pair: pair[0])
    return items


def get_latest_stock_research_source_snapshot() -> dict[str, Any]:
    history = _load_source_history()
    valid_items = _iter_valid_source_history_items(history)
    if not valid_items:
        return {}
    latest_trade_date, latest_item = valid_items[-1]
    rows = latest_item.get("rows") if isinstance(latest_item.get("rows"), list) else []
    return {
        "trade_date": latest_trade_date,
        "recommendation_date": _recommendation_date_from_source_item(latest_item),
        "rows_count": len(rows),
        "pushed_at_bj": str(latest_item.get("pushed_at_bj") or "").strip(),
        "generated_at_bj": str(latest_item.get("generated_at_bj") or "").strip(),
        "source": str(latest_item.get("source") or "").strip(),
    }


def _load_stock_research_rows() -> tuple[list[dict[str, Any]], list[str]]:
    history = _load_source_history()

    rows: list[dict[str, Any]] = []
    used_sources: list[str] = []
    for date10, item in _iter_valid_source_history_items(history):
        day_rows = item.get("rows") if isinstance(item.get("rows"), list) else []
        used_sources.append(str(item.get("source") or f"stock_research_backtest_source:{date10}"))
        rows.extend(day_rows)
    rows.sort(key=lambda x: (x["date"], -x["score"], x["code"]))
    return rows, used_sources


def _row_selection_priority(row: dict[str, Any]) -> tuple[float, ...]:
    bucket = str(row.get("bucket") or "").strip()
    relay_rank = int(row.get("relay_rank") or 0)
    watch_rank = int(row.get("watch_rank") or 0)
    watch_group = str(row.get("watch_group") or "").strip()
    hit_rules = [str(x).strip() for x in (row.get("hit_rules") or []) if str(x).strip()]
    block_reasons = [str(x).strip() for x in (row.get("block_reasons") or []) if str(x).strip()]
    theme_ladder = row.get("theme_ladder_profile") if isinstance(row.get("theme_ladder_profile"), dict) else {}

    primary_rank = relay_rank if relay_rank > 0 else watch_rank if watch_rank > 0 else 999
    bucket_bias = 0 if bucket == "relay" else 1 if bucket == "watch" else 2
    watch_group_rank = {
        "高标/题材核心": 0,
        "高位分歧": 1,
        "容量核心": 2,
        "风险观察": 3,
        "补充观察": 4,
    }.get(watch_group, 5)
    core_hit = 1 if any(rule in {"高标龙头", "主线接力", "高度突破"} for rule in hit_rules) else 0
    one_to_two_hit = 1 if "1进2" in hit_rules else 0
    broad_only = 1 if any("题材偏泛化" in reason for reason in block_reasons) else 0
    ladder_gap = int(theme_ladder.get("gap_count") or 0)

    return (
        bucket_bias,
        primary_rank,
        watch_group_rank,
        -core_hit,
        -one_to_two_hit,
        -float(row.get("leader_factor_score") or 0.0),
        -float(row.get("relay_factor_score") or 0.0),
        -float(row.get("leader_philosophy_score") or 0.0),
        -float(row.get("step_context_score") or 0.0),
        float(row.get("break_risk") or 0.0),
        broad_only,
        ladder_gap,
        -int(row.get("lbc") or 0),
        -int(row.get("score") or 0),
        str(row.get("code") or ""),
    )


def _sort_rows_by_selection_priority(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = [dict(row) for row in rows]
    ordered.sort(key=_row_selection_priority)
    return ordered


def _attach_daily_rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("date10") or "")].append(dict(row))

    ranked_rows: list[dict[str, Any]] = []
    for date10 in sorted(grouped.keys()):
        day_rows = _sort_rows_by_selection_priority(grouped[date10])
        for idx, row in enumerate(day_rows, start=1):
            row["daily_rank"] = idx
            ranked_rows.append(row)

    ranked_rows.sort(key=lambda x: (x["date"], *_row_selection_priority(x)))
    return ranked_rows


def _pick_active_trade_date(rows: list[dict[str, Any]], *, now: datetime | None = None) -> str:
    trade_dates = sorted({str(row.get("trade_date10") or "") for row in rows if str(row.get("trade_date10") or "")})
    if not trade_dates:
        return ""
    current = now or _now_bj()
    today10 = current.strftime("%Y-%m-%d")
    if _is_open_session(current) and today10 in trade_dates:
        return today10
    recommendation_dates = sorted({str(row.get("date10") or "") for row in rows if str(row.get("date10") or "")})
    latest_recommendation_date = recommendation_dates[-1] if recommendation_dates else ""
    if latest_recommendation_date:
        target_trade_date = _resolve_next_trade_date(latest_recommendation_date)
        if target_trade_date in trade_dates:
            return target_trade_date
    future_or_today = [date10 for date10 in trade_dates if date10 >= today10]
    if future_or_today:
        return future_or_today[0]
    return trade_dates[-1]


def _has_realtime_snapshot_payload(realtime_buy: dict[str, Any] | None) -> bool:
    return _has_valid_current_realtime_snapshot_payload(realtime_buy)


def _quote_time_matches_trade_date(quote_time: str, trade_date10: str) -> bool:
    quote_text = str(quote_time or "").strip()
    trade_date_text = str(trade_date10 or "").strip()
    return len(trade_date_text) == 10 and quote_text.startswith(f"{trade_date_text} ")


def _has_valid_current_realtime_snapshot_payload(
    realtime_buy: dict[str, Any] | None,
    *,
    active_trade_date10: str = "",
) -> bool:
    if not isinstance(realtime_buy, dict):
        return False
    reference_date = str(realtime_buy.get("reference_date") or "").strip()
    trade_date10 = str(realtime_buy.get("trade_date") or "").strip()
    expected_trade_date10 = str(active_trade_date10 or trade_date10).strip()
    quote_time = str(realtime_buy.get("quote_time") or "").strip()
    quoted_count = int(realtime_buy.get("quoted_count") or 0)
    diagnostics = realtime_buy.get("diagnostics") if isinstance(realtime_buy.get("diagnostics"), dict) else {}
    forced_query = bool(diagnostics.get("forced_query"))
    if not reference_date or quoted_count <= 0 or not quote_time or len(expected_trade_date10) != 10:
        return False
    if trade_date10 and trade_date10 != expected_trade_date10:
        return False
    if not _quote_time_matches_trade_date(quote_time, expected_trade_date10):
        return False
    return forced_query or _is_entry_window_time(quote_time)


def _resolve_display_anchors(
    *,
    current_pool_rows: list[dict[str, Any]],
    backtest_rows: list[dict[str, Any]],
    historical_snapshots: list[dict[str, Any]],
    realtime_buy: dict[str, Any],
    active_trade_date10: str,
    latest_recommendation_date10: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or _now_bj()
    today10 = current.strftime("%Y-%m-%d")

    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in historical_snapshots:
        if not isinstance(item, dict):
            continue
        reference_date = str(item.get("reference_date") or "").strip()
        trade_date = str(item.get("trade_date") or item.get("trade_date10") or "").strip()
        if len(reference_date) != 10 or len(trade_date) != 10:
            continue
        key = (reference_date, trade_date)
        if key in seen:
            continue
        seen.add(key)
        candidates.append({"recommendation_date": reference_date, "trade_date": trade_date})

    if not candidates:
        fallback_candidates: dict[tuple[str, str], dict[str, str]] = {}
        for row in backtest_rows:
            reference_date = str(row.get("date10") or "").strip()
            trade_date = str(row.get("trade_date10") or "").strip()
            if len(reference_date) != 10 or len(trade_date) != 10:
                continue
            fallback_candidates[(reference_date, trade_date)] = {
                "recommendation_date": reference_date,
                "trade_date": trade_date,
            }
        candidates = list(fallback_candidates.values())

    candidates.sort(key=lambda item: (item["trade_date"], item["recommendation_date"]))
    latest_closed = candidates[-1] if candidates else {}
    default_closed = {}
    for item in reversed(candidates):
        trade_date = str(item.get("trade_date") or "").strip()
        if trade_date and trade_date <= today10:
            default_closed = item
            break
    if not default_closed:
        default_closed = latest_closed

    has_current_plan = bool(current_pool_rows)
    default_display = dict(default_closed) if default_closed else {}
    realtime_reference_date10 = str(realtime_buy.get("reference_date") or "").strip()
    realtime_trade_date10 = str(realtime_buy.get("trade_date") or "").strip()
    is_today_pending_or_missing = bool(
        has_current_plan
        and active_trade_date10
        and active_trade_date10 <= today10
        and not _has_valid_current_realtime_snapshot_payload(realtime_buy, active_trade_date10=active_trade_date10)
    )
    has_pending_next_trade_day = bool(current_pool_rows and active_trade_date10 and active_trade_date10 > today10)
    if has_current_plan and not has_pending_next_trade_day:
        current_reference_dates = sorted(
            {
                str(row.get("date10") or "").strip()
                for row in current_pool_rows
                if len(str(row.get("date10") or "").strip()) == 10
            }
        )
        current_reference_date10 = current_reference_dates[-1] if current_reference_dates else latest_recommendation_date10
        default_display = {
            "recommendation_date": current_reference_date10,
            "trade_date": active_trade_date10,
        }
    elif (
        _has_valid_current_realtime_snapshot_payload(realtime_buy, active_trade_date10=active_trade_date10)
        and len(realtime_reference_date10) == 10
        and len(realtime_trade_date10) == 10
        and realtime_trade_date10 <= today10
    ):
        default_display = {
            "recommendation_date": realtime_reference_date10,
            "trade_date": realtime_trade_date10,
        }

    latest_closed_trade_date10 = str(latest_closed.get("trade_date") or "").strip()
    latest_closed_recommendation_date10 = str(latest_closed.get("recommendation_date") or "").strip()
    default_display_trade_date10 = str(default_display.get("trade_date") or "").strip()
    default_display_recommendation_date10 = str(default_display.get("recommendation_date") or "").strip()

    if is_today_pending_or_missing and default_display_trade_date10 and default_display_recommendation_date10:
        default_display_note = (
            f"页面默认停留在 {default_display_trade_date10} 这批待验证结果（对应推荐日 {default_display_recommendation_date10}），"
            "不会自动回退到历史闭环。"
        )
    elif has_pending_next_trade_day and latest_closed_trade_date10 and default_display_trade_date10 and default_display_recommendation_date10:
        default_display_note = (
            f"已生成下一交易日 {active_trade_date10 or '-'} 的待验证池，"
            f"页面默认仍展示最近已闭环日 {default_display_trade_date10}（对应推荐日 {default_display_recommendation_date10}）。"
        )
    elif default_display_trade_date10 and default_display_recommendation_date10:
        default_display_note = (
            f"页面默认展示 {default_display_trade_date10} 的结果（对应推荐日 {default_display_recommendation_date10}）。"
        )
    elif default_display_trade_date10:
        default_display_note = f"页面默认展示 {default_display_trade_date10} 的结果。"
    else:
        default_display_note = "当前还没有可默认展示的闭环结果。"

    return {
        "latest_closed_trade_date": latest_closed_trade_date10,
        "latest_closed_recommendation_date": latest_closed_recommendation_date10,
        "default_display_trade_date": default_display_trade_date10,
        "default_display_recommendation_date": default_display_recommendation_date10,
        "has_pending_next_trade_day": has_pending_next_trade_day,
        "default_display_note": default_display_note,
    }


def _build_lifecycle(
    *,
    latest_recommendation_date10: str,
    active_trade_date10: str,
    latest_backtest_date10: str,
    latest_closed_trade_date10: str,
    latest_closed_recommendation_date10: str,
    default_display_trade_date10: str,
    default_display_recommendation_date10: str,
    has_pending_next_trade_day: bool,
    default_display_note: str,
    current_pool_rows: list[dict[str, Any]],
    backtest_rows: list[dict[str, Any]],
    realtime_buy: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or _now_bj()
    today10 = current.strftime("%Y-%m-%d")
    now_seconds = _seconds_of_day(current)
    quote_time = str(realtime_buy.get("quote_time") or "").strip()
    quoted_count = int(realtime_buy.get("quoted_count") or 0)
    candidate_count = int(realtime_buy.get("candidate_count") or 0)
    diagnostics = realtime_buy.get("diagnostics") if isinstance(realtime_buy.get("diagnostics"), dict) else {}
    forced_query = bool(diagnostics.get("forced_query"))
    has_current_plan = bool(current_pool_rows)
    has_historical_records = bool(backtest_rows)
    has_realtime_snapshot = _has_valid_current_realtime_snapshot_payload(
        realtime_buy,
        active_trade_date10=active_trade_date10,
    )

    quote_state = "pending_source"
    quote_state_label = "等待推送"
    quote_state_note = "当前还没有落地到可读的竞价引用日。"

    if has_realtime_snapshot:
        quote_state = "ready"
        if forced_query:
            quote_state_label = "快照已补齐"
            quote_state_note = f"今日缺失的竞价快照已补齐，时间 {quote_time or '-'}。"
        else:
            quote_state_label = "快照已落地"
            quote_state_note = f"9:25 竞价快照已生成，时间 {quote_time or '-'}。"
    elif has_current_plan:
        if active_trade_date10 and active_trade_date10 > today10:
            quote_state = "waiting_trade_day"
            quote_state_label = "等待明日竞价"
            quote_state_note = (
                f"盘后样本已经推到推荐日 {latest_recommendation_date10 or '-'}，已生成 {active_trade_date10} 的待验证池；"
                "等待明日 09:25-09:30 竞价快照。"
                f" {default_display_note}"
            ).strip()
        elif active_trade_date10 and active_trade_date10 == today10:
            if now_seconds < 9 * 3600 + 25 * 60:
                quote_state = "waiting_window"
                quote_state_label = "等待开盘窗口"
                quote_state_note = f"今天要验证 {active_trade_date10}，需等 09:25-09:30 才能落地真实竞价结果。"
            elif _should_request_realtime_quotes(current):
                quote_state = "window_live"
                quote_state_label = "窗口进行中"
                quote_state_note = "当前正处于 09:25-09:30，可直接抓取实时竞价结果。"
            else:
                quote_state = "missing"
                quote_state_label = "快照缺失"
                quote_state_note = f"{active_trade_date10} 的 09:25 竞价窗口已过，但没有拿到有效快照；当前仅保留今日待验证池，需补抓后才能展示真实闭环结果。"
        else:
            quote_state = "missing" if candidate_count > 0 else "pending_source"
            quote_state_label = "快照缺失" if candidate_count > 0 else "等待推送"
            quote_state_note = "当前待验证池存在，但缺少可用的 9:25 竞价快照。"
    elif has_historical_records:
        quote_state = "historical_only"
        quote_state_label = "仅历史统计"
        quote_state_note = "当前没有待验证池，仅保留历史胜率和样本明细。"

    stage = "empty"
    stage_label = "暂无数据"
    stage_note = "当前还没有可展示的个股回测样本。"
    if has_current_plan and has_realtime_snapshot:
        stage = "auction_snapshot_ready"
        if forced_query:
            stage_label = "竞价结果已补齐"
            stage_note = f"推荐日 {latest_recommendation_date10 or '-'} 的待验证池缺失快照已补齐，当前可按正常闭环查看竞价命中结果。"
        else:
            stage_label = "竞价结果已落地"
            stage_note = f"推荐日 {latest_recommendation_date10 or '-'} 的待验证池已匹配到 {active_trade_date10 or '-'} 9:25 竞价结果，历史统计与当前快照都可同时查看。"
    elif has_current_plan:
        if quote_state in {"waiting_trade_day", "waiting_window", "window_live"}:
            stage = "post_close_wait_auction"
            stage_label = "盘后待验证"
            stage_note = (
                f"收盘后样本已经更新到推荐日 {latest_recommendation_date10 or '-'}；"
                f"{active_trade_date10 or '-'} 这批待验证推荐已准备好，明日 09:25-09:30 再补真实竞价结果。 {default_display_note}"
            ).strip()
        else:
            stage = "auction_snapshot_missing"
            stage_label = "竞价快照缺失"
            stage_note = f"待验证池已经存在，但 {active_trade_date10 or '-'} 的 9:25 快照没有成功落地；页面会停留在当前批次，不再自动跳到历史闭环结果。"
    elif has_historical_records:
        stage = "historical_only"
        stage_label = "仅历史统计"
        stage_note = "当前没有新待验证池，页面仅展示历史样本和策略表现。"

    return {
        "stage": stage,
        "stage_label": stage_label,
        "stage_note": stage_note,
        "quote_state": quote_state,
        "quote_state_label": quote_state_label,
        "quote_state_note": quote_state_note,
        "has_current_plan": has_current_plan,
        "has_historical_records": has_historical_records,
        "has_realtime_snapshot": has_realtime_snapshot,
        "latest_recommendation_date": latest_recommendation_date10,
        "active_trade_date": active_trade_date10,
        "latest_historical_recommendation_date": latest_backtest_date10,
        "latest_closed_trade_date": latest_closed_trade_date10,
        "latest_closed_recommendation_date": latest_closed_recommendation_date10,
        "default_display_trade_date": default_display_trade_date10,
        "default_display_recommendation_date": default_display_recommendation_date10,
        "has_pending_next_trade_day": has_pending_next_trade_day,
        "default_display_note": default_display_note,
        "realtime_reference_date": str(realtime_buy.get("reference_date") or "").strip(),
        "quote_time": quote_time,
        "forced_query": forced_query,
    }


def upgrade_stock_research_backtest_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if str(payload.get("schema") or "") != "stock_research_backtest_v2":
        return payload

    upgraded = json.loads(json.dumps(payload, ensure_ascii=False))
    meta = upgraded.get("meta") if isinstance(upgraded.get("meta"), dict) else {}
    trade_days = _load_trade_days()
    realtime_buy = upgraded.get("realtimeBuy") if isinstance(upgraded.get("realtimeBuy"), dict) else {}
    current_pool_rows = upgraded.get("currentPoolRecords") if isinstance(upgraded.get("currentPoolRecords"), list) else []
    backtest_rows = upgraded.get("records") if isinstance(upgraded.get("records"), list) else []
    display_rows = upgraded.get("displayRecords") if isinstance(upgraded.get("displayRecords"), list) else []
    current_pool_rows = _upgrade_rows_trade_dates(current_pool_rows, trade_days=trade_days)
    backtest_rows = _upgrade_rows_trade_dates(backtest_rows, trade_days=trade_days)
    display_rows = _upgrade_rows_trade_dates(display_rows or backtest_rows, trade_days=trade_days)
    realtime_buy = _upgrade_realtime_buy_trade_date(realtime_buy, trade_days=trade_days)
    latest_recommendation_date10 = str(meta.get("latest_recommendation_date") or realtime_buy.get("reference_date") or "").strip()
    active_trade_date10 = str(meta.get("active_trade_date") or realtime_buy.get("trade_date") or "").strip()
    historical_snapshots = (
        upgraded.get("historicalSnapshots")
        if isinstance(upgraded.get("historicalSnapshots"), list)
        else _build_historical_snapshots(backtest_rows)
    )
    historical_snapshots = _upgrade_historical_snapshots(historical_snapshots, backtest_rows, trade_days=trade_days)
    active_trade_date10 = _resolve_trade_date10_for_reference_date(
        latest_recommendation_date10,
        active_trade_date10,
        trade_days=trade_days,
    )
    quote_time = str(realtime_buy.get("quote_time") or "").strip()
    quoted_count = int(realtime_buy.get("quoted_count") or 0)
    diagnostics = realtime_buy.get("diagnostics") if isinstance(realtime_buy.get("diagnostics"), dict) else {}
    forced_query = bool(diagnostics.get("forced_query"))
    if (
        quoted_count <= 0
        or not quote_time
        or not _quote_time_matches_trade_date(quote_time, active_trade_date10)
        or (not forced_query and not _is_entry_window_time(quote_time))
    ):
        realtime_buy["quote_time"] = ""
    historical_dates = sorted({str(row.get("date10") or "").strip() for row in backtest_rows if str(row.get("date10") or "").strip()})
    latest_backtest_date10 = historical_dates[-1] if historical_dates else ""
    anchors = _resolve_display_anchors(
        current_pool_rows=current_pool_rows,
        backtest_rows=backtest_rows,
        historical_snapshots=historical_snapshots,
        realtime_buy=realtime_buy,
        active_trade_date10=active_trade_date10,
        latest_recommendation_date10=latest_recommendation_date10,
    )

    upgraded["meta"] = meta
    meta.setdefault("is_empty", not current_pool_rows and not backtest_rows)
    meta["latest_closed_trade_date"] = anchors["latest_closed_trade_date"]
    meta["latest_closed_recommendation_date"] = anchors["latest_closed_recommendation_date"]
    meta["default_display_trade_date"] = anchors["default_display_trade_date"]
    meta["default_display_recommendation_date"] = anchors["default_display_recommendation_date"]
    meta["has_pending_next_trade_day"] = anchors["has_pending_next_trade_day"]
    upgraded["currentPoolRecords"] = current_pool_rows
    upgraded["records"] = backtest_rows
    upgraded["realtimeBuy"] = realtime_buy
    upgraded["displayRecords"] = display_rows or json.loads(json.dumps(backtest_rows, ensure_ascii=False))
    upgraded["historicalSnapshots"] = historical_snapshots
    metrics = upgraded.get("metrics") if isinstance(upgraded.get("metrics"), dict) else {}
    upgraded["metrics"] = metrics
    for key in ("next_day", "hold_2d", "hold_3d"):
        item = metrics.get(key)
        if not isinstance(item, dict):
            continue
        scopes = item.get("scopes") if isinstance(item.get("scopes"), dict) else {}
        if "tradable" not in scopes:
            tradable_scope = json.loads(json.dumps(item, ensure_ascii=False))
            tradable_scope.pop("scopes", None)
            scopes["tradable"] = tradable_scope
        if "all" not in scopes:
            all_scope = json.loads(json.dumps(scopes["tradable"], ensure_ascii=False))
            all_scope["base_total"] = int(item.get("total") or all_scope.get("total") or 0)
            scopes["all"] = all_scope
        item["scopes"] = scopes
    upgraded["lifecycle"] = _build_lifecycle(
        latest_recommendation_date10=latest_recommendation_date10,
        active_trade_date10=active_trade_date10,
        latest_backtest_date10=latest_backtest_date10,
        latest_closed_trade_date10=anchors["latest_closed_trade_date"],
        latest_closed_recommendation_date10=anchors["latest_closed_recommendation_date"],
        default_display_trade_date10=anchors["default_display_trade_date"],
        default_display_recommendation_date10=anchors["default_display_recommendation_date"],
        has_pending_next_trade_day=bool(anchors["has_pending_next_trade_day"]),
        default_display_note=str(anchors["default_display_note"] or "").strip(),
        current_pool_rows=current_pool_rows,
        backtest_rows=backtest_rows,
        realtime_buy=realtime_buy,
    )
    meta["active_trade_date"] = active_trade_date10
    meta["latest_recommendation_date"] = latest_recommendation_date10
    return upgraded


def _empty_backtest_payload(*, generated_from: list[str] | None = None) -> dict[str, Any]:
    return {
        "schema": "stock_research_backtest_v2",
        "meta": {
            "title": "个股研究开盘回测",
            "subtitle": "回测数据只读取收盘后由个股研究推送进单一历史 JSON 的样本；当前没有可用样本时只展示空结果。",
            "dates": [],
            "generated_at_bj": _now_bj().strftime("%Y-%m-%d %H:%M:%S"),
            "generated_from": list(generated_from or []),
            "price_source": "biying hsstock/history + 本地 recommendation_price_history 缓存",
            "entry_window": "09:25-09:30",
            "source_module": "ztAnalysis.relay/watch",
            "latest_recommendation_date": "",
            "active_trade_date": "",
            "latest_closed_trade_date": "",
            "latest_closed_recommendation_date": "",
            "default_display_trade_date": "",
            "default_display_recommendation_date": "",
            "has_pending_next_trade_day": False,
            "is_empty": True,
        },
        "summary": {
            "total_samples": 0,
            "source_samples": 0,
            "filtered_non_backtest_samples": 0,
            "eligible_samples": 0,
            "expected_count": 0,
            "super_count": 0,
            "pending_count": 0,
            "wait_reseal_count": 0,
            "rejected_count": 0,
            "unique_codes": 0,
            "trade_days": 0,
            "priced_codes": 0,
            "missing_price_codes": [],
            "realtime_candidate_count": 0,
            "realtime_buy_count": 0,
            "realtime_pending_count": 0,
            "realtime_unavailable_count": 0,
        },
        "assumptions": [
            "回测数据只读取收盘后由个股研究推送进专用历史源的样本，不再扫描其他 market_data 缓存。",
            "所有交易日样本都沉淀在同一个 JSON 内，页面只按时间规则选择当前应读取的交易日分桶。",
            "没有同源研究样本时不补造数据，页面只展示空结果。",
        ],
        "breakdowns": {
            "by_bucket": [],
            "by_open_status": [],
            "by_mainline": [],
            "by_date_status": [],
        },
        "metrics": {},
        "lifecycle": {
            "stage": "empty",
            "stage_label": "暂无数据",
            "stage_note": "当前还没有可展示的个股回测样本。",
            "quote_state": "pending_source",
            "quote_state_label": "等待推送",
            "quote_state_note": "当前还没有落地到可读的竞价引用日。",
            "has_current_plan": False,
            "has_historical_records": False,
            "has_realtime_snapshot": False,
            "latest_recommendation_date": "",
            "active_trade_date": "",
            "latest_historical_recommendation_date": "",
            "latest_closed_trade_date": "",
            "latest_closed_recommendation_date": "",
            "default_display_trade_date": "",
            "default_display_recommendation_date": "",
            "has_pending_next_trade_day": False,
            "default_display_note": "",
            "realtime_reference_date": "",
            "quote_time": "",
        },
        "realtimeBuy": {
            "reference_date": "",
            "trade_date": "",
            "entry_window": "09:25-09:30",
            "quote_time": "",
            "source_module": "ztAnalysis.relay/watch",
            "quote_source": "biying hsrl/ssjy_more 实时行情（失败时回退 raw.quotes）",
            "candidate_count": 0,
            "quoted_count": 0,
            "buy_count": 0,
            "direct_super_count": 0,
            "direct_expected_count": 0,
            "pending_count": 0,
            "rejected_count": 0,
            "unavailable_count": 0,
            "buy_list": [],
            "pending_list": [],
            "rejected_list": [],
            "unavailable_list": [],
            "diagnostics": {"source": "empty"},
        },
        "currentPoolRecords": [],
        "displayRecords": [],
        "historicalSnapshots": [],
        "records": [],
        "diagnostics": {
            "price_history": {"source": "empty", "fetched": 0, "cached": 0, "missing": []},
            "realtime_buy": {"source": "empty"},
            "display_only_codes": [],
        },
    }


def _market_data_snapshot_candidates(*, date10: str = "") -> list[Path]:
    candidates: list[tuple[str, int, int, Path]] = []
    for source_priority, base_dir in ((1, CACHE_DIR), (0, ONLINE_CACHE_DIR)):
        if not base_dir.exists():
            continue
        for fp in base_dir.glob("market_data-*.json"):
            match = re.match(r"^market_data-(\d{8})(-intraday)?$", fp.stem)
            if not match:
                continue
            d8 = match.group(1)
            if date10 and d8 != date10.replace("-", ""):
                continue
            # 同日优先使用 intraday 快照；同类型下优先当前 cache，再回退 cache_online。
            intraday_priority = 1 if match.group(2) else 0
            candidates.append((d8, intraday_priority, source_priority, fp))
    return [fp for _, _, _, fp in sorted(candidates, reverse=True)]


def _load_latest_stock_research_snapshot(date10: str) -> dict[str, Any]:
    if len(date10) != 10:
        return {}
    for fp in _market_data_snapshot_candidates(date10=date10):
        raw = _load_json(fp, default={})
        if isinstance(raw, dict):
            return raw
    return {}


def _extract_raw_quotes_items(market_data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(market_data, dict):
        return {}
    raw = market_data.get("raw") if isinstance(market_data.get("raw"), dict) else {}
    quotes = raw.get("quotes") if isinstance(raw.get("quotes"), dict) else {}
    items = quotes.get("items")
    return items if isinstance(items, dict) else {}


def _research_quotes_cache_path(date10: str) -> Path:
    return CACHE_DIR / f"stock_research_realtime_quotes-{date10.replace('-', '')}.json"


def load_prefetched_realtime_quotes(date10: str) -> dict[str, Any]:
    if len(date10) != 10:
        return {}
    data = _load_json(_research_quotes_cache_path(date10), default={})
    return data if isinstance(data, dict) else {}


def save_prefetched_realtime_quotes(*, date10: str, items: dict[str, Any], as_of: str, source: str) -> Path:
    payload = {
        "schema": "stock_research_realtime_quotes_v1",
        "date": date10,
        "as_of": as_of,
        "source": source,
        "count": len(items),
        "items": items,
        "saved_at_bj": _now_bj().strftime("%Y-%m-%d %H:%M:%S"),
    }
    path = _research_quotes_cache_path(date10)
    _write_json(path, payload)
    return path


def _save_normalized_prefetched_realtime_quotes(*, date10: str, quotes_map: dict[str, dict[str, Any]], source: str) -> Path | None:
    if len(date10) != 10 or not isinstance(quotes_map, dict) or not quotes_map:
        return None
    items: dict[str, Any] = {}
    as_of = ""
    for code6, quote in quotes_map.items():
        if not isinstance(quote, dict):
            continue
        raw = quote.get("raw") if isinstance(quote.get("raw"), dict) else {}
        quote_time = str(quote.get("time") or quote.get("quote_time") or "").strip()
        auction_amount_yuan = quote.get("auction_amount_yuan")
        if not auction_amount_yuan and quote.get("auction_amount_yi") not in (None, ""):
            try:
                auction_amount_yuan = float(quote.get("auction_amount_yi")) * 1e8
            except Exception:
                auction_amount_yuan = 0.0
        payload = dict(raw) if raw else {
            "dm": code6,
            "t": quote_time,
            "yc": quote.get("prev_close"),
            "o": quote.get("open_price") or quote.get("auction_price"),
            "p": quote.get("auction_price") or quote.get("last_price"),
            "cje": auction_amount_yuan,
        }
        items[str(code6)] = payload
        if not as_of:
            as_of = str(payload.get("t") or quote_time).strip()
    if not items:
        return None
    return save_prefetched_realtime_quotes(date10=date10, items=items, as_of=as_of, source=source)


def _is_entry_window_time(hhmmss: str) -> bool:
    text = str(hhmmss or "").strip()
    if not text:
        return False
    if " " in text:
        text = text.split(" ")[-1]
    if len(text) >= 8:
        text = text[:8]
    try:
        hour, minute, second = [int(part) for part in text.split(":")[:3]]
    except Exception:
        return False
    if hour != 9:
        return False
    total = hour * 3600 + minute * 60 + second
    return 9 * 3600 + 25 * 60 <= total < 9 * 3600 + 30 * 60


def _should_request_realtime_quotes(now: datetime | None = None) -> bool:
    current = now or _now_bj()
    total = current.hour * 3600 + current.minute * 60 + current.second
    return 9 * 3600 + 25 * 60 <= total < 9 * 3600 + 30 * 60


def _load_preserved_realtime_buy(latest_date10: str) -> dict[str, Any] | None:
    today10 = _now_bj().strftime("%Y-%m-%d")
    for fp in _market_data_snapshot_candidates():
        data = _load_json(fp, default={})
        if not isinstance(data, dict):
            continue
        backtest = data.get("stockResearchBacktest")
        if not isinstance(backtest, dict):
            continue
        realtime_buy = backtest.get("realtimeBuy")
        if not isinstance(realtime_buy, dict):
            continue
        if str(realtime_buy.get("reference_date") or "") != latest_date10:
            continue
        trade_date10 = str(realtime_buy.get("trade_date") or "").strip()
        if trade_date10 and trade_date10 > today10:
            continue
        quote_time = str(realtime_buy.get("quote_time") or "")
        diagnostics = realtime_buy.get("diagnostics") if isinstance(realtime_buy.get("diagnostics"), dict) else {}
        forced_query = bool(diagnostics.get("forced_query"))
        if not quote_time or (not forced_query and not _is_entry_window_time(quote_time)):
            continue
        return json.loads(json.dumps(realtime_buy, ensure_ascii=False))
    return None


def _upgrade_preserved_realtime_buy_payload(realtime_buy: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(realtime_buy, dict):
        return {}

    upgraded_rows: list[dict[str, Any]] = []
    migrated_high_gap = 0
    trade_date10 = str(realtime_buy.get("trade_date") or "").strip()
    for bucket in ("buy_list", "pending_list", "rejected_list", "unavailable_list"):
        for raw_row in realtime_buy.get(bucket) or []:
            if not isinstance(raw_row, dict):
                continue
            row = json.loads(json.dumps(raw_row, ensure_ascii=False))
            auction_price = row.get("auction_price")
            if row.get("open_price") in (None, "") and auction_price not in (None, ""):
                row["open_price"] = auction_price
            row.setdefault("close_price", None)
            row.setdefault("close_pct", None)
            if trade_date10 and not str(row.get("trade_date10") or "").strip():
                row["trade_date10"] = trade_date10
            row.setdefault("next_day_status", "pending")
            row.setdefault("next_day_label", "隔日收益")
            row.setdefault("next_day_return_pct", None)
            row.setdefault("hold_2d_status", "pending")
            row.setdefault("hold_2d_return_pct", None)
            row.setdefault("hold_3d_status", "pending")
            row.setdefault("hold_3d_return_pct", None)
            decision_status = str(row.get("decision_status") or "")
            gap_pct = row.get("gap_pct")
            try:
                gap_pct_value = float(gap_pct) if gap_pct is not None else None
            except Exception:
                gap_pct_value = None
            if decision_status == "buy" and gap_pct_value is not None and gap_pct_value > CAUTION_GAP_PCT:
                row["decision_status"] = "pending"
                row["decision_label"] = "观察"
                row["signal_status"] = "pending"
                row["signal_label"] = "谨慎接力"
                row["note"] = f"竞价涨幅 {gap_pct_value:+.2f}% 大于 {CAUTION_GAP_PCT:.0f}% ，高开偏猛，先观察承接，不直接买入。"
                migrated_high_gap += 1
            upgraded_rows.append(row)

    upgraded_rows.sort(key=lambda x: (_signal_rank(str(x.get("signal_status") or "")), -int(x.get("score") or 0), str(x.get("code") or "")))
    buy_list = [row for row in upgraded_rows if row.get("decision_status") == "buy"]
    pending_list = [row for row in upgraded_rows if row.get("decision_status") == "pending"]
    rejected_list = [row for row in upgraded_rows if row.get("decision_status") == "reject"]
    unavailable_list = [row for row in upgraded_rows if row.get("decision_status") == "unavailable"]
    direct_super = [row for row in buy_list if row.get("signal_status") == "super"]
    direct_expected = [row for row in buy_list if row.get("signal_status") == "expected"]

    upgraded = json.loads(json.dumps(realtime_buy, ensure_ascii=False))
    diagnostics = upgraded.get("diagnostics") if isinstance(upgraded.get("diagnostics"), dict) else {}
    diagnostics["upgraded_rules"] = {
        "migrated_high_gap_buy_to_pending": migrated_high_gap,
    }
    upgraded.update(
        {
            "candidate_count": len(upgraded_rows),
            "buy_count": len(buy_list),
            "direct_super_count": len(direct_super),
            "direct_expected_count": len(direct_expected),
            "pending_count": len(pending_list),
            "rejected_count": len(rejected_list),
            "unavailable_count": len(unavailable_list),
            "buy_list": buy_list,
            "pending_list": pending_list,
            "rejected_list": rejected_list,
            "unavailable_list": unavailable_list,
            "diagnostics": diagnostics,
        }
    )
    return upgraded


def _normalize_realtime_quote(row: dict[str, Any]) -> dict[str, Any] | None:
    code6 = normalize_stock_code(str(row.get("dm") or row.get("code") or row.get("symbol") or ""))
    if not code6:
        return None
    prev_close = float(row.get("yc") or 0.0)
    open_price = float(row.get("o") or 0.0)
    last_price = float(row.get("p") or row.get("c") or 0.0)
    auction_price = open_price if open_price > 0 else last_price
    auction_amount_yuan = float(row.get("cje") or 0.0)
    open_board_count = row.get("zbc")
    try:
        open_board_count = int(float(open_board_count)) if open_board_count not in (None, "") else None
    except Exception:
        open_board_count = None
    return {
        "code": code6,
        "time": str(row.get("t") or "").strip(),
        "prev_close": round(prev_close, 2),
        "open_price": round(open_price, 2) if open_price > 0 else 0.0,
        "last_price": round(last_price, 2) if last_price > 0 else 0.0,
        "auction_price": round(auction_price, 2) if auction_price > 0 else 0.0,
        "auction_price_field": "o" if open_price > 0 else ("p" if last_price > 0 else ""),
        "auction_amount_yuan": auction_amount_yuan,
        "auction_amount_yi": round(auction_amount_yuan / 1e8, 2) if auction_amount_yuan > 0 else 0.0,
        "open_board_count": open_board_count,
        "raw": row,
    }


def _fetch_realtime_quotes(codes: list[str], *, fallback_quotes: dict[str, Any] | None = None, force: bool = False) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    normalized_codes = [normalize_stock_code(code) for code in codes if normalize_stock_code(code)]
    uniq_codes = sorted(dict.fromkeys(normalized_codes))
    diagnostics: dict[str, Any] = {
        "requested": len(uniq_codes),
        "received": 0,
        "remote_received": 0,
        "fallback_used": 0,
        "missing": [],
        "source": "remote",
        "as_of": "",
        "error": "",
        "request_window": "09:25-09:30",
        "request_batches": 0,
    }
    quotes_map: dict[str, dict[str, Any]] = {}

    forced_query = force or _is_forced_query_tag()
    if forced_query or _should_request_realtime_quotes():
        try:
            cfg = load_config_from_env()
            client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=12, retries=REALTIME_HTTP_RETRIES)
            step = 20
            for i in range(0, len(uniq_codes), step):
                batch = uniq_codes[i : i + step]
                diagnostics["request_batches"] = int(diagnostics["request_batches"] or 0) + 1
                rows = fetch_stocks_realtime(client, ",".join(batch)) if batch else []
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    quote = _normalize_realtime_quote(row)
                    if not quote:
                        continue
                    if not forced_query and not _is_entry_window_time(str(quote.get("time") or "")):
                        continue
                    if quote.get("time") and not diagnostics["as_of"]:
                        diagnostics["as_of"] = quote["time"]
                    quotes_map[quote["code"]] = quote
            diagnostics["remote_received"] = len(quotes_map)
        except Exception as exc:
            err_type = type(exc).__name__
            if "timeout" in err_type.lower():
                diagnostics["error"] = f"remote_timeout: {exc}; request_batches={diagnostics['request_batches']}"
            else:
                diagnostics["error"] = f"remote_http_error: {exc}; request_batches={diagnostics['request_batches']}"
    else:
        diagnostics["source"] = "window_closed"
        diagnostics["error"] = "仅允许在 09:25-09:30 请求批量竞价接口，当前时段跳过远端请求。"

    fallback_map = fallback_quotes if isinstance(fallback_quotes, dict) else {}
    if fallback_map:
        for code6 in uniq_codes:
            if code6 in quotes_map:
                continue
            raw = fallback_map.get(code6)
            if not isinstance(raw, dict):
                continue
            quote = _normalize_realtime_quote(raw)
            if not quote:
                continue
            if not forced_query and not _is_entry_window_time(str(quote.get("time") or "")):
                continue
            quotes_map[code6] = quote
            diagnostics["fallback_used"] += 1
            if quote.get("time") and not diagnostics["as_of"]:
                diagnostics["as_of"] = quote["time"]

    if diagnostics["source"] == "window_closed" and diagnostics["fallback_used"] > 0:
        diagnostics["source"] = "cache.raw.quotes"
    elif not quotes_map and diagnostics["fallback_used"] > 0:
        diagnostics["source"] = "cache.raw.quotes"
    elif quotes_map and diagnostics["fallback_used"] > 0:
        diagnostics["source"] = "remote+cache.raw.quotes"
    elif not quotes_map and diagnostics["source"] != "window_closed":
        diagnostics["source"] = "unavailable"

    diagnostics["received"] = len(quotes_map)
    diagnostics["missing"] = [code for code in uniq_codes if code not in quotes_map]
    if forced_query:
        diagnostics["source"] = "forced_query" if quotes_map else "forced_query_unavailable"
        diagnostics["forced_query"] = True
        diagnostics["request_window"] = "forced"
        if quotes_map:
            diagnostics["error"] = "已跳过 09:25-09:30 时间窗限制，尝试补齐今天缺失的竞价快照。"
        elif not diagnostics["error"]:
            diagnostics["error"] = f"forced_query_unavailable: request_batches={diagnostics['request_batches']}"
    return quotes_map, diagnostics


def _signal_rank(status: str) -> int:
    if status == "super":
        return 0
    if status == "expected":
        return 1
    if status == "pending":
        return 2
    if status == "reject":
        return 3
    return 4


def _evaluate_realtime_signal(record: dict[str, Any], quote: dict[str, Any] | None) -> dict[str, Any]:
    exp = record.get("expectation") or {}
    expected_range = exp.get("expected_range")
    super_gap_min = exp.get("super_gap_min")
    auction_amount_min_yi = float(exp.get("auction_amount_min_yi") or 0.0)
    base = {
        "date10": record.get("date10"),
        "code": record.get("code"),
        "name": record.get("name"),
        "bucket": record.get("bucket"),
        "bucket_label": record.get("bucket_label"),
        "placement_label": record.get("placement_label"),
        "score": record.get("score"),
        "daily_rank": int(record.get("daily_rank") or 0),
        "relay_rank": int(record.get("relay_rank") or 0),
        "watch_rank": int(record.get("watch_rank") or 0),
        "relay_selection_mode": str(record.get("relay_selection_mode") or "").strip(),
        "watch_group": str(record.get("watch_group") or "").strip(),
        "main_line": record.get("main_line"),
        "score_label": str(record.get("score_label") or "").strip(),
        "reason_text": record.get("reason_text"),
        "factor_hint": str(record.get("factor_hint") or "").strip(),
        "hit_rules": [str(x).strip() for x in (record.get("hit_rules") or []) if str(x).strip()],
        "block_reasons": [str(x).strip() for x in (record.get("block_reasons") or []) if str(x).strip()],
        "leader_factor_score": record.get("leader_factor_score"),
        "relay_factor_score": record.get("relay_factor_score"),
        "leader_philosophy_score": record.get("leader_philosophy_score"),
        "break_risk": record.get("break_risk"),
        "environment_score": record.get("environment_score"),
        "capacity_factor_score": record.get("capacity_factor_score"),
        "step_context_score": record.get("step_context_score"),
        "tide_relay_gate": record.get("tide_relay_gate"),
        "theme_ladder_profile": json.loads(json.dumps(record.get("theme_ladder_profile") or {}, ensure_ascii=False)),
        "expected_text": exp.get("expected_text") or "",
        "super_text": exp.get("super_text") or "",
        "low_text": exp.get("low_text") or "",
        "quote_time": str((quote or {}).get("time") or "").strip(),
        "auction_amount_need_yi": round(auction_amount_min_yi, 2),
    }
    if not isinstance(quote, dict):
        return {
            **base,
            "decision_status": "unavailable",
            "decision_label": "报价缺失",
            "signal_status": "unavailable",
            "signal_label": "无法判断",
            "note": "未拿到 9:25 实时报价，当前不生成买入信号。",
        }

    prev_close = float(quote.get("prev_close") or 0.0)
    auction_price = float(quote.get("auction_price") or 0.0)
    auction_amount_yi = float(quote.get("auction_amount_yi") or 0.0)
    gap_pct = round((auction_price - prev_close) / prev_close * 100.0, 2) if prev_close > 0 and auction_price > 0 else None
    base.update(
        {
            "prev_close": round(prev_close, 2) if prev_close > 0 else None,
            "auction_price": round(auction_price, 2) if auction_price > 0 else None,
            "open_price": round(auction_price, 2) if auction_price > 0 else None,
            "close_price": None,
            "close_pct": None,
            "auction_amount_yi": round(auction_amount_yi, 2),
            "gap_pct": gap_pct,
            "trade_date10": str(record.get("trade_date10") or "").strip(),
            "next_day_status": "pending",
            "next_day_label": "隔日收益",
            "next_day_return_pct": None,
            "hold_2d_status": "pending",
            "hold_2d_return_pct": None,
            "hold_3d_status": "pending",
            "hold_3d_return_pct": None,
        }
    )
    if prev_close <= 0 or auction_price <= 0 or auction_amount_yi <= 0:
        return {
            **base,
            "decision_status": "unavailable",
            "decision_label": "价格/量能不完整",
            "signal_status": "unavailable",
            "signal_label": "无法判断",
            "note": "9:25 价格或竞价成交额缺失，暂不纳入买入列表。",
        }

    super_gap_ok = super_gap_min is not None and gap_pct is not None and gap_pct >= float(super_gap_min)
    expected_ok = expected_range is not None and gap_pct is not None and expected_range[0] <= gap_pct <= expected_range[1]
    auction_ok = auction_amount_yi >= auction_amount_min_yi if auction_amount_min_yi > 0 else True
    high_gap_caution = gap_pct is not None and gap_pct > CAUTION_GAP_PCT

    # 超预期：涨幅达标 + 量能达标 → 直接买入
    if super_gap_ok and auction_ok:
        if high_gap_caution:
            return {
                **base,
                "decision_status": "pending",
                "decision_label": "观察",
                "signal_status": "pending",
                "signal_label": "谨慎接力",
                "rule_text": exp.get("super_text") or "",
                "note": f"竞价涨幅 {gap_pct:+.2f}% 大于 {CAUTION_GAP_PCT:.0f}% ，属于高开过猛，先观察承接，不直接买入。",
            }
        return {
            **base,
            "decision_status": "buy",
            "decision_label": "直接买入",
            "signal_status": "super",
            "signal_label": "超预期",
            "rule_text": exp.get("super_text") or "",
            "note": f"竞价涨幅 {gap_pct:+.2f}% ≥ 超预期阈值 {super_gap_min:+.2f}%，竞价成交额 {auction_amount_yi:.2f}亿 ≥ {auction_amount_min_yi:.2f}亿，直接买入。",
        }

    # 符合预期：涨幅落在预期区间内 → 直接买入
    if expected_ok:
        if high_gap_caution:
            return {
                **base,
                "decision_status": "pending",
                "decision_label": "观察",
                "signal_status": "pending",
                "signal_label": "谨慎接力",
                "rule_text": exp.get("expected_text") or "",
                "note": f"竞价涨幅 {gap_pct:+.2f}% 大于 {CAUTION_GAP_PCT:.0f}% ，虽然符合预期，但不直接买入，先看承接。",
            }
        return {
            **base,
            "decision_status": "buy",
            "decision_label": "直接买入",
            "signal_status": "expected",
            "signal_label": "符合预期",
            "rule_text": exp.get("expected_text") or "",
            "note": f"竞价涨幅 {gap_pct:+.2f}% 落在预期区间 {expected_range[0]:+.2f}%~{expected_range[1]:+.2f}%，按计划买入。",
        }

    # 超预期涨幅达标但量能不达标 → 低于预期
    if super_gap_ok and not auction_ok:
        return {
            **base,
            "decision_status": "reject",
            "decision_label": "量能不达标",
            "signal_status": "reject",
            "signal_label": "低于预期",
            "rule_text": exp.get("low_text") or exp.get("super_text") or "",
            "note": f"竞价涨幅 {gap_pct:+.2f}% 达标，但成交额 {auction_amount_yi:.2f}亿 < {auction_amount_min_yi:.2f}亿，量能不达标。",
        }

    # 涨幅不达标 → 低于预期
    return {
        **base,
        "decision_status": "reject",
        "decision_label": "未达买点",
        "signal_status": "reject",
        "signal_label": "低于预期",
        "rule_text": exp.get("low_text") or exp.get("expected_text") or "",
        "note": f"竞价涨幅 {gap_pct:+.2f}%，未落在预期区间或超预期范围。",
    }


def _build_realtime_buy_payload(
    rows: list[dict[str, Any]],
    *,
    latest_date10: str,
    trade_date10: str = "",
    current_market_data: dict[str, Any] | None = None,
    query_tag: str | None = None,
) -> dict[str, Any]:
    latest_rows = [dict(row) for row in rows if row.get("date10") == latest_date10]
    forced_query = _is_forced_query_tag(query_tag)
    today10 = _now_bj().strftime("%Y-%m-%d")
    if trade_date10 and trade_date10 > today10:
        return {
            "reference_date": latest_date10,
            "trade_date": trade_date10,
            "entry_window": "09:25-09:30",
            "quote_time": "",
            "source_module": "ztAnalysis.relay/watch",
            "quote_source": "guard.future_trade_date",
            "candidate_count": len(latest_rows),
            "quoted_count": 0,
            "buy_count": 0,
            "direct_super_count": 0,
            "direct_expected_count": 0,
            "pending_count": 0,
            "rejected_count": 0,
            "unavailable_count": 0,
            "buy_list": [],
            "pending_list": [],
            "rejected_list": [],
            "unavailable_list": [],
            "diagnostics": {
                "requested": 0,
                "received": 0,
                "remote_received": 0,
                "fallback_used": 0,
                "missing": [],
                "source": "future_trade_day_guard",
                "as_of": "",
                "error": (
                    f"{'fore 补丁也不能' if forced_query else '普通模式禁止'}"
                    f"用 {today10} 的实时行情去匹配未来交易日 {trade_date10}。"
                ),
                "request_window": "09:25-09:30",
                "future_trade_day_guard": True,
                "current_session_date": today10,
                "forced_query": forced_query,
            },
        }
    if forced_query and trade_date10 and trade_date10 != today10:
        return {
            "reference_date": latest_date10,
            "trade_date": trade_date10,
            "entry_window": "09:25-09:30",
            "quote_time": "",
            "source_module": "ztAnalysis.relay/watch",
            "quote_source": "guard.fore_today_only",
            "candidate_count": len(latest_rows),
            "quoted_count": 0,
            "buy_count": 0,
            "direct_super_count": 0,
            "direct_expected_count": 0,
            "pending_count": 0,
            "rejected_count": 0,
            "unavailable_count": 0,
            "buy_list": [],
            "pending_list": [],
            "rejected_list": [],
            "unavailable_list": [],
            "diagnostics": {
                "requested": 0,
                "received": 0,
                "remote_received": 0,
                "fallback_used": 0,
                "missing": [],
                "source": "fore_today_only_guard",
                "as_of": "",
                "error": f"fore 只允许补抓今天 {today10} 的缺失快照，当前目标交易日 {trade_date10} 不可补抓。",
                "request_window": "09:25-09:30",
                "fore_today_only_guard": True,
                "current_session_date": today10,
                "forced_query": True,
            },
        }
    in_window = forced_query or _should_request_realtime_quotes()
    if not in_window:
        preserved = _load_preserved_realtime_buy(latest_date10)
        if isinstance(preserved, dict):
            preserved = _upgrade_preserved_realtime_buy_payload(preserved)
            diagnostics = preserved.get("diagnostics") if isinstance(preserved.get("diagnostics"), dict) else {}
            preserved["diagnostics"] = {
                **diagnostics,
                "source": "preserved_snapshot",
                "request_window": "09:25-09:30",
                "preserved_note": "当前不在 09:25-09:30，复用已落地的竞价观察结果，不重复请求远端接口。",
            }
            return preserved

    raw_quotes: dict[str, Any] = {}
    latest_raw = _load_latest_stock_research_snapshot(latest_date10)
    raw_quotes.update(_extract_raw_quotes_items(latest_raw))
    raw_quotes.update(_extract_raw_quotes_items(current_market_data))
    prefetched = load_prefetched_realtime_quotes(latest_date10)
    items = prefetched.get("items")
    if isinstance(items, dict):
        raw_quotes.update(items)
    prefetched_as_of = str(prefetched.get("as_of") or "").strip() if isinstance(prefetched, dict) else ""
    prefetched_source = str(prefetched.get("source") or "").strip() if isinstance(prefetched, dict) else ""
    prefetched_codes = set(items.keys()) if isinstance(items, dict) else set()
    codes = [str(row.get("code") or "").strip() for row in latest_rows if str(row.get("code") or "").strip()]

    if not in_window:
        # 窗口外：不从远端拉（ssjy_more 的 t 字段不会落在 9:25-9:30，全被过滤）
        # 直接从缓存构建 quotes_map
        quotes_map: dict[str, dict[str, Any]] = {}
        as_of = prefetched_as_of
        allow_forced_prefetched = prefetched_source == "forced_query"
        for code6 in codes:
            raw = raw_quotes.get(code6)
            if not isinstance(raw, dict):
                continue
            quote = _normalize_realtime_quote(raw)
            if not quote:
                continue
            quote_time = str(quote.get("time") or "").strip()
            if not _is_entry_window_time(quote_time):
                if not (
                    allow_forced_prefetched
                    and code6 in prefetched_codes
                    and quote_time
                    and _quote_time_matches_trade_date(quote_time, trade_date10)
                ):
                    continue
            quotes_map[code6] = quote
            if quote_time and not as_of:
                as_of = quote_time
        source = "cache.raw.quotes" if quotes_map else "unavailable"
        if allow_forced_prefetched and quotes_map:
            source = "forced_query_cache"
        if not quotes_map:
            as_of = ""
        quote_diag: dict[str, Any] = {
            "requested": len(codes),
            "received": len(quotes_map),
            "remote_received": 0,
            "fallback_used": len(quotes_map),
            "missing": [c for c in codes if c not in quotes_map],
            "source": source,
            "as_of": as_of,
            "error": "",
            "request_window": "forced" if allow_forced_prefetched and quotes_map else "09:25-09:30",
        }
        if allow_forced_prefetched and quotes_map:
            quote_diag["forced_query"] = True
            quote_diag["error"] = "已复用同一交易日内此前补齐成功的快照，当前不在 09:25-09:30 也继续沿用该结果。"
        elif quotes_map:
            quote_diag["error"] = "窗口外无 preserved 快照，使用本地缓存数据（无远端请求）"
        else:
            quote_diag["error"] = "窗口外无 preserved 快照且无可用缓存数据"
    else:
        quotes_map, quote_diag = _fetch_realtime_quotes(
            codes,
            fallback_quotes=raw_quotes if isinstance(raw_quotes, dict) else None,
            force=forced_query,
        )
        quote_time = str(quote_diag.get("as_of") or "").strip()
        if quotes_map and latest_date10 and (forced_query or _is_entry_window_time(quote_time)):
            _save_normalized_prefetched_realtime_quotes(
                date10=latest_date10,
                quotes_map=quotes_map,
                source="forced_query" if forced_query else "realtime_buy_snapshot",
            )

    decisions = [_evaluate_realtime_signal(row, quotes_map.get(str(row.get("code") or "").strip())) for row in latest_rows]
    decisions = _sort_rows_by_selection_priority(decisions)
    decisions.sort(key=lambda x: (_signal_rank(str(x.get("signal_status") or "")), *_row_selection_priority(x)))

    buy_list = [row for row in decisions if row.get("decision_status") == "buy"]
    pending_list = [row for row in decisions if row.get("decision_status") == "pending"]
    rejected_list = [row for row in decisions if row.get("decision_status") == "reject"]
    unavailable_list = [row for row in decisions if row.get("decision_status") == "unavailable"]
    direct_super = [row for row in buy_list if row.get("signal_status") == "super"]
    direct_expected = [row for row in buy_list if row.get("signal_status") == "expected"]

    return {
        "reference_date": latest_date10,
        "trade_date": trade_date10,
        "entry_window": "09:25-09:30",
        "quote_time": quote_diag.get("as_of") or "",
        "source_module": "ztAnalysis.relay/watch",
        "quote_source": "biying hsrl/ssjy_more 实时行情（失败时回退 raw.quotes）",
        "candidate_count": len(latest_rows),
        "quoted_count": quote_diag.get("received", 0),
        "buy_count": len(buy_list),
        "direct_super_count": len(direct_super),
        "direct_expected_count": len(direct_expected),
        "pending_count": len(pending_list),
        "rejected_count": len(rejected_list),
        "unavailable_count": len(unavailable_list),
        "buy_list": buy_list,
        "pending_list": pending_list,
        "rejected_list": rejected_list,
        "unavailable_list": unavailable_list,
        "diagnostics": quote_diag,
    }


def _merge_historical_snapshot_row_with_realtime(
    base_row: dict[str, Any],
    decision_row: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(decision_row, dict):
        return base_row

    merged = dict(base_row)
    auction_price = decision_row.get("auction_price")
    merged.update(
        {
            "signal_status": decision_row.get("signal_status") or merged.get("signal_status"),
            "signal_label": decision_row.get("signal_label") or merged.get("signal_label"),
            "decision_status": decision_row.get("decision_status") or merged.get("decision_status"),
            "decision_label": decision_row.get("decision_label") or merged.get("decision_label"),
            "relay_rank": decision_row.get("relay_rank") or merged.get("relay_rank"),
            "watch_rank": decision_row.get("watch_rank") or merged.get("watch_rank"),
            "relay_selection_mode": decision_row.get("relay_selection_mode") or merged.get("relay_selection_mode"),
            "watch_group": decision_row.get("watch_group") or merged.get("watch_group"),
            "score_label": decision_row.get("score_label") or merged.get("score_label"),
            "placement_label": decision_row.get("placement_label") or merged.get("placement_label"),
            "factor_hint": decision_row.get("factor_hint") or merged.get("factor_hint"),
            "hit_rules": decision_row.get("hit_rules") or merged.get("hit_rules"),
            "block_reasons": decision_row.get("block_reasons") or merged.get("block_reasons"),
            "leader_factor_score": decision_row.get("leader_factor_score") if decision_row.get("leader_factor_score") is not None else merged.get("leader_factor_score"),
            "relay_factor_score": decision_row.get("relay_factor_score") if decision_row.get("relay_factor_score") is not None else merged.get("relay_factor_score"),
            "leader_philosophy_score": decision_row.get("leader_philosophy_score") if decision_row.get("leader_philosophy_score") is not None else merged.get("leader_philosophy_score"),
            "break_risk": decision_row.get("break_risk") if decision_row.get("break_risk") is not None else merged.get("break_risk"),
            "environment_score": decision_row.get("environment_score") if decision_row.get("environment_score") is not None else merged.get("environment_score"),
            "capacity_factor_score": decision_row.get("capacity_factor_score") if decision_row.get("capacity_factor_score") is not None else merged.get("capacity_factor_score"),
            "step_context_score": decision_row.get("step_context_score") if decision_row.get("step_context_score") is not None else merged.get("step_context_score"),
            "tide_relay_gate": decision_row.get("tide_relay_gate") if decision_row.get("tide_relay_gate") is not None else merged.get("tide_relay_gate"),
            "theme_ladder_profile": decision_row.get("theme_ladder_profile") or merged.get("theme_ladder_profile"),
            "prev_close": decision_row.get("prev_close") if decision_row.get("prev_close") is not None else merged.get("prev_close"),
            "open_price": auction_price if auction_price is not None else merged.get("open_price"),
            "auction_price": auction_price,
            "auction_amount_yi": decision_row.get("auction_amount_yi"),
            "auction_amount_need_yi": decision_row.get("auction_amount_need_yi"),
            "gap_pct": decision_row.get("gap_pct") if decision_row.get("gap_pct") is not None else merged.get("gap_pct"),
            "quote_time": str(decision_row.get("quote_time") or "").strip(),
            "rule_text": str(decision_row.get("rule_text") or "").strip(),
            "note": str(decision_row.get("note") or "").strip() or merged.get("note"),
        }
    )
    return merged


def _classify_open_window(record: dict[str, Any], entry_bar: dict[str, Any]) -> dict[str, Any]:
    prev_close = float(entry_bar.get("prev_close") or 0.0)
    entry_open = float(entry_bar.get("open") or 0.0)
    gap_pct = round((entry_open - prev_close) / prev_close * 100.0, 2) if prev_close > 0 else 0.0

    exp = record.get("expectation") or {}
    expected_range = exp.get("expected_range")
    super_gap_min = exp.get("super_gap_min")
    expected_text = str(exp.get("expected_text") or "")
    super_text = str(exp.get("super_text") or "")
    high_gap_caution = gap_pct > CAUTION_GAP_PCT

    def _pending(label: str, note: str) -> dict[str, Any]:
        return {
            "status": "pending",
            "label": label,
            "gap_pct": gap_pct,
            "note": note,
            "can_enter": False,
        }

    if expected_range and expected_range[0] <= gap_pct <= expected_range[1]:
        if high_gap_caution:
            return _pending("谨慎接力", f"开盘高开 {gap_pct:+.2f}% 大于 {CAUTION_GAP_PCT:.0f}% ，先观察承接，不按固定买入直接入场。")
        return {
            "status": "expected",
            "label": "符合预期",
            "gap_pct": gap_pct,
            "note": expected_text or "开盘涨幅落在预期区间内",
            "can_enter": True,
        }
    if super_gap_min is not None and gap_pct >= super_gap_min:
        if high_gap_caution:
            return _pending("谨慎接力", f"开盘高开 {gap_pct:+.2f}% 大于 {CAUTION_GAP_PCT:.0f}% ，先观察承接，不按固定买入直接入场。")
        return {
            "status": "super",
            "label": "超预期",
            "gap_pct": gap_pct,
            "note": super_text or "开盘涨幅达到超预期阈值",
            "can_enter": True,
        }
    return {
        "status": "reject",
        "label": "低于预期",
        "gap_pct": gap_pct,
        "note": str(exp.get("low_text") or "开盘涨幅未落在预期/超预期可执行区间"),
        "can_enter": False,
    }


def _evaluate_one(record: dict[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
    future = [bar for bar in bars if bar["date"] > record["date10"]]
    if not future:
        missing = {"status": "missing", "label": "无后续价格", "note": "推荐日后没有可用交易日价格"}
        return {
            "open_check": missing,
            "next_day": {"status": "missing", "label": "隔日收益", "note": "推荐日后没有可用交易日价格"},
            "hold_2d": {"status": "missing", "label": "2日收益", "note": "推荐日后没有可用交易日价格"},
            "hold_3d": {"status": "missing", "label": "3日收益", "note": "推荐日后没有可用交易日价格"},
        }

    entry = future[0]
    open_check = _classify_open_window(record, entry)
    # 高开砸盘检测：高开但当日收阴且放量
    gap_pct = open_check.get("gap_pct") or 0.0
    entry_open_price = float(entry.get("open") or 0.0)
    entry_close = float(entry.get("close") or 0.0)
    entry_prev_close = float(entry.get("prev_close") or 0.0)
    gap_trap = bool(
        gap_pct > 0
        and entry_close < entry_open_price
        and entry_prev_close > 0
    )
    close_pct = round((entry_close - entry_prev_close) / entry_prev_close * 100.0, 2) if entry_prev_close > 0 else None
    open_check["prev_close"] = round(entry_prev_close, 2) if entry_prev_close > 0 else None
    open_check["open_price"] = round(entry_open_price, 2) if entry_open_price > 0 else None
    open_check["close_price"] = round(entry_close, 2) if entry_close > 0 else None
    open_check["close_pct"] = close_pct
    open_check["gap_trap"] = gap_trap

    if not open_check.get("can_enter"):
        skipped = {
            "status": "skipped",
            "label": "未入场",
            "note": open_check.get("note") or "开盘窗口未满足条件",
            "gap_pct": open_check.get("gap_pct"),
            "gap_trap": gap_trap,
        }
        return {
            "open_check": open_check,
            "next_day": skipped,
            "hold_2d": skipped,
            "hold_3d": skipped,
        }

    perf: dict[str, Any] = {"open_check": open_check}
    for key, label, offset in STRATEGIES:
        if len(future) < offset:
            perf[key] = {
                "status": "pending",
                "label": label,
                "entry_date": entry["date"],
                "note": f"当前仅拿到 {len(future)} 个后续交易日，尚不足以计算 T+{offset}",
                "gap_trap": gap_trap,
            }
            continue
        exit_bar = future[offset - 1]
        entry_open = float(entry["open"])
        exit_close = float(exit_bar["close"])
        return_pct = round((exit_close - entry_open) / entry_open * 100.0, 2) if entry_open > 0 else 0.0
        perf[key] = {
            "status": "covered",
            "label": label,
            "entry_date": entry["date"],
            "exit_date": exit_bar["date"],
            "entry_open": round(entry_open, 2),
            "exit_close": round(exit_close, 2),
            "return_pct": return_pct,
            "win": return_pct > 0,
            "flat": return_pct == 0,
            "loss": return_pct < 0,
            "days_after_pick": offset,
        }
    return perf


def _summarize_strategy(records: list[dict[str, Any]], key: str, label: str) -> dict[str, Any]:
    def summarize_scope(scope_rows: list[dict[str, Any]], *, denominator_rows: list[dict[str, Any]]) -> dict[str, Any]:
        covered_rows = [r for r in scope_rows if (r.get("performance") or {}).get(key, {}).get("status") == "covered"]
        pending_rows = [r for r in scope_rows if (r.get("performance") or {}).get(key, {}).get("status") == "pending"]
        missing_rows = [r for r in scope_rows if (r.get("performance") or {}).get(key, {}).get("status") == "missing"]
        skipped_rows = [r for r in scope_rows if (r.get("performance") or {}).get(key, {}).get("status") == "skipped"]
        returns = [float(r["performance"][key]["return_pct"]) for r in covered_rows]
        wins = [r for r in covered_rows if r["performance"][key]["return_pct"] > 0]
        flats = [r for r in covered_rows if r["performance"][key]["return_pct"] == 0]
        losses = [r for r in covered_rows if r["performance"][key]["return_pct"] < 0]

        by_open_status: dict[str, Any] = {}
        for open_status in ("super", "expected", "reject"):
            rows = [r for r in covered_rows if (r.get("performance") or {}).get("open_check", {}).get("status") == open_status]
            row_returns = [float(r["performance"][key]["return_pct"]) for r in rows]
            by_open_status[open_status] = {
                "covered": len(rows),
                "win_rate": _pct(sum(1 for x in row_returns if x > 0), len(rows)),
                "avg_return": _avg(row_returns),
            }

        return {
            "status": "ready" if covered_rows else ("partial" if pending_rows else "missing"),
            "covered": len(covered_rows),
            "total": len(scope_rows),
            "base_total": len(denominator_rows),
            "eligible": len(scope_rows),
            "coverage": _pct(len(covered_rows), len(scope_rows)),
            "pending": len(pending_rows),
            "missing": len(missing_rows),
            "skipped": len(skipped_rows),
            "win_count": len(wins),
            "flat_count": len(flats),
            "loss_count": len(losses),
            "win_rate": _pct(len(wins), len(covered_rows)),
            "avg_return": _avg(returns),
            "avg_win_return": _avg([float(r["performance"][key]["return_pct"]) for r in wins]),
            "avg_loss_return": _avg([float(r["performance"][key]["return_pct"]) for r in losses]),
            "by_open_status": by_open_status,
        }

    tradable_rows = [r for r in records if (r.get("performance") or {}).get("open_check", {}).get("can_enter")]
    all_scope = summarize_scope(records, denominator_rows=records)
    tradable_scope = summarize_scope(tradable_rows, denominator_rows=records)

    return {
        "key": key,
        "label": label,
        "status": tradable_scope["status"],
        "covered": tradable_scope["covered"],
        "total": len(records),
        "eligible": tradable_scope["eligible"],
        "coverage": tradable_scope["coverage"],
        "pending": tradable_scope["pending"],
        "missing": tradable_scope["missing"],
        "skipped": tradable_scope["skipped"],
        "win_count": tradable_scope["win_count"],
        "flat_count": tradable_scope["flat_count"],
        "loss_count": tradable_scope["loss_count"],
        "win_rate": tradable_scope["win_rate"],
        "avg_return": tradable_scope["avg_return"],
        "avg_win_return": tradable_scope["avg_win_return"],
        "avg_loss_return": tradable_scope["avg_loss_return"],
        "by_open_status": tradable_scope["by_open_status"],
        "scopes": {
            "all": all_scope,
            "tradable": tradable_scope,
        },
        "note": "只统计 ztAnalysis 同源推荐；策略表现同时提供全样本口径与可交易样本口径，默认主展示为可交易样本。",
    }


def _build_historical_snapshot_row(record: dict[str, Any]) -> dict[str, Any]:
    performance = record.get("performance") if isinstance(record.get("performance"), dict) else {}
    open_check = performance.get("open_check") if isinstance(performance.get("open_check"), dict) else {}
    next_day = performance.get("next_day") if isinstance(performance.get("next_day"), dict) else {}
    hold_2d = performance.get("hold_2d") if isinstance(performance.get("hold_2d"), dict) else {}
    hold_3d = performance.get("hold_3d") if isinstance(performance.get("hold_3d"), dict) else {}
    signal_status = str(open_check.get("status") or "unavailable")
    can_enter = bool(open_check.get("can_enter"))
    decision_status = "buy" if can_enter else ("pending" if signal_status in {"pending", "wait_reseal"} else "reject")
    decision_label = "直接买入" if decision_status == "buy" else ("观察" if decision_status == "pending" else "低预期")
    return {
        "date10": str(record.get("date10") or "").strip(),
        "trade_date10": str(record.get("trade_date10") or "").strip(),
        "code": str(record.get("code") or "").strip(),
        "name": str(record.get("name") or "").strip(),
        "bucket": str(record.get("bucket") or "").strip(),
        "bucket_label": str(record.get("bucket_label") or "").strip(),
        "placement_label": str(record.get("placement_label") or "").strip(),
        "score": record.get("score"),
        "daily_rank": record.get("daily_rank"),
        "relay_rank": int(record.get("relay_rank") or 0),
        "watch_rank": int(record.get("watch_rank") or 0),
        "relay_selection_mode": str(record.get("relay_selection_mode") or "").strip(),
        "watch_group": str(record.get("watch_group") or "").strip(),
        "main_line": str(record.get("main_line") or "").strip(),
        "score_label": str(record.get("score_label") or "").strip(),
        "reason_text": str(record.get("reason_text") or "").strip(),
        "factor_hint": str(record.get("factor_hint") or "").strip(),
        "hit_rules": [str(x).strip() for x in (record.get("hit_rules") or []) if str(x).strip()],
        "block_reasons": [str(x).strip() for x in (record.get("block_reasons") or []) if str(x).strip()],
        "leader_factor_score": record.get("leader_factor_score"),
        "relay_factor_score": record.get("relay_factor_score"),
        "leader_philosophy_score": record.get("leader_philosophy_score"),
        "break_risk": record.get("break_risk"),
        "environment_score": record.get("environment_score"),
        "capacity_factor_score": record.get("capacity_factor_score"),
        "step_context_score": record.get("step_context_score"),
        "tide_relay_gate": record.get("tide_relay_gate"),
        "theme_ladder_profile": json.loads(json.dumps(record.get("theme_ladder_profile") or {}, ensure_ascii=False)),
        "expected_text": str(((record.get("expectation") or {}) if isinstance(record.get("expectation"), dict) else {}).get("expected_text") or "").strip(),
        "super_text": str(((record.get("expectation") or {}) if isinstance(record.get("expectation"), dict) else {}).get("super_text") or "").strip(),
        "low_text": str(((record.get("expectation") or {}) if isinstance(record.get("expectation"), dict) else {}).get("low_text") or "").strip(),
        "signal_status": signal_status,
        "signal_label": str(open_check.get("label") or "").strip(),
        "decision_status": decision_status,
        "decision_label": decision_label,
        "prev_close": open_check.get("prev_close"),
        "open_price": open_check.get("open_price"),
        "gap_pct": open_check.get("gap_pct"),
        "close_price": open_check.get("close_price"),
        "close_pct": open_check.get("close_pct"),
        "note": str(open_check.get("note") or "").strip(),
        "gap_trap": bool(open_check.get("gap_trap")),
        "next_day_status": str(next_day.get("status") or "").strip(),
        "next_day_label": str(next_day.get("label") or "").strip(),
        "next_day_return_pct": next_day.get("return_pct"),
        "next_day_note": str(next_day.get("note") or "").strip(),
        "hold_2d_status": str(hold_2d.get("status") or "").strip(),
        "hold_2d_return_pct": hold_2d.get("return_pct"),
        "hold_3d_status": str(hold_3d.get("status") or "").strip(),
        "hold_3d_return_pct": hold_3d.get("return_pct"),
    }


def _build_historical_snapshot_from_prefetched_quotes(date10: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    prefetched = load_prefetched_realtime_quotes(date10)
    items = prefetched.get("items") if isinstance(prefetched, dict) else None
    if not isinstance(items, dict) or not items:
        return None

    prefetched_source = str(prefetched.get("source") or "").strip() if isinstance(prefetched, dict) else ""
    allow_non_window_quotes = prefetched_source == "forced_query"
    quote_map: dict[str, dict[str, Any]] = {}
    for code6, raw in items.items():
        if not isinstance(raw, dict):
            continue
        quote = _normalize_realtime_quote(raw)
        if not quote:
            continue
        quote_time = str(quote.get("time") or "").strip()
        if not _is_entry_window_time(quote_time) and not (allow_non_window_quotes and quote_time):
            continue
        quote_map[str(code6)] = quote
    if not quote_map:
        return None

    merged_rows: list[dict[str, Any]] = []
    for row in rows:
        base_row = _build_historical_snapshot_row(row)
        code6 = str(row.get("code") or "").strip()
        quote = quote_map.get(code6)
        if not quote:
            merged_rows.append(base_row)
            continue
        decision_row = _evaluate_realtime_signal(row, quote)
        merged_rows.append(_merge_historical_snapshot_row_with_realtime(base_row, decision_row))

    merged_rows.sort(key=lambda x: (_signal_rank(str(x.get("signal_status") or "")), *_row_selection_priority(x)))
    buy_list = [row for row in merged_rows if row.get("decision_status") == "buy"]
    pending_list = [row for row in merged_rows if row.get("decision_status") == "pending"]
    rejected_list = [row for row in merged_rows if row.get("decision_status") == "reject"]
    unavailable_list = [row for row in merged_rows if row.get("decision_status") == "unavailable"]
    direct_super = [row for row in buy_list if row.get("signal_status") == "super"]
    direct_expected = [row for row in buy_list if row.get("signal_status") == "expected"]
    trade_date10 = str(rows[0].get("trade_date10") or "").strip() if rows else ""
    as_of = str(prefetched.get("as_of") or "").strip() if isinstance(prefetched, dict) else ""
    reused_label = "fore 代理快照" if allow_non_window_quotes else "09:25 竞价快照"
    partial_count = max(len(rows) - len(quote_map), 0)
    note = f"已复用 {trade_date10 or '-'} 的{reused_label}恢复竞价判断；收盘收益字段仍按历史闭环记录计算。"
    if partial_count > 0:
        note += f" 其中 {partial_count} 只未命中原始快照，已回退为收盘后闭环恢复。"
    return {
        "reference_date": date10,
        "trade_date": trade_date10,
        "entry_window": "09:25-09:30",
        "quote_time": as_of,
        "source_module": "ztAnalysis.relay/watch",
        "quote_source": "prefetched_realtime_quotes",
        "candidate_count": len(merged_rows),
        "quoted_count": len(quote_map),
        "buy_count": len(buy_list),
        "direct_super_count": len(direct_super),
        "direct_expected_count": len(direct_expected),
        "pending_count": len(pending_list),
        "rejected_count": len(rejected_list),
        "unavailable_count": len(unavailable_list),
        "buy_list": buy_list,
        "pending_list": pending_list,
        "rejected_list": rejected_list,
        "unavailable_list": unavailable_list,
        "diagnostics": {
            "source": str(prefetched.get("source") or "prefetched_realtime_quotes"),
            "recovered": False,
            "used_prefetched_snapshot": True,
            "note": note,
        },
    }


def _build_historical_snapshots(backtest_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not backtest_rows:
        return []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in backtest_rows:
        date10 = str(row.get("date10") or "").strip()
        if date10:
            grouped[date10].append(row)

    snapshots: list[dict[str, Any]] = []
    for date10 in sorted(grouped.keys(), reverse=True):
        rows = sorted(grouped[date10], key=lambda row: (int(row.get("daily_rank") or 9999), *_row_selection_priority(row)))
        prefetched_snapshot = _build_historical_snapshot_from_prefetched_quotes(date10, rows)
        if prefetched_snapshot:
            snapshots.append(prefetched_snapshot)
            continue
        decisions = [_build_historical_snapshot_row(row) for row in rows]
        decisions.sort(key=lambda x: (_signal_rank(str(x.get("signal_status") or "")), *_row_selection_priority(x)))
        buy_list = [row for row in decisions if row.get("decision_status") == "buy"]
        pending_list = [row for row in decisions if row.get("decision_status") == "pending"]
        rejected_list = [row for row in decisions if row.get("decision_status") == "reject"]
        direct_super = [row for row in buy_list if row.get("signal_status") == "super"]
        direct_expected = [row for row in buy_list if row.get("signal_status") == "expected"]
        trade_date10 = str(rows[0].get("trade_date10") or "").strip() if rows else ""
        snapshots.append(
            {
                "reference_date": date10,
                "trade_date": trade_date10,
                "entry_window": "09:25-09:30",
                "quote_time": "",
                "source_module": "ztAnalysis.relay/watch",
                "quote_source": "recovered_from_backtest_records",
                "candidate_count": len(decisions),
                "quoted_count": len(decisions),
                "buy_count": len(buy_list),
                "direct_super_count": len(direct_super),
                "direct_expected_count": len(direct_expected),
                "pending_count": len(pending_list),
                "rejected_count": len(rejected_list),
                "unavailable_count": 0,
                "buy_list": buy_list,
                "pending_list": pending_list,
                "rejected_list": rejected_list,
                "unavailable_list": [],
                "diagnostics": {
                    "source": "recovered_from_backtest_records",
                    "recovered": True,
                    "note": f"原始 9:25 快照缺失，已根据 {trade_date10 or '-'} 收盘后回测记录恢复开盘涨幅、命中结果与当日收益；原始竞价量能无法事后还原。",
                },
            }
        )
    return snapshots


def _is_backtest_ready_record(record: dict[str, Any]) -> bool:
    performance = record.get("performance") if isinstance(record.get("performance"), dict) else {}
    open_check = performance.get("open_check") if isinstance(performance.get("open_check"), dict) else {}
    return str(open_check.get("status") or "") != "missing"


def _pick_realtime_reference_date(rows: list[dict[str, Any]], *, current_market_data: dict[str, Any] | None = None) -> str:
    dates = sorted({str(row.get("date10") or "") for row in rows if str(row.get("date10") or "")})
    return dates[-1] if dates else ""


def _merge_current_pool_with_realtime(rows: list[dict[str, Any]], realtime_buy: dict[str, Any]) -> list[dict[str, Any]]:
    decision_map: dict[str, dict[str, Any]] = {}
    for bucket in ("buy_list", "pending_list", "rejected_list", "unavailable_list"):
        for row in realtime_buy.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            code = str(row.get("code") or "").strip()
            if code:
                decision_map[code] = row

    merged_rows: list[dict[str, Any]] = []
    for row in rows:
        rec = json.loads(json.dumps(row, ensure_ascii=False))
        code = str(rec.get("code") or "").strip()
        decision = decision_map.get(code)
        if not decision:
            merged_rows.append(rec)
            continue

        performance = rec.get("performance") if isinstance(rec.get("performance"), dict) else {}
        open_check = performance.get("open_check") if isinstance(performance.get("open_check"), dict) else {}
        if str(open_check.get("status") or "") == "missing":
            signal_status = str(decision.get("signal_status") or "")
            auction_price = decision.get("auction_price")
            prev_close = decision.get("prev_close")
            gap_pct = decision.get("gap_pct")
            performance["open_check"] = {
                "status": signal_status or ("expected" if decision.get("decision_status") == "buy" else "reject"),
                "label": decision.get("signal_label") or decision.get("decision_label") or "待判断",
                "gap_pct": gap_pct,
                "note": decision.get("note") or "已按 9:25 实时竞价补齐开盘判断。",
                "can_enter": str(decision.get("decision_status") or "") == "buy",
                "prev_close": round(float(prev_close), 2) if prev_close not in (None, "") else None,
                "open_price": round(float(auction_price), 2) if auction_price not in (None, "") else None,
                "close_price": None,
                "close_pct": None,
                "gap_trap": False,
            }
            for key, label, _ in STRATEGIES:
                item = performance.get(key) if isinstance(performance.get(key), dict) else {}
                if str(item.get("status") or "") == "missing":
                    performance[key] = {
                        "status": "pending",
                        "label": label,
                        "note": "已拿到 9:25 开盘判断，待收盘后补齐收益表现。",
                    }
        rec["performance"] = performance
        if decision.get("prev_close") not in (None, ""):
            rec["prev_close"] = decision.get("prev_close")
        if decision.get("auction_price") not in (None, ""):
            rec["open_price"] = decision.get("auction_price")
            rec["auction_price"] = decision.get("auction_price")
        if decision.get("gap_pct") not in (None, ""):
            rec["gap_pct"] = decision.get("gap_pct")
        if decision.get("auction_amount_yi") not in (None, ""):
            rec["auction_amount_yi"] = decision.get("auction_amount_yi")
        if decision.get("auction_amount_need_yi") not in (None, ""):
            rec["auction_amount_need_yi"] = decision.get("auction_amount_need_yi")
        if decision.get("quote_time"):
            rec["quote_time"] = str(decision.get("quote_time") or "").strip()
        if decision.get("signal_status"):
            rec["signal_status"] = decision.get("signal_status")
        if decision.get("signal_label"):
            rec["signal_label"] = decision.get("signal_label")
        if decision.get("decision_status"):
            rec["decision_status"] = decision.get("decision_status")
        if decision.get("decision_label"):
            rec["decision_label"] = decision.get("decision_label")
        if decision.get("rule_text"):
            rec["rule_text"] = decision.get("rule_text")
        if decision.get("note"):
            rec["note"] = decision.get("note")
        merged_rows.append(rec)
    return merged_rows


def build_stock_research_backtest_payload(
    *,
    current_market_data: dict[str, Any] | None = None,
    query_tag: str | None = None,
    sync_source_from_market_data: bool = True,
) -> dict[str, Any]:
    if sync_source_from_market_data and isinstance(current_market_data, dict):
        sync_stock_research_backtest_source(market_data=current_market_data)
    rows, generated_from = _load_stock_research_rows()
    if not rows:
        return _empty_backtest_payload(generated_from=generated_from)
    rows = _attach_daily_rank(rows)

    unique_codes = sorted({r["code"] for r in rows if r["code"]})
    source_date_list = sorted({r["date10"] for r in rows})
    latest_source_date10 = source_date_list[-1] if source_date_list else ""
    histories, price_diag = _get_price_histories(unique_codes, st8=source_date_list[0].replace("-", ""), et8=_now_bj().strftime("%Y%m%d"))

    enriched_rows: list[dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        rec["performance"] = _evaluate_one(rec, histories.get(rec["code"], []))
        enriched_rows.append(rec)

    active_trade_date10 = _pick_active_trade_date(enriched_rows)
    current_pool_rows = [r for r in enriched_rows if str(r.get("trade_date10") or "") == active_trade_date10]
    current_pool_rows = _sort_rows_by_selection_priority(current_pool_rows)
    reference_date10 = _pick_realtime_reference_date(current_pool_rows, current_market_data=current_market_data)
    realtime_buy = _build_realtime_buy_payload(
        current_pool_rows or enriched_rows,
        latest_date10=reference_date10,
        trade_date10=active_trade_date10,
        current_market_data=current_market_data,
        query_tag=query_tag,
    ) if reference_date10 else _empty_backtest_payload()["realtimeBuy"]
    current_pool_rows = _sort_rows_by_selection_priority(_merge_current_pool_with_realtime(current_pool_rows, realtime_buy))

    backtest_rows = [r for r in enriched_rows if _is_backtest_ready_record(r)]
    display_rows = _sort_rows_by_selection_priority([json.loads(json.dumps(r, ensure_ascii=False)) for r in enriched_rows])
    historical_snapshots = _build_historical_snapshots(backtest_rows)
    latest_backtest_date10 = ""
    if backtest_rows:
        latest_backtest_date10 = sorted({r["date10"] for r in backtest_rows})[-1]
    anchors = _resolve_display_anchors(
        current_pool_rows=current_pool_rows,
        backtest_rows=backtest_rows,
        historical_snapshots=historical_snapshots,
        realtime_buy=realtime_buy,
        active_trade_date10=active_trade_date10,
        latest_recommendation_date10=latest_source_date10,
    )
    lifecycle = _build_lifecycle(
        latest_recommendation_date10=latest_source_date10,
        active_trade_date10=active_trade_date10,
        latest_backtest_date10=latest_backtest_date10,
        latest_closed_trade_date10=anchors["latest_closed_trade_date"],
        latest_closed_recommendation_date10=anchors["latest_closed_recommendation_date"],
        default_display_trade_date10=anchors["default_display_trade_date"],
        default_display_recommendation_date10=anchors["default_display_recommendation_date"],
        has_pending_next_trade_day=bool(anchors["has_pending_next_trade_day"]),
        default_display_note=str(anchors["default_display_note"] or "").strip(),
        current_pool_rows=current_pool_rows,
        backtest_rows=backtest_rows,
        realtime_buy=realtime_buy,
    )
    if not backtest_rows:
        payload = _empty_backtest_payload(generated_from=generated_from)
        payload["summary"]["source_samples"] = len(enriched_rows)
        payload["summary"]["filtered_non_backtest_samples"] = len(enriched_rows)
        payload["meta"]["latest_recommendation_date"] = latest_source_date10
        payload["meta"]["active_trade_date"] = active_trade_date10
        payload["meta"]["latest_closed_trade_date"] = anchors["latest_closed_trade_date"]
        payload["meta"]["latest_closed_recommendation_date"] = anchors["latest_closed_recommendation_date"]
        payload["meta"]["default_display_trade_date"] = anchors["default_display_trade_date"]
        payload["meta"]["default_display_recommendation_date"] = anchors["default_display_recommendation_date"]
        payload["meta"]["has_pending_next_trade_day"] = anchors["has_pending_next_trade_day"]
        payload["meta"]["is_empty"] = False
        payload["lifecycle"] = lifecycle
        payload["realtimeBuy"] = realtime_buy
        payload["currentPoolRecords"] = current_pool_rows
        payload["displayRecords"] = display_rows
        payload["historicalSnapshots"] = historical_snapshots
        payload["assumptions"].append("当天尚未走完次日开盘验证的数据会被清洗掉，不混入回测统计。")
        payload["diagnostics"]["filtered_non_backtest_codes"] = [r["code"] for r in enriched_rows if r.get("code")]
        payload["diagnostics"]["display_only_codes"] = [r["code"] for r in display_rows if r.get("code")]
        return payload

    date_list = sorted({r["date10"] for r in backtest_rows})

    total = len(backtest_rows)
    eligible_rows = [r for r in backtest_rows if (r.get("performance") or {}).get("open_check", {}).get("can_enter")]
    super_rows = [r for r in backtest_rows if (r.get("performance") or {}).get("open_check", {}).get("status") == "super"]
    expected_rows = [r for r in backtest_rows if (r.get("performance") or {}).get("open_check", {}).get("status") == "expected"]
    pending_rows_bk = [r for r in backtest_rows if (r.get("performance") or {}).get("open_check", {}).get("status") in ("pending", "wait_reseal")]
    rejected_rows = [r for r in backtest_rows if (r.get("performance") or {}).get("open_check", {}).get("status") == "reject"]

    by_bucket = Counter(r["bucket"] for r in backtest_rows)
    by_open_status = Counter((r.get("performance") or {}).get("open_check", {}).get("status") or "unknown" for r in backtest_rows)
    by_mainline = Counter(r["main_line"] for r in backtest_rows if r["main_line"])
    by_date_status: dict[str, dict[str, int]] = defaultdict(lambda: {"super": 0, "expected": 0, "pending": 0, "reject": 0})
    for row in backtest_rows:
        status = (row.get("performance") or {}).get("open_check", {}).get("status") or "reject"
        if status not in by_date_status[row["date10"]]:
            by_date_status[row["date10"]][status] = 0
        by_date_status[row["date10"]][status] += 1

    metrics = {
        "next_day": _summarize_strategy(backtest_rows, "next_day", "隔日收益"),
        "hold_2d": _summarize_strategy(backtest_rows, "hold_2d", "2日收益"),
        "hold_3d": _summarize_strategy(backtest_rows, "hold_3d", "3日收益"),
    }

    return {
        "schema": "stock_research_backtest_v2",
        "meta": {
            "title": "个股研究开盘回测",
            "subtitle": "回测结果只读取收盘后由个股研究推送过来的专用历史源；JSON 内沉淀每天数据，页面按时间规则选择当前要读的回测日。",
            "dates": date_list,
            "generated_at_bj": _now_bj().strftime("%Y-%m-%d %H:%M:%S"),
            "generated_from": generated_from,
            "price_source": "biying hsstock/history + 本地 recommendation_price_history 缓存",
            "entry_window": "09:25-09:30",
            "source_module": "ztAnalysis.relay/watch",
            "latest_recommendation_date": latest_source_date10 or latest_backtest_date10,
            "active_trade_date": active_trade_date10,
            "latest_closed_trade_date": anchors["latest_closed_trade_date"],
            "latest_closed_recommendation_date": anchors["latest_closed_recommendation_date"],
            "default_display_trade_date": anchors["default_display_trade_date"],
            "default_display_recommendation_date": anchors["default_display_recommendation_date"],
            "has_pending_next_trade_day": anchors["has_pending_next_trade_day"],
        },
        "summary": {
            "total_samples": total,
            "source_samples": len(enriched_rows),
            "filtered_non_backtest_samples": len(enriched_rows) - total,
            "eligible_samples": len(eligible_rows),
            "expected_count": len(expected_rows),
            "super_count": len(super_rows),
            "pending_count": len(pending_rows_bk),
            "wait_reseal_count": len(pending_rows_bk),
            "rejected_count": len(rejected_rows),
            "unique_codes": len(unique_codes),
            "trade_days": len(date_list),
            "priced_codes": len(histories),
            "missing_price_codes": price_diag["missing"],
            "realtime_candidate_count": realtime_buy["candidate_count"],
            "realtime_buy_count": realtime_buy["buy_count"],
            "realtime_pending_count": realtime_buy["pending_count"],
            "realtime_unavailable_count": realtime_buy["unavailable_count"],
        },
        "assumptions": [
            f"若次日高开超过 {CAUTION_GAP_PCT:.0f}% ，统一提示谨慎接力，先观察承接，不直接按开盘价买入；历史胜率回测同步排除这类样本的直接入场。",
            "当天尚未走完次日开盘验证的数据会被清洗掉，不混入回测统计或策略表现。",
            "样本源只认收盘后的个股研究推送结果；盘中缓存、旧页面快照、其他补充入口都不作为回测样本源。",
            "这个 JSON 内会按回测交易日沉淀每天数据；开盘前优先读取最新收盘后推出来的下一交易日，开盘后优先读取当天交易日。",
            "最新推荐日的 9:25 买入列表只允许在北京时区 09:25-09:30 请求 biying 批量竞价接口；窗口外只复用已落地结果，不因页面刷新重复取数。",
            "如果当前环境拿不到远端数据，只会展示待补齐/报价缺失，不会伪造买点。",
            "入场窗口限定为次日 09:25-09:30；只有开盘缺口满足“符合预期”或可在开盘窗口确认“超预期”时，才记为买入样本。",
            "若超预期文案要求'盘中冲高确认/量能放大'等开盘后行为，当前历史回测会保守记为待确认（pending），不在开盘窗口直接入场。旧版数据中的回封/封单/开板条件同理。",
            "盘中确认条件（冲高/量能）可用日K高点和成交量事后验证是否达成；达成则记为入场，未达成则记为跳过。较之前 wait_reseal 一律跳过更精细。",
            "收益口径仍按次日开盘买入、目标交易日收盘卖出；未扣除手续费、滑点，也未处理一字板无法成交的真实约束。",
        ],
        "breakdowns": {
            "by_bucket": [{"name": k, "count": v} for k, v in by_bucket.items()],
            "by_open_status": [{"name": k, "count": v} for k, v in by_open_status.items()],
            "by_mainline": [{"name": k, "count": v} for k, v in by_mainline.most_common(10)],
            "by_date_status": [{"date": k, **v} for k, v in sorted(by_date_status.items())],
        },
        "metrics": metrics,
        "lifecycle": lifecycle,
        "realtimeBuy": realtime_buy,
        "currentPoolRecords": current_pool_rows,
        "displayRecords": display_rows,
        "historicalSnapshots": historical_snapshots,
        "records": backtest_rows,
        "diagnostics": {
            "price_history": price_diag,
            "realtime_buy": realtime_buy.get("diagnostics", {}),
            "filtered_non_backtest_codes": [r["code"] for r in enriched_rows if not _is_backtest_ready_record(r) and r.get("code")],
            "display_only_codes": [r["code"] for r in display_rows if not _is_backtest_ready_record(r) and r.get("code")],
        },
    }


def main() -> None:
    payload = build_stock_research_backtest_payload()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    OUT_JSON.write_text(json_text, encoding="utf-8")
    OUT_JS.write_text(f"window.__STOCK_RESEARCH_BACKTEST__ = {json_text};\n", encoding="utf-8")
    print(str(OUT_JSON))
    print(str(OUT_JS))


if __name__ == "__main__":
    main()
