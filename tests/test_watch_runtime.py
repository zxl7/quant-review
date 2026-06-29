#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import daily_review.watch_runtime as watch_runtime


class WatchRuntimeTest(unittest.TestCase):
    def test_write_intraday_runtime_includes_required_indices_and_asof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cache").mkdir()
            (root / "web" / "public").mkdir(parents=True)
            (root / "web" / "dist").mkdir(parents=True)
            (root / "cache" / "market_data-20260629.json").write_text(
                json.dumps(
                    {
                        "date": "2026-06-29",
                        "meta": {"asOf": {"indices": "09:36:00"}},
                        "indices": [
                            {"name": "上证指数", "code": "000001.SH", "val": "3400.01", "chg": "+0.10%"},
                            {"name": "深证成指", "code": "399001.SZ", "val": "10100.22", "chg": "-0.20%"},
                            {"name": "创业板指", "code": "399006.SZ", "val": "2010.33", "chg": "+0.30%"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = watch_runtime.write_intraday_runtime(
                root=root,
                snapshot={
                    "date": "2026-06-29",
                    "ts_bj": "2026-06-29 09:36:00",
                    "source": "intraday_live",
                    "market": {"zt": 10, "dt": 1, "zab": 2, "zab_rate": 16.7, "lianban": 3, "max_lianban": 2, "amount": "1234亿"},
                    "alerts": [],
                    "concepts": [],
                },
                envelope={"latest": {"time": "09:36:00"}, "snapshots": [{"time": "09:36:00"}]},
            )

        self.assertEqual(payload["asOf"]["indices"], "09:36:00")
        self.assertEqual([row["name"] for row in payload["indices"]], ["上证指数", "深证成指", "创业板指"])


if __name__ == "__main__":
    unittest.main()
