#!/usr/bin/env python3

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from daily_review import realtime_watch


class RealtimeWatchTest(unittest.TestCase):
    def test_partial_snapshot_keeps_failed_auxiliary_rate_unknown(self) -> None:
        partial_market = {
            "quality": "partial",
            "zt": 18,
            "dt": 2,
            "zab": None,
            "zab_rate": None,
            "lianban": 6,
            "max_lianban": 3,
            "amount": "",
            "pool_status": {"ztgc": "valid", "dtgc": "valid", "zbgc": "failed"},
            "pool_errors": {"zbgc": "empty_response"},
            "indices": [],
            "indices_as_of": "",
        }
        with (
            patch("daily_review.realtime_watch._now_bj", return_value=datetime(2026, 7, 28, 14, 15, tzinfo=realtime_watch.BJ_TZ)),
            patch("daily_review.realtime_watch._read_local_cache", return_value=None),
            patch("daily_review.realtime_watch._market_from_biying", return_value=partial_market),
            patch("daily_review.realtime_watch._concepts_from_biying", return_value=[]),
        ):
            snapshot = realtime_watch.build_live_snapshot("20260728", intraday=True).to_dict()

        self.assertEqual(snapshot["health"]["status"], "partial")
        self.assertEqual(snapshot["market"]["zt"], 18)
        self.assertIsNone(snapshot["market"]["zab"])
        self.assertIsNone(snapshot["market"]["zab_rate"])
        self.assertIn("盘中三池响应不完整", snapshot["alerts"][-2]["text"])

    def test_partial_snapshot_keeps_failed_core_pool_unknown(self) -> None:
        partial_market = {
            "quality": "partial", "zt": None, "dt": 2, "zab": 4,
            "zab_rate": None, "lianban": None, "max_lianban": None, "amount": "",
            "pool_status": {"ztgc": "failed", "dtgc": "valid", "zbgc": "valid"},
            "pool_errors": {"ztgc": "timed out"}, "indices": [], "indices_as_of": "",
        }
        with (
            patch("daily_review.realtime_watch._now_bj", return_value=datetime(2026, 7, 31, 14, 15, tzinfo=realtime_watch.BJ_TZ)),
            patch("daily_review.realtime_watch._read_local_cache", return_value=None),
            patch("daily_review.realtime_watch._market_from_biying", return_value=partial_market),
            patch("daily_review.realtime_watch._concepts_from_biying", return_value=[]),
        ):
            snapshot = realtime_watch.build_live_snapshot("20260731", intraday=True).to_dict()

        self.assertIsNone(snapshot["market"]["zt"])
        self.assertIsNone(snapshot["market"]["lianban"])
        self.assertEqual(snapshot["market"]["dt"], 2)


if __name__ == "__main__":
    unittest.main()
