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

METRICS_PATH = ROOT / "data" / "account_strategy_metrics.json"
CACHE_METRICS_PATH = ROOT / "cache" / "account_strategy_metrics.json"

STRATEGY_DEFS = (
    ("next_day", "隔日收益"),
    ("hold_2d", "2日收益"),
    ("hold_3d", "3日收益"),
)


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator * 100.0 / denominator, 1)


def _avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _summarize_scope(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    covered_rows = [r for r in rows if str(((r.get("performance") or {}).get(key) or {}).get("status") or "") == "covered"]
    pending_rows = [r for r in rows if str(((r.get("performance") or {}).get(key) or {}).get("status") or "") == "pending"]
    skipped_rows = [r for r in rows if str(((r.get("performance") or {}).get(key) or {}).get("status") or "") == "skipped"]
    missing_rows = [r for r in rows if str(((r.get("performance") or {}).get(key) or {}).get("status") or "") == "missing"]
    returns = [float(((r.get("performance") or {}).get(key) or {}).get("return_pct") or 0.0) for r in covered_rows]
    wins = [val for val in returns if val > 0]
    flats = [val for val in returns if val == 0]
    losses = [val for val in returns if val < 0]

    by_open_status: dict[str, Any] = {}
    for open_status in ("super", "expected", "reject"):
        status_rows = [
            r for r in covered_rows
            if str((((r.get("performance") or {}).get("open_check") or {}).get("status") or "")) == open_status
        ]
        status_returns = [float(((r.get("performance") or {}).get(key) or {}).get("return_pct") or 0.0) for r in status_rows]
        by_open_status[open_status] = {
            "covered": len(status_rows),
            "win_rate": _pct(sum(1 for value in status_returns if value > 0), len(status_rows)),
            "avg_return": _avg(status_returns),
        }

    return {
        "covered": len(covered_rows),
        "eligible": len(rows),
        "coverage": _pct(len(covered_rows), len(rows)),
        "pending": len(pending_rows),
        "missing": len(missing_rows),
        "skipped": len(skipped_rows),
        "win_count": len(wins),
        "flat_count": len(flats),
        "loss_count": len(losses),
        "win_rate": _pct(len(wins), len(covered_rows)),
        "avg_return": _avg(returns),
        "avg_win_return": _avg(wins),
        "avg_loss_return": _avg(losses),
        "by_open_status": by_open_status,
    }


def build_account_strategy_metrics() -> dict[str, Any]:
    from scripts.build_stock_research_backtest import build_stock_research_backtest_payload

    payload = build_stock_research_backtest_payload()
    records = payload.get("records") if isinstance(payload, dict) else []
    valid_records = [row for row in records if isinstance(row, dict)]
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in valid_records:
        recommendation_date = str(row.get("date10") or "").strip()
        if not recommendation_date:
            continue
        by_date.setdefault(recommendation_date, []).append(row)

    daily_records: list[dict[str, Any]] = []
    for recommendation_date in sorted(by_date.keys()):
        rows = by_date[recommendation_date]
        tradable_rows = [
            row for row in rows
            if bool((((row.get("performance") or {}).get("open_check") or {}).get("can_enter")))
        ]
        metrics: dict[str, Any] = {}
        for key, label in STRATEGY_DEFS:
            metrics[key] = {
                "key": key,
                "label": label,
                "tradable": _summarize_scope(tradable_rows, key),
                "all": _summarize_scope(rows, key),
            }
        daily_records.append(
            {
                "recommendation_date": recommendation_date,
                "trade_date": str(rows[0].get("trade_date10") or "").strip() if rows else "",
                "sample_count": len(rows),
                "tradable_count": len(tradable_rows),
                "metrics": metrics,
            }
        )

    latest = daily_records[-1] if daily_records else {}
    return {
        "schema": "account_strategy_metrics_v1",
        "generated_at_bj": str(((payload.get("meta") or {}).get("generated_at_bj")) or ""),
        "records": daily_records,
        "latest_recommendation_date": str(latest.get("recommendation_date") or ""),
        "latest_trade_date": str(latest.get("trade_date") or ""),
    }


def sync_account_strategy_metrics() -> dict[str, Any]:
    payload = build_account_strategy_metrics()
    _write_json(METRICS_PATH, payload)
    _write_json(CACHE_METRICS_PATH, payload)
    return payload


def main() -> None:
    payload = sync_account_strategy_metrics()
    print(str(METRICS_PATH))
    print(str(CACHE_METRICS_PATH))
    print(f"rows={len(payload.get('records') or [])}")


if __name__ == "__main__":
    main()
