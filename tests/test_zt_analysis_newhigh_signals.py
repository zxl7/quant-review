#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daily_review.metrics.zt_analysis as zt_analysis
from daily_review.data.ths_newhigh import _parse_board_rows


def _merge_rows(payload: dict) -> dict[str, dict]:
    return {
        row["name"]: row
        for row in [*(payload.get("relay") or []), *(payload.get("watch") or [])]
        if isinstance(row, dict) and row.get("name")
    }


def _base_market_data() -> dict:
    return {
        "date": "2026-06-08",
        "ztgc": [
            {"dm": "000001", "mc": "强势龙头", "lbc": 3, "hy": "科技", "zj": 220000000, "zbc": 0, "fbt": "09:31:00", "cje": 1500000000, "hs": 8.0, "zf": 10.0, "zsz": 10000000000, "lt": 7600000000},
            {"dm": "000002", "mc": "对照个股", "lbc": 2, "hy": "科技", "zj": 100000000, "zbc": 1, "fbt": "09:39:00", "cje": 1000000000, "hs": 10.0, "zf": 10.0, "zsz": 9000000000, "lt": 7000000000},
        ],
        "zt_code_themes": {
            "000001": ["AI主线"],
            "000002": ["AI主线"],
        },
        "themePanels": {
            "ztTop": [{"name": "AI主线"}],
            "strengthRows": [
                {"name": "AI主线", "net": 12, "risk": 2, "zt": 2, "zb": 0, "dt": 0},
            ],
        },
        "plateRotateTop": [
            {"name": "AI主线", "rank": 1, "strength": 86, "leaders": [{"code": "000001", "name": "强势龙头"}], "lead": "强势龙头"},
        ],
        "features": {
            "mood_inputs": {
                "max_lb": 3,
                "rate_2to3": 63,
                "rate_3to4": 54,
                "jj_rate": 60,
                "jj_rate_adj": 60,
                "broken_lb_rate": 30,
                "broken_lb_rate_adj": 30,
                "trend_jj_rate": 2,
                "trend_broken_lb_rate": -1,
                "trend_max_lb": 1,
                "hist_max_lb": [2, 2, 3],
                "hist_jj_rate": [54, 58, 60],
                "hist_broken_lb_rate": [38, 34, 30],
                "hist_lianban": [7, 9, 10],
                "zt_count": 2,
                "dt_count": 0,
            }
        },
        "prev": {"features": {"mood_inputs": {"max_lb": 2, "jj_rate": 58, "jj_rate_adj": 58, "broken_lb_rate": 32, "broken_lb_rate_adj": 32}}},
        "moodStage": {"type": "warn", "cycle": "FERMENT", "dayState": "修复"},
        "actionAdvisor": {"posture": "谨慎进攻", "position": "2-4成"},
        "heightTrend": {"main": [2, 2, 3], "sub": [1, 1, 2]},
        "themeTrend": {"series": [{"name": "AI主线", "values": [5, 7, 9]}]},
        "volume": {"change": 2},
        "fear": {"broken": 22},
        "mood": {"score": 60, "heat": 61, "risk": 40},
        "panorama": {"ratio": 78, "limitUp": 2, "limitDown": 0},
        "ladder": [
            {"code": "000001", "qualityLabel": "封单充足", "qualityScore": 90, "note": "主线龙头"},
            {"code": "000002", "qualityLabel": "温和放量", "qualityScore": 80, "note": "主线跟风"},
        ],
    }


