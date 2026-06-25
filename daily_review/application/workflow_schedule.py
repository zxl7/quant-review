from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TZ_BJ = timezone(timedelta(hours=8))

SCHEDULE_MODE_BY_CRON: dict[str, str] = {
    "26 1 * * 1-5": "open_fore",
    "35-55/5 1 * * 1-5": "intraday",
    "*/5 2 * * 1-5": "intraday",
    "0-30/5 3 * * 1-5": "intraday",
    "*/5 5-6 * * 1-5": "intraday",
    "0 7 * * 1-5": "eod",
    "0 8 * * 1-5": "eod",
    "0 9 * * 1-5": "eod",
    "0 10 * * 1-5": "eod",
}

INVALID_QUOTE_SOURCES = {"unavailable", "forced_query_unavailable"}

INTRADAY_CUTOFF_HOUR_BJ = 15


def _now_bj() -> datetime:
    return datetime.now(TZ_BJ)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def resolve_publish_schedule_mode(
    event_name: str,
    schedule_expr: str = "",
    *,
    now: datetime | None = None,
) -> dict[str, str]:
    current = now.astimezone(TZ_BJ) if now else _now_bj()
    schedule_text = str(schedule_expr or "").strip()
    result = {
        "event_name": str(event_name or "").strip(),
        "schedule_expr": schedule_text,
        "beijing_now": current.strftime("%H:%M"),
        "skip": "false",
        "mode": "",
        "reason": "",
    }
    if result["event_name"] != "schedule":
        result["reason"] = "non_schedule_event"
        return result

    mode = SCHEDULE_MODE_BY_CRON.get(schedule_text)
    if mode:
        if mode == "intraday" and current.hour >= INTRADAY_CUTOFF_HOUR_BJ:
            result["mode"] = "eod"
            result["reason"] = (
                f"promoted_delayed_intraday_to_eod:{schedule_text}@{result['beijing_now']}"
            )
            return result
        result["mode"] = mode
        result["reason"] = f"resolved_from_schedule:{schedule_text}"
        return result

    result["skip"] = "true"
    result["mode"] = "skip"
    result["reason"] = f"unsupported_schedule:{schedule_text or '<empty>'}"
    return result


def resolve_full_publish_source_cache(cache_dir: Path, requested_date10: str) -> dict[str, Any]:
    requested = str(requested_date10 or "").strip()
    result: dict[str, Any] = {
        "found": False,
        "path": "",
        "requested_date10": requested,
        "effective_date10": "",
        "effective_date8": "",
        "reason": "no_valid_full_cache",
    }
    if len(requested) != 10:
        result["reason"] = "invalid_requested_date"
        return result
    if not cache_dir.exists():
        result["reason"] = "cache_dir_missing"
        return result

    requested_date8 = requested.replace("-", "")
    valid_candidates: list[tuple[str, Path]] = []
    for path in sorted(cache_dir.glob("market_data-*.json"), reverse=True):
        stem = path.stem
        suffix = stem[len("market_data-") :] if stem.startswith("market_data-") else ""
        # full publish 只消费标准收盘缓存，显式忽略 -intraday 变体。
        if len(suffix) != 8 or not suffix.isdigit():
            continue
        payload = _read_json(path)
        expected_date10 = f"{suffix[:4]}-{suffix[4:6]}-{suffix[6:8]}"
        if str(payload.get("date") or "").strip() != expected_date10:
            continue
        valid_candidates.append((suffix, path))
        if suffix == requested_date8:
            result.update(
                {
                    "found": True,
                    "path": str(path),
                    "effective_date10": expected_date10,
                    "effective_date8": suffix,
                    "reason": "requested_date_cache_ready",
                }
            )
            return result

    if not valid_candidates:
        return result

    latest_date8, latest_path = max(valid_candidates, key=lambda item: item[0])
    result.update(
        {
            "found": True,
            "path": str(latest_path),
            "effective_date10": f"{latest_date8[:4]}-{latest_date8[4:6]}-{latest_date8[6:8]}",
            "effective_date8": latest_date8,
            "reason": "fallback_latest_valid_full_cache",
        }
    )
    return result


def describe_prefetched_quotes_snapshot(cache_dir: Path, trade_date10: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "found": False,
        "path": "",
        "source": "",
        "as_of": "",
        "count": 0,
        "reference_date": "",
    }
    if len(trade_date10) != 10 or not cache_dir.exists():
        return result

    for path in sorted(cache_dir.glob("stock_research_realtime_quotes-*.json"), reverse=True):
        payload = _read_json(path)
        items = payload.get("items")
        as_of = str(payload.get("as_of") or "").strip()
        source = str(payload.get("source") or "").strip()
        if not isinstance(items, dict) or not items:
            continue
        if not as_of.startswith(trade_date10) or len(as_of) < 19:
            continue
        if source in INVALID_QUOTE_SOURCES:
            continue
        result.update(
            {
                "found": True,
                "path": str(path),
                "source": source,
                "as_of": as_of,
                "count": len(items),
                "reference_date": str(payload.get("date") or "").strip(),
            }
        )
        return result
    return result


