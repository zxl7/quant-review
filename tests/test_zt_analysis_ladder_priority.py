#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from daily_review.metrics.zt_analysis import build_zt_analysis


class ZtAnalysisLadderPriorityTest(unittest.TestCase):
    def test_complete_theme_ladder_beats_gapped_theme(self) -> None:
        market_data = {
            "date": "2026-06-08",
            "ztgc": [
                {"dm": "000001", "mc": "完整龙头", "lbc": 4, "hy": "科技", "zj": 280000000, "zbc": 0, "fbt": "09:31:00", "cje": 1600000000, "hs": 8.0, "zf": 10.0, "zsz": 12000000000, "lt": 9000000000},
                {"dm": "000002", "mc": "完整中军", "lbc": 3, "hy": "科技", "zj": 180000000, "zbc": 1, "fbt": "09:35:00", "cje": 1300000000, "hs": 10.0, "zf": 10.0, "zsz": 11000000000, "lt": 8500000000},
                {"dm": "000003", "mc": "完整补涨", "lbc": 2, "hy": "科技", "zj": 90000000, "zbc": 1, "fbt": "09:40:00", "cje": 900000000, "hs": 12.0, "zf": 10.0, "zsz": 9000000000, "lt": 7000000000},
                {"dm": "000004", "mc": "完整首板", "lbc": 1, "hy": "科技", "zj": 70000000, "zbc": 0, "fbt": "09:45:00", "cje": 700000000, "hs": 9.0, "zf": 10.0, "zsz": 8000000000, "lt": 6500000000},
                {"dm": "000005", "mc": "断层龙头", "lbc": 4, "hy": "科技", "zj": 290000000, "zbc": 0, "fbt": "09:32:00", "cje": 1700000000, "hs": 7.5, "zf": 10.0, "zsz": 12000000000, "lt": 9500000000},
                {"dm": "000006", "mc": "断层跟风", "lbc": 1, "hy": "科技", "zj": 65000000, "zbc": 0, "fbt": "10:02:00", "cje": 650000000, "hs": 8.0, "zf": 10.0, "zsz": 7800000000, "lt": 6200000000},
            ],
            "zt_code_themes": {
                "000001": ["完整题材"],
                "000002": ["完整题材"],
                "000003": ["完整题材"],
                "000004": ["完整题材"],
                "000005": ["断层题材"],
                "000006": ["断层题材"],
            },
            "themePanels": {
                "ztTop": [{"name": "完整题材"}],
                "strengthRows": [
                    {"name": "完整题材", "net": 14, "risk": 2, "zt": 4, "zb": 0, "dt": 0},
                    {"name": "断层题材", "net": 14, "risk": 2, "zt": 4, "zb": 0, "dt": 0},
                ],
            },
            "plateRotateTop": [
                {"name": "完整题材", "rank": 1, "strength": 88, "leaders": [{"code": "000001", "name": "完整龙头"}], "lead": "完整龙头"},
                {"name": "断层题材", "rank": 2, "strength": 84, "leaders": [{"code": "000005", "name": "断层龙头"}], "lead": "断层龙头"},
            ],
            "features": {
                "mood_inputs": {
                    "max_lb": 4,
                    "rate_2to3": 65,
                    "rate_3to4": 55,
                    "jj_rate": 62,
                    "jj_rate_adj": 62,
                    "broken_lb_rate": 28,
                    "broken_lb_rate_adj": 28,
                    "trend_jj_rate": 3,
                    "trend_broken_lb_rate": -2,
                    "trend_max_lb": 1,
                    "hist_max_lb": [2, 3, 4],
                    "hist_jj_rate": [50, 55, 62],
                    "hist_broken_lb_rate": [40, 35, 28],
                    "hist_lianban": [8, 10, 12],
                    "zt_count": 6,
                    "dt_count": 0,
                }
            },
            "prev": {"features": {"mood_inputs": {"max_lb": 3, "jj_rate": 59, "jj_rate_adj": 59, "broken_lb_rate": 30, "broken_lb_rate_adj": 30}}},
            "moodStage": {"type": "warn", "cycle": "FERMENT", "dayState": "修复"},
            "actionAdvisor": {"posture": "谨慎进攻", "position": "2-4成"},
            "heightTrend": {"main": [2, 3, 4], "sub": [1, 2, 3]},
            "themeTrend": {"series": [{"name": "完整题材", "values": [4, 6, 8]}, {"name": "断层题材", "values": [4, 6, 8]}]},
            "volume": {"change": 3},
            "fear": {"broken": 20},
            "mood": {"score": 62, "heat": 64, "risk": 38},
            "panorama": {"ratio": 80, "limitUp": 6, "limitDown": 0},
            "ladder": [
                {"code": "000001", "qualityLabel": "封单充足", "qualityScore": 92, "note": "完整题材龙头"},
                {"code": "000002", "qualityLabel": "温和放量", "qualityScore": 84, "note": "完整题材中军"},
                {"code": "000003", "qualityLabel": "高换手承接", "qualityScore": 78, "note": "完整题材补涨"},
                {"code": "000004", "qualityLabel": "温和放量", "qualityScore": 80, "note": "完整题材首板"},
                {"code": "000005", "qualityLabel": "封单充足", "qualityScore": 92, "note": "断层题材龙头"},
                {"code": "000006", "qualityLabel": "温和放量", "qualityScore": 72, "note": "断层题材首板"},
            ],
        }

        payload = build_zt_analysis(market_data=market_data)
        by_name = {
            row["name"]: row
            for row in [*(payload.get("relay") or []), *(payload.get("watch") or [])]
            if isinstance(row, dict) and row.get("name")
        }

        self.assertIn("完整龙头", by_name)
        self.assertIn("断层龙头", by_name)
        self.assertGreater(by_name["完整龙头"]["factorScore"], by_name["断层龙头"]["factorScore"])
        self.assertEqual(by_name["完整龙头"]["themeLadderProfile"]["label"], "梯队完整")
        self.assertEqual(by_name["断层龙头"]["themeLadderProfile"]["label"], "梯队断层")
        self.assertGreater(
            by_name["完整龙头"]["themeLadderProfile"]["score"],
            by_name["断层龙头"]["themeLadderProfile"]["score"],
        )


if __name__ == "__main__":
    unittest.main()
