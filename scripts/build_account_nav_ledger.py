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


def build_account_nav_ledger(*, base_nav: float = 1.0) -> list[dict[str, Any]]:
    from scripts.build_stock_research_backtest import build_stock_research_backtest_payload

    payload = build_stock_research_backtest_payload()
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
                "strategy": "equal_weight_next_day_close",
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

    nav = base_nav if base_nav > 0 else 1.0
    out: list[dict[str, Any]] = []
    for trade_date in sorted(grouped.keys()):
        item = grouped[trade_date]
        returns = item.get("returns") if isinstance(item.get("returns"), list) else []
        if not returns:
            continue
        avg_return_pct = round(sum(float(x) for x in returns) / len(returns), 4)
        nav = round(nav * (1 + avg_return_pct / 100.0), 6)
        out.append(
            {
                "trade_date": trade_date,
                "recommendation_date": item.get("recommendation_date") or "",
                "strategy": "equal_weight_next_day_close",
                "stock_count": len(returns),
                "avg_return_pct": avg_return_pct,
                "nav": nav,
                "codes": item.get("codes") or [],
                "names": item.get("names") or [],
            }
        )
    return out


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
