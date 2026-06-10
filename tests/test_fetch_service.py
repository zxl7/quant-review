#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daily_review.application import fetch_service


class UpdateIndexKlineCacheTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
