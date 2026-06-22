#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from daily_review.application.workflow_schedule import (
    SCHEDULE_MODE_BY_CRON,
    describe_prefetched_quotes_snapshot,
    resolve_publish_schedule_mode,
    resolve_stock_research_query_plan,
    validate_market_data_stock_research_snapshot,
)


TZ_BJ = timezone(timedelta(hours=8))


class WorkflowScheduleTest(unittest.TestCase):
    def test_schedule_mapping_covers_every_known_cron(self) -> None:
        fake_now = datetime(2026, 6, 22, 10, 27, tzinfo=TZ_BJ)
        for cron_expr, expected_mode in SCHEDULE_MODE_BY_CRON.items():
            result = resolve_publish_schedule_mode("schedule", cron_expr, now=fake_now)
            self.assertEqual(result["skip"], "false")
            self.assertEqual(result["mode"], expected_mode)

    def test_open_fore_mode_survives_delayed_runner_start(self) -> None:
        delayed_now = datetime(2026, 6, 22, 10, 27, tzinfo=TZ_BJ)
        result = resolve_publish_schedule_mode("schedule", "26 1 * * 1-5", now=delayed_now)
        self.assertEqual(result["mode"], "open_fore")
        self.assertEqual(result["beijing_now"], "10:27")

    def test_query_plan_prefers_prefetched_quotes_cache_before_fore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            (cache_dir / "stock_research_realtime_quotes-20260619.json").write_text(
                json.dumps(
                    {
                        "schema": "stock_research_realtime_quotes_v1",
                        "date": "2026-06-19",
                        "as_of": "2026-06-22 09:25:01",
                        "source": "workflow_prefetch",
                        "count": 1,
                        "items": {"000001": {"dm": "000001", "t": "2026-06-22 09:25:01", "o": 10.1, "p": 10.1, "cje": 10000000}},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            plan = resolve_stock_research_query_plan(
                mode="open_fore",
                trade_date10="2026-06-22",
                is_trade_today=True,
                input_query_tag="",
                cache_dir=cache_dir,
            )

        self.assertEqual(plan["effective_query_tag"], "")
        self.assertEqual(plan["resolution_reason"], "prefetched_quotes_ready")
        self.assertTrue(plan["prefetched_snapshot"]["found"])

    def test_query_plan_falls_back_to_fore_when_snapshot_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()

            plan = resolve_stock_research_query_plan(
                mode="open_fore",
                trade_date10="2026-06-22",
                is_trade_today=True,
                input_query_tag="",
                cache_dir=cache_dir,
            )

        self.assertEqual(plan["effective_query_tag"], "fore")
        self.assertEqual(plan["resolution_reason"], "snapshot_missing_fallback_to_fore")

    def test_describe_prefetched_quotes_snapshot_matches_trade_day_by_as_of(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            (cache_dir / "stock_research_realtime_quotes-20260619.json").write_text(
                json.dumps(
                    {
                        "schema": "stock_research_realtime_quotes_v1",
                        "date": "2026-06-19",
                        "as_of": "2026-06-22 09:25:03",
                        "source": "workflow_prefetch",
                        "count": 1,
                        "items": {"000001": {"dm": "000001", "t": "2026-06-22 09:25:03"}},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            snapshot = describe_prefetched_quotes_snapshot(cache_dir, "2026-06-22")

        self.assertTrue(snapshot["found"])
        self.assertEqual(snapshot["reference_date"], "2026-06-19")
        self.assertEqual(snapshot["as_of"], "2026-06-22 09:25:03")

    def test_validate_market_data_snapshot_requires_quote_time_when_candidates_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            market_path = Path(tmp) / "market_data.json"
            market_path.write_text(
                json.dumps(
                    {
                        "stockResearchBacktest": {
                            "realtimeBuy": {
                                "trade_date": "2026-06-22",
                                "reference_date": "2026-06-19",
                                "candidate_count": 2,
                                "quote_time": "",
                                "diagnostics": {"source": "unavailable"},
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = validate_market_data_stock_research_snapshot(market_path, "2026-06-22")

        self.assertTrue(result["required"])
        self.assertFalse(result["ok"])

    def test_validate_market_data_snapshot_skips_when_no_candidates_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            market_path = Path(tmp) / "market_data.json"
            market_path.write_text(
                json.dumps(
                    {
                        "stockResearchBacktest": {
                            "realtimeBuy": {
                                "trade_date": "2026-06-22",
                                "reference_date": "2026-06-19",
                                "candidate_count": 0,
                                "quote_time": "",
                                "diagnostics": {"source": "unavailable"},
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = validate_market_data_stock_research_snapshot(market_path, "2026-06-22")

        self.assertFalse(result["required"])
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
