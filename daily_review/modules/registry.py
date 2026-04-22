#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模块注册表：用于“部分更新”（只更新某个模块）
"""

from __future__ import annotations

from typing import Callable, Dict, Any

from .style_radar import rebuild_style_radar
from .mood import rebuild_mood_panel
from .leader import rebuild_leaders

ModuleFn = Callable[[Dict[str, Any]], Dict[str, Any]]


REGISTRY: dict[str, ModuleFn] = {
    "style_radar": rebuild_style_radar,
    "mood": rebuild_mood_panel,
    "leader": rebuild_leaders,
}


def available_modules() -> list[str]:
    return sorted(REGISTRY.keys())


def apply_modules(market_data: Dict[str, Any], modules: list[str]) -> Dict[str, Any]:
    """
    返回更新后的 market_data（**不修改入参**，偏函数式风格）。

    约定：
    - 每个模块函数 `fn(market_data) -> patch`
    - patch 只包含需要覆盖的 *顶层 key*（与前端 marketData 契约保持一致）
    """
    updated: Dict[str, Any] = dict(market_data)
    for name in modules:
        fn = REGISTRY.get(name)
        if not fn:
            raise KeyError(f"未知模块: {name}，可选：{', '.join(available_modules())}")
        patch = fn(updated)
        if not isinstance(patch, dict):
            raise TypeError(f"模块 {name} 必须返回 dict patch，实际: {type(patch)}")
        # 纯函数合并：后者覆盖前者
        updated = {**updated, **patch}
    return updated
