#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""股票基础工具。"""

from __future__ import annotations

from typing import Any, Iterable


def is_st_name(name: Any) -> bool:
    """统一识别 ST 名称，避免跌停/风险统计在不同模块里各写一套口径。"""
    text = str(name or "").upper()
    return ("ST" in text) or ("*ST" in text)


def is_st_stock(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    return is_st_name(row.get("mc") or row.get("name") or "")


def filter_non_st_stocks(rows: Iterable[Any] | None) -> list[dict[str, Any]]:
    """跌停口径统一收敛到“非 ST”，供情绪/风控/盯盘共用。"""
    result: list[dict[str, Any]] = []
    for row in rows or []:
        if isinstance(row, dict) and not is_st_stock(row):
            result.append(row)
    return result
