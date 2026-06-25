#!/usr/bin/env python3
"""
fetch_eastmoney_tomorrow.py — 从东方财富 API 预获取"今日题材"数据，输出 JSON。

用于 CI 17:00 全量 fetch 阶段，将 East Money 明日热门主题数据提前下载好，
注入到 HTML 中，避免前端运行时 API 调用失败（CORS/网络问题）。

使用方式:
  python3 tools/fetch_eastmoney_tomorrow.py [输出路径]

默认输出: web/public/eastmoney_tomorrow.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# 临时将项目根加入 sys.path，方便导入 daily_review 模块
sys.path.insert(0, str(ROOT))


def _normalize_code(code: str) -> str:
    """去掉 .SH/.SZ 后缀，返回纯 6 位代码"""
    return str(code or "").replace(".SH", "").replace(".SZ", "").strip()


def _normalize_reason_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value).strip()
    if isinstance(value, dict):
        for key in ("introduction", "title", "text", "content", "value", "name"):
            text = _normalize_reason_text(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, list):
        parts = [_normalize_reason_text(item) for item in value]
        return "；".join(part for part in parts if part)
    return str(value).strip()


def _flatten_themes(themes_resp: dict) -> list[dict]:
    """将 East Money 原始返回拍平为前端 TomorrowTheme[] 格式"""
    raw = themes_resp.get("raw") if isinstance(themes_resp, dict) else None
    if not isinstance(raw, dict):
        return []
    # 兼容嵌套 raw: save_tomorrow_snapshot 返回的 raw 是 {"ok": true, "raw": {"code": 0, "data": [...]}}
    if "data" not in raw and "raw" in raw and isinstance(raw.get("raw"), dict):
        raw = raw.get("raw")
    payload = raw.get("data")
    items: list[Any] = []
    if isinstance(payload, list):
        items = list(payload)
    elif isinstance(payload, dict):
        numeric_keys = sorted((k for k in payload.keys() if str(k).isdigit()), key=lambda k: int(k))
        items = [payload[k] for k in numeric_keys]
    else:
        return []

    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append({
            "id": str(item.get("eid") or item.get("sortNum") or ""),
            "rank": int(item.get("sortNum") or 0),
            "title": str(item.get("title") or ""),
            "summary": str(item.get("summary") or ""),
            "tradeDate": str(item.get("tradeDate") or ""),
            "themeCode": str(item.get("themeCode") or ""),
            "themeName": str(item.get("themeName") or ""),
            "ztCount": int(item.get("fex3") or 0),
            "gain": float(item.get("f3") or 0),
            "cumulateGain": float(item.get("cumulateF3") or 0),
            "isHot": bool(item.get("isHot") == 1 or item.get("isHot") == "1"),
            "previewStocks": [
                {
                    "code": _normalize_code(s.get("code", "")),
                    "name": str(s.get("name", "") or ""),
                    "gain": float(s.get("f3") or 0),
                }
                for s in (item.get("stockList") or [])
                if isinstance(s, dict)
            ],
        })
    return out


def _flatten_stocks_by_theme(stocks_resp: dict) -> dict[str, list[dict]]:
    """将 East Money 主题成份股原始返回拍平为 {themeCode: TomorrowStock[]} 格式"""
    by_theme = stocks_resp.get("by_theme") if isinstance(stocks_resp, dict) else None
    if not isinstance(by_theme, dict):
        return {}
    out: dict[str, list[dict]] = {}
    for theme_code, resp in by_theme.items():
        if not isinstance(resp, dict):
            continue
        raw_stocks = resp.get("raw", {})
        stock_list = raw_stocks.get("data", {})
        if isinstance(stock_list, dict):
            stock_list = stock_list.get("stockList") or []
        if not isinstance(stock_list, list):
            continue
        parsed = []
        for s in stock_list:
            if not isinstance(s, dict):
                continue
            reasons = [
                _normalize_reason_text(k.get("introduction"))
                for k in (s.get("keywordList") or [])
                if isinstance(k, dict) and k.get("keyword") == "入选理由"
            ]
            reasons = [reason for reason in reasons if reason]
            parsed.append({
                "code": _normalize_code(str(s.get("securityCode") or "")),
                "name": str(s.get("securityName") or ""),
                "gain": float(s.get("f3") or 0),
                "price": float(s.get("f2") or 0),
                "marketCap": float(s.get("f20") or 0),
                "industry": str(s.get("f100") or ""),
                "label": str(s.get("label") or ""),
                "reason": "；".join(reasons) or "涨停",
            })
        out[str(theme_code)] = parsed
    return out


def main() -> int:
    output = sys.argv[1] if len(sys.argv) > 1 else "web/public/eastmoney_tomorrow.json"
    output_path = Path(output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path

    # 导入 eastmoney_theme 模块（需项目 root 在 sys.path 中）
    try:
        from daily_review.data.eastmoney_theme import (
            save_tomorrow_snapshot,
            load_latest_tomorrow_themes,
            load_latest_theme_stocks,
        )
    except ImportError as e:
        print(f"❌ 导入 eastmoney_theme 失败: {e}", file=sys.stderr)
        return 1

    # 1) 拉取 East Money API 数据
    from datetime import datetime, timezone, timedelta
    now_bj = datetime.now(timezone(timedelta(hours=8)))
    date8 = now_bj.strftime("%Y%m%d")
    date10 = now_bj.strftime("%Y-%m-%d")

    print(f"📡 拉取东方财富明日主题数据 ({date10})...")
    themes_path, stocks_path = save_tomorrow_snapshot(
        root=ROOT,
        date=date10,
        mode="eod",
        fetch_stocks=True,
        max_themes_for_stocks=15,
    )
    if not themes_path or not themes_path.exists():
        print("⚠ 明日主题列表获取失败或缓存不存在", file=sys.stderr)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("{}", encoding="utf-8")
        return 1

    # 2) 读取缓存，拍平为前端格式
    themes_cache = load_latest_tomorrow_themes(ROOT, date10)
    stocks_cache = load_latest_theme_stocks(ROOT, date10) if stocks_path else {}

    themes = _flatten_themes(themes_cache)
    stocks = _flatten_stocks_by_theme(stocks_cache)

    theme_cnt = len(themes)
    stock_cnt = sum(len(v) for v in stocks.values())
    print(f"  ✅ 题材列表: {theme_cnt} 条")
    print(f"  ✅ 成份股: {stock_cnt} 只")

    # 3) 写出前端可用 JSON
    payload = {
        "schema": "eastmoney_tomorrow_v1",
        "date": date10,
        "updatedAt": now_bj.strftime("%Y-%m-%d %H:%M:%S"),
        "themes": themes,
        "stocksByTheme": stocks,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"✅ 东财明日主题数据已写入: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
