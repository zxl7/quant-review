#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from daily_review.data.biying import extract_money_flow_day_map


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


if __name__ == "__main__":
    unittest.main()
