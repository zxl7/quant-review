#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

"""
模块协议：requires/provides + compute(ctx)->patch

约定：
- requires/provides 使用“点路径”描述依赖/产物，例如：
  - requires: ["features.style_inputs"]
  - provides: ["marketData.styleRadar"]
- compute 返回 patch（dict），key 同样使用点路径
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from .context import Context


ComputeFn = Callable[[Context], Dict[str, Any]]


@dataclass(frozen=True)
class Module:
    name: str
    requires: List[str]
    provides: List[str]
    compute: ComputeFn

