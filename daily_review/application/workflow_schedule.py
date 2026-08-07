from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


TZ_BJ = timezone(timedelta(hours=8))

SCHEDULE_MODE_BY_CRON: dict[str, str] = {
    "26 1 * * 1-5": "open_fore",
    "31 1 * * 1-5": "open_fore",
    "36 1 * * 1-5": "open_fore",
    "0 7 * * 1-5": "eod",
    "0 8 * * 1-5": "eod",
    "0 9 * * 1-5": "eod",
    "0 10 * * 1-5": "eod",
}

INTRADAY_SESSION_BY_CRON: dict[str, str] = {
    "15 22 * * 0-4": "morning",
    "30 22 * * 0-4": "morning",
    "45 1 * * 1-5": "afternoon",
    "0 2 * * 1-5": "afternoon",
}
INTRADAY_SESSION_WINDOWS: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {
    "morning": ((9, 30), (11, 30)),
    "afternoon": ((13, 0), (15, 0)),
}

INVALID_QUOTE_SOURCES = {"unavailable", "forced_query_unavailable"}
AUCTION_QUOTE_SOURCES = {"workflow_prefetch", "realtime_buy_snapshot"}

INTRADAY_CUTOFF_HOUR_BJ = 15
INTRADAY_SLOT_SECONDS = 10 * 60
INTRADAY_SLOT_GRACE_SECONDS = 2 * 60
PREFETCH_HTTP_TIMEOUT = 12
PREFETCH_HTTP_RETRIES = 2
PREFETCH_FETCH_ATTEMPTS = 2
PREFETCH_RETRY_SLEEP_SECONDS = 1.2
AUCTION_SESSION_POLL_SECONDS = 10


def _now_bj() -> datetime:
    return datetime.now(TZ_BJ)


