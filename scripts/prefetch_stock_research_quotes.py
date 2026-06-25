#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import time
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daily_review.config import load_config_from_env
from daily_review.application.workflow_schedule import resolve_auction_snapshot_prefetch_plan
from daily_review.data.biying import fetch_stocks_realtime_map, normalize_stock_code
from daily_review.http import HttpClient
from scripts.build_stock_research_backtest import _load_stock_research_rows, save_prefetched_realtime_quotes


TZ_BJ = timezone(timedelta(hours=8))
PREFETCH_HTTP_RETRIES = 2
PREFETCH_FETCH_ATTEMPTS = 2
PREFETCH_RETRY_SLEEP_SECONDS = 1.2


def _now_bj() -> datetime:
    return datetime.now(TZ_BJ)


def _is_entry_window(now: datetime) -> bool:
    total = now.hour * 3600 + now.minute * 60 + now.second
    return 9 * 3600 + 25 * 60 <= total < 9 * 3600 + 30 * 60


def _pick_reference_date(rows: list[dict], *, before_date10: str = "") -> str:
    dates = sorted({str(row.get("date10") or "") for row in rows if str(row.get("date10") or "")})
    if before_date10:
        older = [d for d in dates if d < before_date10]
        if older:
            return older[-1]
    return dates[-1] if dates else ""


def _collect_reference_codes(rows: list[dict], *, reference_date: str) -> list[str]:
    if len(reference_date) != 10:
        return []
    return sorted(
        {
            normalize_stock_code(str(row.get("code") or ""))
            for row in rows
            if str(row.get("date10") or "") == reference_date and normalize_stock_code(str(row.get("code") or ""))
        }
    )


def _fetch_and_save_snapshot(*, reference_date: str, codes: list[str], source: str) -> tuple[Path | None, dict[str, object]]:
    diag: dict[str, object] = {
        "reference_date": str(reference_date or "").strip(),
        "codes_count": len(codes),
        "attempts": 0,
        "success": False,
        "as_of": "",
        "last_error": "",
        "source": source,
    }
    if len(reference_date) != 10 or not codes:
        diag["last_error"] = "invalid_reference_or_codes"
        return None, diag
    cfg = load_config_from_env()
    client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=12, retries=PREFETCH_HTTP_RETRIES)
    quotes_map = {}
    as_of = ""
    for attempt in range(1, PREFETCH_FETCH_ATTEMPTS + 1):
        diag["attempts"] = attempt
        try:
            quotes_map, as_of = fetch_stocks_realtime_map(client, codes)
            if quotes_map:
                diag["success"] = True
                diag["as_of"] = as_of or ""
                break
            diag["last_error"] = "empty_quotes_map"
        except Exception as exc:
            diag["last_error"] = f"{type(exc).__name__}: {exc}"
        if attempt < PREFETCH_FETCH_ATTEMPTS:
            time.sleep(PREFETCH_RETRY_SLEEP_SECONDS)
    if not quotes_map:
        return None, diag
    path = save_prefetched_realtime_quotes(
        date10=reference_date,
        items=quotes_map,
        as_of=as_of or _now_bj().strftime("%Y-%m-%d %H:%M:%S"),
        source=source,
    )
    diag["as_of"] = as_of or ""
    return path, diag


def build_prefetch_execution_plan(*, trade_date10: str, cache_dir: Path) -> dict[str, object]:
    auction_plan = resolve_auction_snapshot_prefetch_plan(cache_dir, trade_date10)
    rows, _ = _load_stock_research_rows()
    reference_date = _pick_reference_date(rows, before_date10=str(trade_date10 or "").strip())
    codes = _collect_reference_codes(rows, reference_date=reference_date)
    return {
        **auction_plan,
        "has_rows": bool(rows),
        "reference_date": reference_date,
        "codes": codes,
        "codes_count": len(codes),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="当前运行日期 YYYY-MM-DD；若提供，则优先抓取早于该日期的最新研究池")
    ap.add_argument("--must-succeed", action="store_true", help="仅用于 09:25-09:30 守窗场景；窗口内没抓到则返回非 0")
    args = ap.parse_args(argv)

    run_date = str(args.date or "").strip()
    if len(run_date) != 10:
        run_date = _now_bj().strftime("%Y-%m-%d")

    plan = build_prefetch_execution_plan(trade_date10=run_date, cache_dir=ROOT / "cache")
    if not plan["should_prefetch"]:
        print(
            f"{plan['status']}: trade_date={run_date} "
            f"ready_source={plan['ready_source'] or '-'} "
            f"reference_date={plan['reference_date'] or '-'} "
            f"codes={plan['codes_count']}"
        )
        return 0

    if not plan["has_rows"]:
        print("skip: no stock research rows in cache")
        return 2 if args.must_succeed else 0

    reference_date = str(plan["reference_date"] or "")
    if not reference_date:
        print("skip: no valid reference date")
        return 2 if args.must_succeed else 0

    codes = list(plan["codes"]) if isinstance(plan["codes"], list) else []
    if not codes:
        print(f"skip: no codes for {reference_date}")
        return 2 if args.must_succeed else 0

    now_bj = _now_bj()
    if _is_entry_window(now_bj):
        path, diag = _fetch_and_save_snapshot(reference_date=reference_date, codes=codes, source="workflow_prefetch")
        if path:
            print(
                f"ok: {path} codes={len(codes)} reference_date={reference_date} "
                f"attempts={diag['attempts']} as_of={diag['as_of'] or '-'} last_error={diag['last_error'] or '-'}"
            )
            return 0
        print(
            f"skip: no realtime quotes fetched for {reference_date} "
            f"attempts={diag['attempts']} last_error={diag['last_error'] or '-'}"
        )
        return 2 if args.must_succeed else 0

    if not args.must_succeed:
        print("skip: outside 09:25-09:30 window")
        return 0

    path, diag = _fetch_and_save_snapshot(reference_date=reference_date, codes=codes, source="forced_query")
    if path:
        print(
            "ok: "
            f"{path} codes={len(codes)} reference_date={reference_date} "
            f"mode=forced_query reason=delayed_schedule_recovery attempts={diag['attempts']} "
            f"as_of={diag['as_of'] or '-'} last_error={diag['last_error'] or '-'}"
        )
        return 0

    print(
        f"skip: outside 09:25-09:30 window and forced fallback failed for {reference_date} "
        f"attempts={diag['attempts']} last_error={diag['last_error'] or '-'}"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
