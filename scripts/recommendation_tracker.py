#!/usr/bin/env python3
"""
系统推荐命中率追踪脚本
记录系统推荐标的及后续走势，每周生成命中率小结

用法:
  # 添加推荐记录
  python3 recommendation_tracker.py --add --date 20260601 --name "中金电子" --code 002498 --price 25.30 --reason "系统选股模块推荐"

  # 更新推荐结果（指定当前价格）
  python3 recommendation_tracker.py --update --name "中金电子" --current-price 27.50

  # 生成本周小结
  python3 recommendation_tracker.py --weekly

  # 查看所有推荐记录
  python3 recommendation_tracker.py --list
"""

import json
import sys
import os
import argparse
from datetime import datetime, timedelta

TRACKER_FILE = "/Users/zxl/Desktop/private/quant-review/cache/recommendation_tracker.json"


def load_tracker() -> dict:
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE) as f:
            return json.load(f)
    return {"records": []}


def save_tracker(data: dict):
    os.makedirs(os.path.dirname(TRACKER_FILE), exist_ok=True)
    with open(TRACKER_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_record(date_str: str, name: str, code: str, price: float, reason: str):
    data = load_tracker()
    # 检查是否已存在
    for r in data["records"]:
        if r["name"] == name and r["date"] == date_str:
            print(f"已存在: {name} {date_str} 的推荐记录")
            return
    data["records"].append({
        "date": date_str,
        "name": name,
        "code": code,
        "recommend_price": price,
        "current_price": None,
        "pnl_pct": None,
        "reason": reason,
        "status": "pending",
        "updated_at": None,
    })
    save_tracker(data)
    print(f"已添加: {name}({code}) 推荐价{price}")


def update_record(name: str, current_price: float):
    data = load_tracker()
    found = False
    for r in data["records"]:
        if r["name"] == name and r["status"] == "pending":
            r["current_price"] = current_price
            rec_price = r["recommend_price"]
            if rec_price and rec_price > 0:
                r["pnl_pct"] = round((current_price - rec_price) / rec_price * 100, 2)
            r["status"] = "closed"
            r["updated_at"] = datetime.now().strftime("%Y-%m-%d")
            found = True
            print(f"已更新: {name} 推荐价{rec_price} → 当前{current_price} 盈亏{r['pnl_pct']}%")
            break
    if not found:
        print(f"未找到待更新的记录: {name}")
    save_tracker(data)


def weekly_report():
    data = load_tracker()
    records = data.get("records", [])
    if not records:
        print("暂无推荐记录")
        return

    # 按日期排序
    records.sort(key=lambda x: x["date"])

    # 本周范围
    today = datetime.now()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    week_records = [r for r in records
                    if week_start.strftime("%Y%m%d") <= r["date"] <= week_end.strftime("%Y%m%d")]

    print(f"=== 系统推荐周报 ({week_start.strftime('%m.%d')}-{week_end.strftime('%m.%d')}) ===\n")

    if not week_records:
        print("本周无推荐记录")
        return

    # 表格输出
    print(f"{'日期':>10} | {'标的':>8} | {'推荐价':>8} | {'当前价':>8} | {'盈亏%':>8} | {'状态':>6}")
    print("-" * 70)

    hit = 0
    total = 0
    for r in week_records:
        if r["status"] == "closed":
            total += 1
            if r["pnl_pct"] and r["pnl_pct"] > 0:
                hit += 1

        date_display = f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:8]}"
        rec_price = f"{r['recommend_price']:.2f}" if r["recommend_price"] else "?"
        cur_price = f"{r['current_price']:.2f}" if r["current_price"] else "—"
        pnl = f"{r['pnl_pct']:.2f}" if r["pnl_pct"] is not None else "—"
        status = r["status"]

        print(f"{date_display:>10} | {r['name']:>8} | {rec_price:>8} | {cur_price:>8} | {pnl:>8} | {status:>6}")

    if total > 0:
        print(f"\n命中率: {hit}/{total} = {hit/total*100:.1f}%")


def list_all():
    data = load_tracker()
    records = data.get("records", [])
    if not records:
        print("暂无推荐记录")
        return
    for r in records:
        pnl = f"{r['pnl_pct']:.2f}%" if r["pnl_pct"] is not None else "—"
        print(f"{r['date']} {r['name']}({r['code']}) 推荐价{r['recommend_price']} 当前{r['current_price'] or '—'} {pnl} [{r['status']}]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="系统推荐命中率追踪")
    parser.add_argument("--add", action="store_true")
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--weekly", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--name", default=None)
    parser.add_argument("--code", default="")
    parser.add_argument("--price", type=float, default=0)
    parser.add_argument("--current-price", type=float, default=0)
    parser.add_argument("--reason", default="")
    args = parser.parse_args()

    if args.add:
        if not args.name:
            print("--add 需要 --name 参数", file=sys.stderr)
            sys.exit(1)
        add_record(args.date, args.name, args.code, args.price, args.reason)
    elif args.update:
        if not args.name:
            print("--update 需要 --name 参数", file=sys.stderr)
            sys.exit(1)
        update_record(args.name, args.current_price)
    elif args.weekly:
        weekly_report()
    elif args.list:
        list_all()
    else:
        parser.print_help()
