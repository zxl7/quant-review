#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
data.eastmoney_theme：东财明日主题数据源（不做业务判断）

职责（仅数据获取 + 落盘）：
- fetch_fry_tomorrow_list:  /api/themeInvest/getFryTomorrowList   明日热门主题 TopN
- fetch_theme_stock_list:   /api/themeInvest/getStockList         指定主题成份股

设计约定：
- POST + JSON body（与前端 useTomorrowPicks.ts 保持完全一致的签名）
- 不解析业务字段，原始 JSON 透传；归一化交给 features 层
- 缓存路径：cache_online/eastmoney_*.json
- 失败降级：保留 error 字段，调用方决定回退到上一次缓存

参考：
- web/src/components/tomorrow/useTomorrowPicks.ts:62
- web/src/composables/useThemeHotStore.ts:102
"""

from __future__ import annotations

import datetime as _dt
import json
import random
import string
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from daily_review.cache_io import read_json, write_json


BASE_THEME = "https://emcfgdata.eastmoney.com/api/themeInvest"

_UA_MOBILE_SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)


def _now_bj_str() -> str:
    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def _make_random_code(length: int = 32) -> str:
    """与前端 useTomorrowPicks.makeAuth() 等价：ts + ts + 随机字符 截断"""
    ts = str(int(time.time() * 1000))
    pool = string.ascii_lowercase + string.digits
    rand = "".join(random.choices(pool, k=10))
    return (ts + ts + rand)[:length]


def _http_post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: int = 15,
    headers: dict[str, str] | None = None,
) -> Any:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", _UA_MOBILE_SAFARI)
    req.add_header("Accept", "application/json, text/plain, */*")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    return json.loads(raw) if raw else {}


# ---------------------------------------------------------------------------
# Fetch 函数
# ---------------------------------------------------------------------------


def fetch_fry_tomorrow_list(
    *,
    page_size: int = 15,
    last_trade_date: str = "",
    timeout: int = 12,
) -> dict[str, Any]:
    """
    拉取东财"明日热门主题"列表。

    Body schema 参考前端 useTomorrowPicks.ts:62。
    """
    ts = str(int(time.time() * 1000))
    payload = {
        "args": {"pageSize": int(page_size), "lastTradeDate": last_trade_date or ""},
        "client": "wap",
        "clientType": "cfw",
        "clientVersion": "9001",
        "randomCode": _make_random_code(32),
        "timestamp": ts,
    }
    url = f"{BASE_THEME}/getFryTomorrowList"
    try:
        data = _http_post_json(url, payload, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"url": url, "ok": False, "error": str(e), "raw": {}}
    return {"url": url, "ok": isinstance(data, dict) and data.get("code") == 0, "raw": data}


def fetch_theme_stock_list(
    theme_code: str,
    *,
    page_size: int = 200,
    page_num: int = 1,
    sort_field: str = "f3",
    sort: int = -1,
    timeout: int = 12,
) -> dict[str, Any]:
    """
    拉取某主题的成份股列表。

    Body schema 参考前端 useTomorrowPicks.ts:129。
    返回字段包含：securityCode / securityName / f3(涨幅) / f20(市值) / label / keywordList[入选理由]
    """
    code = str(theme_code or "").strip()
    if not code:
        return {"url": "", "ok": False, "error": "empty theme_code", "raw": {}}
    ts = str(int(time.time() * 1000))
    payload = {
        "args": {
            "themeCode": code,
            "pageSize": int(page_size),
            "pageNum": int(page_num),
            "sort": int(sort),
            "sortField": sort_field,
        },
        "client": "web",
        "clientType": "cfw",
        "clientVersion": "8.3",
        "randomCode": _make_random_code(20),
        "timestamp": ts,
    }
    url = f"{BASE_THEME}/getStockList"
    try:
        data = _http_post_json(url, payload, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"url": url, "ok": False, "error": str(e), "raw": {}}
    return {"url": url, "ok": isinstance(data, dict) and data.get("code") == 0, "raw": data}


# ---------------------------------------------------------------------------
# 缓存
# ---------------------------------------------------------------------------


def cache_path_tomorrow_themes(root: Path, date: str) -> Path:
    d8 = str(date or "").replace("-", "")
    return root / "cache_online" / f"eastmoney_tomorrow_themes-{d8}.json"


def cache_path_theme_stocks(root: Path, date: str) -> Path:
    """所有主题下的成份股聚合存为单一文件"""
    d8 = str(date or "").replace("-", "")
    return root / "cache_online" / f"eastmoney_theme_stocks-{d8}.json"


def save_tomorrow_snapshot(
    *,
    root: Path,
    date: str,
    mode: str = "eod",
    note: str = "",
    fetch_stocks: bool = True,
    max_themes_for_stocks: int = 15,
) -> tuple[Path, Path | None]:
    """
    拉取明日主题清单 + 每个主题的成份股，落盘到 cache_online/。

    失败降级：若主清单失败，仍写入 error 字段；调用方可读取上一次缓存。
    """
    themes_resp = fetch_fry_tomorrow_list(page_size=max(max_themes_for_stocks, 15))
    themes_path = cache_path_tomorrow_themes(root, date)
    now_bj = _now_bj_str()
    write_json(
        themes_path,
        {
            "schema": "eastmoney_tomorrow_themes_v1",
            "date": date,
            "updated_at_bj": now_bj,
            "mode": mode,
            "note": note,
            "raw": themes_resp,
        },
    )

    if not fetch_stocks or not themes_resp.get("ok"):
        return themes_path, None

    theme_codes = _extract_theme_codes(themes_resp, limit=max_themes_for_stocks)
    by_theme: dict[str, Any] = {}
    for tc in theme_codes:
        by_theme[tc] = fetch_theme_stock_list(tc)

    stocks_path = cache_path_theme_stocks(root, date)
    write_json(
        stocks_path,
        {
            "schema": "eastmoney_theme_stocks_v1",
            "date": date,
            "updated_at_bj": now_bj,
            "mode": mode,
            "note": note,
            "theme_codes": theme_codes,
            "by_theme": by_theme,
        },
    )
    return themes_path, stocks_path


def _extract_theme_codes(themes_resp: dict[str, Any], *, limit: int = 15) -> list[str]:
    """
    从 getFryTomorrowList 原始返回中按 sortNum 升序提取 themeCode。

    接口实际返回 data 为 list（前端通过 Object.keys 的数字索引兼容了 list/dict 两种形态）。
    这里同时兼容两种结构：
    - list[item]
    - dict 以数字字符串为 key 的 item
    """
    raw = themes_resp.get("raw") if isinstance(themes_resp, dict) else None
    if not isinstance(raw, dict):
        return []
    payload = raw.get("data")
    items: list[Any] = []
    if isinstance(payload, list):
        items = list(payload)
    elif isinstance(payload, dict):
        numeric_keys = sorted((k for k in payload.keys() if str(k).isdigit()), key=lambda k: int(k))
        items = [payload[k] for k in numeric_keys]
    else:
        return []

    # 优先按 sortNum 升序（接口正常时已排好）
    def _sort_key(it: Any) -> int:
        if isinstance(it, dict):
            try:
                return int(it.get("sortNum") or 0)
            except Exception:
                return 0
        return 0

    items.sort(key=_sort_key)

    out: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        code = str(item.get("themeCode") or "").strip()
        if code and code not in out:
            out.append(code)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# 读取已缓存的快照
# ---------------------------------------------------------------------------


def load_latest_tomorrow_themes(root: Path, date: str) -> dict[str, Any]:
    return read_json(cache_path_tomorrow_themes(root, date), default={})


def load_latest_theme_stocks(root: Path, date: str) -> dict[str, Any]:
    return read_json(cache_path_theme_stocks(root, date), default={})
