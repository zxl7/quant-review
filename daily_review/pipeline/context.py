#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

"""
Context：统一数据容器（raw/features/marketData）

设计目标：
- 数据传递显式化：模块只能从 ctx 中取数据
- 便于 partial：缓存 ctx.marketData/features/raw 后，可局部重算模块
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


def get_path(obj: Dict[str, Any], path: str, default: Any = None) -> Any:
    """
    获取 dict 的点路径：a.b.c
    """
    cur: Any = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def set_path(obj: Dict[str, Any], path: str, value: Any) -> None:
    """
    设置 dict 的点路径：a.b.c
    """
    parts = path.split(".")
    cur: Any = obj
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


@dataclass
class Context:
    meta: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)
    features: Dict[str, Any] = field(default_factory=dict)
    market_data: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "meta": self.meta,
            "raw": self.raw,
            "features": self.features,
            "marketData": self.market_data,
        }

    @staticmethod
    def from_market_data(market_data: Dict[str, Any]) -> "Context":
        """
        兼容现有缓存：目前缓存的是 marketData（含 features）。
        """
        return Context(
            meta={"date": market_data.get("date"), "dateNote": market_data.get("dateNote", "")},
            raw=market_data.get("raw", {}) or {},
            features=market_data.get("features", {}) or {},
            market_data=market_data,
        )

