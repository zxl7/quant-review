#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
题材映射（hszg/zg）：
- 单股题材查询
- 代码归一化（sz000001/sh600519 -> 000001）
- 落盘缓存（跨天复用）
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from ..cache.json_cache import read_json, write_json
from ..config import AppConfig, DEFAULT_CONFIG
from ..http import HttpClient
from .clean import clean_theme


def normalize_stock_code(dm: str) -> str:
    """
    纯函数：把各种股票代码格式统一成 6 位数字代码。

    例：
    - "sz000001" / "sh600519" -> "000001" / "600519"
    - 传入为空 -> ""
    """
    if not dm:
        return ""
    digits = "".join(filter(str.isdigit, str(dm)))
    return digits[-6:] if len(digits) >= 6 else digits


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    """
    纯函数：去重且保序。
    """
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


@dataclass
class ThemeMapper:
    client: HttpClient
    cache_path: Path
    cfg: AppConfig = DEFAULT_CONFIG
    timeout: int = 5

    def load_cache(self) -> Dict[str, List[str]]:
        raw = read_json(self.cache_path)
        codes = raw.get("codes", {}) if isinstance(raw, dict) else {}
        if not isinstance(codes, dict):
            return {}
        # 简单净化：确保 list[str]
        def _clean_list(v: object) -> list[str]:
            if not isinstance(v, list):
                return []
            return [
                t
                for t in v
                if isinstance(t, str)
                and t
                and t not in self.cfg.exclude_theme_names
                and t not in self.cfg.noise_themes
            ]

        return {k: _clean_list(v) for k, v in codes.items()}

    def save_cache(self, codes: Dict[str, List[str]]) -> None:
        write_json(self.cache_path, {"version": 1, "codes": codes})

    def fetch_stock_themes(self, code6: str, codes_cache: Dict[str, List[str]]) -> List[str]:
        if not code6:
            return []
        if code6 in codes_cache:
            return codes_cache[code6]

        url = f"{self.client.base_url}/hszg/zg/{code6}/{self.client.token}"
        data = self.client.get_json(url)
        if not isinstance(data, list):
            codes_cache[code6] = []
            return []

        # 提取 + 清洗（尽量保持纯函数风格）
        result = [
            t
            for t in (clean_theme((item or {}).get("name", ""), self.cfg) for item in data)
            if t and t not in self.cfg.noise_themes
        ]
        uniq = _dedupe_preserve_order(result)

        codes_cache[code6] = uniq
        return uniq