def describe_market_data_snapshot(path: Path, trade_date10: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "found": False,
        "path": str(path),
        "source": "",
        "quote_time": "",
        "trade_date": "",
        "reference_date": "",
        "candidate_count": 0,
        "future_trade_day_guard": False,
    }
    if len(trade_date10) != 10 or not path.exists():
        return result

    payload = _read_json(path)
    backtest = payload.get("stockResearchBacktest") if isinstance(payload.get("stockResearchBacktest"), dict) else {}
    realtime_buy = backtest.get("realtimeBuy") if isinstance(backtest.get("realtimeBuy"), dict) else {}
    diagnostics = realtime_buy.get("diagnostics") if isinstance(realtime_buy.get("diagnostics"), dict) else {}
    quote_time = str(realtime_buy.get("quote_time") or "").strip()
    source = str(diagnostics.get("source") or "").strip()
    trade_date = str(realtime_buy.get("trade_date") or "").strip()
    reference_date = str(realtime_buy.get("reference_date") or "").strip()
    candidate_count = int(realtime_buy.get("candidate_count") or 0)
    future_trade_day_guard = bool(diagnostics.get("future_trade_day_guard")) or source == "future_trade_day_guard"
    quote_time_matches_trade_date = quote_time.startswith(f"{trade_date10} ") if trade_date10 and quote_time else False
    valid = (
        quote_time_matches_trade_date
        and len(quote_time) >= 19
        and trade_date == trade_date10
        and source not in INVALID_QUOTE_SOURCES
    )
    result.update(
        {
            "found": valid,
            "source": source,
            "quote_time": quote_time,
            "trade_date": trade_date,
            "reference_date": reference_date,
            "candidate_count": candidate_count,
            "future_trade_day_guard": future_trade_day_guard,
            "quote_time_matches_trade_date": quote_time_matches_trade_date,
        }
    )
    return result


def resolve_stock_research_query_plan(
    *,
    mode: str,
    trade_date10: str,
    is_trade_today: bool,
    input_query_tag: str,
    cache_dir: Path,
) -> dict[str, Any]:
    normalized_input = str(input_query_tag or "").strip().lower()
    prefetched = describe_prefetched_quotes_snapshot(cache_dir, trade_date10)
    market_data = describe_market_data_snapshot(cache_dir / f"market_data-{trade_date10.replace('-', '')}.json", trade_date10)

    if normalized_input:
        effective_query_tag = normalized_input
        reason = "manual_input"
        refresh_backtest = True
        validate_snapshot = True
    elif mode == "intraday":
        effective_query_tag = ""
        reason = "intraday_mode"
        refresh_backtest = False
        validate_snapshot = False
    elif not is_trade_today:
        effective_query_tag = ""
        reason = "not_trade_today"
        refresh_backtest = False
        validate_snapshot = False
    elif mode == "eod":
        effective_query_tag = ""
        reason = "eod_refresh_prediction_pool"
        refresh_backtest = True
        validate_snapshot = False
    elif mode != "open_fore":
        effective_query_tag = ""
        reason = "non_open_fore_mode"
        refresh_backtest = False
        validate_snapshot = False
    elif prefetched["found"]:
        effective_query_tag = ""
        reason = "prefetched_quotes_ready"
        refresh_backtest = True
        validate_snapshot = True
    elif market_data["found"]:
        effective_query_tag = ""
        reason = "market_data_snapshot_ready"
        refresh_backtest = True
        validate_snapshot = True
    else:
        effective_query_tag = "fore"
        reason = "snapshot_missing_fallback_to_fore"
        refresh_backtest = True
        validate_snapshot = True

    return {
        "effective_query_tag": effective_query_tag,
        "resolution_reason": reason,
        "refresh_backtest": refresh_backtest,
        "validate_snapshot": validate_snapshot,
        "prefetched_snapshot": prefetched,
        "market_data_snapshot": market_data,
    }


