#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LEDGER_PATH = ROOT / "data" / "account_nav_history.jsonl"
CACHE_LEDGER_PATH = ROOT / "cache" / "account_nav_history.jsonl"
DEFAULT_STRATEGY = "equal_weight_next_day_close"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    if payload:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")


def _load_existing_ledger() -> list[dict[str, Any]]:
    rows = _read_jsonl(LEDGER_PATH)
    if rows:
        return rows
    return _read_jsonl(CACHE_LEDGER_PATH)


def _implied_base_nav(rows: list[dict[str, Any]], *, default_base: float) -> float:
    if not rows:
        return default_base if default_base > 0 else 1.0
    first = rows[0]
    try:
        first_nav = float(first.get("nav") or 0)
        first_pct = float(first.get("avg_return_pct") or 0)
    except Exception:
        return default_base if default_base > 0 else 1.0
    divisor = 1.0 + first_pct / 100.0
    if first_nav > 0 and divisor > 0:
        return round(first_nav / divisor, 6)
    return default_base if default_base > 0 else 1.0


def _ledger_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("trade_date") or "").strip(),
        str(row.get("strategy") or DEFAULT_STRATEGY).strip(),
    )


def _normalize_existing_row(row: dict[str, Any]) -> dict[str, Any] | None:
    trade_date = str(row.get("trade_date") or "").strip()
    if not trade_date:
        return None
    strategy = str(row.get("strategy") or DEFAULT_STRATEGY).strip() or DEFAULT_STRATEGY
    try:
        avg_return_pct = round(float(row.get("avg_return_pct") or 0.0), 4)
    except Exception:
        avg_return_pct = 0.0
    return {
        "trade_date": trade_date,
        "recommendation_date": str(row.get("recommendation_date") or "").strip(),
        "strategy": strategy,
        "stock_count": int(float(row.get("stock_count") or 0)),
        "avg_return_pct": avg_return_pct,
        "nav": 0.0,
        "codes": [str(x).strip() for x in (row.get("codes") or []) if str(x).strip()],
        "names": [str(x).strip() for x in (row.get("names") or []) if str(x).strip()],
    }


def _build_incremental_rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("records") if isinstance(payload, dict) else []
    grouped: dict[str, dict[str, Any]] = {}

    for row in records if isinstance(records, list) else []:
        if not isinstance(row, dict):
            continue
        performance = row.get("performance") if isinstance(row.get("performance"), dict) else {}
        open_check = performance.get("open_check") if isinstance(performance.get("open_check"), dict) else {}
        next_day = performance.get("next_day") if isinstance(performance.get("next_day"), dict) else {}
        if not bool(open_check.get("can_enter")):
            continue
        if str(next_day.get("status") or "") != "covered":
            continue
        trade_date = str(next_day.get("entry_date") or next_day.get("exit_date") or "").strip()
        if not trade_date:
            continue
        item = grouped.setdefault(
            trade_date,
            {
                "trade_date": trade_date,
                "recommendation_date": str(row.get("date10") or "").strip(),
                "strategy": DEFAULT_STRATEGY,
                "returns": [],
                "codes": [],
                "names": [],
            },
        )
        try:
            ret = float(next_day.get("return_pct"))
        except Exception:
            continue
        item["returns"].append(ret)
        code = str(row.get("code") or "").strip()
        name = str(row.get("name") or "").strip()
        if code:
            item["codes"].append(code)
        if name:
            item["names"].append(name)

    out: list[dict[str, Any]] = []
    for trade_date in sorted(grouped.keys()):
        item = grouped[trade_date]
        returns = item.get("returns") if isinstance(item.get("returns"), list) else []
        if not returns:
            continue
        avg_return_pct = round(sum(float(x) for x in returns) / len(returns), 4)
        out.append(
            {
                "trade_date": trade_date,
                "recommendation_date": item.get("recommendation_date") or "",
                "strategy": DEFAULT_STRATEGY,
                "stock_count": len(returns),
                "avg_return_pct": avg_return_pct,
                "nav": 0.0,
                "codes": item.get("codes") or [],
                "names": item.get("names") or [],
            }
        )
    return out


def _merge_ledger_rows(
    existing_rows: list[dict[str, Any]],
    incremental_rows: list[dict[str, Any]],
    *,
    base_nav: float,
) -> list[dict[str, Any]]:
    normalized_existing = [row for row in (_normalize_existing_row(row) for row in existing_rows) if row]
    normalized_incremental = [row for row in (_normalize_existing_row(row) for row in incremental_rows) if row]
    implied_base = _implied_base_nav(sorted(normalized_existing, key=_ledger_sort_key), default_base=base_nav)

    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in normalized_existing:
        by_key[_ledger_sort_key(row)] = row
    for row in normalized_incremental:
        by_key[_ledger_sort_key(row)] = row

    nav = implied_base
    out: list[dict[str, Any]] = []
    for row in sorted(by_key.values(), key=_ledger_sort_key):
        avg_return_pct = float(row.get("avg_return_pct") or 0.0)
        nav = round(nav * (1 + avg_return_pct / 100.0), 6)
        row = dict(row)
        row["nav"] = nav
        out.append(row)
    return out


def build_account_nav_ledger(*, base_nav: float = 1.0) -> list[dict[str, Any]]:
    from scripts.build_stock_research_backtest import build_stock_research_backtest_payload

    payload = build_stock_research_backtest_payload()
    existing_rows = _load_existing_ledger()
    incremental_rows = _build_incremental_rows_from_payload(payload if isinstance(payload, dict) else {})
    return _merge_ledger_rows(existing_rows, incremental_rows, base_nav=base_nav)


def sync_account_nav_ledger(*, base_nav: float = 1.0) -> list[dict[str, Any]]:
    rows = build_account_nav_ledger(base_nav=base_nav)
    _write_jsonl(LEDGER_PATH, rows)
    _write_jsonl(CACHE_LEDGER_PATH, rows)
    return rows


def main() -> None:
    rows = sync_account_nav_ledger()
    print(str(LEDGER_PATH))
    print(str(CACHE_LEDGER_PATH))
    print(f"rows={len(rows)}")


if __name__ == "__main__":
    main()
