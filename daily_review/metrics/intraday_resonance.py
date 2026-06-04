#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
盘中板块共振检测（Python 后端）

从前端 useIntradayAlertPool.detectResonance 镜像而来。
读取 cache_online/xuangubao_abnormal-YYYYMMDD.json 中全天积累的异动事件，
按板块聚合后在 300 秒窗口内检测共振（>=3 只异动联动），输出共振事件列表。

输出注入 window.__INTRADAY_RESONANCE__，前端作为 baseline 读取。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from daily_review.cache_io import read_json

RESONANCE_WINDOW_SEC = 300
RESONANCE_THRESHOLD_COUNT = 3
RESONANCE_MIN_UNIQUE_STOCKS = 2
# 前端 ALERT_FETCH_TYPES（与 useIntradayAlertPool.ts 一致）
ALERT_TYPES = {11000, 11001, 10005, 10006, 10003, 10004, 10009, 10010, 10008, 10007}


def _is_st_name(name: Any) -> bool:
    return "ST" in str(name or "").upper()


def _normalize_pct(pcp: Any, *, default: float | None = None) -> float | None:
    """归一化涨跌幅；失败返回 default。"""
    if pcp is None:
        return default
    try:
        return float(pcp)
    except (TypeError, ValueError):
        return default


def _format_pct(pcp: float | None) -> str:
    """还原前端 toPctText 格式。"""
    if pcp is None:
        return ""
    sign = "+" if pcp >= 0 else ""
    return f"{sign}{pcp * 100:.2f}%"


def _format_bj_time(ts: int) -> str:
    """Unix 时间戳 → HH:MM:SS（北京时间）。"""
    from datetime import datetime, timezone, timedelta
    bj = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(ts, tz=bj).strftime("%H:%M:%S")


def _blank_sector_hit() -> dict[str, Any]:
    return {
        "lastTs": 0,
        "stockBriefs": {},
        "platePcp": None,
        "_signals": [],
    }


