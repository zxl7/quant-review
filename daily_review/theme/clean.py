#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
题材清洗口径
"""

from __future__ import annotations

from typing import Optional

from ..config import AppConfig, DEFAULT_CONFIG


def clean_theme(name: str, cfg: AppConfig = DEFAULT_CONFIG) -> Optional[str]:
    if not name:
        return None
    if name in cfg.exclude_theme_names:
        return None
    for p in cfg.noise_prefixes:
        if name.startswith(p):
            return None
    if name.startswith("A股-热门概念-"):
        return name.replace("A股-热门概念-", "")
    return name

