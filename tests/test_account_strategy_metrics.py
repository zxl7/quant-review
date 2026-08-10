#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from scripts import build_account_strategy_metrics as metrics


class AccountStrategyMetricsTest(unittest.TestCase):
    def test_explicit_backtest_payload_does_not_rebuild(self) -> None:
        backtest = {
            "meta": {"generated_at_bj": "2026-08-10 15:10:00"},
            "records": [
                {
                    "date10": "2026-08-07",
                    "trade_date10": "2026-08-10",
                    "performance": {
                        "open_check": {"can_enter": True, "status": "expected"},
                        "next_day": {"status": "covered", "return_pct": 2.0},
                    },
                }
            ],
        }
        with patch("scripts.build_stock_research_backtest.build_stock_research_backtest_payload") as builder:
            payload = metrics.build_account_strategy_metrics(backtest_payload=backtest)

        builder.assert_not_called()
        self.assertEqual(payload["latest_trade_date"], "2026-08-10")
        self.assertEqual(payload["records"][-1]["metrics"]["next_day"]["tradable"]["covered"], 1)

    def test_build_account_strategy_metrics_disables_history_fetch_by_default(self) -> None:
        def fake_payload_builder() -> dict:
            self.assertEqual(os.environ.get("QR_DISABLE_STOCK_RESEARCH_HISTORY_FETCH"), "1")
            return {
                "meta": {"generated_at_bj": "2026-06-23 15:01:00"},
                "records": [],
            }

        with patch("scripts.build_stock_research_backtest.build_stock_research_backtest_payload", side_effect=fake_payload_builder):
            payload = metrics.build_account_strategy_metrics()

        self.assertEqual(payload["records"], [])
        self.assertEqual(payload["generated_at_bj"], "2026-06-23 15:01:00")
        self.assertIsNone(os.environ.get("QR_DISABLE_STOCK_RESEARCH_HISTORY_FETCH"))

    def test_build_account_strategy_metrics_respects_explicit_history_fetch_enable(self) -> None:
        def fake_payload_builder() -> dict:
            self.assertEqual(os.environ.get("QR_DISABLE_STOCK_RESEARCH_HISTORY_FETCH"), "0")
            return {
                "meta": {"generated_at_bj": "2026-06-24 15:01:00"},
                "records": [],
            }

        with patch.dict(metrics.os.environ, {"QR_DISABLE_STOCK_RESEARCH_HISTORY_FETCH": "0"}, clear=False):
            with patch("scripts.build_stock_research_backtest.build_stock_research_backtest_payload", side_effect=fake_payload_builder):
                payload = metrics.build_account_strategy_metrics()

        self.assertEqual(payload["records"], [])
        self.assertEqual(payload["generated_at_bj"], "2026-06-24 15:01:00")
        self.assertIsNone(os.environ.get("QR_DISABLE_STOCK_RESEARCH_HISTORY_FETCH"))


if __name__ == "__main__":
    unittest.main()
