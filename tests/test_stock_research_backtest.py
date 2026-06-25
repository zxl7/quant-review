#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime as real_datetime
from pathlib import Path
from unittest.mock import patch

import daily_review.application.stock_research_service as stock_research_service
import daily_review.data.biying as biying
import daily_review.publish.web_bundle as web_bundle
import scripts.build_stock_research_backtest as backtest
from daily_review.features.ladder_builder import LadderResult, MainLine, TierCell
from daily_review.features.stock_ranker import build_picks_advisor, StockScore, _selection_sort_key


class StockResearchBacktestRowsTest(unittest.TestCase):
    def test_resolve_next_trade_date_merges_local_sources_before_weekday_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            cache_online_dir = root / "cache_online"
            cache_dir.mkdir()
            cache_online_dir.mkdir()
            (cache_dir / "trade_days_cache.json").write_text(
                json.dumps({"days": ["2026-04-20", "2026-04-21"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (cache_dir / "pools_cache.json").write_text(
                json.dumps(
                    {
                        "pools": {
                            "ztgc": {
                                "2026-06-18": [],
                                "2026-06-22": [],
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (cache_dir / "market_data-20260622.json").write_text("{}", encoding="utf-8")

            with patch.object(backtest, "ROOT", root), patch.object(backtest, "CACHE_DIR", cache_dir):
                self.assertEqual(backtest._resolve_next_trade_date("2026-06-18"), "2026-06-22")

    def test_row_from_item_keeps_selection_diagnostics(self) -> None:
        row = backtest._row_from_item(
            {
                "code": "000001",
                "name": "接力核心",
                "factorScore": 87,
                "predTheme": "机器人",
                "qualityLabel": "封单充足",
                "lbc": 3,
                "cjeYi": 31.2,
                "capacityFactorScore": 69.4,
                "nextStep": "分歧转一致",
                "plateName": "机器人",
                "hy": "机器人",
                "factorHint": "辨识度高",
                "relayRank": 1,
                "watchRank": 0,
                "relaySelectionMode": "strict",
                "watchGroup": "",
                "scoreLabel": "推荐因子",
                "leaderFactorScore": 88.1,
                "relayFactorScore": 83.6,
                "leaderPhilosophyScore": 86.3,
                "breakRisk": 32.0,
                "environmentScore": 74.0,
                "stepContextScore": 72.0,
                "tideRelayGate": 4.0,
                "themeLadderProfile": {
                    "label": "梯队完整",
                    "score": 92.0,
                    "gapCount": 0,
                    "frontCount": 3,
                    "leaderBoards": 3,
                    "hasCarry": True,
                },
                "hitRules": ["高标龙头", "主线接力"],
                "blockReasons": ["梯队断层"],
                "reason": "预期 +1% ~ +3%",
            },
            date10="2026-06-03",
            bucket="relay",
        )

        self.assertEqual(row["placement_label"], "接力候选")
        self.assertEqual(row["relay_rank"], 1)
        self.assertEqual(row["relay_selection_mode"], "strict")
        self.assertEqual(row["leader_factor_score"], 88.1)
        self.assertEqual(row["theme_ladder_profile"]["label"], "梯队完整")
        self.assertEqual(row["hit_rules"], ["高标龙头", "主线接力"])
        self.assertEqual(row["block_reasons"], ["梯队断层"])

    def test_daily_rank_prefers_selection_priority_over_raw_score(self) -> None:
        ranked = backtest._attach_daily_rank(
            [
                {
                    "date": "20260603",
                    "date10": "2026-06-03",
                    "code": "000001",
                    "bucket": "watch",
                    "score": 99,
                    "watch_rank": 1,
                    "relay_rank": 0,
                    "watch_group": "容量核心",
                },
                {
                    "date": "20260603",
                    "date10": "2026-06-03",
                    "code": "000002",
                    "bucket": "relay",
                    "score": 81,
                    "relay_rank": 1,
                    "watch_rank": 0,
                },
            ]
        )

        by_code = {row["code"]: row for row in ranked}
        self.assertEqual(by_code["000002"]["daily_rank"], 1)
        self.assertEqual(by_code["000001"]["daily_rank"], 2)
        self.assertEqual([row["code"] for row in ranked], ["000002", "000001"])

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

    def test_invalid_same_day_pre_close_close_push_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            (cache_dir / "stock_research_backtest_source.json").write_text(
                json.dumps(
                    {
                        "schema": "stock_research_backtest_source_v1",
                        "dates": {
                            "2026-06-22": {
                                "date": "2026-06-22",
                                "recommendation_date": "2026-06-19",
                                "source": "ztAnalysis.relay/watch.close_push",
                                "generated_at_bj": "2026-06-19 17:02:29",
                                "rows": [
                                    {"date": "20260619", "date10": "2026-06-19", "trade_date10": "2026-06-22", "code": "000111", "name": "有效接力", "bucket": "relay", "score": 90}
                                ],
                            },
                            "2026-06-23": {
                                "date": "2026-06-23",
                                "recommendation_date": "2026-06-22",
                                "source": "ztAnalysis.relay/watch.close_push",
                                "generated_at_bj": "2026-06-22 09:45:56",
                                "pushed_at_bj": "2026-06-22 09:48:32",
                                "rows": [
                                    {"date": "20260622", "date10": "2026-06-22", "trade_date10": "2026-06-23", "code": "000222", "name": "脏早盘记录", "bucket": "relay", "score": 95}
                                ],
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(backtest, "CACHE_DIR", cache_dir):
                rows, _ = backtest._load_stock_research_rows()
                snapshot = backtest.get_latest_stock_research_source_snapshot()

        self.assertEqual([row["code"] for row in rows], ["000111"])
        self.assertEqual(snapshot["trade_date"], "2026-06-22")
        self.assertEqual(snapshot["recommendation_date"], "2026-06-19")

    def test_sync_source_skips_same_day_pre_close_market_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            market_data = {
                "date": "2026-06-22",
                "meta": {"generatedAt": "2026-06-22 09:45:56"},
                "ztAnalysis": {
                    "relay": [{"code": "000333", "name": "早盘接力", "factorScore": 88, "reason": "预期 +1% ~ +3%"}],
                    "watch": [],
                },
            }

            fake_now = real_datetime(2026, 6, 22, 10, 0, tzinfo=backtest.TZ_BJ)
            with patch.object(backtest, "CACHE_DIR", cache_dir), patch.object(backtest, "_now_bj", return_value=fake_now):
                synced = backtest.sync_stock_research_backtest_source(market_data=market_data)
                history = backtest._load_source_history()

        self.assertFalse(synced)
        self.assertEqual(history.get("dates"), {})

    def test_empty_payload_is_returned_when_no_rows_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()

            with patch.object(backtest, "CACHE_DIR", cache_dir):
                payload = backtest.build_stock_research_backtest_payload()

        self.assertTrue(payload["meta"]["is_empty"])
        self.assertEqual(payload["summary"]["total_samples"], 0)
        self.assertEqual(payload["displayRecords"], [])
        self.assertEqual(payload["historicalSnapshots"], [])
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

    def test_payload_propagates_selection_diagnostics_and_unified_ordering(self) -> None:
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
                            "name": "接力龙头",
                            "factorScore": 88,
                            "predTheme": "机器人",
                            "plateName": "机器人",
                            "hy": "机器人",
                            "lbc": 3,
                            "cjeYi": 38.0,
                            "capacityFactorScore": 68.0,
                            "relayRank": 1,
                            "relaySelectionMode": "strict",
                            "scoreLabel": "推荐因子",
                            "leaderFactorScore": 90.0,
                            "relayFactorScore": 84.0,
                            "leaderPhilosophyScore": 87.0,
                            "breakRisk": 31.0,
                            "environmentScore": 75.0,
                            "stepContextScore": 72.0,
                            "tideRelayGate": 4.0,
                            "themeLadderProfile": {"label": "梯队完整", "score": 93.0, "gapCount": 0, "frontCount": 3, "leaderBoards": 3, "hasCarry": True},
                            "hitRules": ["高标龙头", "主线接力"],
                            "blockReasons": ["梯队断层"],
                            "factorHint": "辨识度强",
                            "reason": "预期 +1% ~ +3%",
                        }
                    ],
                    "watch": [
                        {
                            "code": "000004",
                            "name": "容量观察",
                            "factorScore": 96,
                            "predTheme": "机器人",
                            "plateName": "机器人",
                            "hy": "机器人",
                            "lbc": 1,
                            "cjeYi": 66.0,
                            "capacityFactorScore": 91.0,
                            "watchRank": 1,
                            "watchGroup": "容量核心",
                            "scoreLabel": "观察因子",
                            "leaderFactorScore": 61.0,
                            "relayFactorScore": 56.0,
                            "leaderPhilosophyScore": 58.0,
                            "breakRisk": 48.0,
                            "environmentScore": 71.0,
                            "stepContextScore": 53.0,
                            "tideRelayGate": 2.0,
                            "themeLadderProfile": {"label": "梯队良好", "score": 72.0, "gapCount": 0, "frontCount": 2, "leaderBoards": 1, "hasCarry": True},
                            "hitRules": ["宽松候选"],
                            "blockReasons": ["题材偏泛化"],
                            "factorHint": "容量承接",
                            "reason": "预期 0% ~ +2%",
                        }
                    ],
                },
            }
            histories = {
                "000003": [
                    {"date": "2026-06-03", "open": 10.0, "close": 10.0, "prev_close": 9.8},
                    {"date": "2026-06-04", "open": 10.2, "close": 10.7, "prev_close": 10.0},
                ],
                "000004": [
                    {"date": "2026-06-03", "open": 8.0, "close": 8.0, "prev_close": 7.9},
                    {"date": "2026-06-04", "open": 8.08, "close": 8.2, "prev_close": 8.0},
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
                backtest.sync_stock_research_backtest_source(market_data=backtest_payload)
                backtest.save_prefetched_realtime_quotes(
                    date10="2026-06-03",
                    items={
                        "000003": {"dm": "000003", "t": "2026-06-04 09:25:01", "yc": 10.0, "o": 10.2, "p": 10.2, "cje": 200000000},
                        "000004": {"dm": "000004", "t": "2026-06-04 09:25:02", "yc": 8.0, "o": 8.08, "p": 8.08, "cje": 260000000},
                    },
                    as_of="2026-06-04 09:25:02",
                    source="unit_test",
                )
                payload = backtest.build_stock_research_backtest_payload()

        self.assertEqual([row["code"] for row in payload["currentPoolRecords"]], ["000003", "000004"])
        relay_row = payload["currentPoolRecords"][0]
        watch_row = payload["currentPoolRecords"][1]
        self.assertEqual(relay_row["relay_rank"], 1)
        self.assertEqual(relay_row["relay_selection_mode"], "strict")
        self.assertEqual(relay_row["theme_ladder_profile"]["label"], "梯队完整")
        self.assertEqual(watch_row["watch_rank"], 1)
        self.assertEqual(watch_row["watch_group"], "容量核心")

        realtime_rows = [
            row
            for bucket in ("buy_list", "pending_list", "rejected_list", "unavailable_list")
            for row in payload["realtimeBuy"][bucket]
        ]
        realtime_by_code = {row["code"]: row for row in realtime_rows}
        self.assertEqual(realtime_rows[0]["code"], "000003")
        self.assertEqual(realtime_by_code["000003"]["hit_rules"], ["高标龙头", "主线接力"])
        self.assertEqual(realtime_by_code["000003"]["block_reasons"], ["梯队断层"])
        self.assertEqual(realtime_by_code["000004"]["watch_group"], "容量核心")

        snapshot = payload["historicalSnapshots"][0]
        self.assertEqual(snapshot["buy_list"][0]["code"], "000003")
        self.assertEqual(snapshot["buy_list"][0]["relay_rank"], 1)
        self.assertEqual(snapshot["buy_list"][0]["theme_ladder_profile"]["label"], "梯队完整")

    def test_forced_query_tag_uses_current_realtime_quote_outside_window(self) -> None:
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

            with patch.object(backtest, "CACHE_DIR", cache_dir), patch.object(
                backtest,
                "_get_price_histories",
                return_value=(
                    {
                        "000003": [
                            {"date": "2026-06-03", "open": 10.0, "close": 10.0, "prev_close": 9.9},
                        ]
                    },
                    {"source": "mock", "fetched": 1, "cached": 0, "missing": []},
                ),
            ), patch.object(
                backtest, "_should_request_realtime_quotes", return_value=False
            ), patch.dict(
                "os.environ", {"STOCK_RESEARCH_QUERY_TAG": "fore"}, clear=False
            ), patch.object(
                backtest,
                "fetch_stocks_realtime",
                return_value=[
                    {
                        "dm": "000003",
                        "t": "2026-06-04 13:14:15",
                        "yc": 10.0,
                        "o": 10.2,
                        "p": 10.3,
                        "cje": 200000000,
                    }
                ],
            ):
                backtest.sync_stock_research_backtest_source(market_data=backtest_payload)
                payload = backtest.build_stock_research_backtest_payload(query_tag="fore")

        self.assertEqual(payload["realtimeBuy"]["quoted_count"], 0)
        self.assertEqual(payload["realtimeBuy"]["buy_count"], 0)
        self.assertEqual(payload["realtimeBuy"]["quote_time"], "")
        self.assertEqual(payload["realtimeBuy"]["diagnostics"]["source"], "fore_today_only_guard")
        self.assertTrue(payload["realtimeBuy"]["diagnostics"]["forced_query"])
        self.assertEqual(payload["lifecycle"]["quote_state"], "missing")
        self.assertTrue(payload["lifecycle"]["forced_query"])

    def test_default_display_anchors_prefer_current_trade_day_when_today_snapshot_missing(self) -> None:
        rows = [
            {"date10": "2026-06-19", "trade_date10": "2026-06-22", "code": "000001", "bucket": "relay", "score": 90},
            {"date10": "2026-06-22", "trade_date10": "2026-06-23", "code": "000002", "bucket": "relay", "score": 88},
        ]
        backtest_rows = [dict(rows[0])]
        historical_snapshots = [{"reference_date": "2026-06-19", "trade_date": "2026-06-22"}]
        realtime_buy = {
            "reference_date": "2026-06-22",
            "trade_date": "2026-06-23",
            "quote_time": "",
            "quoted_count": 0,
            "candidate_count": 1,
            "diagnostics": {"source": "unavailable"},
        }

        anchors = backtest._resolve_display_anchors(
            current_pool_rows=[dict(rows[1])],
            backtest_rows=backtest_rows,
            historical_snapshots=historical_snapshots,
            realtime_buy=realtime_buy,
            active_trade_date10="2026-06-23",
            latest_recommendation_date10="2026-06-22",
            now=real_datetime(2026, 6, 23, 10, 0, 0, tzinfo=backtest.TZ_BJ),
        )

        self.assertEqual(anchors["latest_closed_trade_date"], "2026-06-22")
        self.assertEqual(anchors["latest_closed_recommendation_date"], "2026-06-19")
        self.assertEqual(anchors["default_display_trade_date"], "2026-06-23")
        self.assertEqual(anchors["default_display_recommendation_date"], "2026-06-22")
        self.assertIn("不会自动回退到历史闭环", anchors["default_display_note"])
        self.assertFalse(anchors["has_pending_next_trade_day"])

    def test_default_display_anchors_prefer_latest_closed_loop_over_future_pending_next_day(self) -> None:
        rows = [
            {"date10": "2026-06-19", "trade_date10": "2026-06-22", "code": "000001", "bucket": "relay", "score": 90},
            {"date10": "2026-06-22", "trade_date10": "2026-06-23", "code": "000002", "bucket": "relay", "score": 88},
        ]
        backtest_rows = [dict(rows[0])]
        historical_snapshots = [{"reference_date": "2026-06-19", "trade_date": "2026-06-22"}]
        realtime_buy = {
            "reference_date": "",
            "trade_date": "",
            "quote_time": "",
            "quoted_count": 0,
            "diagnostics": {},
        }

        anchors = backtest._resolve_display_anchors(
            current_pool_rows=[dict(rows[1])],
            backtest_rows=backtest_rows,
            historical_snapshots=historical_snapshots,
            realtime_buy=realtime_buy,
            active_trade_date10="2026-06-23",
            latest_recommendation_date10="2026-06-22",
            now=real_datetime(2026, 6, 22, 16, 0, 0, tzinfo=backtest.TZ_BJ),
        )

        self.assertEqual(anchors["latest_closed_trade_date"], "2026-06-22")
        self.assertEqual(anchors["latest_closed_recommendation_date"], "2026-06-19")
        self.assertEqual(anchors["default_display_trade_date"], "2026-06-22")
        self.assertEqual(anchors["default_display_recommendation_date"], "2026-06-19")
        self.assertTrue(anchors["has_pending_next_trade_day"])
        self.assertIn("已生成下一交易日 2026-06-23 的待验证池", anchors["default_display_note"])

    def test_default_display_anchors_prefer_same_day_realtime_snapshot_when_ready(self) -> None:
        realtime_buy = {
            "reference_date": "2026-06-22",
            "trade_date": "2026-06-23",
            "quote_time": "2026-06-23 09:25:01",
            "quoted_count": 1,
            "candidate_count": 1,
            "diagnostics": {"source": "workflow_prefetch"},
        }

        anchors = backtest._resolve_display_anchors(
            current_pool_rows=[{"date10": "2026-06-22", "trade_date10": "2026-06-23", "code": "000002", "bucket": "relay", "score": 88}],
            backtest_rows=[{"date10": "2026-06-19", "trade_date10": "2026-06-22", "code": "000001", "bucket": "relay", "score": 90}],
            historical_snapshots=[{"reference_date": "2026-06-19", "trade_date": "2026-06-22"}],
            realtime_buy=realtime_buy,
            active_trade_date10="2026-06-23",
            latest_recommendation_date10="2026-06-22",
            now=real_datetime(2026, 6, 23, 9, 28, 0, tzinfo=backtest.TZ_BJ),
        )

        self.assertEqual(anchors["default_display_trade_date"], "2026-06-23")
        self.assertEqual(anchors["default_display_recommendation_date"], "2026-06-22")

    def test_normal_mode_blocks_future_trade_date_realtime_matching(self) -> None:
        row = {"date10": "2026-06-22", "trade_date10": "2026-06-23", "code": "000001", "bucket": "relay", "score": 90}
        with patch.object(backtest, "_now_bj", return_value=real_datetime(2026, 6, 22, 16, 0, 0, tzinfo=backtest.TZ_BJ)):
            payload = backtest._build_realtime_buy_payload([row], latest_date10="2026-06-22", trade_date10="2026-06-23")

        self.assertEqual(payload["quoted_count"], 0)
        self.assertEqual(payload["diagnostics"]["source"], "future_trade_day_guard")
        self.assertTrue(payload["diagnostics"]["future_trade_day_guard"])

    def test_forced_query_also_blocks_future_trade_date_realtime_matching(self) -> None:
        row = {"date10": "2026-06-22", "trade_date10": "2026-06-23", "code": "000001", "bucket": "relay", "score": 90}
        with patch.object(backtest, "_now_bj", return_value=real_datetime(2026, 6, 22, 16, 0, 0, tzinfo=backtest.TZ_BJ)):
            payload = backtest._build_realtime_buy_payload([row], latest_date10="2026-06-22", trade_date10="2026-06-23", query_tag="fore")

        self.assertEqual(payload["quoted_count"], 0)
        self.assertEqual(payload["diagnostics"]["source"], "future_trade_day_guard")
        self.assertTrue(payload["diagnostics"]["future_trade_day_guard"])
        self.assertTrue(payload["diagnostics"]["forced_query"])


class PicksAdvisorStabilityTest(unittest.TestCase):
    def test_does_not_duplicate_same_stock_across_main_lines(self) -> None:
        ladder = LadderResult(
            date="2026-06-16",
            tiers={1: [], 2: [], 3: [], 4: []},
            main_lines=[
                MainLine(
                    name="宽主线",
                    is_chain=False,
                    constituents=["AI", "算力"],
                    confidence=0.82,
                    biying_signal=0.6,
                    em_signal=0.5,
                    xgb_signal=0.4,
                    leading_stocks=["000001"],
                ),
                MainLine(
                    name="窄主线",
                    is_chain=False,
                    constituents=["AI"],
                    confidence=0.78,
                    biying_signal=0.6,
                    em_signal=0.5,
                    xgb_signal=0.4,
                    leading_stocks=["000001"],
                ),
            ],
        )
        ladder.tiers = {
            1: [
                TierCell(
                    code="000001",
                    name="同一只票",
                    lbc=2,
                    cje_yi=45,
                    turnover=8,
                    seal_fund_yi=2.2,
                    zbc=0,
                    score=88,
                    sectors=[("AI", 1.0)],
                    primary_sector="AI",
                )
            ],
            2: [],
            3: [],
            4: [],
        }
        market_data = {
            "leaders": [{"code": "000001", "score": 88}],
            "ztAnalysis": {"relay": [{"code": "000001", "factorScore": 88}], "watch": []},
            "moodStage": {"cycle": "FERMENT", "dayState": "修复"},
            "actionAdvisor": {"posture": "谨慎进攻"},
        }

        payload = build_picks_advisor(ladder=ladder, market_data=market_data, top_k_lines=2, buy_n=1, watch_n=2)
        picked_codes = [
            row["code"]
            for group in payload.to_dict()["main_line_picks"]
            for row in [*(group.get("buy") or []), *(group.get("watch") or [])]
        ]

        self.assertEqual(picked_codes.count("000001"), 1)

    def test_weak_watch_fallback_does_not_force_low_quality_stock(self) -> None:
        ladder = LadderResult(
            date="2026-06-16",
            tiers={1: [], 2: [], 3: [], 4: []},
            main_lines=[
                MainLine(
                    name="弱主线",
                    is_chain=False,
                    constituents=["铜箔"],
                    confidence=0.5,
                    biying_signal=0.3,
                    em_signal=0.2,
                    xgb_signal=0.1,
                ),
            ],
        )
        ladder.tiers = {
            1: [
                TierCell(
                    code="000002",
                    name="低质票",
                    lbc=1,
                    cje_yi=8,
                    turnover=2,
                    seal_fund_yi=0.1,
                    zbc=0,
                    score=28,
                    sectors=[("铜箔", 1.0)],
                    primary_sector="铜箔",
                )
            ],
            2: [],
            3: [],
            4: [],
        }
        market_data = {
            "leaders": [{"code": "000002", "score": 28}],
            "ztAnalysis": {"relay": [], "watch": []},
            "moodStage": {"cycle": "ICE", "dayState": "分歧"},
            "actionAdvisor": {"posture": "防守"},
        }

        payload = build_picks_advisor(ladder=ladder, market_data=market_data, top_k_lines=1, buy_n=1, watch_n=2)
        picks = payload.to_dict()["main_line_picks"][0]

        self.assertEqual(picks["buy"], [])
        self.assertEqual(picks["watch"], [])

    def test_sorting_prefers_certainty_identity_and_lower_risk_on_close_scores(self) -> None:
        risky = StockScore(
            code="000010",
            name="高弹性高风险",
            action="skip",
            score=66,
            main_line="测试主线",
            primary_sector="AI",
            primary_confidence=0.45,
            breakdown={"贴合度": 10, "封板": 4, "换手": 2, "板块": 7, "量能": 12},
            reasons=["AI"],
            cautions=["换手过热"],
            lbc=1,
            cje_yi=150,
            seal_fund_yi=0.3,
            turnover=38,
            leaders_score=20,
            env_adjust=1,
            relay_adjust=0,
            risk_penalty=11,
            zt_placement="watch",
            style_tag="容量",
            style_confidence=78,
            relay_power_score=62,
        )
        steady = StockScore(
            code="000011",
            name="稳健核心",
            action="skip",
            score=64,
            main_line="测试主线",
            primary_sector="AI",
            primary_confidence=0.82,
            breakdown={"贴合度": 20, "封板": 11, "换手": 10, "板块": 7, "量能": 9},
            reasons=["AI核心", "主线领涨"],
            cautions=[],
            lbc=2,
            cje_yi=36,
            seal_fund_yi=2.6,
            turnover=9,
            leaders_score=86,
            env_adjust=3,
            relay_adjust=8,
            risk_penalty=3,
            zt_placement="relay",
            style_tag="龙头博弈",
            style_confidence=92,
            relay_power_score=68,
        )

        ordered = sorted([risky, steady], key=_selection_sort_key, reverse=True)

        self.assertEqual([row.code for row in ordered], ["000011", "000010"])

    def test_sorting_prefers_lbc2_relay_over_lbc1_capacity_when_quality_is_close(self) -> None:
        relay = StockScore(
            code="000020",
            name="龙头接力",
            action="skip",
            score=62,
            main_line="测试主线",
            primary_sector="AI",
            primary_confidence=0.76,
            breakdown={"贴合度": 16, "封板": 10, "换手": 8, "板块": 7, "量能": 8},
            reasons=["AI核心", "主线领涨"],
            cautions=[],
            lbc=2,
            cje_yi=42,
            seal_fund_yi=2.1,
            turnover=10,
            leaders_score=84,
            env_adjust=2,
            relay_adjust=10,
            risk_penalty=4,
            zt_placement="relay",
            style_tag="龙头博弈",
            style_confidence=92,
            relay_power_score=66,
        )
        capacity = StockScore(
            code="000021",
            name="容量首板",
            action="skip",
            score=63,
            main_line="测试主线",
            primary_sector="AI",
            primary_confidence=0.88,
            breakdown={"贴合度": 18, "封板": 9, "换手": 10, "板块": 7, "量能": 12},
            reasons=["AI", "板块强共振"],
            cautions=[],
            lbc=1,
            cje_yi=95,
            seal_fund_yi=2.8,
            turnover=12,
            leaders_score=60,
            env_adjust=2,
            relay_adjust=2,
            risk_penalty=4,
            zt_placement="",
            style_tag="容量",
            style_confidence=78,
            relay_power_score=52,
        )

        ordered = sorted([capacity, relay], key=_selection_sort_key, reverse=True)

        self.assertEqual([row.code for row in ordered], ["000020", "000021"])

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
        self.assertEqual([row["code"] for row in payload["displayRecords"]], ["000003", "000004"])
        self.assertEqual([row["code"] for row in payload["records"]], ["000003"])
        self.assertEqual(len(payload["historicalSnapshots"]), 1)
        snapshot = payload["historicalSnapshots"][0]
        self.assertEqual(snapshot["reference_date"], "2026-06-03")
        self.assertEqual(snapshot["trade_date"], "2026-06-04")
        self.assertEqual(snapshot["buy_count"], 1)
        self.assertEqual(snapshot["quoted_count"], 1)
        self.assertEqual(snapshot["diagnostics"]["source"], "unit_test")
        self.assertTrue(snapshot["diagnostics"]["used_prefetched_snapshot"])
        self.assertEqual(snapshot["quote_time"], "2026-06-04 09:25:03")
        self.assertEqual(snapshot["buy_list"][0]["auction_price"], 10.2)
        self.assertEqual(snapshot["buy_list"][0]["prev_close"], 10.0)
        self.assertEqual(payload["diagnostics"]["filtered_non_backtest_codes"], ["000004"])
        self.assertEqual(payload["diagnostics"]["display_only_codes"], ["000004"])

    def test_forced_query_persists_snapshot_for_later_historical_reuse(self) -> None:
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

            with patch.object(backtest, "CACHE_DIR", cache_dir), patch.object(
                backtest,
                "_get_price_histories",
                return_value=(
                    {
                        "000003": [
                            {"date": "2026-06-03", "open": 10.0, "close": 10.0, "prev_close": 9.9},
                        ]
                    },
                    {"source": "mock", "fetched": 1, "cached": 0, "missing": []},
                ),
            ), patch.object(
                backtest,
                "fetch_stocks_realtime",
                return_value=[
                    {
                        "dm": "000003",
                        "t": "2026-06-04 13:14:15",
                        "yc": 10.0,
                        "o": 10.2,
                        "p": 10.3,
                        "cje": 200000000,
                    }
                ],
            ):
                backtest.sync_stock_research_backtest_source(market_data=backtest_payload)
                payload = backtest.build_stock_research_backtest_payload(query_tag="fore")
                persisted = backtest.load_prefetched_realtime_quotes("2026-06-03")

        self.assertEqual(payload["realtimeBuy"]["quote_time"], "")
        self.assertEqual(payload["realtimeBuy"]["diagnostics"]["source"], "fore_today_only_guard")
        self.assertEqual(persisted, {})

    def test_forced_query_cache_same_trade_day_is_reused_outside_window(self) -> None:
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

            with patch.object(backtest, "CACHE_DIR", cache_dir), patch.object(
                backtest,
                "_get_price_histories",
                return_value=(
                    {
                        "000003": [
                            {"date": "2026-06-03", "open": 10.0, "close": 10.0, "prev_close": 9.9},
                        ]
                    },
                    {"source": "mock", "fetched": 1, "cached": 0, "missing": []},
                ),
            ), patch.object(
                backtest, "_should_request_realtime_quotes", return_value=False
            ), patch.object(
                backtest, "_load_preserved_realtime_buy", return_value=None
            ):
                backtest.sync_stock_research_backtest_source(market_data=backtest_payload)
                backtest.save_prefetched_realtime_quotes(
                    date10="2026-06-03",
                    items={
                        "000003": {
                            "dm": "000003",
                            "t": "2026-06-04 13:14:15",
                            "yc": 10.0,
                            "o": 10.2,
                            "p": 10.3,
                            "cje": 200000000,
                        }
                    },
                    as_of="2026-06-04 13:14:15",
                    source="forced_query",
                )
                payload = backtest.build_stock_research_backtest_payload()

        self.assertEqual(payload["realtimeBuy"]["quote_time"], "2026-06-04 13:14:15")
        self.assertEqual(payload["realtimeBuy"]["diagnostics"]["source"], "forced_query_cache")
        self.assertTrue(payload["realtimeBuy"]["diagnostics"]["forced_query"])
        self.assertEqual(payload["lifecycle"]["quote_state"], "ready")

    def test_forced_query_cache_does_not_cross_trade_day_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            backtest_payload = {
                "date": "2026-06-24",
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

            with patch.object(backtest, "CACHE_DIR", cache_dir), patch.object(
                backtest,
                "_get_price_histories",
                return_value=(
                    {
                        "000003": [
                            {"date": "2026-06-24", "open": 10.0, "close": 10.0, "prev_close": 9.9},
                        ]
                    },
                    {"source": "mock", "fetched": 1, "cached": 0, "missing": []},
                ),
            ), patch.object(
                backtest, "_should_request_realtime_quotes", return_value=False
            ), patch.object(
                backtest, "_load_preserved_realtime_buy", return_value=None
            ), patch.object(
                backtest,
                "_now_bj",
                return_value=real_datetime(2026, 6, 25, 9, 10, 0, tzinfo=backtest.TZ_BJ),
            ):
                backtest.sync_stock_research_backtest_source(market_data=backtest_payload)
                backtest.save_prefetched_realtime_quotes(
                    date10="2026-06-24",
                    items={
                        "000003": {
                            "dm": "000003",
                            "t": "2026-06-24 15:00:00",
                            "yc": 10.0,
                            "o": 10.2,
                            "p": 10.3,
                            "cje": 200000000,
                        }
                    },
                    as_of="2026-06-24 15:00:00",
                    source="forced_query",
                )
                payload = backtest.build_stock_research_backtest_payload()

        self.assertEqual(payload["meta"]["active_trade_date"], "2026-06-25")
        self.assertEqual(payload["realtimeBuy"]["quote_time"], "")
        self.assertNotEqual(payload["realtimeBuy"]["diagnostics"]["source"], "forced_query_cache")
        self.assertEqual(payload["lifecycle"]["quote_state"], "waiting_window")
        self.assertEqual(payload["lifecycle"]["stage"], "post_close_wait_auction")


class StockResearchBacktestPublishFreshnessTest(unittest.TestCase):
    def test_attach_stock_research_backtest_disables_history_fetch_by_default(self) -> None:
        from daily_review.application import stock_research_service as service

        market_data = {"date": "2026-06-23"}

        def fake_build_stock_research_backtest_payload(**kwargs):
            self.assertEqual(os.environ.get("QR_DISABLE_STOCK_RESEARCH_HISTORY_FETCH"), "1")
            self.assertFalse(kwargs["sync_source_from_market_data"])
            return {"meta": {"date": "2026-06-23"}}

        with patch("scripts.build_stock_research_backtest.build_stock_research_backtest_payload", side_effect=fake_build_stock_research_backtest_payload):
            service.attach_stock_research_backtest(
                market_data=market_data,
                sync_source=False,
                query_tag="",
                log_fn=None,
            )

        self.assertEqual(market_data["stockResearchBacktest"]["meta"], {"date": "2026-06-23"})
        self.assertIsNone(os.environ.get("QR_DISABLE_STOCK_RESEARCH_HISTORY_FETCH"))

    def test_attach_stock_research_backtest_respects_explicit_history_fetch_enable(self) -> None:
        from daily_review.application import stock_research_service as service

        market_data = {"date": "2026-06-24"}

        def fake_build_stock_research_backtest_payload(**kwargs):
            self.assertEqual(os.environ.get("QR_DISABLE_STOCK_RESEARCH_HISTORY_FETCH"), "0")
            self.assertFalse(kwargs["sync_source_from_market_data"])
            return {"meta": {"date": "2026-06-24"}}

        with patch("scripts.build_stock_research_backtest.build_stock_research_backtest_payload", side_effect=fake_build_stock_research_backtest_payload), patch.dict(
            os.environ,
            {"QR_DISABLE_STOCK_RESEARCH_HISTORY_FETCH": "0"},
            clear=False,
        ):
            service.attach_stock_research_backtest(
                market_data=market_data,
                sync_source=False,
                query_tag="",
                log_fn=None,
            )

        self.assertEqual(market_data["stockResearchBacktest"]["meta"], {"date": "2026-06-24"})
        self.assertIsNone(os.environ.get("QR_DISABLE_STOCK_RESEARCH_HISTORY_FETCH"))

    def test_history_fetch_can_be_disabled_for_publish_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            cache_online_dir = root / "cache_online"
            cache_dir.mkdir()
            cache_online_dir.mkdir()
            (cache_online_dir / "recommendation_price_history.json").write_text(
                json.dumps(
                    {
                        "schema": "recommendation_price_history_v1",
                        "codes": {
                            "000001": {
                                "code": "000001",
                                "bars": [
                                    {
                                        "date": "2026-06-20",
                                        "open": 10.0,
                                        "close": 10.1,
                                        "high": 10.2,
                                        "low": 9.9,
                                        "prev_close": 9.8,
                                    }
                                ],
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(backtest, "ROOT", root), patch.object(
                backtest, "PRICE_CACHE", cache_online_dir / "recommendation_price_history.json"
            ), patch.dict(
                backtest.os.environ, {"QR_DISABLE_STOCK_RESEARCH_HISTORY_FETCH": "1"}, clear=False
            ), patch.object(
                backtest, "fetch_stock_history_k"
            ) as mock_fetch:
                histories, diag = backtest._get_price_histories(["000001", "000002"], st8="20260620", et8="20260623")

        self.assertFalse(mock_fetch.called)
        self.assertEqual(diag["source"], "cache_only")
        self.assertTrue(diag["history_fetch_disabled"])
        self.assertIn("000001", histories)
        self.assertEqual(diag["missing"], ["000002"])

    def test_publish_marks_payload_stale_when_selection_fields_are_missing(self) -> None:
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
                                "rows": [{"code": "000001"}],
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            payload = {
                "schema": "stock_research_backtest_v2",
                "meta": {"latest_recommendation_date": "2026-06-09", "active_trade_date": "2026-06-10"},
                "summary": {
                    "total_samples": 1,
                    "source_samples": 1,
                    "filtered_non_backtest_samples": 0,
                    "eligible_samples": 1,
                    "realtime_candidate_count": 1,
                    "realtime_buy_count": 0,
                    "realtime_pending_count": 0,
                    "realtime_unavailable_count": 1,
                },
                "lifecycle": {"stage": "post_close_wait_auction", "quote_state": "waiting_trade_day"},
                "realtimeBuy": {"trade_date": "2026-06-10"},
                "currentPoolRecords": [{"code": "000001"}],
                "displayRecords": [{"code": "000001"}],
                "historicalSnapshots": [],
                "records": [{"code": "000001"}],
            }

            with patch.object(web_bundle, "ROOT", root):
                self.assertFalse(web_bundle._is_fresh_stock_research_backtest(payload))

    def test_upgrade_backfills_default_display_anchor_fields(self) -> None:
        payload = {
            "schema": "stock_research_backtest_v2",
            "meta": {"latest_recommendation_date": "2026-06-22", "active_trade_date": "2026-06-23"},
            "summary": {
                "total_samples": 1,
                "source_samples": 1,
                "filtered_non_backtest_samples": 0,
                "eligible_samples": 1,
                "realtime_candidate_count": 1,
                "realtime_buy_count": 0,
                "realtime_pending_count": 0,
                "realtime_unavailable_count": 1,
            },
            "lifecycle": {"stage": "post_close_wait_auction", "quote_state": "waiting_trade_day"},
            "realtimeBuy": {"trade_date": "2026-06-23", "reference_date": "2026-06-22", "quoted_count": 0, "diagnostics": {}},
            "currentPoolRecords": [{"code": "000002", "date10": "2026-06-22", "trade_date10": "2026-06-23"}],
            "displayRecords": [{"code": "000001", "date10": "2026-06-19", "trade_date10": "2026-06-22"}],
            "historicalSnapshots": [{"reference_date": "2026-06-19", "trade_date": "2026-06-22"}],
            "records": [{"code": "000001", "date10": "2026-06-19", "trade_date10": "2026-06-22"}],
        }

        with patch.object(backtest, "_now_bj", return_value=real_datetime(2026, 6, 22, 16, 0, 0, tzinfo=backtest.TZ_BJ)):
            upgraded = backtest.upgrade_stock_research_backtest_payload(payload)

        self.assertEqual(upgraded["meta"]["default_display_trade_date"], "2026-06-22")
        self.assertEqual(upgraded["meta"]["default_display_recommendation_date"], "2026-06-19")
        self.assertTrue(upgraded["meta"]["has_pending_next_trade_day"])

    def test_upgrade_corrects_invalid_trade_dates_before_recomputing_anchors(self) -> None:
        payload = {
            "schema": "stock_research_backtest_v2",
            "meta": {"latest_recommendation_date": "2026-06-22", "active_trade_date": "2026-06-23"},
            "summary": {
                "total_samples": 1,
                "source_samples": 1,
                "filtered_non_backtest_samples": 0,
                "eligible_samples": 1,
                "realtime_candidate_count": 1,
                "realtime_buy_count": 0,
                "realtime_pending_count": 0,
                "realtime_unavailable_count": 1,
            },
            "lifecycle": {"stage": "post_close_wait_auction", "quote_state": "waiting_trade_day"},
            "realtimeBuy": {"trade_date": "2026-06-23", "reference_date": "2026-06-22", "quoted_count": 0, "diagnostics": {}},
            "currentPoolRecords": [{"code": "000002", "date10": "2026-06-22", "trade_date10": "2026-06-23"}],
            "displayRecords": [{"code": "000001", "date10": "2026-06-18", "trade_date10": "2026-06-19"}],
            "historicalSnapshots": [{"reference_date": "2026-06-18", "trade_date": "2026-06-19"}],
            "records": [{"code": "000001", "date10": "2026-06-18", "trade_date10": "2026-06-19"}],
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            (cache_dir / "pools_cache.json").write_text(
                json.dumps({"pools": {"ztgc": {"2026-06-18": [], "2026-06-22": [], "2026-06-23": []}}}, ensure_ascii=False),
                encoding="utf-8",
            )
            with patch.object(backtest, "ROOT", root), patch.object(backtest, "CACHE_DIR", cache_dir), patch.object(
                backtest,
                "_now_bj",
                return_value=real_datetime(2026, 6, 22, 16, 0, 0, tzinfo=backtest.TZ_BJ),
            ):
                upgraded = backtest.upgrade_stock_research_backtest_payload(payload)

        self.assertEqual(upgraded["records"][0]["trade_date10"], "2026-06-22")
        self.assertEqual(upgraded["historicalSnapshots"][0]["trade_date"], "2026-06-22")
        self.assertEqual(upgraded["meta"]["default_display_trade_date"], "2026-06-22")
        self.assertEqual(upgraded["meta"]["default_display_recommendation_date"], "2026-06-18")

    def test_upgrade_prefers_today_pending_batch_over_historical_closed_loop(self) -> None:
        payload = {
            "schema": "stock_research_backtest_v2",
            "meta": {"latest_recommendation_date": "2026-06-22", "active_trade_date": "2026-06-23"},
            "summary": {
                "total_samples": 1,
                "source_samples": 1,
                "filtered_non_backtest_samples": 0,
                "eligible_samples": 1,
                "realtime_candidate_count": 1,
                "realtime_buy_count": 0,
                "realtime_pending_count": 1,
                "realtime_unavailable_count": 0,
            },
            "lifecycle": {"stage": "auction_snapshot_missing", "quote_state": "missing"},
            "realtimeBuy": {
                "trade_date": "2026-06-23",
                "reference_date": "2026-06-22",
                "candidate_count": 1,
                "quoted_count": 0,
                "quote_time": "",
                "diagnostics": {"source": "unavailable"},
            },
            "currentPoolRecords": [{"code": "000002", "date10": "2026-06-22", "trade_date10": "2026-06-23"}],
            "displayRecords": [{"code": "000001", "date10": "2026-06-19", "trade_date10": "2026-06-22"}],
            "historicalSnapshots": [{"reference_date": "2026-06-19", "trade_date": "2026-06-22"}],
            "records": [{"code": "000001", "date10": "2026-06-19", "trade_date10": "2026-06-22"}],
        }

        with patch.object(backtest, "_now_bj", return_value=real_datetime(2026, 6, 23, 10, 0, 0, tzinfo=backtest.TZ_BJ)):
            upgraded = backtest.upgrade_stock_research_backtest_payload(payload)

        self.assertEqual(upgraded["meta"]["default_display_trade_date"], "2026-06-23")
        self.assertEqual(upgraded["meta"]["default_display_recommendation_date"], "2026-06-22")
        self.assertEqual(upgraded["lifecycle"]["quote_state"], "missing")
        self.assertEqual(upgraded["lifecycle"]["stage"], "auction_snapshot_missing")
        self.assertIn("不再自动跳到历史闭环结果", upgraded["lifecycle"]["stage_note"])
        self.assertIn("当前仅保留今日待验证池", upgraded["lifecycle"]["quote_state_note"])

    def test_upgrade_prefers_latest_closed_day_when_future_pending_next_day_exists(self) -> None:
        payload = {
            "schema": "stock_research_backtest_v2",
            "meta": {
                "latest_recommendation_date": "2026-06-25",
                "active_trade_date": "2026-06-26",
                "latest_closed_trade_date": "2026-06-25",
            },
            "summary": {
                "total_samples": 2,
                "source_samples": 2,
                "filtered_non_backtest_samples": 0,
                "eligible_samples": 2,
                "realtime_candidate_count": 1,
                "realtime_buy_count": 0,
                "realtime_pending_count": 1,
                "realtime_unavailable_count": 0,
            },
            "lifecycle": {"stage": "post_close_wait_auction", "quote_state": "waiting_trade_day"},
            "realtimeBuy": {
                "trade_date": "2026-06-26",
                "reference_date": "2026-06-25",
                "quoted_count": 0,
                "quote_time": "",
                "diagnostics": {"source": "future_trade_day_guard"},
            },
            "currentPoolRecords": [{"code": "000002", "date10": "2026-06-25", "trade_date10": "2026-06-26"}],
            "displayRecords": [{"code": "000001", "date10": "2026-06-24", "trade_date10": "2026-06-25"}],
            "historicalSnapshots": [{"reference_date": "2026-06-24", "trade_date": "2026-06-25"}],
            "records": [{"code": "000001", "date10": "2026-06-24", "trade_date10": "2026-06-25"}],
        }

        with patch.object(backtest, "_now_bj", return_value=real_datetime(2026, 6, 25, 16, 0, 0, tzinfo=backtest.TZ_BJ)):
            upgraded = backtest.upgrade_stock_research_backtest_payload(payload)

        self.assertEqual(upgraded["meta"]["active_trade_date"], "2026-06-26")
        self.assertEqual(upgraded["meta"]["latest_closed_trade_date"], "2026-06-25")
        self.assertEqual(upgraded["meta"]["default_display_trade_date"], "2026-06-25")
        self.assertEqual(upgraded["meta"]["default_display_recommendation_date"], "2026-06-24")
        self.assertTrue(upgraded["meta"]["has_pending_next_trade_day"])
        self.assertEqual(upgraded["lifecycle"]["quote_state"], "waiting_trade_day")
        self.assertEqual(upgraded["lifecycle"]["stage"], "post_close_wait_auction")
        self.assertIn("页面默认仍展示最近已闭环日 2026-06-25", upgraded["lifecycle"]["quote_state_note"])

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
                "displayRecords": [{"code": "000001"}],
                "historicalSnapshots": [],
                "records": [{"code": "000001"}],
            }

            with patch.object(web_bundle, "ROOT", root):
                self.assertTrue(web_bundle._is_complete_stock_research_backtest(stale_payload))
                self.assertFalse(web_bundle._is_fresh_stock_research_backtest(stale_payload))

    def test_preserved_snapshot_keeps_stock_research_backtest_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            (cache_dir / "market_data-20260615.json").write_text(
                json.dumps(
                    {
                        "date": "2026-06-15",
                        "ztAnalysis": {"relay": [{"code": "000001", "name": "接力龙头"}], "watch": []},
                        "stockResearchBacktest": {
                            "schema": "stock_research_backtest_v2",
                            "meta": {"latest_recommendation_date": "2026-06-15"},
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            snapshot = stock_research_service.load_latest_valid_research_snapshot(root=root, current_date="2026-06-16")

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["marketData"]["stockResearchBacktest"]["meta"]["latest_recommendation_date"], "2026-06-15")

    def test_publish_can_skip_live_backtest_rebuild(self) -> None:
        md = {}
        with patch.dict(web_bundle.os.environ, {"QR_DISABLE_STOCK_RESEARCH_BACKTEST_REBUILD": "1"}, clear=False), patch.object(
            web_bundle, "_latest_stock_research_source_snapshot", return_value={}
        ), patch.object(
            web_bundle, "_is_fresh_stock_research_backtest", return_value=False
        ), patch.object(
            web_bundle, "_is_complete_stock_research_backtest", return_value=False
        ):
            web_bundle._ensure_stock_research_backtest(md)

        self.assertNotIn("stockResearchBacktest", md)

    def test_fresh_backtest_requires_latest_closed_trade_date_to_reach_source_trade_date(self) -> None:
        payload = {
            "schema": "stock_research_backtest_v2",
            "meta": {
                "latest_recommendation_date": "2026-06-23",
                "active_trade_date": "2026-06-24",
                "latest_closed_trade_date": "2026-06-18",
            },
            "summary": {
                "total_samples": 8,
                "source_samples": 8,
                "filtered_non_backtest_samples": 0,
                "eligible_samples": 4,
                "realtime_candidate_count": 8,
                "realtime_buy_count": 0,
                "realtime_pending_count": 8,
                "realtime_unavailable_count": 0,
            },
            "lifecycle": {
                "stage": "post_close_wait_auction",
                "quote_state": "missing",
            },
            "realtimeBuy": {"trade_date": "2026-06-24"},
            "currentPoolRecords": [{"code": "000001"} for _ in range(8)],
            "displayRecords": [{"code": "000001"}],
            "historicalSnapshots": [],
            "records": [{"code": "000001"}],
        }

        self.assertFalse(
            web_bundle._is_fresh_stock_research_backtest(
                payload,
                latest_source_snapshot={
                    "trade_date": "2026-06-24",
                    "recommendation_date": "2026-06-23",
                    "rows_count": 8,
                },
            )
        )

    def test_fresh_backtest_allows_waiting_trade_day_when_closed_day_matches_latest_recommendation(self) -> None:
        payload = {
            "schema": "stock_research_backtest_v2",
            "meta": {
                "latest_recommendation_date": "2026-06-25",
                "active_trade_date": "2026-06-26",
                "latest_closed_trade_date": "2026-06-25",
            },
            "summary": {
                "total_samples": 8,
                "source_samples": 8,
                "filtered_non_backtest_samples": 0,
                "eligible_samples": 4,
                "realtime_candidate_count": 8,
                "realtime_buy_count": 0,
                "realtime_pending_count": 8,
                "realtime_unavailable_count": 0,
            },
            "lifecycle": {
                "stage": "post_close_wait_auction",
                "quote_state": "waiting_trade_day",
            },
            "realtimeBuy": {"trade_date": "2026-06-26", "reference_date": "2026-06-25"},
            "currentPoolRecords": [
                {"code": "000001", "placement_label": "接力候选", "relay_rank": 1, "watch_rank": 0}
                for _ in range(8)
            ],
            "displayRecords": [{"code": "000001", "date10": "2026-06-24", "trade_date10": "2026-06-25"}],
            "historicalSnapshots": [{"reference_date": "2026-06-24", "trade_date": "2026-06-25"}],
            "records": [{"code": "000001", "date10": "2026-06-24", "trade_date10": "2026-06-25"}],
        }

        self.assertTrue(
            web_bundle._is_fresh_stock_research_backtest(
                payload,
                latest_source_snapshot={
                    "trade_date": "2026-06-26",
                    "recommendation_date": "2026-06-25",
                    "rows_count": 8,
                },
            )
        )

    def test_publish_missing_payload_is_not_fresh_when_same_day_snapshot_is_already_ready(self) -> None:
        payload = {
            "schema": "stock_research_backtest_v2",
            "meta": {
                "latest_recommendation_date": "2026-06-24",
                "active_trade_date": "2026-06-25",
                "latest_closed_trade_date": "2026-06-25",
            },
            "summary": {
                "total_samples": 10,
                "source_samples": 10,
                "filtered_non_backtest_samples": 0,
                "eligible_samples": 10,
                "realtime_candidate_count": 10,
                "realtime_buy_count": 0,
                "realtime_pending_count": 0,
                "realtime_unavailable_count": 10,
            },
            "lifecycle": {
                "stage": "auction_snapshot_missing",
                "quote_state": "missing",
            },
            "realtimeBuy": {
                "trade_date": "2026-06-25",
                "reference_date": "2026-06-24",
                "candidate_count": 10,
                "quoted_count": 0,
                "quote_time": "",
                "diagnostics": {"source": "unavailable"},
            },
            "currentPoolRecords": [
                {"code": "000001", "placement_label": "接力候选", "relay_rank": 1, "watch_rank": 0}
                for _ in range(10)
            ],
            "displayRecords": [{"code": "000001"}],
            "historicalSnapshots": [],
            "records": [{"code": "000001"}],
        }

        with patch.object(
            web_bundle,
            "ROOT",
            Path("/tmp/quant-review-test"),
        ), patch(
            "daily_review.application.workflow_schedule.resolve_auction_snapshot_prefetch_plan",
            return_value={
                "trade_date10": "2026-06-25",
                "should_prefetch": False,
                "status": "auction_snapshot_ready_skip",
                "ready_source": "prefetched_snapshot",
            },
        ):
            self.assertFalse(
                web_bundle._is_fresh_stock_research_backtest(
                    payload,
                    latest_source_snapshot={
                        "trade_date": "2026-06-25",
                        "recommendation_date": "2026-06-24",
                        "rows_count": 10,
                    },
                )
            )


class TradeDateResolveTest(unittest.TestCase):
    def test_after_close_today_keeps_today_even_if_kline_list_lags(self) -> None:
        client = object()
        fake_datetime_cls = type(
            "FakeDateTime",
            (),
            {
                "now": staticmethod(lambda: real_datetime(2026, 6, 19, 17, 2, 0)),
                "strptime": staticmethod(real_datetime.strptime),
            },
        )
        fake_dt_module = type("FakeDtModule", (), {"datetime": fake_datetime_cls})
        with patch.object(biying, "_dt", fake_dt_module), patch.object(
            biying, "get_recent_trade_dates", return_value=["2026-06-17", "2026-06-18"]
        ), patch.object(biying, "get_realtime_market_date", return_value="2026-06-19"):
            actual, note = biying.resolve_trade_date(client, "2026-06-19")

        self.assertEqual(actual, "2026-06-19")
        self.assertIn("收盘后模式", note)


if __name__ == "__main__":
    unittest.main()
