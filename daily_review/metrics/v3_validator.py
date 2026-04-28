#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3 数据校验层 — SentimentInput.validate() 实现

对每日输入数据做完整性校验，缺失字段给出警告而非崩溃。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SentimentInput:
    """每日收盘后需要采集的基础数据（v3.0完整版）"""
    # === 涨停相关 ===
    zt_count: int = 0              # 今日涨停家数（不含ST）[必填]
    zt_count_yesterday: int = 0    # 昨日涨停家数 [必填]
    lianban_count: int = 0         # 今日连板家数 [必填]
    max_lianban: int = 0           # 今日最高连板数 [必填]

    # === 炸板相关 ===
    zab_count: int = 0             # 今日炸板家数 [必填]
    try_zt_total: int = 0          # 今日尝试涨停总数 [必填]
    zab_rate: float = 0.0          # 炸板率 %

    # === 昨日反馈（核心！）===
    yest_zt_avg_chg: float = 0.0   # 昨日涨停票今日平均涨幅%
    yest_lianban_promote_rate: float = 0.0  # 晋级率%
    yest_duanban_nuclear: int = 0   # 昨日断板票今日核按钮(<-5%低开)家数

    # === 跌停相关 ===
    dt_count: int = 0              # 今日非ST跌停家数

    # === 高度趋势（近5日）===
    height_history: List[int] = field(default_factory=list)

    # === 主线判断辅助 ===
    main_theme_clear: bool = False
    main_theme_strength: str = "无"  # "强" / "中" / "弱" / "无"
    theme_rotation_freq: int = 0   # 近5日主线切换次数

    # === 特殊事件标志 ===
    has_tiandiban: bool = False    # 天地板
    has_ditianban: bool = False    # 地天板
    has_waipan_shock: bool = False # 外盘冲击
    is_weekend_ahead: bool = False # 周末效应

    # === 扩展字段（有数据才填）===
    index_drop_3d: Optional[float] = None  # 近3日指数跌幅%
    has_trap_pattern: bool = False  # 诱多形态

    def validate(self) -> Dict[str, Any]:
        """数据完整性校验。返回 {valid, errors, warnings, cleaned}"""
        errors = []
        warnings = []

        # 必填校验
        if self.try_zt_total == 0 and (self.zt_count > 0 or self.zab_count > 0):
            errors.append("try_zt_total应为zt_count+zab_count之和")
        if len(self.height_history) != 5:
            warnings.append(f"height_history需要5个值，当前{len(self.height_history)}个")
        if self.zt_count < 0 or self.dt_count < 0:
            errors.append("涨停/跌停数不能为负")

        # 自动修正
        zab_rate_calc = (self.zab_count / self.try_zt_total * 100) if self.try_zt_total > 0 else 0.0
        if abs(zab_rate_calc - self.zab_rate) > 1:
            self.zab_rate = round(zab_rate_calc, 1)
            warnings.append(f"炸板率自动校正为{self.zab_rate}%")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "cleaned": True,
        }


def validate_and_clean(raw_data: Dict[str, Any]) -> tuple:
    """
    从原始dict构建SentimentInput并校验。
    返回: (SentimentInput实例, 校验结果dict)
    """
    inp = SentimentInput(
        zt_count=int(raw_data.get("zt_count", 0) or 0),
        zt_count_yesterday=int(raw_data.get("zt_count_yesterday", 0) or 0),
        lianban_count=int(raw_data.get("lianban_count", 0) or 0),
        max_lianban=int(raw_data.get("max_lianban", 0) or 0),
        zab_count=int(raw_data.get("zab_count", 0) or 0),
        try_zt_total=int(raw_data.get("try_zt_total", 0) or 0),
        zab_rate=float(raw_data.get("zab_rate", 0) or 0),
        yest_zt_avg_chg=float(raw_data.get("yest_zt_avg_chg", 0) or 0),
        yest_lianban_promote_rate=float(raw_data.get("yest_lianban_promote_rate", 0) or 0),
        yest_duanban_nuclear=int(raw_data.get("yest_duanban_nuclear", 0) or 0),
        dt_count=int(raw_data.get("dt_count", 0) or 0),
        height_history=raw_data.get("height_history", []),
        main_theme_clear=bool(raw_data.get("main_theme_clear", False)),
        main_theme_strength=str(raw_data.get("main_theme_strength", "无")),
        theme_rotation_freq=int(raw_data.get("theme_rotation_freq", 0) or 0),
        has_tiandiban=bool(raw_data.get("has_tiandiban", False)),
        has_ditianban=bool(raw_data.get("has_ditianban", False)),
        has_waipan_shock=bool(raw_data.get("has_waipan_shock", False)),
        is_weekend_ahead=bool(raw_data.get("is_weekend_ahead", False)),
        index_drop_3d=raw_data.get("index_drop_3d"),
        has_trap_pattern=bool(raw_data.get("has_trap_pattern", False)),
    )
    result = inp.validate()
    return inp, result
