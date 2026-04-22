#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
轻量自测入口（不依赖 pytest）

用途：
- 单独验证：交易日推断 / 缓存读写 / 评分函数不报错
- 避免“改一处牵一身”
"""

from __future__ import annotations

import datetime
from pathlib import Path

from daily_review.config import DEFAULT_CONFIG
from daily_review.http import HttpClient
from daily_review.calendar import get_trading_days_from_volume_k
from daily_review.metrics.scoring import calc_heat_risk


def run() -> None:
    cfg = DEFAULT_CONFIG
    client = HttpClient(base_url=cfg.base_url, token=cfg.token)

    today = datetime.date.today().strftime("%Y-%m-%d")
    days = []
    # 没有 token 时不请求接口：自测仍然覆盖“纯函数部分”
    if cfg.token:
        days = get_trading_days_from_volume_k(client, date=today, n=7)
        assert isinstance(days, list)
    else:
        print("⚠️  未设置 BIYING_TOKEN：跳过接口类自测（仅做纯函数 smoke test）")

    # 评分函数 smoke test
    s = calc_heat_risk(
        fb_rate=75.0,
        jj_rate=40.0,
        zt_count=60,
        zt_early_ratio=55.0,
        zb_rate=20.0,
        dt_count=2,
        bf_count=3,
        zb_high_ratio=5.0,
        broken_lb_rate=20.0,
    )
    assert 0 <= s.heat <= 100 and 0 <= s.risk <= 100 and 0 <= s.sentiment <= 100

    print("selftest_ok")
    if days:
        print("recent_trading_days:", days)


if __name__ == "__main__":
    run()