def validate_eod_stock_research_prediction_pool(path: Path, run_date10: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "required": False,
        "message": "no_eod_candidates",
        "path": str(path),
        "run_date": str(run_date10 or "").strip(),
        "published_date": "",
        "active_trade_date": "",
        "current_pool_count": 0,
        "candidate_count": 0,
    }
    if len(result["run_date"]) != 10:
        result["ok"] = False
        result["message"] = "invalid_run_date"
        return result
    if not path.exists():
        result["ok"] = False
        result["message"] = "market_data_missing"
        return result

    payload = _read_json(path)
    published_date = str(payload.get("date") or "").strip()
    result["published_date"] = published_date
    if published_date != result["run_date"]:
        result["ok"] = False
        result["message"] = "published_date_mismatch"
        return result

    zt = payload.get("ztAnalysis") if isinstance(payload.get("ztAnalysis"), dict) else {}
    relay = zt.get("relay") if isinstance(zt.get("relay"), list) else []
    watch = zt.get("watch") if isinstance(zt.get("watch"), list) else []
    candidate_count = len(relay) + len(watch)
    result["candidate_count"] = candidate_count
    if candidate_count <= 0:
        return result

    result["required"] = True
    backtest = payload.get("stockResearchBacktest") if isinstance(payload.get("stockResearchBacktest"), dict) else {}
    meta = backtest.get("meta") if isinstance(backtest.get("meta"), dict) else {}
    current_pool = backtest.get("currentPoolRecords") if isinstance(backtest.get("currentPoolRecords"), list) else []
    active_trade_date = str(meta.get("active_trade_date") or "").strip()
    result["active_trade_date"] = active_trade_date
    result["current_pool_count"] = len(current_pool)

    if active_trade_date > result["run_date"] and current_pool:
        result["message"] = "prediction_pool_ready"
        return result

    result["ok"] = False
    result["message"] = (
        "eod stockResearchBacktest prediction pool missing or stale: "
        f"run_date={result['run_date']} active_trade_date={active_trade_date or '<missing>'} "
        f"current_pool_count={len(current_pool)} candidate_count={candidate_count}"
    )
    return result


def validate_intraday_runtime_indices(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "message": "indices_ready",
        "path": str(path),
        "count": 0,
        "names": [],
        "as_of": "",
    }
    if not path.exists():
        result["ok"] = False
        result["message"] = "intraday_runtime_missing"
        return result

    payload = _read_json(path)
    rows = payload.get("indices") if isinstance(payload.get("indices"), list) else []
    names = [str(row.get("name") or "").strip() for row in rows if isinstance(row, dict) and str(row.get("name") or "").strip()]
    as_of = str(((payload.get("asOf") or {}) if isinstance(payload.get("asOf"), dict) else {}).get("indices") or "").strip()
    result["count"] = len(names)
    result["names"] = names
    result["as_of"] = as_of
    required = {"上证指数", "深证成指", "创业板指"}
    if len(names) < 3 or not required.issubset(set(names)) or not as_of:
        result["ok"] = False
        result["message"] = (
            "intraday_runtime_indices_incomplete: "
            f"count={len(names)} names={names} as_of={as_of or '<missing>'}"
        )
    return result


