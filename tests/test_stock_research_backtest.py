#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daily_review.publish.web_bundle as web_bundle
import scripts.build_stock_research_backtest as backtest


class StockResearchBacktestRowsTest(unittest.TestCase):
    def test_rows_are_built_only_from_pushed_source_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            (cache_dir / "stock_research_backtest_source.json").write_text(
                json.dumps(
                    {
                        "schema": "stock_research_backtest_source_v1",
                        "dates": {
                            "2026-06-04": {
                                "date": "2026-06-04",
                                "recommendation_date": "2026-06-03",
                                "source": "ztAnalysis.relay/watch.close_push",
                                "rows": [
                                    {"date": "20260603", "date10": "2026-06-03", "trade_date10": "2026-06-04", "code": "000003", "name": "今天接力", "bucket": "relay", "score": 90},
                                    {"date": "20260603", "date10": "2026-06-03", "trade_date10": "2026-06-04", "code": "000004", "name": "今天观察", "bucket": "watch", "score": 60},
                                ],
                            }
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
        self.assertEqual(sources, ["ztAnalysis.relay/watch.close_push"])

    def test_empty_payload_is_returned_when_no_rows_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()

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
            backtest_payload = {
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
            }

            with patch.object(backtest, "CACHE_DIR", cache_dir):
                backtest.sync_stock_research_backtest_source(market_data=backtest_payload)
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
                    return_value=(
                        {
                            "000003": [
                                {"date": "2026-06-03", "open": 10.0, "close": 10.0, "prev_close": 9.9},
                                {"date": "2026-06-04", "open": 10.2, "close": 10.5, "prev_close": 10.0},
                            ]
                        },
                        {"source": "mock", "fetched": 1, "cached": 0, "missing": []},
                    ),
                ):
                    payload = backtest.build_stock_research_backtest_payload()

        self.assertEqual(payload["realtimeBuy"]["quoted_count"], 1)
        self.assertEqual(payload["realtimeBuy"]["buy_count"], 1)
        self.assertEqual(payload["realtimeBuy"]["direct_expected_count"], 1)
        self.assertEqual(payload["realtimeBuy"]["diagnostics"]["source"], "cache.raw.quotes")
        self.assertEqual(payload["realtimeBuy"]["reference_date"], "2026-06-03")
        self.assertEqual(payload["realtimeBuy"]["trade_date"], "2026-06-04")
        self.assertEqual(payload["realtimeBuy"]["quote_time"], "2026-06-04 09:25:01")
        self.assertEqual(payload["realtimeBuy"]["diagnostics"]["as_of"], "2026-06-04 09:25:01")

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

    def test_current_day_non_backtest_rows_are_filtered_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            md_0603 = {
                "date": "2026-06-03",
                "meta": {"mode": "eod"},
                "ztAnalysis": {
                    "relay": [{"code": "000003", "name": "昨日接力", "factorScore": 90, "reason": "预期 +1% ~ +3%"}],
                    "watch": [],
                },
            }
            md_0604 = {
                "date": "2026-06-04",
                "meta": {"mode": "eod"},
                "ztAnalysis": {
                    "relay": [{"code": "000004", "name": "当天接力", "factorScore": 88, "reason": "预期 +1% ~ +3%"}],
                    "watch": [],
                },
            }

            histories = {
                "000003": [
                    {"date": "2026-06-03", "open": 10.0, "close": 10.0, "prev_close": 9.9},
                    {"date": "2026-06-04", "open": 10.2, "close": 10.5, "prev_close": 10.0},
                ],
                "000004": [
                    {"date": "2026-06-04", "open": 8.0, "close": 8.1, "prev_close": 7.9},
                ],
            }

            with patch.object(backtest, "CACHE_DIR", cache_dir), patch.object(
                backtest,
                "_get_price_histories",
                return_value=(histories, {"source": "mock", "fetched": 2, "cached": 0, "missing": []}),
            ), patch.object(
                backtest, "_should_request_realtime_quotes", return_value=False
            ), patch.object(
                backtest, "_load_preserved_realtime_buy", return_value=None
            ):
                backtest.sync_stock_research_backtest_source(market_data=md_0603)
                backtest.save_prefetched_realtime_quotes(
                    date10="2026-06-03",
                    items={
                        "000003": {
                            "dm": "000003",
                            "t": "2026-06-04 09:25:03",
                            "yc": 10.0,
                            "o": 10.2,
                            "p": 10.2,
                            "cje": 200000000,
                        }
                    },
                    as_of="2026-06-04 09:25:03",
                    source="unit_test",
                )
                payload = backtest.build_stock_research_backtest_payload(current_market_data=md_0604)

        self.assertEqual(payload["summary"]["source_samples"], 2)
        self.assertEqual(payload["summary"]["filtered_non_backtest_samples"], 1)
        self.assertEqual(payload["summary"]["total_samples"], 1)
        self.assertEqual(payload["meta"]["latest_recommendation_date"], "2026-06-04")
        self.assertEqual(payload["meta"]["active_trade_date"], "2026-06-05")
        self.assertEqual(payload["realtimeBuy"]["reference_date"], "2026-06-04")
        self.assertEqual(payload["realtimeBuy"]["trade_date"], "2026-06-05")
        self.assertEqual([row["code"] for row in payload["records"]], ["000003"])
        self.assertEqual(payload["diagnostics"]["filtered_non_backtest_codes"], ["000004"])


class StockResearchBacktestPublishFreshnessTest(unittest.TestCase):
    def test_publish_rebuilds_when_source_history_is_newer_than_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            (cache_dir / "stock_research_backtest_source.json").write_text(
                json.dumps(
                    {
                        "schema": "stock_research_backtest_source_v1",
                        "dates": {
                            "2026-06-10": {
                                "date": "2026-06-10",
                                "recommendation_date": "2026-06-09",
                                "pushed_at_bj": "2026-06-09 15:50:02",
                                "rows": [
                                    {"code": "000001"},
                                    {"code": "000002"},
                                    {"code": "000003"},
                                ],
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            stale_payload = {
                "schema": "stock_research_backtest_v2",
                "meta": {
                    "latest_recommendation_date": "2026-06-08",
                    "active_trade_date": "2026-06-09",
                },
                "summary": {
                    "total_samples": 19,
                    "source_samples": 19,
                    "filtered_non_backtest_samples": 0,
                    "eligible_samples": 16,
                    "realtime_candidate_count": 9,
                    "realtime_buy_count": 5,
                    "realtime_pending_count": 0,
                    "realtime_unavailable_count": 0,
                },
                "lifecycle": {
                    "stage": "post_close_wait_auction",
                    "quote_state": "waiting_trade_day",
                },
                "realtimeBuy": {"trade_date": "2026-06-09"},
                "currentPoolRecords": [{"code": "000001"}],
                "records": [{"code": "000001"}],
            }

            with patch.object(web_bundle, "ROOT", root):
                self.assertTrue(web_bundle._is_complete_stock_research_backtest(stale_payload))
                self.assertFalse(web_bundle._is_fresh_stock_research_backtest(stale_payload))


if __name__ == "__main__":
    unittest.main()
