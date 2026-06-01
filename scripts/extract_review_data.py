#!/usr/bin/env python3
"""
quant-review 数据提取脚本
从 market_data JSON 中提取核心复盘数字，输出为简单文本供公众号写作直接读取

用法:
  python3 extract_review_data.py [--date YYYYMMDD] [--json market_data路径]

输出:
  标准输出，格式化的核心数据摘要
"""

import json
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime


def load_data(date_str: str, json_path: str = None) -> dict:
    """加载市场数据，优先用指定路径，其次线上，最后本地缓存"""
    if json_path and os.path.exists(json_path):
        with open(json_path) as f:
            return json.load(f)

    # 尝试线上
    import urllib.request
    url = f"https://raw.githubusercontent.com/zxl7/quant-review/gh-pages/cache/market_data-{date_str}.json"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        pass

    # 尝试本地缓存
    local = f"/Users/zxl/Desktop/private/quant-review/cache/market_data-{date_str}.json"
    if os.path.exists(local):
        with open(local) as f:
            return json.load(f)

    print(f"ERROR: 找不到 {date_str} 的市场数据", file=sys.stderr)
    sys.exit(1)


def extract(d: dict) -> str:
    """提取核心数据，输出格式化文本"""
    lines = []

    # 日期
    date = d.get("date", "?")
    lines.append(f"日期: {date}")

    # 三大指数
    lines.append("\n=== 三大指数 ===")
    for idx in d.get("indices", []):
        name = idx.get("name", "?")
        val = idx.get("val", "?")
        chg = idx.get("chg", "?")
        lines.append(f"  {name}: {val} ({chg})")

    # 涨跌停全景
    p = d.get("panorama", {})
    lines.append("\n=== 涨跌停全景 ===")
    lines.append(f"  涨停: {p.get('limitUp', '?')}家")
    lines.append(f"  跌停: {p.get('limitDown', '?')}家")
    lines.append(f"  炸板: {p.get('broken', '?')}家")
    lines.append(f"  封板率: {p.get('ratio', '?')}")

    # 量能
    v = d.get("volume", {})
    lines.append("\n=== 量能 ===")
    lines.append(f"  成交额: {v.get('total', '?')}亿")
    lines.append(f"  变化: {v.get('increase', '?')}")

    # 情绪
    m = d.get("mood", {})
    score = m.get("score", "?")
    heat = m.get("heat", "?")
    risk = m.get("risk", "?")
    lines.append("\n=== 情绪 ===")
    lines.append(f"  评分: {score}")
    lines.append(f"  热度: {heat} | 风险: {risk}")

    headline = d.get("headline", "")
    if headline:
        lines.append(f"  盘面定性: {headline}")

    # 高度 - 从天梯推导
    ladder = d.get("ladder", [])
    max_board = "?"
    board_count = len(ladder) if ladder else "?"
    if ladder and isinstance(ladder, list) and len(ladder) > 0:
        badges = [item.get("badge", 0) for item in ladder if isinstance(item, dict)]
        if badges:
            max_board = max(badges)
    lines.append("\n=== 连板高度 ===")
    lines.append(f"  最高板: {max_board}板")
    lines.append(f"  连板家数: {board_count}家")

    # 题材TOP8（过滤无关）
    skip = {"每日互动", "融资融券", "小盘", "中盘", "沪股通", "深股通",
            "转融券", "含可转债", "大盘", "超级大盘", "预盈预增"}
    lines.append("\n=== 题材TOP8 ===")
    count = 0
    for s in d.get("sectors", []):
        name = s.get("name", "")
        if name in skip:
            continue
        cnt = s.get("count", "?")
        chg = s.get("chg", "?")
        lines.append(f"  {name}: {cnt}家 (涨幅{chg})")
        count += 1
        if count >= 8:
            break

    # 连板天梯
    lines.append("\n=== 连板天梯 ===")
    ladder = d.get("ladder", [])
    if isinstance(ladder, list):
        for item in ladder[:10]:
            if isinstance(item, dict):
                badge = item.get("badge", "?")
                name = item.get("name", "?")
                code = item.get("code", "?")
                zf = item.get("zf", "?")
                if isinstance(zf, float):
                    zf = f"{zf:.2f}"
                status = item.get("status", "")
                lines.append(f"  {badge}板: {name}({code}) 涨{zf}% {status}")

    return "\n".join(lines)


def extract_json(d: dict) -> dict:
    """提取核心数据，返回结构化 dict，供程序读取"""
    result = {
        "date": d.get("date", "?"),
        "indices": [],
        "panorama": d.get("panorama", {}),
        "volume": d.get("volume", {}),
        "mood": d.get("mood", {}),
        "headline": d.get("headline", ""),
        "heightTrend": d.get("heightTrend", {}),
        "topSectors": [],
    }
    for idx in d.get("indices", []):
        result["indices"].append({
            "name": idx.get("name", "?"),
            "val": idx.get("val", "?"),
            "chg": idx.get("chg", "?"),
        })
    skip = {"每日互动", "融资融券", "小盘", "中盘", "沪股通", "深股通",
            "转融券", "含可转债", "大盘", "超级大盘", "预盈预增"}
    for s in d.get("sectors", []):
        if s.get("name", "") in skip:
            continue
        result["topSectors"].append(s)
        if len(result["topSectors"]) >= 8:
            break
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="提取 quant-review 核心复盘数据")
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"), help="日期 YYYYMMDD")
    parser.add_argument("--json", default=None, help="market_data JSON 文件路径")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="输出格式")
    args = parser.parse_args()

    data = load_data(args.date, args.json)

    if args.format == "json":
        print(json.dumps(extract_json(data), ensure_ascii=False, indent=2))
    else:
        print(extract(data))