def _latest_resonance_signal(signals: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    在 300 秒窗口内寻找“更准确”的共振确认：
    - 必须有板块异动背书；
    - 至少 2 只不同个股联动；
    - 同一只股票多次异动不重复计数。
    """
    ordered = sorted(
        (
            sig for sig in signals
            if isinstance(sig, dict) and isinstance(sig.get("ts"), (int, float))
        ),
        key=lambda sig: int(sig["ts"]),
    )
    if len(ordered) < RESONANCE_THRESHOLD_COUNT:
        return None

    left = 0

    matched: dict[str, Any] | None = None

    for right, sig in enumerate(ordered):
        right_ts = int(sig["ts"])
        while left <= right and right_ts - int(ordered[left]["ts"]) > RESONANCE_WINDOW_SEC:
            left += 1

        window = ordered[left:right + 1]
        plate_count = 0
        latest_plate_pcp: float | None = None
        stock_latest: dict[str, dict[str, Any]] = {}
        for candidate in window:
            if candidate.get("kind") == "plate":
                plate_count += 1
                pcp = _normalize_pct(candidate.get("pcp"))
                if pcp is not None:
                    latest_plate_pcp = pcp
                continue
            symbol = str(candidate.get("symbol") or "").strip()
            if not symbol:
                continue
            prev = stock_latest.get(symbol)
            if prev is None or int(candidate.get("ts", 0)) >= int(prev.get("ts", 0)):
                stock_latest[symbol] = candidate

        unique_stock_count = len(stock_latest)
        if plate_count <= 0 or unique_stock_count < RESONANCE_MIN_UNIQUE_STOCKS:
            continue
        signal_count = unique_stock_count + 1
        if signal_count < RESONANCE_THRESHOLD_COUNT:
            continue

        briefs = sorted(
            stock_latest.values(),
            key=lambda item: int(item.get("ts", 0)),
            reverse=True,
        )[:5]
        matched = {
            "ts": right_ts,
            "platePcp": latest_plate_pcp,
            "uniqueStockCount": unique_stock_count,
            "signalCount": signal_count,
            "briefs": [
                {
                    "name": str(item.get("name") or ""),
                    "symbol": str(item.get("symbol") or ""),
                    "pct": _format_pct(_normalize_pct(item.get("pcp"))) if _normalize_pct(item.get("pcp")) is not None else "",
                }
                for item in briefs
            ],
        }

    return matched


def detect_resonance_from_cache(root: Path, date8: str) -> list[dict[str, Any]]:
    """
    从缓存中检测共振事件。

    返回与前端 IntradayAlertItem 兼容的结构：
    [
      {
        "id": "resonance-{ts}-{sector}",
        "title": "板块共振：{sector}",
        "subtitle": "XX +5.2% / YY +3.1%",
        "time": "HH:MM:SS",
        "eventTimestamp": 1234567890,
        "tone": "red" | "green" | "blue",
        "eventTypeLabel": "共振爆发",
        "valueText": "+X.XX%",  # 板块涨跌幅，无数据时为空
        "sector": "板块名称",
        "count": 3,
        "stocks": [{"name": "XX", "symbol": "000001", "pct": "+5.2%"}]
      }
    ]
    """
    cache_path = root / "cache_online" / f"xuangubao_abnormal-{date8}.json"
    raw = read_json(cache_path, default={})
    if not raw or not isinstance(raw, dict):
        return []

    runs = raw.get("runs") or []
    if not runs:
        return []

    # 1) 汇聚所有 run 的事件，按 id 去重
    seen_ids: set[str] = set()
    all_events: list[dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        inner = (
            run.get("combined", {})
            .get("data", {})
            .get("data", [])
        )
        if not isinstance(inner, list):
            continue
        for e in inner:
            if not isinstance(e, dict):
                continue
            eid = e.get("id")
            if not eid or eid in seen_ids:
                continue
            seen_ids.add(eid)
            all_events.append(e)

    if not all_events:
        return []

    # 2) 按板块聚合：只保留前端同口径的题材信息（最多前 3 个 related_plates）
    sector_hits: dict[str, dict[str, Any]] = {}

    for e in all_events:
        et = e.get("event_type", 0)
        if et not in ALERT_TYPES:
            continue

        ts = e.get("event_timestamp", 0)
        if not isinstance(ts, (int, float)):
            ts = 0

        # 板块事件：eventType >= 11000 → 板块名称 = title
        plate_data = e.get("plate_abnormal_event_data")
        stock_data = e.get("stock_abnormal_event_data")

        if isinstance(plate_data, dict) and et >= 11000:
            sector_name = plate_data.get("plate_name", "").strip()
            if sector_name and not _is_st_name(sector_name):
                hit = sector_hits.setdefault(sector_name, _blank_sector_hit())
                hit["lastTs"] = max(hit["lastTs"], ts)
                hit["_signals"].append({
                    "kind": "plate",
                    "ts": int(ts),
                    "pcp": plate_data.get("pcp"),
                })
                pcp = _normalize_pct(plate_data.get("pcp"))
                if pcp is not None:
                    hit["platePcp"] = pcp

        # 个股事件：sectors = related_plates[].plate_name
        elif isinstance(stock_data, dict) and et < 11000:
            plates = stock_data.get("related_plates") or []
            if not isinstance(plates, list):
                plates = []
            plates = plates[:3]
            symbol = str(stock_data.get("symbol", "") or "").strip()
            name = str(stock_data.get("name", "") or "").strip()
            pcp = _normalize_pct(stock_data.get("pcp"))

            for p in plates:
                if not isinstance(p, dict):
                    continue
                pn = p.get("plate_name", "").strip()
                if not pn or _is_st_name(pn):
                    continue
                hit = sector_hits.setdefault(pn, _blank_sector_hit())
                hit["lastTs"] = max(hit["lastTs"], ts)
                hit["_signals"].append({
                    "kind": "stock",
                    "ts": int(ts),
                    "symbol": symbol,
                    "name": name,
                    "pcp": pcp,
                })
                # 同一只个股只保留最新
                if symbol:
                    brief = hit["stockBriefs"].get(symbol)
                    if not brief or ts > brief.get("_ts", 0):
                        hit["stockBriefs"][symbol] = {
                            "name": name,
                            "symbol": symbol,
                            "pct": _format_pct(pcp) if pcp is not None else "",
                            "_ts": ts,
                        }

    # 3) 筛选共振：滑动窗口 300 秒内 >= 3 次
    results: list[dict[str, Any]] = []
    for sector, hit in sorted(sector_hits.items(), key=lambda x: -x[1]["lastTs"]):
        resonance = _latest_resonance_signal(hit.get("_signals", []))
        if not resonance:
            continue

        # 拼装个股摘要
        briefs_for_subtitle = resonance.get("briefs", [])
        subtitle_parts = [
            f'{s["name"]}{" " + s["pct"] if s.get("pct") else ""}'
            for s in briefs_for_subtitle
        ]

        # 板块涨跌幅
        plate_pcp = resonance.get("platePcp", hit.get("platePcp"))
        tone = "blue"
        if plate_pcp is not None:
            tone = "red" if plate_pcp >= 0 else "green"

        ts = int(resonance.get("ts") or hit["lastTs"] or 0)
        results.append({
            "id": f"resonance-{ts}-{sector}",
            "title": f"🔥 板块共振：{sector}",
            "subtitle": " / ".join(subtitle_parts) if subtitle_parts else f'{resonance.get("signalCount", 0)} 路信号联动',
            "time": _format_bj_time(ts),
            "eventTimestamp": ts,
            "tone": tone,
            "eventTypeLabel": "共振爆发",
            "valueText": _format_pct(plate_pcp) if plate_pcp is not None else "",
            "sector": sector,
            "count": int(resonance.get("signalCount", 0) or 0),
            "stocks": [{"name": s["name"], "symbol": s["symbol"], "pct": s.get("pct", "")} for s in briefs_for_subtitle],
        })

    return results


def save_resonance_cache(root: Path, date8: str, results: list[dict[str, Any]]) -> Path:
    """将共振结果写入 cache_online/intraday_resonance-YYYYMMDD.json"""
    path = root / "cache_online" / f"intraday_resonance-{date8}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    return path
