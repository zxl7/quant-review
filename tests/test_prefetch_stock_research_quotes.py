#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts import prefetch_stock_research_quotes as prefetch


TZ_BJ = timezone(timedelta(hours=8))


class PrefetchStockResearchQuotesTest(unittest.TestCase):
    def test_build_prefetch_execution_plan_skips_when_today_snapshot_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            (cache_dir / "stock_research_realtime_quotes-20260623.json").write_text(
                """
                {
                  "schema": "stock_research_realtime_quotes_v1",
                  "date": "2026-06-23",
                  "as_of": "2026-06-24 09:25:02",
                  "source": "workflow_prefetch",
                  "count": 1,
                  "items": {"000001": {"dm": "000001", "t": "2026-06-24 09:25:02"}}
                }
                """.strip(),
                encoding="utf-8",
            )
            fake_rows = [{"date10": "2026-06-23", "code": "000001"}]

            with patch.object(prefetch, "_load_stock_research_rows", return_value=(fake_rows, {})):
                plan = prefetch.build_prefetch_execution_plan(trade_date10="2026-06-24", cache_dir=cache_dir)

        self.assertFalse(plan["should_prefetch"])
        self.assertEqual(plan["status"], "auction_snapshot_ready_skip")
        self.assertEqual(plan["ready_source"], "prefetched_snapshot")
        self.assertEqual(plan["reference_date"], "2026-06-23")
        self.assertEqual(plan["codes"], ["000001"])

    def test_main_skips_when_today_snapshot_already_ready(self) -> None:
        fake_rows = [{"date10": "2026-06-23", "code": "000001"}]
        fake_plan = {
            "trade_date10": "2026-06-24",
            "should_prefetch": False,
            "status": "auction_snapshot_ready_skip",
            "ready_source": "prefetched_snapshot",
            "prefetched_snapshot": {"found": True},
            "market_data_snapshot": {"found": False},
            "has_rows": True,
            "reference_date": "2026-06-23",
            "codes": ["000001"],
            "codes_count": 1,
        }
        with patch.object(prefetch, "_now_bj", return_value=datetime(2026, 6, 24, 9, 25, 1, tzinfo=TZ_BJ)), patch.object(
            prefetch, "_load_stock_research_rows", return_value=(fake_rows, {})
        ), patch.object(
            prefetch, "build_prefetch_execution_plan", return_value=fake_plan
        ), patch.object(prefetch, "_fetch_and_save_snapshot") as mock_fetch, patch("builtins.print") as mock_print:
            rc = prefetch.main(["--date", "2026-06-24", "--must-succeed"])

        self.assertEqual(rc, 0)
        mock_fetch.assert_not_called()
        self.assertTrue(
            any("auction_snapshot_ready_skip" in str(call.args[0]) for call in mock_print.call_args_list if call.args)
        )

    def test_outside_window_without_must_succeed_still_skips(self) -> None:
        fake_rows = [{"date10": "2026-06-23", "code": "000001"}]
        with patch.object(prefetch, "_now_bj", return_value=datetime(2026, 6, 24, 9, 34, 0, tzinfo=TZ_BJ)), patch.object(
            prefetch, "_load_stock_research_rows", return_value=(fake_rows, {})
        ), patch.object(prefetch, "_fetch_and_save_snapshot") as mock_fetch, patch(
            "builtins.print"
        ) as mock_print:
            rc = prefetch.main(["--date", "2026-06-24"])

        self.assertEqual(rc, 0)
        mock_fetch.assert_not_called()
        self.assertTrue(any("outside 09:25-09:30 window" in str(call.args[0]) for call in mock_print.call_args_list if call.args))

    def test_outside_window_must_succeed_uses_forced_query_fallback(self) -> None:
        fake_rows = [{"date10": "2026-06-23", "code": "000001"}]
        fake_path = Path("/tmp/stock_research_realtime_quotes-20260623.json")
        with patch.object(prefetch, "_now_bj", return_value=datetime(2026, 6, 24, 9, 34, 0, tzinfo=TZ_BJ)), patch.object(
            prefetch, "_load_stock_research_rows", return_value=(fake_rows, {})
        ), patch.object(
            prefetch,
            "_fetch_and_save_snapshot",
            return_value=(fake_path, {"attempts": 2, "as_of": "2026-06-24 09:34:01", "last_error": ""}),
        ) as mock_fetch, patch("builtins.print") as mock_print:
            rc = prefetch.main(["--date", "2026-06-24", "--must-succeed"])

        self.assertEqual(rc, 0)
        mock_fetch.assert_called_once_with(
            reference_date="2026-06-23",
            codes=["000001"],
            source="forced_query",
        )
        self.assertTrue(
            any("mode=forced_query" in str(call.args[0]) for call in mock_print.call_args_list if call.args)
        )

    def test_entry_window_retries_once_then_succeeds(self) -> None:
        fake_rows = [{"date10": "2026-06-23", "code": "000001"}]
        fake_path = Path("/tmp/stock_research_realtime_quotes-20260623.json")
        with patch.object(prefetch, "_now_bj", return_value=datetime(2026, 6, 24, 9, 25, 1, tzinfo=TZ_BJ)), patch.object(
            prefetch, "_load_stock_research_rows", return_value=(fake_rows, {})
        ), patch.object(
            prefetch,
            "_fetch_and_save_snapshot",
            return_value=(fake_path, {"attempts": 2, "as_of": "2026-06-24 09:25:03", "last_error": "URLError: boom"}),
        ) as mock_fetch, patch("builtins.print") as mock_print:
            rc = prefetch.main(["--date", "2026-06-24", "--must-succeed"])

        self.assertEqual(rc, 0)
        self.assertEqual(mock_fetch.call_count, 1)
        self.assertTrue(any("attempts=2" in str(call.args[0]) for call in mock_print.call_args_list if call.args))

    def test_forced_query_retries_once_then_succeeds(self) -> None:
        fake_rows = [{"date10": "2026-06-23", "code": "000001"}]
        fake_path = Path("/tmp/stock_research_realtime_quotes-20260623.json")
        with patch.object(prefetch, "_now_bj", return_value=datetime(2026, 6, 24, 9, 34, 0, tzinfo=TZ_BJ)), patch.object(
            prefetch, "_load_stock_research_rows", return_value=(fake_rows, {})
        ), patch.object(
            prefetch,
            "_fetch_and_save_snapshot",
            return_value=(fake_path, {"attempts": 2, "as_of": "2026-06-24 09:34:03", "last_error": "TimeoutError: timeout"}),
        ) as mock_fetch, patch("builtins.print") as mock_print:
            rc = prefetch.main(["--date", "2026-06-24", "--must-succeed"])

        self.assertEqual(rc, 0)
        self.assertEqual(mock_fetch.call_count, 1)
        self.assertTrue(any("mode=forced_query" in str(call.args[0]) for call in mock_print.call_args_list if call.args))

    def test_forced_query_returns_nonzero_after_all_attempts_fail(self) -> None:
        fake_rows = [{"date10": "2026-06-23", "code": "000001"}]
        with patch.object(prefetch, "_now_bj", return_value=datetime(2026, 6, 24, 9, 34, 0, tzinfo=TZ_BJ)), patch.object(
            prefetch, "_load_stock_research_rows", return_value=(fake_rows, {})
        ), patch.object(
            prefetch,
            "_fetch_and_save_snapshot",
            side_effect=[
                (None, {"attempts": 2, "as_of": "", "last_error": "TimeoutError: timeout"}),
                (None, {"attempts": 2, "as_of": "", "last_error": "TimeoutError: timeout"}),
            ],
        ), patch("builtins.print") as mock_print:
            rc = prefetch.main(["--date", "2026-06-24", "--must-succeed"])

        self.assertEqual(rc, 2)
        self.assertTrue(any("last_error=TimeoutError: timeout" in str(call.args[0]) for call in mock_print.call_args_list if call.args))

    def test_entry_window_uses_workflow_prefetch_source(self) -> None:
        fake_rows = [{"date10": "2026-06-23", "code": "000001"}]
        fake_path = Path("/tmp/stock_research_realtime_quotes-20260623.json")
        with patch.object(prefetch, "_now_bj", return_value=datetime(2026, 6, 24, 9, 25, 1, tzinfo=TZ_BJ)), patch.object(
            prefetch, "_load_stock_research_rows", return_value=(fake_rows, {})
        ), patch.object(
            prefetch,
            "_fetch_and_save_snapshot",
            return_value=(fake_path, {"attempts": 1, "as_of": "2026-06-24 09:25:01", "last_error": ""}),
        ) as mock_fetch:
            rc = prefetch.main(["--date", "2026-06-24", "--must-succeed"])

        self.assertEqual(rc, 0)
        mock_fetch.assert_called_once_with(
            reference_date="2026-06-23",
            codes=["000001"],
            source="workflow_prefetch",
        )

    def test_fetch_and_save_snapshot_persists_forced_query_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            saved_path = Path(tmp) / "stock_research_realtime_quotes-20260623.json"
            with patch.object(
                prefetch,
                "load_config_from_env",
                return_value=type("Cfg", (), {"base_url": "https://example.test", "token": "token"})(),
            ), patch.object(
                prefetch, "HttpClient", return_value=object()
            ) as mock_client, patch.object(
                prefetch,
                "fetch_stocks_realtime_map",
                return_value=({"000001": {"dm": "000001", "t": "2026-06-24 09:34:01"}}, "2026-06-24 09:34:01"),
            ), patch.object(
                prefetch, "save_prefetched_realtime_quotes", return_value=saved_path
            ) as mock_save:
                path = prefetch._fetch_and_save_snapshot(
                    reference_date="2026-06-23",
                    codes=["000001"],
                    source="forced_query",
                )

        self.assertEqual(path[0], saved_path)
        mock_client.assert_called_once()
        mock_save.assert_called_once_with(
            date10="2026-06-23",
            items={"000001": {"dm": "000001", "t": "2026-06-24 09:34:01"}},
            as_of="2026-06-24 09:34:01",
            source="forced_query",
        )

    def test_fetch_and_save_snapshot_retries_after_single_network_failure(self) -> None:
        with patch.object(
            prefetch,
            "load_config_from_env",
            return_value=type("Cfg", (), {"base_url": "https://example.test", "token": "token"})(),
        ), patch.object(
            prefetch, "save_prefetched_realtime_quotes", return_value=Path("/tmp/recovered.json")
        ), patch.object(
            prefetch,
            "fetch_stocks_realtime_map",
            side_effect=[
                urllib.error.URLError("boom"),
                ({"000001": {"dm": "000001", "t": "2026-06-24 09:25:03"}}, "2026-06-24 09:25:03"),
            ],
        ):
            path, diag = prefetch._fetch_and_save_snapshot(reference_date="2026-06-23", codes=["000001"], source="workflow_prefetch")

        self.assertEqual(path, Path("/tmp/recovered.json"))
        self.assertEqual(diag["attempts"], 2)
        self.assertEqual(diag["as_of"], "2026-06-24 09:25:03")


if __name__ == "__main__":
    unittest.main()
