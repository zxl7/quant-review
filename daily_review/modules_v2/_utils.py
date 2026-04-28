#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3 模块适配器共享工具

核心功能：
- ztgc 字段名映射（中文缩写 → 英文标准名）
- 统一的 stock 数据标准化接口
"""

from __future__ import annotations
from typing import Any, Dict, List

# biyingapi 原始字段 → v3 metrics 期望字段的映射表
ZTGC_FIELD_MAP: Dict[str, str] = {
    "dm": "code",              # 股票代码
    "mc": "name",              # 股票名称
    "zf": "change_pct",        # 涨跌幅 %
    "p": "price",              # 最新价
    "p": "close",              # 收盘价 (同 price)
    "cje": "amount",           # 成交额 (元)
    "lt": "float_market_cap",  # 流通市值
    "hs": "turnover_rate",     # 换手率 %
    "zsz": "prev_close",       # 昨收价
    "zj": "volume",            # 成交量 (手)
    "fbt": "first_board_time", # 首次封板时间
    "lbt": "last_board_time",  # 最后封板时间/开板时间
    "zbc": "zab_count",        # 炸板次数
    "tj": "stats",             # 统计信息 (如 "2/2")
    "lbc": "consecutive_boards",  # 连板数
    "hy": "sector_name",       # 所属行业/板块
}

# 反向映射（英文 → 原始），用于从已映射数据中取回原始值
REVERSE_MAP: Dict[str, str] = {v: k for k, v in ZTGC_FIELD_MAP.items()}


def map_ztgc_stock(raw: Dict[str, Any]) -> Dict[str, Any]:
    """将单只 ztgc 原始记录映射为 v3 metrics 标准格式。

    同时保留所有原始字段（以原始key为前缀避免冲突），
    确保下游函数无论用哪种命名都能找到数据。
    """
    if not isinstance(raw, dict):
        return {}

    mapped: Dict[str, Any] = {}

    # 1) 先写入标准英文字段
    for raw_key, std_key in ZTGC_FIELD_MAP.items():
        if raw_key in raw:
            mapped[std_key] = raw[raw_key]

    # 2) 兼容性别名
    _aliases: Dict[str, str] = {
        "change_pct": "chg_pct",
        "consecutive_boards": "lbc",
        "amount": "turnover",
    }
    for src, alias in _aliases.items():
        if src in mapped and alias not in mapped:
            mapped[alias] = mapped[src]

    # 3) 保留全部原始字段（确保不丢数据）
    for k, v in raw.items():
        if k not in mapped:
            mapped[k] = v

    return mapped


def map_ztgc_list(raw_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """批量映射 ztgc 列表。"""
    return [map_ztgc_stock(s) for s in raw_list if isinstance(s, dict)]
