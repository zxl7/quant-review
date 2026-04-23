#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
data.biying：外部数据源访问（不做业务判断）

覆盖：
- 指数实时：hsindex/real/time
- 指数日K：hsindex/latest/history（用于交易日与量能）
- 三池：hslt/{pool}/{date}
- 个股题材：hszg/zg/{code6}
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional, Sequence, Tuple

from daily_review.http import HttpClient


def _extract_trade_dates(items: Any) -> list[str]:
    """
    从指数K线条目提取“真实交易日”列表。
    过滤规则：
    - sf=1：占位/停牌/未收盘
    - a<=0 或 v<=0：无成交的占位数据
    """
    out: list[str] = []
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        t = it.get("t", "")
        if not (isinstance(t, str) and len(t) >= 10):
            continue
        sf = int(it.get("sf", 0) or 0)
        a = float(it.get("a", 0) or 0)
        v = float(it.get("v", 0) or 0)
        if sf == 1:
            continue
        if a <= 0 or v <= 0:
            continue
        out.append(t[:10])
    return out


def get_recent_trade_dates(client: HttpClient, *, n: int = 15) -> list[str]:
    """
    从指数日K提取最近交易日列表，用于非交易日回退。
    """
    try:
        url = f"{client.base_url}/hsindex/latest/000001.SH/d/{client.token}?lt={max(n, 12)}"
        data = client.get_json(url)
        uniq = sorted(set(_extract_trade_dates(data)))
        return uniq[-n:] if len(uniq) >= n else uniq
    except Exception:
        return []


def resolve_trade_date(client: HttpClient, requested_date: str | None) -> tuple[str, str]:
    """
    将非交易日请求自动回退到最近交易日。
    返回：(date, date_note)
    """
    if not requested_date:
        # 默认用今天；若非交易日则回退
        requested_date = _dt.datetime.now().strftime("%Y-%m-%d")
    note = ""
    try:
        _dt.datetime.strptime(requested_date, "%Y-%m-%d")
    except Exception:
        return requested_date, ""

    dates = get_recent_trade_dates(client, n=20)
    if not dates:
        return requested_date, ""
    if requested_date in dates:
        return requested_date, ""
    # 回退：取 <= requested_date 的最近一个
    past = [d for d in dates if d <= requested_date]
    if past:
        actual = past[-1]
        note = f"非交易日自动回退到最近交易日：{actual}"
        return actual, note
    return requested_date, ""


def fetch_indices_realtime(client: HttpClient, codes: Sequence[tuple[str, str]]) -> tuple[list[dict[str, Any]], str]:
    """
    获取主要指数实时数据。
    返回：(indices, as_of_time)
    """
    out: list[dict[str, Any]] = []
    as_of = ""
    for code, name in codes:
        url = f"{client.base_url}/hsindex/real/time/{code}/{client.token}"
        rt = client.get_json(url) or {}
        t = str(rt.get("t", "") or "")
        if t:
            as_of = t
        out.append(
            {
                "name": name,
                "code": code,
                "val": float(rt.get("p", 0) or 0),
                "chg": float(rt.get("pc", 0) or 0),  # %
                "cje": float(rt.get("cje", 0) or 0),  # 元
                "t": t,
            }
        )
    # as_of 只展示 HH:MM:SS
    as_of_short = as_of[11:19] if len(as_of) >= 19 else as_of
    return out, (as_of_short or _dt.datetime.now().strftime("%H:%M:%S"))


def fetch_pool(client: HttpClient, *, pool_name: str, date: str) -> list[dict[str, Any]]:
    """
    三池/强势池：hslt/{pool}/{date}
    """
    path = f"hslt/{pool_name}/{date}"
    data = client.api(path, exit_on_404=False, quiet_404=True)
    return data if isinstance(data, list) else []


def fetch_index_latest_k(client: HttpClient, *, code: str, lt: int = 5) -> list[dict[str, Any]]:
    url = f"{client.base_url}/hsindex/latest/{code}/d/{client.token}?lt={max(lt, 5)}"
    data = client.get_json(url)
    return data if isinstance(data, list) else []


def fetch_index_history_k(client: HttpClient, *, code: str, st: str, et: str) -> list[dict[str, Any]]:
    url = f"{client.base_url}/hsindex/history/{code}/d/{client.token}?st={st}&et={et}"
    data = client.get_json(url)
    return data if isinstance(data, list) else []


def get_trading_days_from_index_k(client: HttpClient, *, date: str, n: int = 7) -> list[str]:
    """
    用指数日K确定最近 n 个交易日（参考 gen_report_v4 的策略）。
    """
    if n <= 5:
        sh = fetch_index_latest_k(client, code="000001.SH", lt=n)
        sz = fetch_index_latest_k(client, code="399001.SZ", lt=n)
        uniq = sorted(set(_extract_trade_dates(sh) + _extract_trade_dates(sz)))
        return uniq[-n:] if len(uniq) >= n else uniq

    et = date.replace("-", "")
    st_dt = (_dt.datetime.strptime(date, "%Y-%m-%d") - _dt.timedelta(days=40)).strftime("%Y%m%d")
    sh = fetch_index_history_k(client, code="000001.SH", st=st_dt, et=et)
    sz = fetch_index_history_k(client, code="399001.SZ", st=st_dt, et=et)
    uniq = sorted(set(_extract_trade_dates(sh) + _extract_trade_dates(sz)))
    uniq = [d for d in uniq if d <= date]
    return uniq[-n:] if len(uniq) >= n else uniq


def normalize_stock_code(code: str) -> str:
    """
    统一 code 为 6 位数字。
    """
    digits = "".join([c for c in str(code or "") if c.isdigit()])
    return digits[-6:] if len(digits) >= 6 else digits


def fetch_stock_themes(client: HttpClient, *, code6: str) -> list[dict[str, Any]]:
    """
    获取个股题材原始列表（不做过滤）。
    """
    url = f"{client.base_url}/hszg/zg/{code6}/{client.token}"
    data = client.get_json(url)
    return data if isinstance(data, list) else []
