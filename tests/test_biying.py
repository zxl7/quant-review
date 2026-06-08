#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest
from unittest.mock import patch

from daily_review.data.biying import extract_money_flow_day_map, fetch_indices_realtime


class MoneyFlowMapTest(unittest.TestCase):
    def test_extract_money_flow_day_map_from_transaction_rows(self) -> None:
        rows = [
            {
                "t": "2026-06-02 15:00:00",
                "zmbtdcje": 230000000,
                "zmbddcje": 70000000,
                "zmstdcje": 110000000,
                "zmsddcje": 40000000,
            },
            {
                "date": "20260603",
                "zmbtdcje": "100000000",
                "zmbddcje": "20000000",
                "zmstdcje": "50000000",
                "zmsddcje": "10000000",
            },
        ]

        self.assertEqual(
            extract_money_flow_day_map(rows),
            {
                "20260602": 1.5,
                "20260603": 0.6,
            },
        )


class FetchIndicesRealtimeTest(unittest.TestCase):
    def test_fetch_indices_realtime_degrades_when_one_index_request_fails(self) -> None:
        class FakeClient:
            base_url = "https://example.test"
            token = "token"

            def __init__(self) -> None:
                self.calls = 0

            def get_json(self, url: str) -> dict:
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("network down")
                return {
                    "t": "2026-06-08 14:30:01",
                    "p": 3500.0,
                    "yc": 3450.0,
                    "cje": 123456789,
                }

        with patch("daily_review.data.biying._dt.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "09:30:00"
            client = FakeClient()
            rows, as_of = fetch_indices_realtime(
                client,
                codes=[("000001.SH", "上证指数"), ("399001.SZ", "深证成指")],
            )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["name"], "上证指数")
        self.assertEqual(rows[0]["val"], 0.0)
        self.assertEqual(rows[0]["chg"], 0.0)
        self.assertEqual(rows[1]["name"], "深证成指")
        self.assertEqual(rows[1]["val"], 3500.0)
        self.assertEqual(as_of, "14:30:01")


if __name__ == "__main__":
    unittest.main()
