#!/usr/bin/env python3
"""
持仓快照管理脚本
支持创建、读取持仓快照，供公众号复盘写作和盯盘系统使用

用法:
  # 创建持仓快照（交互式）
  python3 position_snapshot.py --create --date 20260601

  # 从JSON文件创建
  python3 position_snapshot.py --create --date 20260601 --input positions.json

  # 读取最新快照
  python3 position_snapshot.py --read

  # 读取指定日期快照
  python3 position_snapshot.py --read --date 20260601
"""

import json
import sys
import os
import argparse
from datetime import datetime

CACHE_DIR = "/Users/zxl/Desktop/private/quant-review/cache"


def snapshot_path(date_str: str) -> str:
    return os.path.join(CACHE_DIR, f"positions-{date_str}.json")


def create_snapshot(date_str: str, input_file: str = None):
    """创建持仓快照"""
    if input_file and os.path.exists(input_file):
        with open(input_file) as f:
            positions = json.load(f)
    else:
        # 交互式输入
        print("请输入持仓信息（空行结束）：")
        positions = {"date": date_str, "positions": []}
        while True:
            name = input("股票名（回车结束）: ").strip()
            if not name:
                break
            code = input("代码: ").strip()
            pnl = input("累计盈亏%: ").strip()
            chg = input("今日涨跌%: ").strip()
            note = input("备注: ").strip()
            positions["positions"].append({
                "name": name,
                "code": code,
                "pnl_pct": float(pnl) if pnl else 0,
                "today_chg": float(chg) if chg else 0,
                "note": note,
            })

    os.makedirs(CACHE_DIR, exist_ok=True)
    path = snapshot_path(date_str)
    with open(path, "w") as f:
        json.dump(positions, f, ensure_ascii=False, indent=2)
    print(f"持仓快照已保存: {path}")


def read_snapshot(date_str: str = None):
    """读取持仓快照"""
    if date_str:
        path = snapshot_path(date_str)
        if not os.path.exists(path):
            print(f"未找到 {date_str} 的持仓快照", file=sys.stderr)
            sys.exit(1)
    else:
        # 找最新的
        files = sorted([f for f in os.listdir(CACHE_DIR) if f.startswith("positions-")])
        if not files:
            print("未找到任何持仓快照", file=sys.stderr)
            sys.exit(1)
        path = os.path.join(CACHE_DIR, files[-1])

    with open(path) as f:
        data = json.load(f)

    print(f"日期: {data.get('date', '?')}")
    print(f"持仓数: {len(data.get('positions', []))}只\n")
    for p in data.get("positions", []):
        chg_str = f"+{p['today_chg']}" if p.get("today_chg", 0) > 0 else str(p.get("today_chg", "?"))
        pnl_str = f"+{p['pnl_pct']}" if p.get("pnl_pct", 0) > 0 else str(p.get("pnl_pct", "?"))
        print(f"  {p['name']}({p['code']}) 今日{chg_str}% 累计{pnl_str}%")
        if p.get("note"):
            print(f"    备注: {p['note']}")

    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="持仓快照管理")
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--create", action="store_true", help="创建快照")
    parser.add_argument("--read", action="store_true", help="读取快照")
    parser.add_argument("--input", default=None, help="从JSON文件导入")
    args = parser.parse_args()

    if args.create:
        create_snapshot(args.date, args.input)
    elif args.read:
        read_snapshot(args.date if args.date != datetime.now().strftime("%Y%m%d") else None)
    else:
        parser.print_help()
