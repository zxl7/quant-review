#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.build_stock_research_backtest as backtest


class StockResearchBacktestRowsTest(unittest.TestCase):
    def test_pool_is_augmented_with_missing_eod_market_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            pool_path = cache_dir / "stock_research_backtest_pool.json"
            pool_path.write_text(
                json.dumps(
                    {
                        "schema": "stock_research_backtest_pool_v1",
                        "days": {
                            "2026-06-02": {
                                "source_market_data": "market_data-20260602.json",
                                "relay": [{"date": "20260602", "date10": "2026-06-02", "bucket": "relay", "code": "000001", "name": "昨天接力", "score": 80}],
                                "watch": [{"date": "20260602", "date10": "2026-06-02", "bucket": "watch", "code": "000002", "name": "昨天观察", "score": 70}],
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (cache_dir / "market_data-20260603.json").write_text(
                json.dumps(
                    {
                        "date": "2026-06-03",
                        "meta": {"mode": "eod"},
                        "ztAnalysis": {
                            "relay": [{"code": "000003", "name": "今天接力", "factorScore": 90}],
                            "watch": [{"code": "000004", "name": "今天观察", "factorScore": 60}],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (cache_dir / "market_data-20260604-intraday.json").write_text(
                json.dumps(
                    {
                        "date": "2026-06-04",
                        "meta": {"mode": "intraday"},
                        "ztAnalysis": {"relay": [{"code": "000005", "name": "盘中样本", "factorScore": 99}], "watch": []},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(backtest, "CACHE_DIR", cache_dir), patch.object(backtest, "BACKTEST_POOL", pool_path):
                rows, sources = backtest._load_stock_research_rows()

        by_date = {row["date10"] for row in rows}
        latest_rows = [row for row in rows if row["date10"] == "2026-06-03"]

        self.assertEqual(by_date, {"2026-06-02", "2026-06-03"})
        self.assertEqual([row["name"] for row in latest_rows], ["今天接力", "今天观察"])
        self.assertEqual(sources, ["market_data-20260602.json", "market_data-20260603.json"])


if __name__ == "__main__":
    unittest.main()
