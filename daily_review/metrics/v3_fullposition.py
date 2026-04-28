#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3 满仓三条件共振检测系统

满仓必须同时满足三个条件(AND关系):
1. 指数单边上涨趋势(上证/深证/创业板至少两个站上5日线且方向一致向上)
2. 板块同步启动(主线板块涨停占比>20%且有梯队)
3. 个股人气核心(目标股是主线龙头/成交排名前20/有辨识度)

任意一条不满足 → 不允许满仓。建议最大仓位降至50-80%。
额外安全阀: 情绪评分<7 → 即使三条件满足也不建议满仓
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FullPositionResonance:
    condition_1_index: bool = False       # 条件1: 指数趋势
    condition_2_sector: bool = False      # 条件2: 板块同步
    condition_3_stock: bool = False       # 条件3: 个股人气
    passed: bool = False                   # 三条件全部通过
    passed_count: int = 0                 # 通过几条
    max_recommended_position: float = 0.0 # 建议最大仓位 0-1
    details: Dict[str, Any] = field(default_factory=dict)
    confidence: int = 50


def check_full_position_resonance(
    *,
    indices: Optional[List[Dict]] = None,
    sector_data: Optional[Dict] = None,
    stock_data: Optional[Dict] = None,
    sentiment_score: float = 5.0,
) -> FullPositionResonance:
    """
    检测是否满足满仓三条件共振。

    Args:
        indices: 指数列表，每项含 {name, chg_pct, ma5, ma20}
        sector_data: 主线板块数据，含 zt_ratio, ladder_health, active_days
        stock_data: 目标个股数据，含 is_dragon, volume_rank, consecutive_boards
        sentiment_score: 市场情绪评分 0-10
    """
    details = {}
    passed_count = 0

    # ── 条件1：指数单边上涨趋势 ──
    c1_ok = False
    c1_details = []
    if indices and len(indices) >= 2:
        up_on_ma5 = 0
        up_trend = 0
        for idx in indices:
            price = float(idx.get("price", 0) or 0)
            ma5 = float(idx.get("ma5", 0) or 0)
            chg = float(idx.get("chg_pct", 0) or 0)
            if ma5 > 0 and price > 0:
                on_ma5 = price >= ma5
                trending = chg > 0.3  # 至少微涨
                c1_details.append(f"{idx.get('name', '?')}: {'站上5日线' if on_ma5 else '在5日线下'} ({'+' if chg>=0 else ''}{chg:.1f}%)")
                if on_ma5:
                    up_on_ma5 += 1
                if trending:
                    up_trend += 1
            else:
                c1_details.append(f"{idx.get('name', '?')}: 数据不足")
        
        # 至少2/3主要指数站上5日线且多数向上
        total = min(len(indices), 3)
        c1_ok = (up_on_ma5 >= max(2, (total + 1) // 2)) and (up_trend >= (total + 1) // 2)
    
    details["c1"] = {"ok": c1_ok, "checks": c1_details}
    if c1_ok:
        passed_count += 1

    # ── 条件2：板块同步启动 ──
    c2_ok = False
    if sector_data:
        zt_ratio = float(sector_data.get("zt_ratio", 0) or 0)
        ladder_health = float(sector_data.get("ladder_health", 0) or 0)
        active_days = int(sector_data.get("active_days", 1) or 1)
        c2_ok = (zt_ratio >= 0.20 and ladder_health >= 3 and active_days >= 2)
        details["c2"] = {
            "ok": c2_ok,
            "zt_ratio": f"{zt_ratio*100:.0f}%",
            "ladder_health": round(ladder_health, 1),
            "active_days": active_days,
        }
    else:
        details["c2"] = {"ok": False, "reason": "无板块数据"}
    if c2_ok:
        passed_count += 1

    # ── 条件3：个股人气核心 ──
    c3_ok = False
    if stock_data:
        is_dragon = bool(stock_data.get("is_dragon", False) or stock_data.get("is_sector_leader", False))
        vol_rank = int(stock_data.get("volume_rank", 999) or 999)
        boards = int(stock_data.get("consecutive_boards", 0) or 0)
        c3_ok = is_dragon or vol_rank <= 20 or boards >= 3
        details["c3"] = {
            "ok": c3_ok,
            "is_dragon": is_dragon,
            "volume_rank": vol_rank,
            "consecutive_boards": boards,
        }
    else:
        details["c3"] = {"ok": False, "reason": "无个股数据"}
    if c3_ok:
        passed_count += 1

    # 综合判定
    all_passed = passed_count == 3

    # 安全阀：情绪不够高时不建议满仓
    safe_valve = sentiment_score < 7
    
    # 计算推荐仓位
    if all_passed and not safe_valve:
        max_pos = 1.00
    elif passed_count >= 2:
        max_pos = 0.70 if not safe_valve else 0.50
    elif passed_count >= 1:
        max_pos = 0.40 if not safe_valve else 0.25
    else:
        max_pos = 0.15

    conf = min(90, 45 + passed_count * 15)

    return FullPositionResonance(
        condition_1_index=c1_ok,
        condition_2_sector=c2_ok,
        condition_3_stock=c3_ok,
        passed=all_passed and not safe_valve,
        passed_count=passed_count,
        max_recommended_position=max_pos,
        details=details,
        confidence=conf,
    )
