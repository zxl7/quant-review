#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
配置层（数据源 / 过滤口径 / 权重阈值）

原则：
- 所有“口径”与“常量”集中在这里，避免散落在各模块导致难以维护。
- **敏感信息不落库**：token 必须来自环境变量（例如 BIYING_TOKEN），避免误提交。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .env import load_dotenv_if_needed, read_dotenv


def _env(name: str, default: str = "") -> str:
    """
    纯函数：读取环境变量并做 strip。
    说明：集中封装便于后续统一处理（例如支持多别名、或记录缺失项）。
    """
    return (os.getenv(name) or default).strip()


def _read_dotenv_if_exists() -> dict[str, str]:
    """
    读取项目根目录的 .env（如果存在），用于“自动化本地运行”。

    说明：
    - 只在环境变量缺失时作为 fallback
    - .env 属于敏感信息文件，应保持在 .gitignore 中
    """
    dotenv_path = Path(__file__).resolve().parent.parent / ".env"
    return read_dotenv(dotenv_path)


@dataclass(frozen=True)
class AppConfig:
    base_url: str = "https://api.biyingapi.com"
    # 重要：不要在代码里写 token，避免泄露；运行时通过环境变量 BIYING_TOKEN 注入
    token: str = ""

    # 题材清洗口径
    noise_prefixes: tuple[str, ...] = (
        "A股-分类",
        "A股-指数成分",
        "A股-证监会行业",
        "A股-申万行业",
        "A股-申万二级",
        "A股-地域板块",
        "基金-",
        "港股-",
        "美股-",
        "A股-概念板块",
    )
    noise_themes: set[str] = frozenset(
        {
            "小盘",
            "中盘",
            "大盘",
            "融资融券",
            "QFII持股",
            "基金重仓",
            "年度强势",
            "深股通",
            "沪股通",
            "富时罗素",
        }
    )
    exclude_theme_names: set[str] = frozenset({"昨日涨停", "昨日连板"})


def load_config_from_env() -> AppConfig:
    """
    从环境变量加载配置（推荐方式）。

    支持的环境变量：
    - BIYING_BASE_URL: API 根地址（可选）
    - BIYING_TOKEN: API token（必填，调用接口时会校验）
    """
    dotenv_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv_if_needed(dotenv_path=dotenv_path, required_keys=("BIYING_TOKEN",))
    dotenv = _read_dotenv_if_exists() if not _env("BIYING_TOKEN") else {}
    return AppConfig(
        base_url=_env("BIYING_BASE_URL", dotenv.get("BIYING_BASE_URL", "https://api.biyingapi.com")),
        token=_env("BIYING_TOKEN", dotenv.get("BIYING_TOKEN", "")),
    )


DEFAULT_CONFIG = load_config_from_env()
