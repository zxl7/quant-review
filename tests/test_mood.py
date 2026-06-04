#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from daily_review.metrics.mood import rebuild_mood


class MoodDualTrackTest(unittest.TestCase):
    def test_rebuild_mood_keeps_market_score_but_restores_shortline_judgment(self) -> None:
        patch = rebuild_mood(
            {
                "fb_rate": 74.5,
                "jj_rate": 33.0,
                "zt_count": 120,
                "zt_early_ratio": 53.0,
                "zb_rate": 25.5,
                "dt_count": 21,
                "bf_count": 24,
                "loss": 45,
                "zb_high_ratio": 0.0,
                "broken_lb_rate": 67.0,
                "avg_zt_zbc": 2.0,
                "zt_zbc_ge3_ratio": 13.0,
                "yest_zt_avg_chg": -1.5,
                "rate_2to3": 20.0,
                "rate_3to4": 100.0,
                "max_lb": 4,
                "second_lb": 4,
                "yest_2b_count": 5,
                "succ_2to3": 1,
                "yest_3b_count": 2,
                "succ_3to4": 2,
                "smallcap_ratio": 38.0,
                "smallcap_cnt": 46,
                "zb_high_count": 0,
                "zb_count": 41,
                "zt_early_count": 64,
            },
            {
                "indices": [
                    {"name": "上证指数", "chg": "+0.43%", "price": 4050, "ma5": 4020, "ma20": 3980},
                    {"name": "深证成指", "chg": "+1.63%", "price": 15300, "ma5": 15020, "ma20": 14980},
                    {"name": "创业板指", "chg": "+2.66%", "price": 3950, "ma5": 3880, "ma20": 3800},
                ],
                "volume": {"change": "+8.0%"},
                "coreTideSignal": {"marketRegime": {"breadth_score": 62}},
            },
        )

        mood = patch["mood"]
        self.assertEqual(mood["short_score"], 48)
        self.assertGreater(mood["market_score"], mood["short_score"])
        self.assertEqual(mood["score"], 48)
        self.assertEqual(mood["overall_score"], 48)
        self.assertEqual(mood["market_tone"], "good")
        self.assertEqual(mood["market_label"], "大盘偏强")


if __name__ == "__main__":
    unittest.main()
