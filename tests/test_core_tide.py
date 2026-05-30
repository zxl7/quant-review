#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from daily_review.metrics.core_tide import build_core_tide_signal


class CoreTideSignalTest(unittest.TestCase):
    def test_confirmed_mainline_with_five_factor_resonance(self) -> None:
        signal = build_core_tide_signal(
            market_data={
                "date": "2026-05-29",
                "sentiment": {"score": 68, "risk": 32},
                "panorama": {"limitUp": 86, "limitDown": 4, "ratio": "78%"},
                "volume": {"change": "+12%"},
                "indices": [{"name": "上证", "chg": "+0.8%", "price": 3100, "ma5": 3080, "ma20": 3000}],
            },
            tide_signal={
                "date": "2026-05-29",
                "market": {"is_ebb_day": False},
                "themes": [
                    {
                        "name": "电力",
                        "status": "confirmed_mainline",
                        "tide_score": 82,
                        "strength_rank": 2,
                        "strength_score": 84,
                        "today_zt": 9,
                        "prev_zt": 8,
                        "confidence": "high",
                        "action_hint": "确认主线",
                    }
                ],
            },
            catalyst_data={
                "surge_plates": {
                    "raw": {
                        "data": {
                            "data": {
                                "items": [
                                    {"id": "1", "name": "电力", "description": "电改催化"},
                                ]
                            }
                        }
                    }
                }
            },
        )

        power = signal["themes"][0]
        self.assertEqual(signal["marketRegime"]["status"], "attack")
        self.assertEqual(power["name"], "电力")
        self.assertEqual(power["status"], "core_mainline")
        self.assertEqual(power["action"], "confirm")
        self.assertTrue(power["confirms"]["news"])
        self.assertIn("电力", signal["summary"]["confirmed"])

    def test_rebound_warning_keeps_no_new_position(self) -> None:
        signal = build_core_tide_signal(
            market_data={
                "date": "2026-05-29",
                "sentiment": {"score": 55},
                "panorama": {"limitUp": 55, "limitDown": 12, "ratio": "58%"},
                "volume": {"change": "-10%"},
                "indices": [{"name": "上证", "chg": "-0.4%", "price": 3000, "ma5": 3020, "ma20": 3030}],
            },
            tide_signal={
                "date": "2026-05-29",
                "market": {"is_ebb_day": True},
                "themes": [
                    {
                        "name": "机器人",
                        "status": "rebound_warning",
                        "tide_score": 20,
                        "strength_score": 35,
                        "today_zt": 5,
                        "prev_zt": 2,
                        "confidence": "medium",
                        "action_hint": "回光返照",
                    }
                ],
            },
        )

        robot = signal["themes"][0]
        self.assertEqual(robot["status"], "afterglow_risk")
        self.assertEqual(robot["action"], "no_new_position")
        self.assertIn("不开新仓", robot["cautions"])
        self.assertIn("机器人", signal["summary"]["avoid"])

    def test_missing_tide_themes_is_safe(self) -> None:
        signal = build_core_tide_signal(market_data={}, tide_signal={}, catalyst_data={})

        self.assertEqual(signal["themes"], [])
        self.assertEqual(signal["summary"]["action_hint"], "核心潮汐数据不足，按原系统判断。")


if __name__ == "__main__":
    unittest.main()
