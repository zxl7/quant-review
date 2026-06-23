#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_account_nav_ledger as ledger


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _payload(records: list[dict]) -> dict:
    return {"records": records}


def _covered_row(*, code: str, name: str, recommendation_date: str, trade_date: str, return_pct: float) -> dict:
    return {
        "code": code,
        "name": name,
        "date10": recommendation_date,
        "performance": {
            "open_check": {"can_enter": True},
            "next_day": {
                "status": "covered",
                "entry_date": trade_date,
                "return_pct": return_pct,
            },
        },
    }


class AccountNavLedgerTest(unittest.TestCase):
    def test_build_account_nav_ledger_disables_history_fetch_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "data" / "account_nav_history.jsonl"
            cache_path = root / "cache" / "account_nav_history.jsonl"

            def fake_payload_builder() -> dict:
                self.assertEqual(os.environ.get("QR_DISABLE_STOCK_RESEARCH_HISTORY_FETCH"), "1")
                return _payload([])

            with patch.object(ledger, "LEDGER_PATH", data_path), patch.object(
                ledger, "CACHE_LEDGER_PATH", cache_path
            ), patch("scripts.build_stock_research_backtest.build_stock_research_backtest_payload", side_effect=fake_payload_builder):
                rows = ledger.build_account_nav_ledger()

        self.assertEqual(rows, [])
        self.assertIsNone(os.environ.get("QR_DISABLE_STOCK_RESEARCH_HISTORY_FETCH"))

    def test_keeps_existing_history_when_payload_window_is_short(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "data" / "account_nav_history.jsonl"
            cache_path = root / "cache" / "account_nav_history.jsonl"
            _write_jsonl(
                data_path,
                [
                    {
                        "trade_date": "2026-06-05",
                        "recommendation_date": "2026-06-04",
                        "strategy": ledger.DEFAULT_STRATEGY,
                        "stock_count": 1,
                        "avg_return_pct": 10.0,
                        "nav": 1.1,
                        "codes": ["000001"],
                        "names": ["老样本"],
                    }
                ],
            )
            payload = _payload(
                [
                    _covered_row(
                        code="000002",
                        name="新样本",
                        recommendation_date="2026-06-22",
                        trade_date="2026-06-23",
                        return_pct=5.0,
                    )
                ]
            )
            with patch.object(ledger, "LEDGER_PATH", data_path), patch.object(
                ledger, "CACHE_LEDGER_PATH", cache_path
            ), patch("scripts.build_stock_research_backtest.build_stock_research_backtest_payload", return_value=payload):
                rows = ledger.build_account_nav_ledger()

        self.assertEqual([row["trade_date"] for row in rows], ["2026-06-05", "2026-06-23"])
        self.assertEqual(rows[0]["nav"], 1.1)
        self.assertEqual(rows[1]["nav"], 1.155)

    def test_same_trade_date_is_updated_without_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "data" / "account_nav_history.jsonl"
            cache_path = root / "cache" / "account_nav_history.jsonl"
            _write_jsonl(
                data_path,
                [
                    {
                        "trade_date": "2026-06-05",
                        "recommendation_date": "2026-06-04",
                        "strategy": ledger.DEFAULT_STRATEGY,
                        "stock_count": 1,
                        "avg_return_pct": 10.0,
                        "nav": 1.1,
                        "codes": ["000001"],
                        "names": ["旧名字"],
                    }
                ],
            )
            payload = _payload(
                [
                    _covered_row(
                        code="000002",
                        name="新名字A",
                        recommendation_date="2026-06-04",
                        trade_date="2026-06-05",
                        return_pct=2.0,
                    ),
                    _covered_row(
                        code="000003",
                        name="新名字B",
                        recommendation_date="2026-06-04",
                        trade_date="2026-06-05",
                        return_pct=4.0,
                    ),
                ]
            )
            with patch.object(ledger, "LEDGER_PATH", data_path), patch.object(
                ledger, "CACHE_LEDGER_PATH", cache_path
            ), patch("scripts.build_stock_research_backtest.build_stock_research_backtest_payload", return_value=payload):
                rows = ledger.build_account_nav_ledger()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stock_count"], 2)
        self.assertEqual(rows[0]["avg_return_pct"], 3.0)
        self.assertEqual(rows[0]["codes"], ["000002", "000003"])
        self.assertEqual(rows[0]["nav"], 1.03)

    def test_empty_payload_does_not_clear_existing_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "data" / "account_nav_history.jsonl"
            cache_path = root / "cache" / "account_nav_history.jsonl"
            original = {
                "trade_date": "2026-06-05",
                "recommendation_date": "2026-06-04",
                "strategy": ledger.DEFAULT_STRATEGY,
                "stock_count": 1,
                "avg_return_pct": 10.0,
                "nav": 1.1,
                "codes": ["000001"],
                "names": ["老样本"],
            }
            _write_jsonl(data_path, [original])
            payload = _payload(
                [
                    {
                        "code": "000002",
                        "name": "未覆盖",
                        "date10": "2026-06-22",
                        "performance": {
                            "open_check": {"can_enter": True},
                            "next_day": {"status": "pending"},
                        },
                    }
                ]
            )
            with patch.object(ledger, "LEDGER_PATH", data_path), patch.object(
                ledger, "CACHE_LEDGER_PATH", cache_path
            ), patch("scripts.build_stock_research_backtest.build_stock_research_backtest_payload", return_value=payload):
                rows = ledger.build_account_nav_ledger()

        self.assertEqual(rows, [original])

    def test_sync_writes_same_long_ledger_to_data_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "data" / "account_nav_history.jsonl"
            cache_path = root / "cache" / "account_nav_history.jsonl"
            payload = _payload(
                [
                    _covered_row(
                        code="000002",
                        name="新样本",
                        recommendation_date="2026-06-22",
                        trade_date="2026-06-23",
                        return_pct=5.0,
                    )
                ]
            )
            with patch.object(ledger, "LEDGER_PATH", data_path), patch.object(
                ledger, "CACHE_LEDGER_PATH", cache_path
            ), patch("scripts.build_stock_research_backtest.build_stock_research_backtest_payload", return_value=payload):
                rows = ledger.sync_account_nav_ledger()

            self.assertEqual(_read_jsonl(data_path), rows)
            self.assertEqual(_read_jsonl(cache_path), rows)


if __name__ == "__main__":
    unittest.main()
