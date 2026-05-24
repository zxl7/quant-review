#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
API_URL = "http://page1.tdx.com.cn:7615/TQLEX?Entry=CWServ.cfg_fx_yzlhb"
QUOTE_URL = "https://flash-api.xuangubao.cn/api/stock/data"


def normalize_date8(value: str) -> str:
    raw = str(value or "").strip().replace("-", "")
    if len(raw) != 8 or not raw.isdigit():
        raise ValueError(f"非法日期: {value}")
    return raw


def date8_to_date10(date8: str) -> str:
    return f"{date8[0:4]}-{date8[4:6]}-{date8[6:8]}"


def post_json(url: str, payload: dict[str, Any], timeout: int = 20) -> Any:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="ignore")
    return json.loads(text) if text else {}


def get_json(url: str, timeout: int = 20) -> Any:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="ignore")
    return json.loads(text) if text else {}


def rows_from_result(json_data: dict[str, Any]) -> list[dict[str, Any]]:
    result_sets = json_data.get("ResultSets") if isinstance(json_data, dict) else None
    first = result_sets[0] if isinstance(result_sets, list) and result_sets else {}
    cols = first.get("ColName") if isinstance(first.get("ColName"), list) else []
    content = first.get("Content") if isinstance(first.get("Content"), list) else []
    rows: list[dict[str, Any]] = []
    for cells in content:
        if not isinstance(cells, list):
            continue
        row: dict[str, Any] = {}
        for idx, key in enumerate(cols):
            row[str(key)] = cells[idx] if idx < len(cells) else None
        rows.append(row)
    return rows


def normalize_code(value: Any) -> str:
    return str(value or "").strip().replace(".SH", "").replace(".SZ", "").replace(".SS", "")


def to_xgb_symbol(code: str) -> str:
    raw = normalize_code(code)
    if len(raw) != 6 or not raw.isdigit():
        return ""
    return f"{raw}.SS" if raw.startswith("6") else f"{raw}.SZ"


def to_number(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def fetch_quote_map(codes: list[str]) -> dict[str, Any]:
    symbols = [to_xgb_symbol(code) for code in codes]
    symbols = [x for x in symbols if x]
    if not symbols:
        return {}
    url = f"{QUOTE_URL}?fields=symbol,stock_chi_name,change_percent,price&strict=true&symbols={','.join(symbols)}&_ts={int(time.time() * 1000)}"
    data = get_json(url)
    return data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else {}


def build_payload(date8: str) -> dict[str, Any]:
    date10 = date8_to_date10(date8)
    date_json = post_json(API_URL, {"Params": ["rq", "", "", "", "", 0, 20]})
    rows_json = post_json(API_URL, {"Params": ["yzlhb", date10, "", "", "", 0, 500]})

    date_rows = rows_from_result(date_json)
    row_dicts = rows_from_result(rows_json)
    codes = sorted({normalize_code(row.get("gpdm")) for row in row_dicts if normalize_code(row.get("gpdm"))})
    quote_map = fetch_quote_map(codes)

    rows: list[dict[str, Any]] = []
    for row in row_dicts:
        code = normalize_code(row.get("gpdm"))
        symbol = to_xgb_symbol(code)
        quote = quote_map.get(symbol, {}) if symbol else {}
        change_percent = quote.get("change_percent")
        rows.append(
            {
                "yzmc": str(row.get("yzmc") or "").strip(),
                "yyb": str(row.get("yyb") or "").strip(),
                "sblx": str(row.get("sblx") or "").strip(),
                "gpdm": code,
                "gpmc": str(row.get("gpmc") or code).strip(),
                "sc": str(row.get("sc") or "").strip(),
                "mrje": to_number(row.get("mrje")),
                "mcje": to_number(row.get("mcje")),
                "rq": str(row.get("rq") or "").strip()[0:10],
                "price": to_number(quote.get("price")) if quote.get("price") is not None else None,
                "changePct": to_number(change_percent) * 100 if change_percent is not None else None,
            }
        )

    date_options = []
    for row in date_rows:
        value = str(row.get("rq") or "").strip()[0:10]
        if value and value not in date_options:
            date_options.append(value)

    return {
        "date": date10,
        "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "dateOptions": date_options,
        "rows": rows,
    }


def write_cache(payload: dict[str, Any], date8: str) -> Path:
    cache_dir = ROOT / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"dragon_tiger-{date8}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取龙虎榜并写入本地缓存")
    parser.add_argument("date8", help="交易日 YYYYMMDD 或 YYYY-MM-DD")
    args = parser.parse_args()

    date8 = normalize_date8(args.date8)
    payload = build_payload(date8)
    out = write_cache(payload, date8)
    print(out)


if __name__ == "__main__":
    main()
