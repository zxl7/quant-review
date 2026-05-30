#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from daily_review.metrics.tide import build_tide_signal


class TideSignalTest(unittest.TestCase):
    def test_ebb_day_three_triggers(self) -> None:
        signal = build_tide_signal(
            market_data={
                "date": "2026-05-29",
                "sentiment": {"score": 56},
                "panorama": {"limitUp": 49, "ratio": "56.3%"},
                "volume": {"total": "33190.32亿"},
                "prev": {
                    "sentiment": {"score": 78},
                    "panorama": {"limitUp": 102, "ratio": "82.9%"},
                    "volume": {"total": "29681.51亿"},
                },
            },
            theme_trend_cache={},
        )

        self.assertTrue(signal["market"]["is_ebb_day"])
        self.assertEqual(signal["market"]["trigger_count"], 3)
        self.assertAlmostEqual(signal["market"]["sentiment_delta"], -22)
        self.assertAlmostEqual(signal["market"]["limit_up_delta_pct"], -51.96, places=2)
        self.assertAlmostEqual(signal["market"]["seal_rate_delta_pct"], -26.6, places=1)

    def test_traverse_candidate_on_ebb_day(self) -> None:
        signal = build_tide_signal(
            market_data={
                "date": "2026-05-29",
                "sentiment": {"score": 50},
                "panorama": {"limitUp": 50, "ratio": "60%"},
                "prev": {
                    "sentiment": {"score": 70},
                    "panorama": {"limitUp": 100, "ratio": "80%"},
                },
            },
            theme_trend_cache={
                "by_day": {
                    "2026-05-27": {"电力": 12},
                    "2026-05-28": {"电力": 10},
                    "2026-05-29": {"电力": 8},
                }
            },
        )

        power = next(t for t in signal["themes"] if t["name"] == "电力")
        self.assertEqual(power["status"], "traverse_candidate")
        self.assertGreater(power["resilience"], 0)
        self.assertIn("电力", signal["summary"]["mainline_candidates"])

    def test_rebound_warning_under_shrinking_volume(self) -> None:
        signal = build_tide_signal(
            market_data={
                "date": "2026-05-29",
                "sentiment": {"score": 72},
                "panorama": {"limitUp": 80, "ratio": "78%"},
                "volume": {"total": "9000亿"},
                "prev": {
                    "sentiment": {"score": 76},
                    "panorama": {"limitUp": 82, "ratio": "79%"},
                    "volume": {"total": "10000亿"},
                },
            },
            theme_trend_cache={
                "by_day": {
                    "2026-05-27": {"机器人": 10},
                    "2026-05-28": {"机器人": 2},
                    "2026-05-29": {"机器人": 5},
                }
            },
        )

        robot = next(t for t in signal["themes"] if t["name"] == "机器人")
        self.assertEqual(robot["status"], "rebound_warning")
        self.assertEqual(robot["warning_level"], "danger")
        self.assertIn("机器人", signal["summary"]["risk_themes"])

    def test_missing_data_default(self) -> None:
        signal = build_tide_signal(market_data={}, theme_trend_cache={})

        self.assertFalse(signal["market"]["is_ebb_day"])
        self.assertEqual(signal["themes"], [])
        self.assertEqual(signal["summary"]["action_hint"], "潮汐数据不足，按原系统判断")


if __name__ == "__main__":
    unittest.main()

