#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
龙头模块（部分更新）

输入（来自 market_data）：
- ztgc：涨停池（至少含 dm/mc/zj/hs/zbc/fbt/hy）
- zt_code_themes：涨停股->题材映射（可选，但推荐）
- sectors：热点题材 Top 列表（用于“板块爆发”评估）

输出：
- {"leaders": [...]} 覆盖/新增 marketData.leaders
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.metrics.leader import pick_leaders


def rebuild_leaders(market_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    纯函数（对外表现）：基于现有 market_data 计算 leaders，返回 patch。
    """
    ztgc = market_data.get("ztgc") or []
    code2themes = market_data.get("zt_code_themes") or {}
    hot_sectors = market_data.get("sectors") or []
    ohlc_by_code = ((market_data.get("features") or {}).get("leader_inputs") or {}).get("ohlc_by_code") or {}

    picks = pick_leaders(
        ztgc=ztgc,
        code2themes=code2themes,
        hot_sectors=hot_sectors,
        ohlc_by_code=ohlc_by_code,
        topk=5,
    )
    leaders = [
        {
            "rank": i + 1,
            "code": p.code,
            "name": p.name,
            "theme": p.theme,
            "score": p.score,
            "tags": (p.reason.get("tags") or []),
            "reason": p.reason,
        }
        for i, p in enumerate(picks)
    ]
    return {"leaders": leaders}