class ZtAnalysisNewHighSignalsTest(unittest.TestCase):
    def test_recent_high_and_ths_confirmation_raise_strength_and_reasons(self) -> None:
        market_data = _base_market_data()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache_online"
            cache_dir.mkdir()
            price_path = cache_dir / "recommendation_price_history.json"
            price_path.write_text(
                json.dumps(
                    {
                        "codes": {
                            "000001": {
                                "bars": [
                                    {"date": "2026-05-29", "high": 10.00},
                                    {"date": "2026-06-02", "high": 10.10},
                                    {"date": "2026-06-03", "high": 10.18},
                                    {"date": "2026-06-04", "high": 10.25},
                                    {"date": "2026-06-05", "high": 10.30},
                                    {"date": "2026-06-06", "high": 10.35},
                                    {"date": "2026-06-07", "high": 10.40},
                                    {"date": "2026-06-08", "high": 10.68},
                                ]
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (cache_dir / "ths_newhigh-20260608.json").write_text(
                json.dumps(
                    {
                        "rows": [
                            {"code": "000001", "board": 3, "boardLabel": "一年新高", "preHigh": "10.40", "preHighDate": "2026-06-07", "intervalDays": "1"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(zt_analysis, "ROOT", root), patch.object(zt_analysis, "PRICE_HISTORY_CACHE", price_path):
                enhanced = zt_analysis.build_zt_analysis(market_data=market_data)

            with patch.object(zt_analysis, "ROOT", root), patch.object(zt_analysis, "PRICE_HISTORY_CACHE", cache_dir / "missing.json"):
                baseline = zt_analysis.build_zt_analysis(market_data=market_data)

        enhanced_row = _merge_rows(enhanced)["强势龙头"]
        baseline_row = _merge_rows(baseline)["强势龙头"]

        self.assertTrue(enhanced_row["recentHighSignal"]["isRecentHigh"])
        self.assertEqual(enhanced_row["thsNewhigh"]["boardLabel"], "一年新高")
        self.assertTrue(enhanced_row["_breakoutDoubleConfirm"])
        self.assertGreater(enhanced_row["leaderFactorScore"], baseline_row["leaderFactorScore"])
        tag_texts = [str(tag.get("text") or "") for tag in enhanced_row["tags"]]
        self.assertIn("近7日新高", tag_texts)
        self.assertIn("一年新高", tag_texts)

    def test_monthly_ths_newhigh_is_kept_in_raw_data_but_not_promoted_to_frontend_tags(self) -> None:
        market_data = _base_market_data()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache_online"
            cache_dir.mkdir()
            (cache_dir / "ths_newhigh-20260608.json").write_text(
                json.dumps(
                    {
                        "rows": [
                            {"code": "000001", "board": 1, "boardLabel": "创月新高", "preHigh": "10.12", "preHighDate": "2026-05-30", "intervalDays": "6"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(zt_analysis, "ROOT", root), patch.object(zt_analysis, "PRICE_HISTORY_CACHE", cache_dir / "missing.json"):
                payload = zt_analysis.build_zt_analysis(market_data=market_data)

        row = _merge_rows(payload)["强势龙头"]
        tag_texts = [str(tag.get("text") or "") for tag in row["tags"]]
        self.assertEqual(row["thsNewhigh"]["boardLabel"], "创月新高")
        self.assertNotIn("创月新高", tag_texts)
        self.assertNotIn("创月新高", row["reason"])


class ThsNewHighParserTest(unittest.TestCase):
    def test_parse_board_rows_extracts_core_fields(self) -> None:
        html = """
        <table>
          <tbody>
            <tr>
              <td>1</td>
              <td><a href="/stock/300001.html">300001</a></td>
              <td><a href="/stock/300001.html">特锐德</a></td>
              <td>25.66</td>
              <td>25.10</td>
              <td>2026-06-01</td>
              <td>7</td>
            </tr>
          </tbody>
        </table>
        """
        rows = _parse_board_rows(html, board=3)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "300001")
        self.assertEqual(rows[0]["name"], "特锐德")
        self.assertEqual(rows[0]["boardLabel"], "一年新高")
        self.assertEqual(rows[0]["preHigh"], "25.10")
        self.assertEqual(rows[0]["preHighDate"], "2026-06-01")
        self.assertEqual(rows[0]["intervalDays"], "7")


if __name__ == "__main__":
    unittest.main()
