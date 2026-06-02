#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from daily_review.metrics.scoring import calc_heat_risk


class HeatRiskScoreTest(unittest.TestCase):
    def test_divergence_market_is_not_double_penalized(self) -> None:
        score = calc_heat_risk(
            fb_rate=74.5,
            jj_rate=33.0,
            zt_count=120,
            zt_early_ratio=53.0,
            zb_rate=25.5,
            dt_count=21,
            bf_count=24,
            loss=45,
            zb_high_ratio=0.0,
            broken_lb_rate=67.0,
            avg_zt_zbc=2.0,
            zt_zbc_ge3_ratio=13.0,
            yest_zt_avg_chg=-1.5,
        )

        self.assertEqual(score.heat, 67)
        self.assertEqual(score.risk, 60)
        self.assertEqual(score.sentiment, 48)

    def test_extreme_ebb_market_stays_low(self) -> None:
        score = calc_heat_risk(
            fb_rate=45.0,
            jj_rate=18.0,
            zt_count=22,
            zt_early_ratio=20.0,
            zb_rate=55.0,
            dt_count=28,
            bf_count=30,
            loss=58,
            zb_high_ratio=30.0,
            broken_lb_rate=82.0,
            avg_zt_zbc=3.4,
            zt_zbc_ge3_ratio=38.0,
            yest_zt_avg_chg=-4.2,
        )

        self.assertEqual(score.heat, 29)
        self.assertEqual(score.risk, 76)
        self.assertLessEqual(score.sentiment, 20)


if __name__ == "__main__":
    unittest.main()