def resolve_intraday_session(
    event_name: str,
    schedule_expr: str,
    *,
    dispatch_mode: str = "once",
    now: datetime | None = None,
) -> dict[str, Any]:
    """解析 GitHub 托管的盘中会话，并把延迟启动对齐到下一个真实十分钟槽位。"""
    current = (now or _now_bj()).astimezone(TZ_BJ)
    is_manual = str(event_name or "").strip() == "workflow_dispatch"
    if is_manual and str(dispatch_mode or "").strip() != "remaining":
        return {
            "mode": "once",
            "skip": False,
            "reason": "manual_once",
            "is_fallback": False,
            "start_epoch": 0,
            "end_epoch": 0,
            "next_slot_epoch": 0,
            "wait_seconds": 0,
            "expected_iterations": 1,
        }

    session = INTRADAY_SESSION_BY_CRON.get(str(schedule_expr or "").strip(), "")
    if is_manual:
        clock = current.hour * 60 + current.minute
        if 9 * 60 + 20 <= clock <= 11 * 60 + 30:
            session = "morning"
        elif 12 * 60 + 30 <= clock <= 15 * 60:
            session = "afternoon"
    if not session:
        return {"mode": "", "skip": True, "reason": "unknown_schedule", "is_fallback": False, "start_epoch": 0, "end_epoch": 0, "next_slot_epoch": 0, "wait_seconds": 0, "expected_iterations": 0}

    (start_hour, start_minute), (end_hour, end_minute) = INTRADAY_SESSION_WINDOWS[session]
    start = current.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    end = current.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    is_fallback = not is_manual and str(schedule_expr or "").strip() in {"30 22 * * 0-4", "0 2 * * 1-5"}
    common = {
        "mode": session,
        "is_fallback": is_fallback,
        "start_epoch": int(start.timestamp()),
        "end_epoch": int(end.timestamp()),
    }
    if current.weekday() >= 5:
        return {**common, "skip": True, "reason": "non_weekday", "next_slot_epoch": 0, "wait_seconds": 0, "expected_iterations": 0}
    if current > end:
        return {**common, "skip": True, "reason": "session_finished", "next_slot_epoch": 0, "wait_seconds": 0, "expected_iterations": 0}

    if current <= start:
        next_slot = start
        reason = "session_wait"
    else:
        elapsed = int((current - start).total_seconds())
        completed_slots, remainder = divmod(elapsed, INTRADAY_SLOT_SECONDS)
        # Runner 在刻度后两分钟内启动时仍消费当前槽位，避免初始化耗时把 09:30 节点推迟到 09:40。
        slot_index = completed_slots if remainder <= INTRADAY_SLOT_GRACE_SECONDS else completed_slots + 1
        next_slot = start + timedelta(seconds=slot_index * INTRADAY_SLOT_SECONDS)
        reason = "session_active" if next_slot <= end else "session_finished"
    if next_slot > end:
        return {**common, "skip": True, "reason": "session_finished", "next_slot_epoch": 0, "wait_seconds": 0, "expected_iterations": 0}

    expected = int((end - next_slot).total_seconds()) // INTRADAY_SLOT_SECONDS + 1
    return {
        **common,
        "skip": False,
        "reason": reason,
        "next_slot_epoch": int(next_slot.timestamp()),
        "wait_seconds": max(0, int((next_slot - current).total_seconds())),
        "expected_iterations": expected,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_stock_research_rows_for_prefetch() -> tuple[list[dict[str, Any]], list[str]]:
    from scripts.build_stock_research_backtest import _load_stock_research_rows

    return _load_stock_research_rows()


def _normalize_prefetch_code(raw_code: str) -> str:
    from daily_review.data.biying import normalize_stock_code

    return normalize_stock_code(raw_code)


def _load_prefetch_runtime_config() -> Any:
    from daily_review.config import load_config_from_env

    return load_config_from_env()


def _fetch_prefetch_quotes_map(client: Any, codes: list[str]) -> tuple[dict[str, Any], str]:
    from daily_review.data.biying import fetch_stocks_realtime_map

    return fetch_stocks_realtime_map(client, codes)


def _build_prefetch_http_client(*, base_url: str, token: str) -> Any:
    from daily_review.http import HttpClient

    return HttpClient(
        base_url=base_url,
        token=token,
        timeout=PREFETCH_HTTP_TIMEOUT,
        retries=PREFETCH_HTTP_RETRIES,
    )


def _save_prefetched_quotes_snapshot(*, date10: str, items: dict[str, Any], as_of: str, source: str) -> Path:
    from scripts.build_stock_research_backtest import save_prefetched_realtime_quotes

    return save_prefetched_realtime_quotes(date10=date10, items=items, as_of=as_of, source=source)


def _pick_prefetch_reference_date(rows: list[dict[str, Any]], *, before_date10: str = "") -> str:
    dates = sorted({str(row.get("date10") or "") for row in rows if str(row.get("date10") or "")})
    if before_date10:
        older = [d for d in dates if d < before_date10]
        if older:
            return older[-1]
    return dates[-1] if dates else ""


def _collect_prefetch_codes(rows: list[dict[str, Any]], *, reference_date: str) -> list[str]:
    if len(reference_date) != 10:
        return []

    return sorted(
        {
            _normalize_prefetch_code(str(row.get("code") or ""))
            for row in rows
            if str(row.get("date10") or "") == reference_date and _normalize_prefetch_code(str(row.get("code") or ""))
        }
    )


def execute_auction_snapshot_prefetch(
    *,
    cache_dir: Path,
    trade_date10: str,
    force_outside_window: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "trade_date10": str(trade_date10 or "").strip(),
        "reference_date": "",
        "codes": [],
        "codes_count": 0,
        "quotes_count": 0,
        "attempts": 0,
        "should_prefetch": False,
        "status": "",
        "ready_source": "",
        "path": "",
        "as_of": "",
        "source": "",
        "last_error": "",
        "reason": "",
    }
    plan = resolve_auction_snapshot_prefetch_plan(cache_dir, trade_date10)
    result["should_prefetch"] = bool(plan["should_prefetch"])
    result["status"] = str(plan["status"] or "")
    result["ready_source"] = str(plan.get("ready_source") or "")
    if not plan["should_prefetch"]:
        result["ok"] = True
        result["reason"] = "snapshot_ready_skip"
        return result

    rows, _ = _load_stock_research_rows_for_prefetch()
    reference_date = _pick_prefetch_reference_date(rows, before_date10=str(trade_date10 or "").strip())
    codes = _collect_prefetch_codes(rows, reference_date=reference_date)
    result["reference_date"] = reference_date
    result["codes"] = codes
    result["codes_count"] = len(codes)
    if not rows:
        result["reason"] = "no_stock_research_rows"
        result["last_error"] = "no_stock_research_rows"
        return result
    if not reference_date:
        result["reason"] = "no_reference_date"
        result["last_error"] = "no_reference_date"
        return result
    if not codes:
        result["reason"] = "no_codes_for_reference_date"
        result["last_error"] = "no_codes_for_reference_date"
        return result

    current = now.astimezone(TZ_BJ) if now else _now_bj()
    total = current.hour * 3600 + current.minute * 60 + current.second
    in_window = 9 * 3600 + 25 * 60 <= total < 9 * 3600 + 30 * 60
    allow_outside_window_fetch = force_outside_window
    if not in_window and not allow_outside_window_fetch:
        result["reason"] = "outside_entry_window"
        result["last_error"] = "outside 09:25-09:30 window"
        return result

    cfg = _load_prefetch_runtime_config()
    client = _build_prefetch_http_client(base_url=cfg.base_url, token=cfg.token)
    quotes_map: dict[str, Any] = {}
    as_of = ""
    for attempt in range(1, PREFETCH_FETCH_ATTEMPTS + 1):
        result["attempts"] = attempt
        try:
            quotes_map, as_of = _fetch_prefetch_quotes_map(client, codes)
            returned_text = str(as_of or "").strip()
            returned_clock = returned_text[11:19]
            returned_same_day = returned_text.startswith(f"{trade_date10} ")
            returned_is_auction = (
                returned_same_day and "09:25:00" <= returned_clock < "09:30:00"
            )
            if quotes_map and (returned_is_auction or (allow_outside_window_fetch and returned_same_day)):
                path = _save_prefetched_quotes_snapshot(
                    date10=reference_date,
                    items=quotes_map,
                    as_of=as_of or current.strftime("%Y-%m-%d %H:%M:%S"),
                    source="forced_query" if allow_outside_window_fetch and not in_window else "workflow_prefetch",
                )
                result["ok"] = True
                result["quotes_count"] = len(quotes_map)
                result["path"] = str(path)
                result["as_of"] = as_of or ""
                result["source"] = "forced_query" if allow_outside_window_fetch and not in_window else "workflow_prefetch"
                result["reason"] = "prefetch_saved"
                return result
            result["last_error"] = "empty_quotes_map" if not quotes_map else "returned_quote_outside_auction_window"
        except Exception as exc:
            result["last_error"] = f"{type(exc).__name__}: {exc}"
        if attempt < PREFETCH_FETCH_ATTEMPTS:
            time.sleep(PREFETCH_RETRY_SLEEP_SECONDS)

    result["reason"] = "prefetch_failed"
    return result


def execute_auction_snapshot_prefetch_until_deadline(
    *,
    cache_dir: Path,
    trade_date10: str,
    now_fn: Callable[[], datetime] = _now_bj,
    sleep_fn: Callable[[float], None] = time.sleep,
    poll_seconds: int = AUCTION_SESSION_POLL_SECONDS,
    recover_outside_window: bool = False,
) -> dict[str, Any]:
    """优先抓取原始竞价；缺失时可在 09:30 后立即降级为同日实时补抓。"""
    started = now_fn().astimezone(TZ_BJ)
    deadline = started.replace(hour=9, minute=29, second=30, microsecond=0)
    latest: dict[str, Any] = {
        "ok": False,
        "trade_date10": trade_date10,
        "reason": "outside_entry_window",
        "last_error": "outside 09:25-09:30 window",
        "attempts": 0,
        "codes_count": 0,
        "quotes_count": 0,
        "as_of": "",
        "source": "",
    }
    rounds = 0
    total_attempts = 0

    current = started
    window_start = started.replace(hour=9, minute=25, second=0, microsecond=0)
    if current < window_start:
        # 手动恢复或延迟初始化也统一守在 09:25 起点，不能因为过早启动而
        # 直接跳过原始竞价窗口，降级到 09:30 以后才查询。
        sleep_fn((window_start - current).total_seconds())
        current = now_fn().astimezone(TZ_BJ)
    while current <= deadline:
        clock = current.hour * 3600 + current.minute * 60 + current.second
        if clock < 9 * 3600 + 25 * 60 or clock >= 9 * 3600 + 30 * 60:
            break
        rounds += 1
        latest = execute_auction_snapshot_prefetch(
            cache_dir=cache_dir,
            trade_date10=trade_date10,
            force_outside_window=False,
            now=current,
        )
        total_attempts += int(latest.get("attempts") or 0)
        print(
            "auction_capture_round="
            f"{rounds} ok={latest.get('ok')} attempts={latest.get('attempts') or 0} "
            f"codes={latest.get('codes_count') or 0} as_of={latest.get('as_of') or '-'} "
            f"reason={latest.get('reason') or '-'} error={latest.get('last_error') or '-'}"
        )
        if latest.get("ok"):
            break
        if latest.get("reason") in {"no_stock_research_rows", "no_reference_date", "no_codes_for_reference_date"}:
            break

        current = now_fn().astimezone(TZ_BJ)
        remaining = (deadline - current).total_seconds()
        if remaining <= 0:
            break
        sleep_fn(min(max(1, poll_seconds), remaining))
        current = now_fn().astimezone(TZ_BJ)

    if not latest.get("ok") and recover_outside_window:
        recovery_start = current.replace(hour=9, minute=30, second=0, microsecond=0)
        recovery_end = current.replace(hour=15, minute=0, second=0, microsecond=0)
        if current < recovery_start:
            sleep_fn((recovery_start - current).total_seconds())
            current = now_fn().astimezone(TZ_BJ)
        if recovery_start <= current < recovery_end:
            recovery = execute_auction_snapshot_prefetch(
                cache_dir=cache_dir,
                trade_date10=trade_date10,
                force_outside_window=True,
                now=current,
            )
            rounds += 1
            total_attempts += int(recovery.get("attempts") or 0)
            print(
                "auction_recovery_round="
                f"{rounds} ok={recovery.get('ok')} attempts={recovery.get('attempts') or 0} "
                f"quotes={recovery.get('quotes_count') or 0} as_of={recovery.get('as_of') or '-'} "
                f"reason={recovery.get('reason') or '-'} error={recovery.get('last_error') or '-'}"
            )
            latest = recovery
            if latest.get("ok") and latest.get("source") == "forced_query":
                latest["reason"] = "post_auction_recovery_saved"

    # 会话结束时间沿用最后一次状态采样，避免额外调用时钟导致调度边界
    # 被推进，也让采集结果、状态文件和测试使用同一条时间轴。
    finished = current
    latest = dict(latest)
    latest["session_rounds"] = rounds
    latest["session_attempts"] = total_attempts
    latest["started_at"] = started.strftime("%Y-%m-%d %H:%M:%S")
    latest["finished_at"] = finished.strftime("%Y-%m-%d %H:%M:%S")
    if not latest.get("ok") and rounds > 0:
        latest["reason"] = "auction_window_exhausted"
    return latest


def describe_auction_snapshot_status(cache_dir: Path, trade_date10: str) -> dict[str, Any]:
    result = {"found": False, "status": "", "path": "", "quote_time": "", "source": "", "valid_quote_count": 0}
    path = cache_dir / f"auction_snapshot_status-{trade_date10.replace('-', '')}.json"
    payload = _read_json(path)
    status = str(payload.get("status") or "").strip()
    quote_time = str(payload.get("quote_time") or "").strip()
    source = str(payload.get("source") or "").strip()
    quote_count = int(payload.get("valid_quote_count") or 0)
    if str(payload.get("date") or "").strip() != trade_date10 or status not in {"success", "recovered", "missing"}:
        return result
    if status in {"success", "recovered"} and not quote_time.startswith(f"{trade_date10} "):
        return result
    quote_clock = quote_time[11:19] if len(quote_time) >= 19 else ""
    # success 必须有真实竞价窗口证据；recovered 只接受同日 forced_query，
    # 防止单独残留的状态文件阻止后续任务修复实际报价缓存。
    if status == "success" and (source not in AUCTION_QUOTE_SOURCES or not ("09:25:00" <= quote_clock < "09:30:00") or quote_count <= 0):
        return result
    if status == "recovered" and (source != "forced_query" or quote_count <= 0):
        return result
    result.update(
        {
            "found": True,
            "status": status,
            "path": str(path),
            "quote_time": quote_time,
            "source": source,
            "valid_quote_count": quote_count,
        }
    )
    return result


def write_auction_snapshot_status(
    *,
    cache_dir: Path,
    trade_date10: str,
    capture_result: dict[str, Any],
    now: datetime | None = None,
) -> Path:
    """持久化成功或缺失状态，保证失败轮次也能在 09:31 发布中被观察到。"""
    current = (now or _now_bj()).astimezone(TZ_BJ)
    plan = resolve_auction_snapshot_prefetch_plan(cache_dir, trade_date10)
    prefetched = plan.get("prefetched_snapshot") if isinstance(plan.get("prefetched_snapshot"), dict) else {}
    market_data = plan.get("market_data_snapshot") if isinstance(plan.get("market_data_snapshot"), dict) else {}
    ready = plan.get("status") == "auction_snapshot_ready_skip"
    recovered = (
        bool(capture_result.get("ok"))
        and str(capture_result.get("source") or "") == "forced_query"
        and str(capture_result.get("as_of") or "").startswith(f"{trade_date10} ")
    )
    ready_snapshot = prefetched if prefetched.get("found") else market_data
    quote_time = str(ready_snapshot.get("as_of") or ready_snapshot.get("quote_time") or "") if ready else str(capture_result.get("as_of") or "")
    quote_source = str(ready_snapshot.get("source") or "") if ready else str(capture_result.get("source") or "")
    quote_count = int(ready_snapshot.get("count") or ready_snapshot.get("candidate_count") or 0) if ready else int(capture_result.get("quotes_count") or 0)
    payload = {
        "schema": "auction_snapshot_status_v1",
        "date": trade_date10,
        "status": "success" if ready else ("recovered" if recovered else "missing"),
        "started_at": str(capture_result.get("started_at") or ""),
        "finished_at": str(capture_result.get("finished_at") or current.strftime("%Y-%m-%d %H:%M:%S")),
        "session_rounds": int(capture_result.get("session_rounds") or 0),
        "attempts": int(capture_result.get("session_attempts") or capture_result.get("attempts") or 0),
        "codes_count": int(capture_result.get("codes_count") or 0),
        "valid_quote_count": quote_count,
        "quote_time": quote_time,
        "source": quote_source,
        "reason": "snapshot_ready" if ready else ("post_auction_recovery_saved" if recovered else str(capture_result.get("reason") or "auction_snapshot_missing")),
        "last_error": "" if ready or recovered else str(capture_result.get("last_error") or "auction_snapshot_missing"),
    }
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"auction_snapshot_status-{trade_date10.replace('-', '')}.json"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


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
        quote_clock = as_of[11:19]
        auction_window = "09:25:00" <= quote_clock < "09:30:00"
        if source not in {"workflow_prefetch", "realtime_buy_snapshot"} or not auction_window:
            continue
        result.update(
            {
                "found": True,
                "path": str(path),
                "source": source,
                "as_of": as_of,
                "count": len(items),
                "reference_date": str(payload.get("date") or "").strip(),
                "auction_window": True,
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
        "forced_query": False,
        "future_trade_day_guard": False,
        "auction_window": False,
        "quality": "missing",
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
    quote_clock = quote_time[11:19] if len(quote_time) >= 19 else ""
    auction_window = "09:25:00" <= quote_clock < "09:30:00"
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
            "forced_query": bool(diagnostics.get("forced_query")),
            "future_trade_day_guard": future_trade_day_guard,
            "quote_time_matches_trade_date": quote_time_matches_trade_date,
            "auction_window": auction_window,
            "quality": "auction" if valid and auction_window else ("degraded" if valid else "missing"),
        }
    )
    return result


def resolve_auction_snapshot_prefetch_plan(cache_dir: Path, trade_date10: str) -> dict[str, Any]:
    prefetched = describe_prefetched_quotes_snapshot(cache_dir, trade_date10)
    market_data = describe_market_data_snapshot(
        cache_dir / f"market_data-{trade_date10.replace('-', '')}.json",
        trade_date10,
    )

    if prefetched["found"] and prefetched.get("auction_window"):
        should_prefetch = False
        status = "auction_snapshot_ready_skip"
        ready_source = "prefetched_snapshot"
    elif (
        market_data["found"]
        and market_data.get("auction_window")
        and market_data.get("source") in AUCTION_QUOTE_SOURCES
        and not bool(market_data.get("forced_query"))
        and int(market_data.get("candidate_count") or 0) > 0
    ):
        should_prefetch = False
        status = "auction_snapshot_ready_skip"
        ready_source = "market_data_snapshot"
    else:
        should_prefetch = True
        status = "auction_snapshot_missing_prefetch_required"
        ready_source = ""

    return {
        "trade_date10": str(trade_date10 or "").strip(),
        "should_prefetch": should_prefetch,
        "status": status,
        "ready_source": ready_source,
        "prefetched_snapshot": prefetched,
        "market_data_snapshot": market_data,
    }


def resolve_stock_research_query_plan(
    *,
    mode: str,
    trade_date10: str,
    is_trade_today: bool,
    input_query_tag: str,
    cache_dir: Path,
) -> dict[str, Any]:
    normalized_input = str(input_query_tag or "").strip().lower()
    prefetch_plan = resolve_auction_snapshot_prefetch_plan(cache_dir, trade_date10)
    prefetched = prefetch_plan["prefetched_snapshot"]
    market_data = prefetch_plan["market_data_snapshot"]

    if normalized_input == "fore":
        if prefetch_plan["status"] == "auction_snapshot_ready_skip" or market_data["found"]:
            effective_query_tag = ""
            reason = "manual_fore_snapshot_ready_reuse"
        else:
            effective_query_tag = normalized_input
            reason = "manual_fore_prefetch_required"
        refresh_backtest = True
        validate_snapshot = True
    elif normalized_input:
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
    elif mode == "full":
        effective_query_tag = ""
        reason = "default_full_refresh"
        refresh_backtest = True
        validate_snapshot = True
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


def validate_intraday_runtime_indices(path: Path, *, require_indices: bool = True) -> dict[str, Any]:
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
        result["message"] = (
            "intraday_runtime_indices_incomplete: "
            f"count={len(names)} names={names} as_of={as_of or '<missing>'}"
        )
        if require_indices:
            result["ok"] = False
            return result
        result["message"] = "market_snapshot_valid_indices_unavailable"

    # 发布前拒绝把午休、空池或与 latest 不一致的旧轨迹重新带回线上。
    snapshots = payload.get("snapshots") if isinstance(payload.get("snapshots"), list) else []
    if snapshots:
        latest = payload.get("latest") if isinstance(payload.get("latest"), dict) else {}
        last = snapshots[-1] if isinstance(snapshots[-1], dict) else {}
        for row in snapshots:
            if not isinstance(row, dict):
                result.update({"ok": False, "message": "intraday_runtime_invalid_snapshot_row"})
                return result
            ts = str(row.get("ts_bj") or row.get("time") or "")
            time_text = ts[11:16] if len(ts) >= 16 else ts[:5]
            in_session = ("09:30" <= time_text <= "11:30") or ("13:00" <= time_text <= "15:00")
            quality = str(row.get("data_quality") or "")
            explicitly_degraded = quality in {"partial", "unavailable"} and isinstance(row.get("pool_status"), dict)
            if not in_session or (not explicitly_degraded and not row.get("zt") and not row.get("lianban") and not row.get("max_lb")):
                result.update({"ok": False, "message": "intraday_runtime_polluted_snapshot"})
                return result
        if str(latest.get("ts_bj") or latest.get("time") or "") != str(last.get("ts_bj") or last.get("time") or ""):
            result.update({"ok": False, "message": "intraday_runtime_latest_mismatch"})
            return result
        live_market = ((payload.get("live") or {}).get("market") if isinstance(payload.get("live"), dict) else {}) or {}
        for latest_key, live_key in (("zt", "zt"), ("dt", "dt"), ("zab", "zab"), ("lianban", "lianban"), ("max_lb", "max_lianban")):
            if live_market.get(live_key) != latest.get(latest_key):
                result.update({"ok": False, "message": f"intraday_runtime_live_mismatch:{live_key}"})
                return result
    return result


def _intraday_expected_slots(trade_date10: str) -> list[datetime]:
    try:
        day = datetime.strptime(trade_date10, "%Y-%m-%d").replace(tzinfo=TZ_BJ)
    except ValueError:
        return []
    slots: list[datetime] = []
    for start_parts, end_parts in INTRADAY_SESSION_WINDOWS.values():
        cursor = day.replace(hour=start_parts[0], minute=start_parts[1])
        end = day.replace(hour=end_parts[0], minute=end_parts[1])
        while cursor <= end:
            slots.append(cursor)
            cursor += timedelta(seconds=INTRADAY_SLOT_SECONDS)
    return slots


def validate_intraday_runtime_coverage(
    path: Path,
    trade_date10: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """检查盘中时间轴的日期、顺序和已到期十分钟槽位，不虚构错过的历史节点。"""
    current = (now or _now_bj()).astimezone(TZ_BJ)
    expected = _intraday_expected_slots(str(trade_date10 or "").strip())
    result: dict[str, Any] = {
        "ok": True,
        "status": "collecting",
        "message": "intraday_coverage_collecting",
        "path": str(path),
        "date": str(trade_date10 or "").strip(),
        "expected_count": len(expected),
        "due_count": 0,
        "observed_count": 0,
        "observed_slots": [],
        "missing_slots": [],
        "duplicate_slots": [],
        "out_of_session": [],
        "monotonic": True,
        "morning_coverage": 0,
        "afternoon_coverage": 0,
    }
    if not expected:
        result.update({"ok": False, "status": "invalid", "message": "invalid_trade_date"})
        return result
    if not path.exists():
        result.update({"ok": False, "status": "missing", "message": "intraday_runtime_missing"})
        return result

    payload = _read_json(path)
    if str(payload.get("date") or "").strip() != result["date"]:
        result.update({"ok": False, "status": "stale", "message": "intraday_runtime_date_mismatch"})
        return result

    due = [slot for slot in expected if slot <= current]
    result["due_count"] = len(due)
    snapshots = payload.get("snapshots") if isinstance(payload.get("snapshots"), list) else []
    raw_times: list[datetime] = []
    slot_counts: dict[str, int] = {}
    out_of_session: list[str] = []
    for row in snapshots:
        if not isinstance(row, dict):
            out_of_session.append("<invalid-row>")
            continue
        raw = str(row.get("ts_bj") or row.get("time") or "").strip()
        if len(raw) <= 8:
            raw = f"{result['date']} {raw}"
        try:
            timestamp = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ_BJ)
        except ValueError:
            out_of_session.append(raw or "<missing-time>")
            continue
        raw_times.append(timestamp)
        nearest = min(expected, key=lambda slot: abs((timestamp - slot).total_seconds()))
        if abs((timestamp - nearest).total_seconds()) > INTRADAY_SLOT_SECONDS // 2:
            out_of_session.append(timestamp.strftime("%H:%M:%S"))
            continue
        slot_text = nearest.strftime("%H:%M")
        slot_counts[slot_text] = slot_counts.get(slot_text, 0) + 1

    observed = sorted(slot_counts)
    due_text = [slot.strftime("%H:%M") for slot in due]
    result["observed_count"] = len(observed)
    result["observed_slots"] = observed
    result["missing_slots"] = [slot for slot in due_text if slot not in slot_counts]
    result["duplicate_slots"] = sorted(slot for slot, count in slot_counts.items() if count > 1)
    result["out_of_session"] = out_of_session
    result["monotonic"] = raw_times == sorted(raw_times)
    result["morning_coverage"] = sum(1 for slot in observed if "09:30" <= slot <= "11:30")
    result["afternoon_coverage"] = sum(1 for slot in observed if "13:00" <= slot <= "15:00")

    healthy = not result["missing_slots"] and not result["duplicate_slots"] and not out_of_session and result["monotonic"]
    result["ok"] = healthy
    if healthy and len(due) == len(expected):
        result.update({"status": "complete", "message": "intraday_coverage_complete"})
    elif healthy:
        result.update({"status": "collecting", "message": "intraday_coverage_collecting"})
    else:
        result.update({"status": "degraded", "message": "intraday_coverage_incomplete"})
    return result


def annotate_intraday_runtime_coverage(path: Path, trade_date10: str, *, now: datetime | None = None) -> dict[str, Any]:
    """把非阻断式覆盖诊断写回运行时，供页面和 Actions 日志共同展示。"""
    result = validate_intraday_runtime_coverage(path, trade_date10, now=now)
    if path.exists() and str(_read_json(path).get("date") or "") == str(trade_date10 or ""):
        payload = _read_json(path)
        health = dict(payload.get("health") or {}) if isinstance(payload.get("health"), dict) else {}
        health["coverage"] = {key: value for key, value in result.items() if key != "path"}
        payload["health"] = health
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def validate_external_data_freshness(*, root: Path, date10: str) -> dict[str, Any]:
    """收盘发布只接受同日外部题材链，防止主报告更新而证据仍停在昨日。"""
    date8 = str(date10 or "").replace("-", "")
    required = {
        "xuangubao_abnormal": root / "cache_online" / f"xuangubao_abnormal-{date8}.json",
        "xuangubao_surge": root / "cache_online" / f"xuangubao_surge_plates-{date8}.json",
        "eastmoney_themes": root / "cache_online" / f"eastmoney_tomorrow_themes-{date8}.json",
        "eastmoney_stocks": root / "cache_online" / f"eastmoney_theme_stocks-{date8}.json",
        "watchlist": root / "cache_online" / f"watchlist_cache-{date8}.json",
        "tomorrow_picks": root / "web" / "public" / "tomorrow_picks.json",
        "eastmoney_public": root / "web" / "public" / "eastmoney_tomorrow.json",
    }
    result: dict[str, Any] = {"ok": True, "date": date10, "sources": {}, "message": "external_data_fresh"}
    for name, path in required.items():
        payload = _read_json(path)
        payload_date = str(payload.get("data_date") or payload.get("date") or "").strip()
        updated_at = str(payload.get("updated_at_bj") or payload.get("updatedAt") or payload.get("generatedAt") or payload.get("generated_at_bj") or "").strip()
        fresh = bool(payload) and payload_date == date10
        result["sources"][name] = {"path": str(path), "date": payload_date, "updated_at": updated_at, "fresh": fresh}
        if not fresh:
            result["ok"] = False
    if not result["ok"]:
        stale = [name for name, item in result["sources"].items() if not item["fresh"]]
        result["message"] = "external_data_stale_or_missing:" + ",".join(stale)
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
    payload = _read_json(path)
    backtest = payload.get("stockResearchBacktest") if isinstance(payload.get("stockResearchBacktest"), dict) else {}
    current_pool_records = backtest.get("currentPoolRecords") if isinstance(backtest.get("currentPoolRecords"), list) else []
    display_records = backtest.get("displayRecords") if isinstance(backtest.get("displayRecords"), list) else []
    historical_snapshots = backtest.get("historicalSnapshots") if isinstance(backtest.get("historicalSnapshots"), list) else []
    records = backtest.get("records") if isinstance(backtest.get("records"), list) else []
    lifecycle = backtest.get("lifecycle") if isinstance(backtest.get("lifecycle"), dict) else {}
    renderability = {
        "has_current_plan_section": bool(current_pool_records),
        "has_history_section": bool(display_records) or bool(historical_snapshots) or bool(records),
        "has_renderable_backtest": (
            bool(current_pool_records)
            or bool(display_records)
            or bool(historical_snapshots)
            or bool(records)
            or bool(str(lifecycle.get("stage") or "").strip())
            or bool(str(snapshot.get("reference_date") or "").strip())
        ),
    }
    result: dict[str, Any] = {
        "ok": True,
        "required": False,
        "message": "no_candidate_rows",
        **snapshot,
        **renderability,
    }
    if not renderability["has_renderable_backtest"]:
        result["ok"] = False
        result["required"] = True
        result["message"] = "renderable_stock_research_backtest_missing"
        return result
    candidate_count = int(snapshot.get("candidate_count") or 0)
    if candidate_count <= 0:
        return result

    result["required"] = True
    if snapshot["found"]:
        result["message"] = "snapshot_ready" if snapshot.get("auction_window") else "snapshot_degraded_outside_auction_window"
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
