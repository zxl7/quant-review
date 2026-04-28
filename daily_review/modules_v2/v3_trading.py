#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3_trading 模块：基于v3.0算法规格书的交易性质判断

结合涨停池数据、情绪评分和情绪阶段，判断当前市场交易性质
（如：趋势主升 / 震荡轮动 / 情绪博弈 / 趋势破位 等）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _derive_inputs(ctx: Context) -> Dict[str, Any]:
    """从Context中提取交易性质判断所需数据"""
    md = ctx.market_data or {}
    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
    quotes = (ctx.raw.get("quotes") or {}) if isinstance(ctx.raw, dict) else {}

    return {
        "ztgc": pools.get("ztgc") or [],
        "sentiment": md.get("v3", {}).get("sentiment") if isinstance(md.get("v3"), dict) else {},
        "mood_stage": md.get("moodStage") or {},
        "mood": md.get("mood") or {},
        "quotes": quotes.get("items") if isinstance(quotes, dict) else {},
    }


def _compute(ctx: Context) -> Dict[str, Any]:
    """v3 tradingNature 计算主函数"""
    try:
        from daily_review.metrics.v3_trading_nature import determine_trade_nature

        inputs = _derive_inputs(ctx)

        # determine_trade_nature(stock_info: Dict, market_context: Dict)
        # v3 增强：对“高标候选池”批量输出（而不是只取代表股）
        ztgc = inputs["ztgc"] or []
        quotes_map = inputs.get("quotes") or {}

        # 候选：按连板数降序取前 N（默认 20）
        candidates: List[Dict[str, Any]] = []
        if isinstance(ztgc, list):
            rows = [x for x in ztgc if isinstance(x, dict)]
            rows.sort(key=lambda s: int(s.get("lbc", 0) or 0), reverse=True)
            rows = rows[:20]
            for top in rows:
                code6 = str(top.get("dm") or top.get("code") or "")
                # quotes 用 6位代码 key
                from daily_review.data.biying import normalize_stock_code

                c6 = normalize_stock_code(code6)
                q = quotes_map.get(c6) if isinstance(quotes_map, dict) else None
                # pct：优先用实时行情 pc，否则退回涨停池字段
                pct = None
                try:
                    if isinstance(q, dict) and q.get("pc") not in (None, ""):
                        pct = float(q.get("pc"))
                    elif top.get("chg") not in (None, ""):
                        pct = float(top.get("chg"))
                except Exception:
                    pct = None

                stock_info = {
                    "name": top.get("mc") or top.get("name") or "",
                    "code": c6 or code6,
                    "consecutive_boards": int(top.get("lbc", 0) or 0),
                    "chg_pct": float(pct or 0.0),
                    "yest_chg_pct": 0.0,
                    "is_zt": True,  # ztgc 代表涨停池
                    "amount": (q.get("cje") if isinstance(q, dict) else None),
                    "price": (q.get("p") if isinstance(q, dict) else None),
                }
                candidates.append(stock_info)

        rep_stock = candidates[0] if candidates else {}

        sentiment_obj = inputs["sentiment"]
        sentiment_score = (
            float(sentiment_obj.get("score", 5.0))
            if isinstance(sentiment_obj, dict) else 5.0
        )
        phase = (
            sentiment_obj.get("phase", "")
            if isinstance(sentiment_obj, dict) else ""
        )

        market_context = {
            "sentiment_score": sentiment_score,
            "phase": phase,
            "mood_stage": inputs["mood_stage"],
            "mood": inputs["mood"],
        }

        # 代表股判断（用于兼容旧结构）
        result = determine_trade_nature(rep_stock, market_context)

        output = (vars(result) if hasattr(result, "__dataclass_fields__") else result) or {}
        # JSON 兼容：Enum / dataclass 里可能包含不可序列化对象
        try:
            nature_obj = output.get("nature")
            if nature_obj is not None:
                # TradeNature(Enum) 里自定义了 name 属性（中文），_name_ 为枚举键
                output["nature"] = {
                    "code": getattr(nature_obj, "_name_", None),
                    "label": getattr(nature_obj, "name", None),
                    "risk_level": getattr(nature_obj, "risk_level", None),
                    "max_position": getattr(nature_obj, "max_position", None),
                    "stop_loss": getattr(nature_obj, "stop_loss", None),
                    "target_gain": getattr(nature_obj, "target_gain", None),
                }
        except Exception:
            pass

        # 批量候选输出（增强数据量）
        dist: Dict[str, int] = {}
        cand_out: List[Dict[str, Any]] = []
        for s in candidates:
            try:
                r2 = determine_trade_nature(s, market_context)
                o2 = (vars(r2) if hasattr(r2, "__dataclass_fields__") else r2) or {}
                nature_obj = o2.get("nature")
                if nature_obj is not None:
                    code = getattr(nature_obj, "_name_", None)
                    label = getattr(nature_obj, "name", None)
                    o2["nature"] = {"code": code, "label": label}
                    if code:
                        dist[code] = dist.get(code, 0) + 1
                o2["stock"] = {"code": s.get("code"), "name": s.get("name"), "lbc": s.get("consecutive_boards"), "chg_pct": s.get("chg_pct")}
                cand_out.append(o2)
            except Exception:
                continue
        output["candidates"] = cand_out
        output["distribution"] = dist
        output["candidate_count"] = len(cand_out)

        return {"marketData.v3.tradingNature": output}
    except Exception as e:
        return {"marketData.v3.tradingNature": {"error": str(e), "confidence": 0}}


# 注册Module
V3_TRADING_MODULE = Module(
    name="v3_trading",
    requires=[
        "raw.pools.ztgc",
        "marketData.v3.sentiment",
        "marketData.moodStage",
        "marketData.mood",
    ],
    provides=["marketData.v3.tradingNature"],
    compute=_compute,
)
