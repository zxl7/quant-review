#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
市场评分：热度 vs 风险 双线
"""

from __future__ import annotations

from dataclasses import dataclass


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


@dataclass(frozen=True)
class HeatRiskScore:
    heat: int
    risk: int
    sentiment: int


def calc_heat_risk(
    *,
    fb_rate: float,
    jj_rate: float,
    zt_count: int,
    zt_early_ratio: float,
    zb_rate: float,
    dt_count: int,
    bf_count: int,
    zb_high_ratio: float,
    broken_lb_rate: float,
) -> HeatRiskScore:
    # 热度
    zt_breadth_score = clamp(min(zt_count, 90) / 90 * 100, 0, 100) if zt_count else 0
    heat = round(
        clamp(
            fb_rate * 0.35
            + jj_rate * 0.25
            + zt_breadth_score * 0.25
            + zt_early_ratio * 0.15,
            0,
            100,
        )
    )

    # 风险
    dt_score = clamp(min(dt_count, 20) / 20 * 100, 0, 100) if dt_count else 0
    bf_score = clamp(min(bf_count, 20) / 20 * 100, 0, 100) if bf_count else 0
    risk = round(
        clamp(
            zb_rate * 0.25
            + dt_score * 0.20
            + bf_score * 0.20
            + zb_high_ratio * 0.20
            + broken_lb_rate * 0.15,
            0,
            100,
        )
    )

    sentiment = round(clamp(heat * 0.65 + (100 - risk) * 0.35, 0, 100))
    return HeatRiskScore(heat=heat, risk=risk, sentiment=sentiment)

