#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
data.xuangubao：选股宝实时数据源（不做业务判断）

职责（仅数据获取 + 落盘）：
- fetch_abnormal_events:   /api/event/history          异动事件流（自带 related_stocks / related_plates）
- fetch_surge_plates:      /api/surge_stock/plates     当日热点板块（含简介）

设计约定：
- 不引入新依赖，仅使用 stdlib urllib（与 daily_review/data/biying.py 一致）
- 不解析业务字段，原始 JSON 直接返回；归一化在 features 层完成
- 缓存策略由调用方决定（CLI / fetch_watchlist 编排），本模块只提供 fetch_* + load_cached_*
- 注意：选股宝没有公开的 plate_stocks 端点。板块→个股映射应从异动事件反推，
  归一化在 features/sector_resolver.py 实现。

参考：
- daily_review/cli.py:67 已有的临时实现（_fetch_abnormal_event_history_sample）
- web/src/composables/useThemeHotStore.ts:74 (surge_stock/plates)
- web/src/composables/useIntradayAlertPool.ts:144 (event/history)
"""

from __future__ import annotations

import datetime as _dt
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from daily_review.cache_io import read_json, write_json


BASE_FLASH = "https://flash-api.xuangubao.cn"

# 现有 cli.py 中已沉淀的两套事件类型口径，统一到此处
ABNORMAL_EVENT_TYPES_ALL = (10001, 10002, 10003, 10004, 10005, 10006, 10007, 10008, 10009, 10010, 10012, 10014, 11000, 11001)
ABNORMAL_EVENT_TYPES_FOCUS = (11000, 11001, 10005, 10009, 10010)

_UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
)


def _now_bj_str() -> str:
    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def _http_get_json(url: str, *, timeout: int = 20, headers: dict[str, str] | None = None) -> Any:
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json, text/plain, */*")
    req.add_header("User-Agent", _UA_MOBILE)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
    return json.loads(body) if body else {}


# ---------------------------------------------------------------------------
# Fetch 函数：仅做 HTTP 调用 + 原始返回（无业务解析）
# ---------------------------------------------------------------------------


def fetch_abnormal_events(
    *,
    count: int = 120,
    types: tuple[int, ...] | list[int] | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    """
    拉取选股宝异动事件流。

    返回原始 dict（含 url + count + data）—— 与 cli.py 现有结构兼容。
    """
    query = [f"count={int(count)}"]
    if types:
        query.append("types=" + ",".join(str(int(x)) for x in types))
    query.append(f"_ts={int(time.time() * 1000)}")
    url = f"{BASE_FLASH}/api/event/history?" + "&".join(query)
    try:
        data = _http_get_json(url, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"url": url, "count": 0, "data": {}, "error": str(e)}
    rows = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), list) else []
    return {"url": url, "count": len(rows), "data": data}


def fetch_surge_plates(*, timeout: int = 15) -> dict[str, Any]:
    """
    拉取选股宝当日热点板块清单（含 id / name / description）。
    """
    url = f"{BASE_FLASH}/api/surge_stock/plates?_ts={int(time.time() * 1000)}"
    try:
        data = _http_get_json(url, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"url": url, "data": {}, "error": str(e)}
    return {"url": url, "data": data}


def _code6_to_xgb_symbol(code6: str) -> str:
    """6位代码 → 选股宝 symbol 格式（SH600519 / SZ000001）。"""
    c = str(code6 or "").strip()
    return f"SH{c}" if c.startswith("6") else f"SZ{c}"


def _xgb_symbol_to_code6(symbol: str) -> str:
    """选股宝 symbol → 6位代码。"""
    s = str(symbol or "").strip().upper()
    if s.startswith("SH") or s.startswith("SZ"):
        return s[2:]
    return s


def fetch_stock_labels_batch(codes: list[str], *, timeout: int = 20) -> dict[str, list[str]]:
    """
    批量获取个股题材标签（选股宝 stock_label/labels）。

    Args:
        codes: 6位代码列表
        timeout: 超时秒数

    Returns:
        {code6: [label_name, ...], ...}

    端点: /api/stock_label/labels?symbols=SH600519,SZ000001
    """
    if not codes:
        return {}

    xgb_symbols = [_code6_to_xgb_symbol(c) for c in codes if str(c or "").strip()]
    if not xgb_symbols:
        return {}

    url = f"{BASE_FLASH}/api/stock_label/labels?symbols={','.join(xgb_symbols)}"
    try:
        data = _http_get_json(url, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError):
        return {}

    result: dict[str, list[str]] = {}
    items = data.get("data") if isinstance(data, dict) else {}
    if not isinstance(items, dict):
        return {}

    for symbol, labels in items.items():
        code6 = _xgb_symbol_to_code6(symbol)
        if not code6 or not isinstance(labels, list):
            continue
        names: list[str] = []
        for lb in labels:
            if not isinstance(lb, dict):
                continue
            nm = str(lb.get("label_name") or "").strip()
            if nm:
                names.append(nm)
        if names:
            result[code6] = names

    return result


# ---------------------------------------------------------------------------
# 缓存写入：约定 cache_online/xuangubao_*.json，由编排层决定何时调用
# ---------------------------------------------------------------------------


def cache_path_abnormal(root: Path, date: str) -> Path:
    d8 = str(date or "").replace("-", "")
    return root / "cache_online" / f"xuangubao_abnormal-{d8}.json"


def cache_path_surge_plates(root: Path, date: str) -> Path:
    d8 = str(date or "").replace("-", "")
    return root / "cache_online" / f"xuangubao_surge_plates-{d8}.json"


def save_abnormal_snapshot(
    *,
    root: Path,
    date: str,
    mode: str = "intraday",
    note: str = "",
    keep_runs: int = 40,
) -> Path:
    """
    拉取一次异动事件并追加到当日缓存。保留最近 N 次快照用于回测/审计。

    与 cli.py 现有 _save_abnormal_event_history_sample 结构保持兼容。
    """
    path = cache_path_abnormal(root, date)
    prev = read_json(path, default={})
    existing_runs = prev.get("runs") if isinstance(prev, dict) and isinstance(prev.get("runs"), list) else []

    now_bj = _now_bj_str()
    combined = fetch_abnormal_events(count=120, types=ABNORMAL_EVENT_TYPES_ALL)
    focused = fetch_abnormal_events(count=120, types=ABNORMAL_EVENT_TYPES_FOCUS)

    run = {
        "saved_at_bj": now_bj,
        "mode": mode,
        "note": note,
        "recognized_types": list(ABNORMAL_EVENT_TYPES_ALL),
        "default_focus_types": list(ABNORMAL_EVENT_TYPES_FOCUS),
        "combined": combined,
        "focused": focused,
    }
    runs = (existing_runs + [run])[-keep_runs:]
    payload = {
        "schema": "xuangubao_abnormal_v1",
        "date": date,
        "updated_at_bj": now_bj,
        "run_count": len(runs),
        "latest": run,
        "runs": runs,
    }
    write_json(path, payload)
    return path


def save_surge_plates_snapshot(
    *,
    root: Path,
    date: str,
    mode: str = "intraday",
    note: str = "",
) -> Path:
    """
    拉取一次"热点板块清单"。落盘到 cache_online/xuangubao_surge_plates-YYYYMMDD.json。

    注意：板块→个股映射不在此处生成，应由 features/sector_resolver
    从 abnormal 事件的 related_stocks / related_plates 字段反推。
    """
    plates_resp = fetch_surge_plates()
    plates_path = cache_path_surge_plates(root, date)
    now_bj = _now_bj_str()
    write_json(
        plates_path,
        {
            "schema": "xuangubao_surge_plates_v1",
            "date": date,
            "updated_at_bj": now_bj,
            "mode": mode,
            "note": note,
            "raw": plates_resp,
        },
    )
    return plates_path


# ---------------------------------------------------------------------------
# 读取已缓存的快照：供 feature/特征层使用
# ---------------------------------------------------------------------------


def load_latest_abnormal(root: Path, date: str) -> dict[str, Any]:
    return read_json(cache_path_abnormal(root, date), default={})


def load_latest_surge_plates(root: Path, date: str) -> dict[str, Any]:
    return read_json(cache_path_surge_plates(root, date), default={})
