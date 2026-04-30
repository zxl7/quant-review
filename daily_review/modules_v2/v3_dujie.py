#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3_dujie 模块：基于v3.0算法规格书的断板/渡劫诊断

对涨停池中连板>=3的股票逐个调用 diagnose_doujie()，
输出每只票的渡劫诊断结果、生命周期阶段及汇总信息。
"""

from __future__ import annotations

from typing import Any, Dict

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module
from daily_review.modules_v2._utils import map_ztgc_list


def _derive_inputs(ctx: Context) -> Dict[str, Any]:
    """从Context中提取渡劫诊断所需数据"""
    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
    raw_ztgc = pools.get("ztgc") or []
    # 关键：字段映射 dm→code, mc→name, zf→chg_pct 等
    return {"ztgc": map_ztgc_list(raw_ztgc)}


def _safe(val: Any) -> Any:
    """递归将 Enum/tuple/dataclass 转为 JSON 可序列化类型"""
    if isinstance(val, (str, int, float, bool, type(None))):
        return val
    if hasattr(val, "value"):  # Enum
        return val.value
    if hasattr(val, "__dataclass_fields__"):  # dataclass
        return {k: _safe(v) for k, v in vars(val).items()}
    if isinstance(val, tuple):
        return [_safe(x) for x in val]
    if isinstance(val, list):
        return [_safe(x) for x in val]
    if isinstance(val, dict):
        return {k: _safe(v) for k, v in val.items()}
    return str(val)


def _compute(ctx: Context) -> Dict[str, Any]:
    """v3 dujie 计算主函数"""
    try:
        from daily_review.metrics.v3_dujie import (
            diagnose_doujie,
            classify_board_pattern,
            identify_life_cycle,
        )

        inputs = _derive_inputs(ctx)
        ztgc = inputs["ztgc"]

        if not ztgc or not isinstance(ztgc, list):
            return {
                "marketData.v3.dujie": {
                    "stocks": [],
                    "summary": {"total_scanned": 0, "qualified_count": 0},
                },
            }

        # 筛选连板 >= 3 的股票
        candidates = [
            s for s in ztgc
            if isinstance(s, dict) and int(s.get("lbc", 0) or 0) >= 3
        ]

        results = []
        for stock in candidates:
            try:
                history = stock.get("history") or [stock]
                if not isinstance(history, list):
                    history = [stock]
                doujie_result = diagnose_doujie(history)
                lifecycle = identify_life_cycle(stock)
                board_pattern = classify_board_pattern(stock)
            except Exception:
                doujie_result = {"type": "UNKNOWN", "survival_prob": 50}
                lifecycle = ("unknown", "数据不足")
                board_pattern = "UNKNOWN"

            results.append({
                "name": stock.get("name", ""),
                "code": stock.get("code", ""),
                "lbc": stock.get("lbc"),
                "doujie_result": _safe(doujie_result),
                "lifecycle": _safe(lifecycle),
                "board_pattern": _safe(board_pattern),
            })

        # 汇总统计
        total_qualified = sum(
            1 for r in results
            if r.get("doujie_result", {}).get("survival_prob", 0) and
               float(r["doujie_result"]["survival_prob"]) >= 50
        )

        return {
            "marketData.v3.dujie": {
                "stocks": results,
                "summary": {
                    "total_scanned": len(candidates),
                    "qualified_count": total_qualified,
                    "max_lbc": max((s.get("lbc", 0) for s in candidates), default=0),
                },
            },
        }
    except Exception as e:
        return {
            "marketData.v3.dujie": {"error": str(e), "confidence": 0},
        }


# 注册Module
V3_DUJIE_MODULE = Module(
    name="v3_dujie",
    requires=["raw.pools.ztgc"],
    provides=["marketData.v3.dujie"],
    compute=_compute,
)