def validate_eod_stock_research_closeout(path: Path, run_date10: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "required": False,
        "message": "no_eod_candidates",
        "path": str(path),
        "run_date": str(run_date10 or "").strip(),
        "published_date": "",
        "latest_closed_trade_date": "",
        "candidate_count": 0,
        "covered_count": 0,
    }
    if len(result["run_date"]) != 10:
        result["ok"] = False
        result["message"] = "invalid_run_date"
        return result
    if not path.exists():
        result["ok"] = False
        result["message"] = "market_data_missing"
        return result

    payload = _read_json(path)
    published_date = str(payload.get("date") or "").strip()
    result["published_date"] = published_date
    if published_date != result["run_date"]:
        result["ok"] = False
        result["message"] = "published_date_mismatch"
        return result

    zt = payload.get("ztAnalysis") if isinstance(payload.get("ztAnalysis"), dict) else {}
    relay = zt.get("relay") if isinstance(zt.get("relay"), list) else []
    watch = zt.get("watch") if isinstance(zt.get("watch"), list) else []
    candidate_count = len(relay) + len(watch)
    result["candidate_count"] = candidate_count
    if candidate_count <= 0:
        return result

    result["required"] = True
    backtest = payload.get("stockResearchBacktest") if isinstance(payload.get("stockResearchBacktest"), dict) else {}
    meta = backtest.get("meta") if isinstance(backtest.get("meta"), dict) else {}
    display_records = backtest.get("displayRecords") if isinstance(backtest.get("displayRecords"), list) else []
    result["latest_closed_trade_date"] = str(meta.get("latest_closed_trade_date") or "").strip()
    covered_rows = []
    for row in display_records:
        if not isinstance(row, dict):
            continue
        if str(row.get("trade_date10") or "").strip() != result["run_date"]:
            continue
        performance = row.get("performance") if isinstance(row.get("performance"), dict) else {}
        open_check = performance.get("open_check") if isinstance(performance.get("open_check"), dict) else {}
        next_day = performance.get("next_day") if isinstance(performance.get("next_day"), dict) else {}
        hold_2d = performance.get("hold_2d") if isinstance(performance.get("hold_2d"), dict) else {}
        hold_3d = performance.get("hold_3d") if isinstance(performance.get("hold_3d"), dict) else {}
        has_close = row.get("close_price") not in (None, "") or open_check.get("close_price") not in (None, "")
        has_close_pct = row.get("close_pct") not in (None, "") or open_check.get("close_pct") not in (None, "")
        has_return = any(
            row.get(key) not in (None, "")
            for key in ("next_day_return_pct", "hold_2d_return_pct", "hold_3d_return_pct", "return_pct")
        ) or any(
            item.get("return_pct") not in (None, "")
            for item in (next_day, hold_2d, hold_3d)
        )
        if has_close or has_close_pct or has_return:
            covered_rows.append(row)
    result["covered_count"] = len(covered_rows)

    if result["latest_closed_trade_date"] != result["run_date"]:
        result["ok"] = False
        result["message"] = (
            "latest_closed_trade_date_stale: "
            f"run_date={result['run_date']} latest_closed_trade_date={result['latest_closed_trade_date'] or '<missing>'}"
        )
        return result

    if not covered_rows:
        result["ok"] = False
        result["message"] = (
            "eod_stock_research_closeout_missing: "
            f"run_date={result['run_date']} candidate_count={candidate_count} covered_count=0"
        )
    return result


def validate_account_derivatives(*, ledger_path: Path, metrics_path: Path, run_date10: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "message": "account_derivatives_ready",
        "run_date": str(run_date10 or "").strip(),
        "ledger_path": str(ledger_path),
        "metrics_path": str(metrics_path),
        "ledger_latest_trade_date": "",
        "metrics_latest_trade_date": "",
    }
    if len(result["run_date"]) != 10:
        result["ok"] = False
        result["message"] = "invalid_run_date"
        return result
    if not ledger_path.exists():
        result["ok"] = False
        result["message"] = "account_nav_ledger_missing"
        return result
    if not metrics_path.exists():
        result["ok"] = False
        result["message"] = "account_strategy_metrics_missing"
        return result

    ledger_rows: list[dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except Exception:
            continue
        if isinstance(item, dict):
            ledger_rows.append(item)
    if ledger_rows:
        result["ledger_latest_trade_date"] = str(ledger_rows[-1].get("trade_date") or "").strip()

    metrics_payload = _read_json(metrics_path)
    result["metrics_latest_trade_date"] = str(metrics_payload.get("latest_trade_date") or "").strip()

    if result["ledger_latest_trade_date"] != result["run_date"]:
        result["ok"] = False
        result["message"] = (
            "account_nav_ledger_stale: "
            f"run_date={result['run_date']} latest_trade_date={result['ledger_latest_trade_date'] or '<missing>'}"
        )
        return result
    if result["metrics_latest_trade_date"] != result["run_date"]:
        result["ok"] = False
        result["message"] = (
            "account_strategy_metrics_stale: "
            f"run_date={result['run_date']} latest_trade_date={result['metrics_latest_trade_date'] or '<missing>'}"
        )
    return result


def validate_market_data_stock_research_snapshot(path: Path, trade_date10: str) -> dict[str, Any]:
    snapshot = describe_market_data_snapshot(path, trade_date10)
    result: dict[str, Any] = {
        "ok": True,
        "required": False,
        "message": "no_candidate_rows",
        **snapshot,
    }
    candidate_count = int(snapshot.get("candidate_count") or 0)
    if candidate_count <= 0:
        return result

    result["required"] = True
    if snapshot["found"]:
        result["message"] = "snapshot_ready"
        return result

    trade_date = str(snapshot.get("trade_date") or "").strip()
    if trade_date > trade_date10 and bool(snapshot.get("future_trade_day_guard")):
        result["required"] = False
        result["message"] = "future_trade_day_pending"
        return result

    quote_time = str(snapshot.get("quote_time") or "").strip() or "<missing>"
    source = str(snapshot.get("source") or "").strip() or "<missing>"
    trade_date = trade_date or "<missing>"
    result["ok"] = False
    result["message"] = (
        "trade-day stockResearchBacktest snapshot missing or invalid: "
        f"trade_date={trade_date} quote_time={quote_time} source={source}"
    )
    return result
