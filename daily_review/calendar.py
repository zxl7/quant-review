#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
交易日历：用指数成交额日K接口推断最近 N 个交易日
"""

from __future__ import annotations

import datetime
from typing import List

from .http import HttpClient


def _extract_dates(arr) -> list[str]:
    out = []
    if isinstance(arr, list):
        for item in arr:
            t = item.get("t", "")
            if isinstance(t, str) and len(t) >= 10:
                out.append(t[:10])
    return out


def get_trading_days_from_volume_k(client: HttpClient, *, date: str, n: int = 7) -> List[str]:
    """
    规则：
    - n<=5 使用 latest
    - n>5 使用 history（st/et），避免 latest 的 lt 不稳定
    """
    if n <= 0:
        return []

    try:
        if n <= 5:
            sh = client.get_json(f"{client.base_url}/hsindex/latest/000001.SH/d/{client.token}?lt={n}")
            sz = client.get_json(f"{client.base_url}/hsindex/latest/399001.SZ/d/{client.token}?lt={n}")
            uniq = sorted(set(_extract_dates(sh) + _extract_dates(sz)))
            return uniq[-n:] if len(uniq) >= n else uniq

        et = date.replace("-", "")
        st_dt = (datetime.datetime.strptime(date, "%Y-%m-%d") - datetime.timedelta(days=40)).strftime("%Y%m%d")
        sh = client.get_json(f"{client.base_url}/hsindex/history/000001.SH/d/{client.token}?st={st_dt}&et={et}")
        sz = client.get_json(f"{client.base_url}/hsindex/history/399001.SZ/d/{client.token}?st={st_dt}&et={et}")
        uniq = sorted(set(_extract_dates(sh) + _extract_dates(sz)))
        uniq = [d for d in uniq if d <= date]
        return uniq[-n:] if len(uniq) >= n else uniq
    except Exception:
        # 兜底：latest 5
        try:
            sh = client.get_json(f"{client.base_url}/hsindex/latest/000001.SH/d/{client.token}?lt=5")
            sz = client.get_json(f"{client.base_url}/hsindex/latest/399001.SZ/d/{client.token}?lt=5")
            uniq = sorted(set(_extract_dates(sh) + _extract_dates(sz)))
            return uniq[-min(n, 5):]
        except Exception:
            return []

