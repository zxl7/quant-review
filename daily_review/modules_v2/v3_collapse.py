#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3_collapse 模块：基于v3.0算法规格书的崩溃前兆链检测

独立封装崩溃前兆链评分（_score_collapse_chain），从情绪输入数据中
检测 L1~L5 级别的崩盘信号，输出详细的风险预警信息。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


def _derive_inputs(ctx: Context) -> Dict[str, Any]:
    """从Context中提取崩溃链检测所需数据"""
    md = ctx.market_data or {}
    mi = (md.get("features") or {}).get("mood_inputs") or {}
    mi = mi if isinstance(mi, dict) else {}

    pools = (ctx.raw.get("pools") or {}) if isinstance(ctx.raw, dict) else {}
    ztgc = pools.get("ztgc") or []

    # 从 ztgc 推断一些字段
    has_tiandiban = False
    for s in ztgc:
        if isinstance(s, dict):
            low = float(s.get("low", 0) or 0)
            high = float(s.get("high", 0) or 0)
            chg = float(s.get("chg", 0) or 0)
            # 天地板：曾涨停(或接近)后跌停/大跌
            if high > 9.5 and (chg < -9.5 or low < -9.5):
                has_tiandiban = True
                break

    hist_zt = mi.get("hist_zt") or mi.get("hist_zt_count") or []
    zt_yest = hist_zt[-2] if isinstance(hist_zt, list) and len(hist_zt) >= 2 else None

    return {
        "zt_count": mi.get("zt_count"),
        "zt_count_yesterday": zt_yest,
        "yest_zt_avg_chg": mi.get("yest_zt_avg_chg"),
        "dt_count": mi.get("dt_count"),
        "max_lianban": mi.get("max_lb"),
        "yest_duanban_nuclear": None,
        "has_trap_pattern": False,
        "has_tiandiban": has_tiandiban,
        "zab_rate": mi.get("zb_rate"),
    }


def _build_collapse_input(inputs: Dict[str, Any]) -> Any:
    """将dict输入转换为 _score_collapse_chain 所需的类对象接口"""
    class _CollapseInput:
        pass

    d = _CollapseInput()
    for k, v in inputs.items():
        setattr(d, k, v if v is not None else 0)
    return d


def _compute(ctx: Context) -> Dict[str, Any]:
    """v3 collapseChain 计算主函数"""
    md = ctx.market_data or {}

    try:
        from daily_review.metrics.v3_sentiment import _score_collapse_chain

        raw_inputs = _derive_inputs(ctx)
        d = _build_collapse_input(raw_inputs)

        score = _score_collapse_chain(d)

        # 构建详细的链式报告
        chain_report = {
            "score": score,
            "level": (
                "CRITICAL" if score <= 2
                else "WARNING" if score <= 4
                else "CAUTION" if score <= 6
                else "NORMAL"
            ),
            "signals": [],
        }

        # 各级信号描述
        if getattr(d, "yest_zt_avg_chg", 0) < 1.0:
            chain_report["signals"].append({
                "level": "L1",
                "name": "追涨亏损",
                "detail": f"昨日涨停票今日平均涨幅仅{d.yest_zt_avg_chg}%",
                "severity": "HIGH" if d.yest_zt_avg_chg < 0 else "MEDIUM",
            })

        if d.zt_count_yesterday and d.zt_count:
            drop_pct = (d.zt_count_yesterday - d.zt_count) / max(1, d.zt_count_yesterday)
            if drop_pct > 0.30:
                chain_report["signals"].append({
                    "level": "L2",
                    "name": "活跃骤降",
                    "detail": f"涨停数环比下降{drop_pct*100:.0f}%",
                    "severity": "HIGH",
                })

        if getattr(d, "has_trap_pattern", False):
            chain_report["signals"].append({
                "level": "L3",
                "name": "诱多形态",
                "detail": "指数冲高回落诱多信号",
                "severity": "MEDIUM",
            })

        if d.max_lianban >= 5 and getattr(d, "yest_duanban_nuclear", 0) >= 2:
            chain_report["signals"].append({
                "level": "L4",
                "name": "高位补跌",
                "detail": f"连板高度{d.max_lianban}板但核按钮{d.yest_duanban_nuclear}家",
                "severity": "HIGH",
            })

        if d.dt_count and d.dt_count >= 20:
            chain_report["signals"].append({
                "level": "L5",
                "name": "大面积崩溃",
                "detail": f"跌停家数达{d.dt_count}家",
                "severity": "CRITICAL",
            })

        if getattr(d, "has_tiandiban", False):
            chain_report["signals"].append({
                "level": "EXTRA",
                "name": "天地板",
                "detail": "出现天地板极端亏钱信号",
                "severity": "CRITICAL",
            })

        # 综合建议
        if score <= 2:
            advice = "极度危险：立即空仓回避，禁止任何开仓操作"
        elif score <= 4:
            advice = "高风险：大幅减仓至1-2成以内，仅允许极轻仓试错"
        elif score <= 6:
            advice = "中等风险：控制仓位在3-5成，严格止损"
        else:
            advice = "风险可控：正常操作，注意仓位管理"

        chain_report["advice"] = advice

        return {
            "marketData.v3.collapseChain": chain_report,
        }
    except Exception as e:
        return {
            "marketData.v3.collapseChain": {"error": str(e), "confidence": 0},
        }


# 注册Module
V3_COLLAPSE_MODULE = Module(
    name="v3_collapse",
    requires=[
        "features.mood_inputs",
        "raw.pools.ztgc",
        "marketData.volume",
        "marketData.indices",
    ],
    provides=["marketData.v3.collapseChain"],
    compute=_compute,
)
