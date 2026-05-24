#!/usr/bin/env python3
"""预取通达信龙虎榜数据，写入 JSON 供前端注入。"""

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


def main():
    data = fetch_dragon_tiger()
    out = sys.argv[1] if len(sys.argv) > 1 else "dragon_tiger_data.json"

    if not data["records"]:
        # 网络失败 → 保留已有缓存不覆盖
        if os.path.exists(out):
            print(f"⚠ 拉取失败，保留已有 {out}", file=sys.stderr)
            return 0
        print("❌ 无龙虎榜数据且无缓存", file=sys.stderr)
        return 1

    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ {len(data['records'])} 条龙虎榜 ({len(data['dates'])} 个日期) → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
