#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from daily_review.metrics.zt_analysis import build_zt_analysis


class ZtAnalysisLadderPriorityTest(unittest.TestCase):
    def _build_market_data(self, ztgc, zt_code_themes, strength_rows, plate_rotate_top, ladder) -> dict:
        return {
            "date": "2026-06-08",
            "ztgc": ztgc,
            "zt_code_themes": zt_code_themes,
            "themePanels": {
                "ztTop": [{"name": strength_rows[0]["name"]}] if strength_rows else [],
                "strengthRows": strength_rows,
            },
            "plateRotateTop": plate_rotate_top,
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
                    "zt_count": len(ztgc),
                    "dt_count": 0,
                }
            },
            "prev": {"features": {"mood_inputs": {"max_lb": 3, "jj_rate": 59, "jj_rate_adj": 59, "broken_lb_rate": 30, "broken_lb_rate_adj": 30}}},
            "moodStage": {"type": "warn", "cycle": "FERMENT", "dayState": "修复"},
            "actionAdvisor": {"posture": "谨慎进攻", "position": "2-4成"},
            "heightTrend": {"main": [2, 3, 4], "sub": [1, 2, 3]},
            "themeTrend": {"series": [{"name": row["name"], "values": [4, 6, 8]} for row in strength_rows]},
            "volume": {"change": 3},
            "fear": {"broken": 20},
            "mood": {"score": 62, "heat": 64, "risk": 38},
            "panorama": {"ratio": 80, "limitUp": len(ztgc), "limitDown": 0},
            "ladder": ladder,
        }

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

    def test_relay_prefers_multi_board_mainline_leader_over_first_board_capacity(self) -> None:
        payload = build_zt_analysis(
            market_data=self._build_market_data(
                ztgc=[
                    {"dm": "000101", "mc": "主线三板龙头", "lbc": 3, "hy": "机器人", "zj": 260000000, "zbc": 0, "fbt": "09:31:00", "cje": 1200000000, "hs": 8.0, "zf": 10.0, "zsz": 12000000000, "lt": 9000000000},
                    {"dm": "000102", "mc": "容量首板大票", "lbc": 1, "hy": "机器人", "zj": 190000000, "zbc": 0, "fbt": "09:42:00", "cje": 5200000000, "hs": 19.0, "zf": 10.0, "zsz": 52000000000, "lt": 42000000000},
                    {"dm": "000103", "mc": "主线二板助攻", "lbc": 2, "hy": "机器人", "zj": 120000000, "zbc": 1, "fbt": "09:37:00", "cje": 900000000, "hs": 10.0, "zf": 10.0, "zsz": 9000000000, "lt": 7000000000},
                ],
                zt_code_themes={"000101": ["机器人"], "000102": ["机器人"], "000103": ["机器人"]},
                strength_rows=[{"name": "机器人", "net": 16, "risk": 2, "zt": 3, "zb": 0, "dt": 0}],
                plate_rotate_top=[{"name": "机器人", "rank": 1, "strength": 90, "leaders": [{"code": "000101", "name": "主线三板龙头"}], "lead": "主线三板龙头"}],
                ladder=[
                    {"code": "000101", "qualityLabel": "封单充足", "qualityScore": 92, "note": "主线龙头"},
                    {"code": "000102", "qualityLabel": "高换手承接", "qualityScore": 76, "note": "容量首板"},
                    {"code": "000103", "qualityLabel": "温和放量", "qualityScore": 82, "note": "主线助攻"},
                ],
            )
        )

        relay_names = [row["name"] for row in payload.get("relay") or []]
        watch_rows = {row["name"]: row for row in payload.get("watch") or []}
        self.assertEqual(relay_names[0], "主线三板龙头")
        self.assertIn("主线二板助攻", relay_names)
        self.assertNotIn("容量首板大票", relay_names)
        self.assertEqual(watch_rows["容量首板大票"]["watchGroup"], "容量核心")

    def test_broad_and_gapped_names_do_not_easily_enter_relay(self) -> None:
        payload = build_zt_analysis(
            market_data=self._build_market_data(
                ztgc=[
                    {"dm": "000201", "mc": "融资融券大票", "lbc": 1, "hy": "融资融券", "zj": 160000000, "zbc": 0, "fbt": "09:33:00", "cje": 4800000000, "hs": 22.0, "zf": 10.0, "zsz": 60000000000, "lt": 46000000000},
                    {"dm": "000202", "mc": "断层高标", "lbc": 4, "hy": "芯片", "zj": 280000000, "zbc": 0, "fbt": "09:31:00", "cje": 1600000000, "hs": 7.0, "zf": 10.0, "zsz": 15000000000, "lt": 12000000000},
                    {"dm": "000203", "mc": "芯片补涨", "lbc": 1, "hy": "芯片", "zj": 90000000, "zbc": 0, "fbt": "09:50:00", "cje": 600000000, "hs": 8.0, "zf": 10.0, "zsz": 7000000000, "lt": 6000000000},
                ],
                zt_code_themes={"000201": ["融资融券"], "000202": ["芯片"], "000203": ["芯片"]},
                strength_rows=[{"name": "芯片", "net": 14, "risk": 2, "zt": 2, "zb": 0, "dt": 0}, {"name": "融资融券", "net": 14, "risk": 2, "zt": 1, "zb": 0, "dt": 0}],
                plate_rotate_top=[
                    {"name": "芯片", "rank": 1, "strength": 86, "leaders": [{"code": "000202", "name": "断层高标"}], "lead": "断层高标"},
                    {"name": "融资融券", "rank": 2, "strength": 84, "leaders": [{"code": "000201", "name": "融资融券大票"}], "lead": "融资融券大票"},
                ],
                ladder=[
                    {"code": "000201", "qualityLabel": "高换手承接", "qualityScore": 74, "note": "宽题材容量"},
                    {"code": "000202", "qualityLabel": "封单充足", "qualityScore": 93, "note": "断层高标"},
                    {"code": "000203", "qualityLabel": "温和放量", "qualityScore": 70, "note": "断层补涨"},
                ],
            )
        )

        relay_names = [row["name"] for row in payload.get("relay") or []]
        debug_by_name = {row["name"]: row for row in payload.get("meta", {}).get("debug", {}).get("rows", [])}
        self.assertNotIn("融资融券大票", relay_names)
        self.assertNotIn("断层高标", relay_names)
        self.assertIn("题材偏泛化", debug_by_name["融资融券大票"]["blockReasons"])
        self.assertIn("梯队断层", debug_by_name["断层高标"]["blockReasons"])

    def test_one_to_two_requires_mainline_support_and_risk_control(self) -> None:
        payload = build_zt_analysis(
            market_data=self._build_market_data(
                ztgc=[
                    {"dm": "000301", "mc": "强主线一进二", "lbc": 1, "hy": "机器人", "zj": 150000000, "zbc": 0, "fbt": "09:33:00", "cje": 1500000000, "hs": 9.0, "zf": 10.0, "zsz": 12000000000, "lt": 9000000000},
                    {"dm": "000302", "mc": "弱承接一板大票", "lbc": 1, "hy": "机器人", "zj": 80000000, "zbc": 5, "fbt": "10:18:00", "cje": 2600000000, "hs": 28.0, "zf": 10.0, "zsz": 36000000000, "lt": 28000000000},
                    {"dm": "000303", "mc": "主线二板龙头", "lbc": 2, "hy": "机器人", "zj": 190000000, "zbc": 1, "fbt": "09:32:00", "cje": 1100000000, "hs": 9.0, "zf": 10.0, "zsz": 11000000000, "lt": 8500000000},
                ],
                zt_code_themes={"000301": ["机器人"], "000302": ["机器人"], "000303": ["机器人"]},
                strength_rows=[{"name": "机器人", "net": 18, "risk": 1, "zt": 3, "zb": 0, "dt": 0}],
                plate_rotate_top=[{"name": "机器人", "rank": 1, "strength": 92, "leaders": [{"code": "000303", "name": "主线二板龙头"}], "lead": "主线二板龙头"}],
                ladder=[
                    {"code": "000301", "qualityLabel": "温和放量", "qualityScore": 87, "note": "强承接"},
                    {"code": "000302", "qualityLabel": "分歧烂板", "qualityScore": 58, "note": "开板多"},
                    {"code": "000303", "qualityLabel": "封单充足", "qualityScore": 90, "note": "龙头"},
                ],
            )
        )

        relay_names = [row["name"] for row in payload.get("relay") or []]
        debug_by_name = {row["name"]: row for row in payload.get("meta", {}).get("debug", {}).get("rows", [])}
        self.assertIn("强主线一进二", relay_names)
        self.assertNotIn("弱承接一板大票", relay_names)
        self.assertIn("1进2", debug_by_name["强主线一进二"]["hitRules"])
        self.assertIn("开板过多", debug_by_name["弱承接一板大票"]["blockReasons"])

    def test_watch_groups_follow_divergence_capacity_risk_and_supplement_order(self) -> None:
        payload = build_zt_analysis(
            market_data=self._build_market_data(
                ztgc=[
                    {"dm": "000401", "mc": "高位分歧龙头", "lbc": 3, "hy": "机器人", "zj": 120000000, "zbc": 4, "fbt": "10:06:00", "cje": 1400000000, "hs": 18.0, "zf": 10.0, "zsz": 13000000000, "lt": 10000000000},
                    {"dm": "000402", "mc": "容量中军", "lbc": 1, "hy": "机器人", "zj": 70000000, "zbc": 0, "fbt": "09:47:00", "cje": 4200000000, "hs": 14.0, "zf": 10.0, "zsz": 48000000000, "lt": 36000000000},
                    {"dm": "000403", "mc": "风险观察票", "lbc": 1, "hy": "机器人", "zj": 60000000, "zbc": 3, "fbt": "10:20:00", "cje": 2200000000, "hs": 25.0, "zf": 10.0, "zsz": 30000000000, "lt": 22000000000},
                    {"dm": "000404", "mc": "补充观察票", "lbc": 1, "hy": "其它", "zj": 30000000, "zbc": 0, "fbt": "14:21:00", "cje": 300000000, "hs": 3.0, "zf": 10.0, "zsz": 6000000000, "lt": 5000000000},
                    {"dm": "000405", "mc": "主线二板龙头", "lbc": 2, "hy": "机器人", "zj": 200000000, "zbc": 0, "fbt": "09:31:00", "cje": 1200000000, "hs": 8.0, "zf": 10.0, "zsz": 12000000000, "lt": 9000000000},
                ],
                zt_code_themes={"000401": ["机器人"], "000402": ["机器人"], "000403": ["机器人"], "000405": ["机器人"]},
                strength_rows=[{"name": "机器人", "net": 17, "risk": 2, "zt": 4, "zb": 0, "dt": 0}],
                plate_rotate_top=[{"name": "机器人", "rank": 1, "strength": 91, "leaders": [{"code": "000405", "name": "主线二板龙头"}], "lead": "主线二板龙头"}],
                ladder=[
                    {"code": "000401", "qualityLabel": "分歧烂板", "qualityScore": 78, "note": "高位分歧"},
                    {"code": "000402", "qualityLabel": "温和放量", "qualityScore": 68, "note": "容量核心"},
                    {"code": "000403", "qualityLabel": "反复回封", "qualityScore": 60, "note": "风险观察"},
                    {"code": "000404", "qualityLabel": "温和放量", "qualityScore": 52, "note": "补充观察"},
                    {"code": "000405", "qualityLabel": "封单充足", "qualityScore": 92, "note": "二板龙头"},
                ],
            )
        )

        watch_rows = {row["name"]: row for row in payload.get("watch") or []}
        watch_names = [row["name"] for row in payload.get("watch") or []]
        self.assertEqual(watch_rows["高位分歧龙头"]["watchGroup"], "高位分歧")
        self.assertEqual(watch_rows["容量中军"]["watchGroup"], "容量核心")
        self.assertEqual(watch_rows["风险观察票"]["watchGroup"], "风险观察")
        self.assertEqual(watch_rows["补充观察票"]["watchGroup"], "补充观察")
        self.assertLess(watch_names.index("高位分歧龙头"), watch_names.index("容量中军"))
        self.assertLess(watch_names.index("容量中军"), watch_names.index("风险观察票"))
        self.assertLess(watch_names.index("风险观察票"), watch_names.index("补充观察票"))


if __name__ == "__main__":
    unittest.main()
