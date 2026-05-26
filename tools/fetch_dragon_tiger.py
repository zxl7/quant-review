#!/usr/bin/env python3
"""预取通达信龙虎榜数据，写入 JSON 供前端注入。

用法：
    python3 tools/fetch_dragon_tiger.py [YYYYMMDD] [--out PATH]

输出 schema（与前端 DragonTigerPayload 对齐）：
    {date, updatedAt, dateOptions, rows}
每个 row 包含：yzmc, yyb, sblx, gpdm, gpmc, sc, mrje, mcje, rq
"""

import argparse
import json
import os
import sys
import time
import urllib.request

API = "http://page1.tdx.com.cn:7615/TQLEX?Entry=CWServ.cfg_fx_yzlhb"
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def _post(params: list) -> list:
    body = json.dumps({"Params": params}).encode()
    req = urllib.request.Request(API, data=body, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    if data.get("ErrorCode") != 0:
        return []
    return (data.get("ResultSets") or [{}])[0].get("Content") or []


def fetch_dragon_tiger(date: str = "") -> dict:
    # 获取日期列表
    dates_raw = _post(["rq", "", "", "", "", 0, 20])
    dates = [r[0].split(" ")[0] for r in dates_raw if r and r[0]]

    # 用最新日期取数据
    target = date or (dates[0] if dates else "")
    if not target:
        return {"dates": [], "records": []}

    rows = _post(["yzlhb", target, "", "", "", 0, 1000])
    records = []
    seen: dict[tuple, dict] = {}
    for r in rows:
        if not r or len(r) < 9:
            continue
        key = (str(r[3] or ""), str(r[0] or ""), str(r[1] or ""))
        mrje = float(r[6]) if r[6] is not None else None
        mcje = float(r[7]) if r[7] is not None else None
        if key in seen:
            ex = seen[key]
            if mrje is not None and (ex["mrje"] is None or mrje > ex["mrje"]):
                ex["mrje"] = mrje
            if mcje is not None and (ex["mcje"] is None or mcje > ex["mcje"]):
                ex["mcje"] = mcje
        else:
            seen[key] = {
                "yzmc": str(r[0] or ""),
                "yyb": str(r[1] or ""),
                "sblx": str(r[2] or ""),
                "gpdm": str(r[3] or ""),
                "gpmc": str(r[4] or ""),
                "sc": int(r[5]) if r[5] else 0,
                "mrje": mrje,
                "mcje": mcje,
                "rq": str(r[8] or "").split(" ")[0],
            }
    records = list(seen.values())

    return {"dates": dates, "records": records}


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parse_date_arg(raw: str) -> str:
    """YYYYMMDD / YYYY-MM-DD → YYYY-MM-DD；空串 → 空串"""
    if not raw:
        return ""
    d8 = raw.replace("-", "")
    if len(d8) != 8 or not d8.isdigit():
        raise ValueError(f"日期格式错误: {raw}（期望 YYYYMMDD 或 YYYY-MM-DD）")
    return f"{d8[:4]}-{d8[4:6]}-{d8[6:8]}"


def main():
    parser = argparse.ArgumentParser(description="预取通达信龙虎榜数据")
    parser.add_argument("date", nargs="?", default="", help="日期 YYYYMMDD（默认取 API 最新一天）")
    parser.add_argument(
        "--out",
        default="",
        help="输出文件路径；默认 cache/dragon_tiger-{date8}.json",
    )
    args = parser.parse_args()

    try:
        target_date = _parse_date_arg(args.date)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2

    data = fetch_dragon_tiger(target_date)

    # 决定 d8（用于默认输出路径 + payload.date）
    if target_date:
        d8 = target_date.replace("-", "")
    elif data.get("dates"):
        d8 = data["dates"][0].replace("-", "")
        target_date = data["dates"][0]
    else:
        d8 = ""

    if args.out:
        out = args.out
    else:
        if not d8:
            print("❌ 未能确定日期，无法生成默认输出路径", file=sys.stderr)
            return 1
        cache_dir = os.path.join(ROOT, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        out = os.path.join(cache_dir, f"dragon_tiger-{d8}.json")

    if not data["records"]:
        # 网络失败 → 保留已有缓存不覆盖
        if os.path.exists(out):
            print(f"⚠ 拉取失败，保留已有 {out}", file=sys.stderr)
            return 0
        print("❌ 无龙虎榜数据且无缓存", file=sys.stderr)
        return 1

    # schema 转换：→ 前端 DragonTigerPayload {date, updatedAt, dateOptions, rows}
    payload = {
        "date": target_date,
        "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dateOptions": data["dates"],
        "rows": data["records"],
    }

    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"✅ {len(payload['rows'])} 条龙虎榜 ({len(payload['dateOptions'])} 个日期) → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
