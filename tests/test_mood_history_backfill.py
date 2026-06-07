#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from daily_review.cli import _inject_mood_history_and_delta


class MoodHistoryBackfillTest(unittest.TestCase):
    def test_backfills_fb_and_jj_from_legacy_snapshot_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_dir = root / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)

            legacy_rows = [
                (
                    "20260604",
                    {
                        "panorama": {"limitUp": 80, "limitDown": 7, "ratio": "80.8%"},
                        "marketPanorama": {"kpis": {"link_board": 10, "zb_rate": 19.2}},
                        "actionSheet": {"keyNumbers": {"fb": 80.8, "jj": 36.4}},
                        "ladder": [{"badge": "4板"}],
                    },
                ),
                (
                    "20260605",
                    {
                        "panorama": {"limitUp": 73, "limitDown": 11, "ratio": "58.4%"},
                        "marketPanorama": {"kpis": {"link_board": 6, "zb_rate": 41.6}},
                        "actionSheet": {"keyNumbers": {"fb": 58.4, "jj": 20.0}},
                        "ladder": [{"badge": "5板"}],
                    },
                ),
            ]

            for date8, payload in legacy_rows:
                (cache_dir / f"market_data-{date8}.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            market_data = {}
            _inject_mood_history_and_delta(root=root, date="2026-06-05", market_data=market_data)

            mood_inputs = ((market_data.get("features") or {}).get("mood_inputs") or {})
            self.assertEqual(mood_inputs.get("hist_days"), ["2026-06-04", "2026-06-05"])
            self.assertEqual(mood_inputs.get("hist_fb_rate"), [80.8, 58.4])
            self.assertEqual(mood_inputs.get("hist_jj_rate"), [36.4, 20.0])
            self.assertEqual(mood_inputs.get("hist_zb_rate"), [19.2, 41.6])
            self.assertEqual(mood_inputs.get("hist_lianban"), [10, 6])


if __name__ == "__main__":
    unittest.main()
