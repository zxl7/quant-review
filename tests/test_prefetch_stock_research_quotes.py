#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts import prefetch_stock_research_quotes as prefetch


TZ_BJ = timezone(timedelta(hours=8))


class PrefetchStockResearchQuotesTest(unittest.TestCase):
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
            prefetch, "_fetch_and_save_snapshot", return_value=fake_path
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

    def test_entry_window_uses_workflow_prefetch_source(self) -> None:
        fake_rows = [{"date10": "2026-06-23", "code": "000001"}]
        fake_path = Path("/tmp/stock_research_realtime_quotes-20260623.json")
        with patch.object(prefetch, "_now_bj", return_value=datetime(2026, 6, 24, 9, 25, 1, tzinfo=TZ_BJ)), patch.object(
            prefetch, "_load_stock_research_rows", return_value=(fake_rows, {})
        ), patch.object(
            prefetch, "_fetch_and_save_snapshot", return_value=fake_path
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

        self.assertEqual(path, saved_path)
        mock_client.assert_called_once()
        mock_save.assert_called_once_with(
            date10="2026-06-23",
            items={"000001": {"dm": "000001", "t": "2026-06-24 09:34:01"}},
            as_of="2026-06-24 09:34:01",
            source="forced_query",
        )


if __name__ == "__main__":
    unittest.main()
