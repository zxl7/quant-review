#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3 同花顺自选股同步模块

每次 Pipeline 完成后，自动从 v3 算法结果中提取
龙头候选 + 主线龙头，生成同花顺导入格式文件。

同花顺网页版导入格式（TXT）：
  每行一个股票代码，带市场标识
  上交所: sh600519
  深交所: sz000858
  科创板: sh688981
  创业板: sz300750
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from daily_review.pipeline.context import Context
from daily_review.pipeline.module import Module


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _normalize_code(code: str) -> str:
    """将 6 位代码转为同花顺格式: sh600519 / sz000858"""
    code = str(code).strip()
    if not code or len(code) < 6:
        return ""
    # 去掉可能的前缀
    for pfx in ("sh", "sz", "bj", "sh", "sz"):
        if code.startswith(pfx):
            code = code[len(pfx):]
    code6 = code[:6]
    # 判断市场
    prefix = code6[0]
    if prefix == "6":          # 上海主板 / 科创板
        return f"sh{code6}"
    elif prefix == "0":      # 深圳主板 / 创业板
        return f"sz{code6}"
    elif prefix == "3":      # 创业板
        return f"sz{code6}"
    elif prefix == "8":      # 北交所
        return f"bj{code6}"
    elif prefix == "4":      # 新三板
        return f"bj{code6}"
    else:
        return f"sh{code6}"   # 默认上海


def _extract_stocks_from_v3(market_data: Dict) -> List[Dict[str, Any]]:
    """
    从 marketData.v3 中提取推荐标的。
    返回: [{"code": "sh600519", "name": "贵州茅台", "source": "dragon"}, ...]
    """
    results: List[Dict] = []
    v3 = market_data.get("v3")
    if not isinstance(v3, dict):
        return []
    seen: set = set()

    # 1. 龙头三要素候选（优先级最高）
    dragon = v3.get("dragon")
    if not isinstance(dragon, dict):
        dragon = {}
    for r in (dragon.get("rankings") or []):
        code = str(r.get("code", "")).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        results.append({
            "code": _normalize_code(code),
            "raw_code": code,
            "name": r.get("name", ""),
            "source": "dragon",
            "score": (r.get("score") or {}).get("overall", 0),
            "grade": (r.get("score") or {}).get("grade", "?"),
        })

    # 2. 主流主线龙头
    mainstream = v3.get("mainstream")
    if not isinstance(mainstream, dict):
        mainstream = {}
    sector = mainstream.get("sector_ladder")
    if not isinstance(sector, dict):
        sector = {}
    dragon_info = sector.get("dragon")
    if not isinstance(dragon_info, dict):
        dragon_info = {}
    if dragon_info.get("name"):
        code = str(dragon_info.get("code", "")).strip()
        if code and code not in seen:
            seen.add(code)
            results.append({
                "code": _normalize_code(code),
                "raw_code": code,
                "name": dragon_info.get("name", ""),
                "source": "mainstream",
                "score": 0,
                "grade": "主线龙头",
            })

    # 3. 渡劫诊断中存活率高的股票（补充）
    dujie = v3.get("dujie")
    if not isinstance(dujie, dict):
        dujie = {}
    for s in (dujie.get("stocks") or []):
        code = str(s.get("code", "")).strip()
        if not code or code in seen:
            continue
        surv = (s.get("doujie_result") or {}).get("survival_prob", 0)
        if surv >= 50:   # 只加存活率>=50%的
            seen.add(code)
            results.append({
                "code": _normalize_code(code),
                "raw_code": code,
                "name": s.get("name", ""),
                "source": "dujie",
                "score": surv,
                "grade": f"存活{surv}%",
            })

    return results


def _write_tonghuashun_file(stocks: List[Dict], output_path: str) -> Dict[str, Any]:
    """
    生成同花顺导入文件（TXT 格式）。
    返回: {"success": bool, "path": str, "count": int, "content": str}
    """
    lines = []
    for s in stocks:
        code = s["code"]
        name = s.get("name", "")
        # 同花顺导入格式：代码 + 可选名称
        lines.append(f"{code} {name}".strip())

    content = "\n".join(lines) + "\n" if lines else ""

    try:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {
            "success": True,
            "path": str(p),
            "count": len(lines),
            "content": content,
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "path": output_path,
            "count": 0,
            "content": "",
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Pipeline Module 适配层
# ---------------------------------------------------------------------------

def _compute(ctx: Context) -> Dict[str, Any]:
    """
    v3 同花顺同步模块：从 v3 结果提取推荐标的，生成导入文件。
    """
    md = ctx.market_data or {}
    date_str = ctx.meta.get("date", "unknown")

    # 输出目录：quant-review/output/tonghuashun/
    project_root = Path(__file__).resolve().parent.parent.parent
    out_dir = project_root / "output" / "tonghuashun"
    out_file = out_dir / f"sync-{date_str}.txt"

    # 提取股票
    stocks = _extract_stocks_from_v3(md)

    if not stocks:
        return {
            "marketData.v3.tonghuashun_sync": {
                "success": False,
                "count": 0,
                "path": None,
                "stocks": [],
                "message": "v3 数据中无推荐标的，未生成文件",
                "confidence": 0,
            },
        }

    # 写入文件
    result = _write_tonghuashun_file(stocks, str(out_file))

    return {
        "marketData.v3.tonghuashun_sync": {
            "success": result["success"],
            "count": result["count"],
            "path": result["path"],
            "stocks": stocks[:20],   # 只保留前20只，避免 context 过大
            "all_codes": [s["code"] for s in stocks],
            "message": (
                f"已生成 {result['count']} 只标的导入文件: {result['path']}"
                if result["success"]
                else f"写入失败: {result['error']}"
            ),
            "confidence": 90 if result["success"] else 0,
            "import_command": (
                f"前往 同花顺网页版 → 自选股 → 导入 → 选择文件: {result['path']}"
                if result["success"]
                else ""
            ),
        },
    }


# ---------------------------------------------------------------------------
# Module 注册
# ---------------------------------------------------------------------------

TONGHUASHUN_SYNC_MODULE = Module(
    name="v3_tonghuashun_sync",
    requires=["marketData.v3.dragon", "marketData.v3.mainstream", "marketData.v3.dujie"],
    provides=["marketData.v3.tonghuashun_sync"],
    compute=_compute,
)
