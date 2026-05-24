#!/usr/bin/env python3
"""预取东方财富"明天炒什么"数据，写入 JSON 供前端注入。"""

import json
import sys
import time
import urllib.request

API_BASE = "https://emcfgdata.eastmoney.com/api/themeInvest"


def fetch_themes(page_size: int = 15) -> list[dict]:
    ts = str(int(time.time() * 1000))
    rc = ts + str(int(time.time())) + "prefetch"
    body = json.dumps({
        "args": {"pageSize": page_size, "lastTradeDate": ""},
        "client": "wap",
        "clientType": "cfw",
        "clientVersion": "9001",
        "randomCode": rc[:32],
        "timestamp": ts,
    }).encode()
    req = urllib.request.Request(
        f"{API_BASE}/getFryTomorrowList",
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
            "Referer": "https://wap.eastmoney.com/",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("code") != 0:
        print(f"API error: {data.get('message')}", file=sys.stderr)
        return []

    themes = []
    raw = data.get("data") or []
    if not isinstance(raw, list):
        raw = [raw[k] for k in sorted((k for k in raw if str(k).isdigit()), key=lambda k: int(k))]
    for item in raw:
        if not item:
            continue
        themes.append({
            "id": item.get("eid", str(item.get("sortNum", ""))),
            "rank": item.get("sortNum", 0),
            "title": item.get("title", ""),
            "summary": item.get("summary", ""),
            "tradeDate": item.get("tradeDate", ""),
            "themeCode": item.get("themeCode", ""),
            "themeName": item.get("themeName", ""),
            "ztCount": item.get("fex3", 0),
            "gain": item.get("f3", 0),
            "cumulateGain": item.get("cumulateF3", 0),
            "isHot": item.get("isHot") in (1, "1", True),
            "previewStocks": [
                {
                    "code": (s.get("code", "") or "").replace(".SH", "").replace(".SZ", ""),
                    "name": s.get("name", ""),
                    "gain": s.get("f3", 0),
                }
                for s in (item.get("stockList") or [])
            ],
        })
    return themes


def fetch_stocks(theme_code: str) -> list[dict]:
    ts = str(int(time.time() * 1000))
    rc = ts + str(int(time.time())) + "prefetch"
    body = json.dumps({
        "args": {"themeCode": theme_code, "pageSize": 200, "pageNum": 1, "sort": -1, "sortField": "f3"},
        "client": "web",
        "clientType": "cfw",
        "clientVersion": "8.3",
        "randomCode": rc[:20],
        "timestamp": ts,
    }).encode()
    req = urllib.request.Request(
        f"{API_BASE}/getStockList",
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://wap.eastmoney.com/",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("code") != 0:
        return []

    stocks = []
    stock_data = data.get("data", {})
    stock_list = stock_data.get("stockList") if isinstance(stock_data, dict) else []
    for s in stock_list:
        reasons = [
            k.get("introduction", "")
            for k in (s.get("keywordList") or [])
            if k.get("keyword") == "入选理由"
        ]
        stocks.append({
            "code": (s.get("securityCode", "") or "").replace(".SH", "").replace(".SZ", ""),
            "name": s.get("securityName", ""),
            "gain": s.get("f3", 0),
            "price": s.get("f2", 0),
            "marketCap": s.get("f20", 0),
            "industry": s.get("f100", ""),
            "label": s.get("label", ""),
            "reason": "；".join(reasons) if reasons else "涨停",
        })
    return stocks


def main():
    themes = fetch_themes()
    if not themes:
        print("❌ No themes fetched", file=sys.stderr)
        return 1

    # 取前 3 个热门主题的股票详情
    hot = [t for t in themes if t.get("isHot")][:3]
    if not hot:
        hot = themes[:3]

    for t in hot:
        t["stocks"] = fetch_stocks(t["themeCode"])

    output = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "themes": themes,
    }

    out_path = sys.argv[1] if len(sys.argv) > 1 else "tomorrow_picks.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ {len(themes)} themes → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
