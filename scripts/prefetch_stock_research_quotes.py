#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daily_review.config import load_config_from_env
from daily_review.data.biying import fetch_stocks_realtime_map, normalize_stock_code
from daily_review.http import HttpClient
from scripts.build_stock_research_backtest import _load_stock_research_rows, save_prefetched_realtime_quotes


TZ_BJ = timezone(timedelta(hours=8))


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="当前运行日期 YYYY-MM-DD；若提供，则优先抓取早于该日期的最新研究池")
    args = ap.parse_args()

    now_bj = _now_bj()
    if not _is_entry_window(now_bj):
        print("skip: outside 09:25-09:30 window")
        return 0

    rows, _ = _load_stock_research_rows()
    if not rows:
        print("skip: no stock research rows in cache")
        return 0

    reference_date = _pick_reference_date(rows, before_date10=str(args.date or "").strip())
    if not reference_date:
        print("skip: no valid reference date")
        return 0

    codes = sorted(
        {
            normalize_stock_code(str(row.get("code") or ""))
            for row in rows
            if str(row.get("date10") or "") == reference_date and normalize_stock_code(str(row.get("code") or ""))
        }
    )
    if not codes:
        print(f"skip: no codes for {reference_date}")
        return 0

    cfg = load_config_from_env()
    client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=12, retries=0)
    quotes_map, as_of = fetch_stocks_realtime_map(client, codes)

    if not quotes_map:
        print(f"skip: no realtime quotes fetched for {reference_date}")
        return 0

    path = save_prefetched_realtime_quotes(
        date10=reference_date,
        items=quotes_map,
        as_of=as_of or now_bj.strftime("%Y-%m-%d %H:%M:%S"),
        source="workflow_prefetch",
    )
    print(f"ok: {path} codes={len(quotes_map)} reference_date={reference_date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
