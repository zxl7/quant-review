#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""通用数值解析工具（项目优化）。"""

from __future__ import annotations

from typing import Any


def to_float(v: Any, default: float = 0.0) -> float:
    """支持 '40%' / None / '' / number。"""
    try:
        if v is None or v == "":
            return default
        if isinstance(v, str) and v.endswith("%"):
            v = v[:-1]
        return float(v)
    except Exception:
        return default


def to_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default

