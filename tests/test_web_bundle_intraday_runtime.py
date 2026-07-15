#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daily_review.publish.web_bundle as web_bundle
from daily_review.publish.web_bundle import _build_intraday_runtime_payload_from_market_data


class WebBundleIntradayRuntimeTest(unittest.TestCase):
    def test_intraday_runtime_payload_includes_indices_and_asof(self) -> None:
        payload = json.loads(
            _build_intraday_runtime_payload_from_market_data(
                {
                    "date": "2026-06-24",
                    "meta": {"asOf": {"indices": "14:26:01"}},
                    "indices": [
                        {"name": "上证指数", "code": "000001.SH", "val": "3501.23", "chg": "+0.56%"},
                        {"name": "深证成指", "code": "399001.SZ", "val": "10888.12", "chg": "-0.23%"},
                        {"name": "创业板指", "code": "399006.SZ", "val": "2211.09", "chg": "+1.02%"},
                        {"name": "中证1000", "code": "000852.SH", "val": "9999.99", "chg": "+0.10%"},
                    ],
                    "intradaySnapshots": {
                        "updated_at": "2026-06-24 14:26:01",
                        "latest": {
                            "date": "2026-06-24",
                            "ts_bj": "2026-06-24 14:26:01",
                            "provider": "fetch",
                            "zt": 55,
                        },
                        "snapshots": [{"date": "2026-06-24", "ts_bj": "2026-06-24 14:26:01", "zt": 55}],
                    },
                    "live": {"market": {"zt": 55}, "alerts": [], "concepts": []},
                }
            )
        )

        self.assertEqual(payload["date"], "2026-06-24")
        self.assertEqual(payload["asOf"]["indices"], "14:26:01")
        self.assertEqual([row["name"] for row in payload["indices"]], ["上证指数", "深证成指", "创业板指"])
        self.assertEqual(payload["indices"][0]["chg"], "+0.56%")

    def test_prefers_valid_canonical_runtime_over_full_review_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "web" / "public" / "intraday_runtime.json"
            runtime.parent.mkdir(parents=True)
            runtime.write_text(
                json.dumps(
                    {
                        "date": "2026-06-24",
                        "latest": {"ts_bj": "2026-06-24 14:30:00", "time": "14:30:00", "zt": 55, "lianban": 8, "max_lb": 4},
                        "snapshots": [{"ts_bj": "2026-06-24 14:30:00", "time": "14:30:00", "zt": 55, "lianban": 8, "max_lb": 4}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch.object(web_bundle, "ROOT", root):
                payload = json.loads(web_bundle._preferred_intraday_runtime_payload({"date": "2026-06-24", "intradaySnapshots": {}}))

        self.assertEqual(payload["latest"]["zt"], 55)


if __name__ == "__main__":
    unittest.main()
