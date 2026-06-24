#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daily_review.application import fetch_service


class UpdateIndexKlineCacheTest(unittest.TestCase):
    def test_update_index_kline_cache_uses_shorter_lookback_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cache").mkdir()
            calls: list[tuple[str, str, str]] = []

            def fake_fetch(client, *, code: str, st: str, et: str):
                calls.append((code, st, et))
                return []

            with patch.object(fetch_service, "fetch_index_history_k", side_effect=fake_fetch):
                fetch_service.update_index_kline_cache(root=root, client=object(), actual_date="2026-06-23")

        self.assertEqual(len(calls), 3)
        for _, st, et in calls:
            self.assertEqual(st, "20260603")
            self.assertEqual(et, "20260623")
        self.assertEqual({code for code, _, _ in calls}, {"000001.SH", "399001.SZ", "399006.SZ"})

    def test_update_index_kline_cache_skips_malformed_numeric_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cache").mkdir()

            mocked_rows = [
                {"t": "2026-06-09", "sf": "", "a": "--", "v": "123"},
                {"t": "2026-06-09", "sf": None, "a": "1000", "v": None},
                {"t": "2026-06-09", "sf": "0", "a": "2000", "v": "3000", "c": "10", "pc": "9.8"},
                {"t": "2026-06-08", "sf": "1", "a": "2000", "v": "3000"},
            ]

            with patch.object(fetch_service, "fetch_index_history_k", return_value=mocked_rows):
                result = fetch_service.update_index_kline_cache(root=root, client=object(), actual_date="2026-06-09")

        for code in ("000001.SH", "399001.SZ", "399006.SZ"):
            items = (result.get(code) or {}).get("items") or []
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["a"], "2000")
            self.assertEqual(items[0]["v"], "3000")

    def test_update_index_kline_cache_keeps_only_latest_10_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cache").mkdir()
            mocked_rows = [
                {"t": f"2026-06-{day:02d}", "sf": "0", "a": "2000", "v": "3000", "c": str(day), "pc": "1.0"}
                for day in range(1, 16)
            ]

            with patch.object(fetch_service, "fetch_index_history_k", return_value=mocked_rows):
                result = fetch_service.update_index_kline_cache(root=root, client=object(), actual_date="2026-06-23")

        items = (result.get("000001.SH") or {}).get("items") or []
        self.assertEqual(len(items), 10)
        self.assertEqual(items[0]["t"], "2026-06-06")
        self.assertEqual(items[-1]["t"], "2026-06-15")

    def test_update_index_kline_cache_falls_back_to_existing_cache_on_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            cached_payload = {
                "version": 1,
                "codes": {
                    "000001.SH": {"as_of": "2026-06-22", "items": [{"t": "2026-06-22", "c": "10", "pc": "1.2"}]},
                    "399001.SZ": {"as_of": "2026-06-22", "items": [{"t": "2026-06-22", "c": "11", "pc": "1.3"}]},
                    "399006.SZ": {"as_of": "2026-06-22", "items": [{"t": "2026-06-22", "c": "12", "pc": "1.4"}]},
                },
            }
            (cache_dir / "index_kline_cache.json").write_text(
                json.dumps(cached_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            with patch.object(fetch_service, "fetch_index_history_k", side_effect=TimeoutError("timed out")):
                result = fetch_service.update_index_kline_cache(root=root, client=object(), actual_date="2026-06-23")

        self.assertEqual(result["000001.SH"]["as_of"], "2026-06-22")
        self.assertEqual(result["399001.SZ"]["items"][0]["c"], "11")
        self.assertEqual(result["399006.SZ"]["items"][0]["pc"], "1.4")


class BuildBaseMarketDataTest(unittest.TestCase):
    def test_build_base_market_data_backfills_missing_report_index_from_realtime(self) -> None:
        market_data = fetch_service.build_base_market_data(
            actual_date="2026-06-24",
            date_note="trade_day",
            indices_asof="14:26:01",
            generated_at="2026-06-24 14:26:01",
            indices_for_report=[
                {"name": "深证成指", "code": "399001.SZ", "val": "10888.12", "chg": "-0.23%"},
                {"name": "创业板指", "code": "399006.SZ", "val": "2211.09", "chg": "+1.02%"},
            ],
            indices_rt=[
                {"name": "上证指数", "code": "000001.SH", "val": 3501.23, "chg": 0.56, "cje": 123456789},
                {"name": "深证成指", "code": "399001.SZ", "val": 10888.12, "chg": -0.23, "cje": 223456789},
                {"name": "创业板指", "code": "399006.SZ", "val": 2211.09, "chg": 1.02, "cje": 323456789},
            ],
            raw_pools={},
            codes_map={},
            codes_entry={},
            theme_trend_by_day={},
        )

        self.assertEqual([row["name"] for row in market_data["indices"]], ["深证成指", "创业板指", "上证指数"])
        self.assertEqual(market_data["indices"][-1]["code"], "000001.SH")
        self.assertEqual(market_data["indices"][-1]["val"], "3501.23")


if __name__ == "__main__":
    unittest.main()
