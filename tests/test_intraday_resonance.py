#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from daily_review.metrics.intraday_resonance import detect_resonance_from_cache


def _event_stock(event_id: int, ts: int, symbol: str, name: str, sector: str, pcp: float) -> dict:
    return {
        "id": event_id,
        "target": symbol,
        "event_type": 10009,
        "event_timestamp": ts,
        "stock_abnormal_event_data": {
            "symbol": symbol,
            "name": name,
            "pcp": pcp,
            "related_plates": [{"plate_name": sector}],
        },
        "plate_abnormal_event_data": {},
    }


def _event_plate(event_id: int, ts: int, sector: str, pcp: float) -> dict:
    return {
        "id": event_id,
        "target": sector,
        "event_type": 11000,
        "event_timestamp": ts,
        "stock_abnormal_event_data": {},
        "plate_abnormal_event_data": {
            "plate_name": sector,
            "pcp": pcp,
        },
    }


class IntradayResonanceTest(unittest.TestCase):
    def _write_cache(self, root: Path, date8: str, events: list[dict]) -> None:
        path = root / "cache_online" / f"xuangubao_abnormal-{date8}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "runs": [
                {
                    "combined": {
                        "data": {
                            "data": events,
                        }
                    }
                }
            ]
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_requires_plate_plus_two_unique_stocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            date8 = "20260604"
            self._write_cache(
                root,
                date8,
                [
                    _event_plate(1, 1000, "电力", 0.023),
                    _event_stock(2, 1010, "000001.SZ", "平安银行", "电力", 0.041),
                    _event_stock(3, 1020, "000002.SZ", "万科A", "电力", 0.052),
                ],
            )

            rows = detect_resonance_from_cache(root, date8)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["sector"], "电力")
            self.assertEqual(rows[0]["count"], 3)
            self.assertEqual(rows[0]["valueText"], "+2.30%")
            self.assertEqual([x["symbol"] for x in rows[0]["stocks"]], ["000002.SZ", "000001.SZ"])

    def test_duplicate_stock_events_do_not_fake_resonance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            date8 = "20260604"
            self._write_cache(
                root,
                date8,
                [
                    _event_plate(1, 1000, "机器人", 0.018),
                    _event_stock(2, 1010, "300001.SZ", "特锐德", "机器人", 0.031),
                    _event_stock(3, 1020, "300001.SZ", "特锐德", "机器人", 0.038),
                ],
            )

            rows = detect_resonance_from_cache(root, date8)

            self.assertEqual(rows, [])

    def test_stock_only_burst_is_not_resonance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            date8 = "20260604"
            self._write_cache(
                root,
                date8,
                [
                    _event_stock(1, 1000, "600000.SH", "浦发银行", "算力", 0.021),
                    _event_stock(2, 1010, "600004.SH", "白云机场", "算力", 0.028),
                    _event_stock(3, 1020, "600009.SH", "上海机场", "算力", 0.035),
                ],
            )

            rows = detect_resonance_from_cache(root, date8)

            self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
