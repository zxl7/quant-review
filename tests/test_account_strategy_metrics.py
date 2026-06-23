#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from scripts import build_account_strategy_metrics as metrics


class AccountStrategyMetricsTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
