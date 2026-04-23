#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
cache_io：最小缓存读写封装

说明：
- ARCHITECTURE.md 约束：缓存层只做落盘/复用，不做业务判断
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

