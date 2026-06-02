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


def blend_sentiment_score(*, heat: float, risk: float) -> int:
    return round(clamp(heat * 0.58 + (100 - risk) * 0.42, 0, 100))


def _calc_structure_adjustment(
    *,
    risk: float,
    jj_rate: float,
    broken_lb_rate: float,
    loss: float,
    avg_zt_zbc: float,
    zt_zbc_ge3_ratio: float,
    yest_zt_avg_chg: float,
) -> float:
    """
    结构修正只做“二次校准”，不再把已进入 risk 的压力整轮重罚一次。

    原先 structure_penalty 与 risk 共享大量输入字段（晋级率、断板率、大面、炸板等），
    在“热度不差但结构分歧”的盘面里容易把分数从中位区直接打到冰点附近。
    这里保留结构校准，但按 risk 做衰减并加总封顶，避免重复计提。
    """
    raw_penalty = (
        clamp((max(0.0, 35.0 - jj_rate) / 15.0) * 8.0, 0, 8)
        + clamp((max(0.0, broken_lb_rate - 35.0) / 20.0) * 7.0, 0, 7)
        + clamp((max(0.0, loss - 10.0) / 8.0) * 8.0, 0, 8)
        + clamp((max(0.0, zt_zbc_ge3_ratio - 15.0) / 15.0) * 5.0, 0, 5)
        + clamp((max(0.0, avg_zt_zbc - 1.6) / 1.0) * 4.0, 0, 4)
        + clamp((max(0.0, -yest_zt_avg_chg) / 3.0) * 6.0, 0, 6)
    )

    attenuation = max(0.25, 1.0 - clamp(risk, 0, 100) / 100.0)
    return min(10.0, raw_penalty * attenuation)


def calc_heat_risk(
    *,
    fb_rate: float,
    jj_rate: float,
    zt_count: int,
    zt_early_ratio: float,
    zb_rate: float,
    dt_count: int,
    bf_count: int,
    loss: float = 0.0,
    zb_high_ratio: float,
    broken_lb_rate: float,
    avg_zt_zbc: float = 0.0,
    zt_zbc_ge3_ratio: float = 0.0,
    yest_zt_avg_chg: float = 0.0,
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
    loss_score = clamp(min(loss, 20) / 20 * 100, 0, 100) if loss else 0
    avg_zbc_score = clamp(avg_zt_zbc / 3.0 * 100, 0, 100) if avg_zt_zbc else 0
    zbc_ge3_score = clamp(zt_zbc_ge3_ratio, 0, 100) if zt_zbc_ge3_ratio else 0
    jj_weak_score = clamp((40 - jj_rate) / 40 * 100, 0, 100) if jj_rate < 40 else 0
    risk = round(
        clamp(
            zb_rate * 0.18
            + dt_score * 0.15
            + bf_score * 0.13
            + loss_score * 0.14
            + zb_high_ratio * 0.10
            + broken_lb_rate * 0.14
            + zbc_ge3_score * 0.08
            + avg_zbc_score * 0.04
            + jj_weak_score * 0.04,
            0,
            100,
        )
    )

    structure_adjustment = _calc_structure_adjustment(
        risk=risk,
        jj_rate=jj_rate,
        broken_lb_rate=broken_lb_rate,
        loss=loss,
        avg_zt_zbc=avg_zt_zbc,
        zt_zbc_ge3_ratio=zt_zbc_ge3_ratio,
        yest_zt_avg_chg=yest_zt_avg_chg,
    )
    sentiment = round(clamp(blend_sentiment_score(heat=heat, risk=risk) - structure_adjustment, 0, 100))
    return HeatRiskScore(heat=heat, risk=risk, sentiment=sentiment)
