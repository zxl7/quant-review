#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.build_stock_research_backtest as backtest


class StockResearchBacktestRowsTest(unittest.TestCase):
    def test_rows_are_built_only_from_market_data_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            (cache_dir / "market_data-20260603.json").write_text(
                json.dumps(
                    {
                        "date": "2026-06-03",
                        "meta": {"mode": "eod"},
                        "ztAnalysis": {
                            "relay": [{"code": "000003", "name": "今天接力", "factorScore": 90}],
                            "watch": [{"code": "000004", "name": "今天观察", "factorScore": 60}],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (cache_dir / "market_data-20260604-intraday.json").write_text(
                json.dumps(
                    {
                        "date": "2026-06-04",
                        "meta": {"mode": "intraday"},
                        "ztAnalysis": {
                            "relay": [{"code": "000005", "name": "盘中样本", "factorScore": 99}],
                            "watch": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(backtest, "CACHE_DIR", cache_dir):
                rows, sources = backtest._load_stock_research_rows()

        self.assertEqual({row["date10"] for row in rows}, {"2026-06-03"})
        self.assertEqual([row["name"] for row in rows], ["今天接力", "今天观察"])
        self.assertEqual(sources, ["market_data-20260603.json"])

    def test_empty_payload_is_returned_when_no_rows_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            (cache_dir / "market_data-20260604-intraday.json").write_text(
                json.dumps(
                    {
                        "date": "2026-06-04",
                        "meta": {"mode": "intraday"},
                        "ztAnalysis": {"relay": [], "watch": []},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(backtest, "CACHE_DIR", cache_dir):
                payload = backtest.build_stock_research_backtest_payload()

        self.assertTrue(payload["meta"]["is_empty"])
        self.assertEqual(payload["summary"]["total_samples"], 0)
        self.assertEqual(payload["records"], [])
        self.assertEqual(payload["meta"]["generated_from"], [])

    def test_prefetched_quotes_still_feed_realtime_buy_after_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            (cache_dir / "market_data-20260603.json").write_text(
                json.dumps(
                    {
                        "date": "2026-06-03",
                        "meta": {"mode": "eod"},
                        "ztAnalysis": {
                            "relay": [
                                {
                                    "code": "000003",
                                    "name": "今天接力",
                                    "factorScore": 90,
                                    "reason": "预期 +1% ~ +3%",
                                }
                            ],
                            "watch": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(backtest, "CACHE_DIR", cache_dir):
                backtest.save_prefetched_realtime_quotes(
                    date10="2026-06-03",
                    items={
                        "000003": {
                            "dm": "000003",
                            "t": "2026-06-04 09:25:01",
                            "yc": 10.0,
                            "o": 10.2,
                            "p": 10.2,
                            "cje": 200000000,
                        }
                    },
                    as_of="2026-06-04 09:25:01",
                    source="unit_test",
                )
                with patch.object(backtest, "_should_request_realtime_quotes", return_value=False), patch.object(
                    backtest, "_load_preserved_realtime_buy", return_value=None
                ), patch.object(
                    backtest,
                    "_get_price_histories",
                    return_value=({}, {"source": "mock", "fetched": 0, "cached": 0, "missing": []}),
                ):
                    payload = backtest.build_stock_research_backtest_payload()

        self.assertEqual(payload["realtimeBuy"]["quoted_count"], 1)
        self.assertEqual(payload["realtimeBuy"]["buy_count"], 1)
        self.assertEqual(payload["realtimeBuy"]["direct_expected_count"], 1)
        self.assertEqual(payload["realtimeBuy"]["diagnostics"]["source"], "cache.raw.quotes")

    def test_preserved_realtime_buy_reads_intraday_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            (cache_dir / "market_data-20260604-intraday.json").write_text(
                json.dumps(
                    {
                        "stockResearchBacktest": {
                            "realtimeBuy": {
                                "reference_date": "2026-06-03",
                                "quote_time": "2026-06-04 09:25:01",
                                "diagnostics": {"source": "remote"},
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(backtest, "CACHE_DIR", cache_dir):
                preserved = backtest._load_preserved_realtime_buy("2026-06-03")

        self.assertIsNotNone(preserved)
        self.assertEqual(preserved["reference_date"], "2026-06-03")
        self.assertEqual(preserved["quote_time"], "2026-06-04 09:25:01")

    def test_latest_snapshot_prefers_intraday_variant_for_same_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            (cache_dir / "market_data-20260603.json").write_text(
                json.dumps(
                    {"raw": {"quotes": {"items": {"000001": {"dm": "000001", "t": "2026-06-04 09:25:01"}}}}},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (cache_dir / "market_data-20260603-intraday.json").write_text(
                json.dumps(
                    {"raw": {"quotes": {"items": {"000002": {"dm": "000002", "t": "2026-06-04 09:25:02"}}}}},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(backtest, "CACHE_DIR", cache_dir):
                snapshot = backtest._load_latest_stock_research_snapshot("2026-06-03")

        self.assertEqual(snapshot["raw"]["quotes"]["items"]["000002"]["dm"], "000002")


if __name__ == "__main__":
    unittest.main()
