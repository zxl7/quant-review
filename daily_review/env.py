#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
环境变量与 .env 支持（偏函数式实现）

目标：
- 允许本地通过 .env 注入 BIYING_TOKEN 等敏感配置
- 避免在代码里硬编码 token
- 将“解析”与“写入 os.environ（副作用）”分离
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Sequence


def parse_dotenv(text: str) -> dict[str, str]:
    """
    纯函数：解析 .env 文本（KEY=VALUE 行），返回键值对。

    约定：
    - 忽略空行与 # 注释行
    - 忽略不包含 '=' 的行
    - VALUE 支持单/双引号包裹（会去掉最外层引号）
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        val = v.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if key:
            out[key] = val
    return out


def read_dotenv(path: Path) -> dict[str, str]:
    """
    纯函数（IO 除外）：读取 .env 文件并解析。
    - 文件不存在时返回 {}
    - 读取/解析失败时返回 {}
    """
    if not path.exists():
        return {}
    try:
        return parse_dotenv(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_dotenv_if_needed(
    *,
    dotenv_path: Path,
    required_keys: Sequence[str],
    environ: Mapping[str, str] | None = None,
) -> None:
    """
    将 dotenv_path 中的键值写入 os.environ（副作用），但仅在 required_keys 缺失时才加载。

    - required_keys 都已存在：不做任何事
    - required_keys 任一缺失：尝试读取 .env，并用 setdefault 写入（不覆盖已存在环境变量）
    """
    env = os.environ if environ is None else dict(environ)
    if all((env.get(k) or "").strip() for k in required_keys):
        return

    kv = read_dotenv(dotenv_path)
    for k, v in kv.items():
        os.environ.setdefault(k, v)

