#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daily_review.config import load_config_from_env
from daily_review.data.biying import fetch_stock_history_k, fetch_stocks_realtime, normalize_stock_code
from daily_review.http import HttpClient


CACHE_DIR = ROOT / "cache"
OUT_DIR = ROOT / "html" / "recommendation-preview"
OUT_JSON = OUT_DIR / "stock_research_backtest.json"
OUT_JS = OUT_DIR / "stock_research_backtest.js"
PRICE_CACHE = ROOT / "cache_online" / "recommendation_price_history.json"
BACKTEST_POOL = CACHE_DIR / "stock_research_backtest_pool.json"
TZ_BJ = timezone(timedelta(hours=8))

STRATEGIES = (
    ("next_day", "隔日收益", 1),
    ("hold_3d", "3日收益", 3),
    ("hold_5d", "5日收益", 5),
)


def _now_bj() -> datetime:
    return datetime.now(TZ_BJ)


def _load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(part / total * 100.0, 1)


def _avg(values: list[float], digits: int = 2) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), digits)


def _strip_html(text: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", str(text or ""))
    return re.sub(r"\s+", " ", plain).strip()


def _code_with_suffix(code: str) -> str:
    c = str(code or "").strip()
    if "." in c:
        return c
    if c.startswith(("60", "68", "51", "56", "58", "11")):
        return f"{c}.SH"
    if c.startswith(("00", "20", "30", "12")):
        return f"{c}.SZ"
    if c.startswith(("4", "8", "9")):
        return f"{c}.BJ"
    return f"{c}.SZ"


def _normalize_bar(row: dict[str, Any]) -> dict[str, Any] | None:
    try:
        date10 = str(row.get("t") or "")[:10]
        open_price = float(row.get("o") or 0.0)
        close_price = float(row.get("c") or 0.0)
        high_price = float(row.get("h") or 0.0)
        low_price = float(row.get("l") or 0.0)
        prev_close = float(row.get("pc") or 0.0)
        suspended = int(float(row.get("sf") or 0)) == 1
    except Exception:
        return None
    if len(date10) != 10 or suspended or open_price <= 0 or close_price <= 0:
        return None
    return {
        "date": date10,
        "open": round(open_price, 2),
        "close": round(close_price, 2),
        "high": round(high_price, 2),
        "low": round(low_price, 2),
        "prev_close": round(prev_close, 2),
    }


def _load_price_cache() -> dict[str, Any]:
    data = _load_json(PRICE_CACHE, default={})
    if not isinstance(data, dict):
        return {"schema": "recommendation_price_history_v1", "codes": {}}
    data.setdefault("schema", "recommendation_price_history_v1")
    data.setdefault("codes", {})
    return data


def _save_price_cache(payload: dict[str, Any]) -> None:
    payload["updated_at_bj"] = _now_bj().strftime("%Y-%m-%d %H:%M:%S")
    _write_json(PRICE_CACHE, payload)


def _get_price_histories(codes: list[str], *, st8: str, et8: str) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    cache = _load_price_cache()
    code_cache = cache.setdefault("codes", {})
    histories: dict[str, list[dict[str, Any]]] = {}
    diagnostics: dict[str, Any] = {"source": "cache+api", "fetched": 0, "cached": 0, "missing": []}

    cfg = load_config_from_env()
    client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=12, retries=0)

    for code in codes:
        cached = code_cache.get(code) if isinstance(code_cache.get(code), dict) else {}
        cached_bars = cached.get("bars") if isinstance(cached.get("bars"), list) else []
        earliest = cached_bars[0]["date"].replace("-", "") if cached_bars else ""
        latest = cached_bars[-1]["date"].replace("-", "") if cached_bars else ""
        if cached_bars and earliest <= st8 and latest >= et8:
            histories[code] = cached_bars
            diagnostics["cached"] += 1
            continue

        rows = fetch_stock_history_k(client, code=_code_with_suffix(code), st=st8, et=et8)
        bars = [bar for bar in (_normalize_bar(row) for row in rows if isinstance(row, dict)) if bar]
        bars.sort(key=lambda x: x["date"])
        if bars:
            histories[code] = bars
            code_cache[code] = {"code": code, "bars": bars}
            diagnostics["fetched"] += 1
        elif cached_bars:
            histories[code] = cached_bars
            diagnostics["cached"] += 1
        else:
            diagnostics["missing"].append(code)

    cache["requested_range"] = {"st": st8, "et": et8}
    _save_price_cache(cache)
    return histories, diagnostics


def _parse_expected_range(text: str) -> tuple[float, float] | None:
    m = re.search(r"([+-]?\d+(?:\.\d+)?)%\s*~\s*([+-]?\d+(?:\.\d+)?)%", text)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def _parse_super_open_threshold(text: str) -> float | None:
    m = re.search(r"高开≥\+?([+-]?\d+(?:\.\d+)?)%", text)
    if m:
        return float(m.group(1))
    m = re.search(r"高开≥([+-]?\d+(?:\.\d+)?)%", text)
    if m:
        return float(m.group(1))
    return None


def _parse_amount_threshold_yi(text: str, pattern: str) -> float | None:
    m = re.search(pattern, text)
    if not m:
        return None
    return round(float(m.group(1)), 2)


def _parse_open_board_limit(text: str) -> int | None:
    m = re.search(r"开板≤\s*(\d+)", text)
    if not m:
        return None
    return int(m.group(1))


def _extract_expectation(reason_html: str) -> dict[str, Any]:
    flat = _strip_html(reason_html)
    expected_match = re.search(r"预期\s*(.+?)(?=\s*超预期|\s*低预期|$)", flat)
    super_match = re.search(r"超预期\s*(.+?)(?=\s*低预期|$)", flat)
    low_match = re.search(r"低预期\s*(.+?)$", flat)
    expected_text = expected_match.group(1).strip(" ：:;") if expected_match else ""
    super_text = super_match.group(1).strip(" ：:;") if super_match else ""
    low_text = low_match.group(1).strip(" ：:;") if low_match else ""
    return {
        "expected_text": expected_text,
        "super_text": super_text,
        "low_text": low_text,
        "expected_range": _parse_expected_range(expected_text),
        "super_gap_min": _parse_super_open_threshold(super_text),
        "super_requires_reseal": "回封" in super_text,
        "super_requires_open_board_limit": _parse_open_board_limit(super_text),
        "auction_amount_min_yi": _parse_amount_threshold_yi(super_text, r"竞价成交额≥\s*([0-9]+(?:\.[0-9]+)?)亿"),
        "seal_amount_min_yi": _parse_amount_threshold_yi(super_text, r"(?:封单回补|回封后封单)≥\s*([0-9]+(?:\.[0-9]+)?)亿"),
        "raw_text": flat,
    }


def _row_from_item(item: dict[str, Any], *, date10: str, bucket: str) -> dict[str, Any]:
    market_gate = item.get("marketGate") if isinstance(item.get("marketGate"), dict) else {}
    expectation = _extract_expectation(str(item.get("reason") or ""))
    return {
        "date": date10.replace("-", ""),
        "date10": date10,
        "code": str(item.get("code") or "").strip(),
        "name": str(item.get("name") or "").strip(),
        "bucket": bucket,
        "bucket_label": "接力候选" if bucket == "relay" else "观察池",
        "score": int(round(float(item.get("factorScore") or item.get("score") or 0))),
        "score_band": str(item.get("scoreBand") or "").strip(),
        "score_sub_label": str(item.get("scoreSubLabel") or "").strip(),
        "main_line": str(item.get("predTheme") or "").strip(),
        "style_tag": str(item.get("qualityLabel") or "").strip(),
        "lbc": int(round(float(item.get("lbc") or 0))),
        "cje_yi": round(float(item.get("cjeYi") or 0.0), 2),
        "turnover": round(float(item.get("capacityFactorScore") or 0.0), 2),
        "tide_status": str(market_gate.get("label") or "").strip(),
        "next_step": str(item.get("nextStep") or "").strip(),
        "plate_name": str(item.get("plateName") or "").strip(),
        "hy": str(item.get("hy") or "").strip(),
        "factor_hint": str(item.get("factorHint") or "").strip(),
        "reason_html": str(item.get("reason") or ""),
        "reason_text": _strip_html(item.get("reason") or ""),
        "expectation": expectation,
    }


def _default_backtest_pool() -> dict[str, Any]:
    return {
        "schema": "stock_research_backtest_pool_v1",
        "updated_at_bj": "",
        "days": {},
    }


def _load_backtest_pool() -> dict[str, Any]:
    data = _load_json(BACKTEST_POOL, default={})
    if not isinstance(data, dict):
        return _default_backtest_pool()
    data.setdefault("schema", "stock_research_backtest_pool_v1")
    data.setdefault("updated_at_bj", "")
    data.setdefault("days", {})
    if not isinstance(data.get("days"), dict):
        data["days"] = {}
    return data


def upsert_daily_backtest_pool(market_data: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """
    将单日个股研究样本固化到独立历史池。

    这个池只保存“个股回测”真正需要的每日同源样本，不依赖 market_data 历史文件是否仍然保留。
    """
    if not isinstance(market_data, dict):
        return _load_backtest_pool()

    date10 = str(market_data.get("date") or "").strip()
    if len(date10) != 10:
        return _load_backtest_pool()

    zt = market_data.get("ztAnalysis") if isinstance(market_data.get("ztAnalysis"), dict) else {}
    relay = zt.get("relay") if isinstance(zt.get("relay"), list) else []
    watch = zt.get("watch") if isinstance(zt.get("watch"), list) else []
    if not relay and not watch and not force:
        return _load_backtest_pool()

    pool = _load_backtest_pool()
    days = pool.setdefault("days", {})
    if not isinstance(days, dict):
        days = {}
        pool["days"] = days

    relay_rows = [_row_from_item(item, date10=date10, bucket="relay") for item in relay if isinstance(item, dict)]
    watch_rows = [_row_from_item(item, date10=date10, bucket="watch") for item in watch if isinstance(item, dict)]
    days[date10] = {
        "date": date10,
        "generated_at_bj": _now_bj().strftime("%Y-%m-%d %H:%M:%S"),
        "source_module": "ztAnalysis.relay/watch",
        "source_market_data": f"market_data-{date10.replace('-', '')}.json",
        "relay": relay_rows,
        "watch": watch_rows,
        "summary": {
            "relay_count": len(relay_rows),
            "watch_count": len(watch_rows),
            "total": len(relay_rows) + len(watch_rows),
        },
    }
    pool["updated_at_bj"] = _now_bj().strftime("%Y-%m-%d %H:%M:%S")
    _write_json(BACKTEST_POOL, pool)
    return pool


def _load_stock_research_rows() -> tuple[list[dict[str, Any]], list[str]]:
    pool = _load_backtest_pool()
    days = pool.get("days") if isinstance(pool.get("days"), dict) else {}
    rows_by_date: dict[str, list[dict[str, Any]]] = {}
    sources_by_date: dict[str, str] = {}
    if days:
        for date10 in sorted(days.keys()):
            day = days.get(date10)
            if not isinstance(day, dict):
                continue
            relay = day.get("relay") if isinstance(day.get("relay"), list) else []
            watch = day.get("watch") if isinstance(day.get("watch"), list) else []
            if not relay and not watch:
                continue
            rows_by_date[date10] = [dict(item) for item in relay if isinstance(item, dict)]
            rows_by_date[date10].extend(dict(item) for item in watch if isinstance(item, dict))
            sources_by_date[date10] = str(day.get("source_market_data") or f"stock_research_backtest_pool.json:{date10}")

    files = sorted(CACHE_DIR.glob("market_data-*.json"))

    for fp in files:
        raw = _load_json(fp)
        meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
        if str(meta.get("mode") or "").strip() == "intraday":
            continue
        date10 = str(raw.get("date") or "")
        if len(date10) != 10 or date10 in rows_by_date:
            continue
        zt = raw.get("ztAnalysis") if isinstance(raw.get("ztAnalysis"), dict) else {}
        relay = zt.get("relay") if isinstance(zt.get("relay"), list) else []
        watch = zt.get("watch") if isinstance(zt.get("watch"), list) else []
        if not relay and not watch:
            continue
        rows_by_date[date10] = [_row_from_item(item, date10=date10, bucket="relay") for item in relay if isinstance(item, dict)]
        rows_by_date[date10].extend(_row_from_item(item, date10=date10, bucket="watch") for item in watch if isinstance(item, dict))
        sources_by_date[date10] = fp.name

    rows: list[dict[str, Any]] = []
    used_sources: list[str] = []
    for date10 in sorted(rows_by_date.keys()):
        day_rows = rows_by_date[date10]
        if not day_rows:
            continue
        used_sources.append(sources_by_date.get(date10) or f"stock_research_backtest_pool.json:{date10}")
        rows.extend(day_rows)
    rows.sort(key=lambda x: (x["date"], -x["score"], x["code"]))
    return rows, used_sources


def _load_latest_stock_research_snapshot(date10: str) -> dict[str, Any]:
    if len(date10) != 10:
        return {}
    fp = CACHE_DIR / f"market_data-{date10.replace('-', '')}.json"
    raw = _load_json(fp, default={})
    return raw if isinstance(raw, dict) else {}


def _is_entry_window_time(hhmmss: str) -> bool:
    text = str(hhmmss or "").strip()
    if not text:
        return False
    if " " in text:
        text = text.split(" ")[-1]
    if len(text) >= 8:
        text = text[:8]
    try:
        hour, minute, second = [int(part) for part in text.split(":")[:3]]
    except Exception:
        return False
    if hour != 9:
        return False
    total = hour * 3600 + minute * 60 + second
    return 9 * 3600 + 25 * 60 <= total < 9 * 3600 + 30 * 60


def _should_request_realtime_quotes(now: datetime | None = None) -> bool:
    current = now or _now_bj()
    total = current.hour * 3600 + current.minute * 60 + current.second
    return 9 * 3600 + 25 * 60 <= total < 9 * 3600 + 30 * 60


def _load_preserved_realtime_buy(latest_date10: str) -> dict[str, Any] | None:
    candidates = []
    for fp in CACHE_DIR.glob("market_data-*.json"):
        stem = fp.stem
        if not stem.startswith("market_data-"):
            continue
        d8 = stem.replace("market_data-", "")
        if len(d8) == 8 and d8.isdigit():
            candidates.append((d8, fp))

    for _, fp in sorted(candidates, reverse=True):
        data = _load_json(fp, default={})
        if not isinstance(data, dict):
            continue
        backtest = data.get("stockResearchBacktest")
        if not isinstance(backtest, dict):
            continue
        realtime_buy = backtest.get("realtimeBuy")
        if not isinstance(realtime_buy, dict):
            continue
        if str(realtime_buy.get("reference_date") or "") != latest_date10:
            continue
        quote_time = str(realtime_buy.get("quote_time") or "")
        if not _is_entry_window_time(quote_time):
            continue
        return json.loads(json.dumps(realtime_buy, ensure_ascii=False))
    return None


def _normalize_realtime_quote(row: dict[str, Any]) -> dict[str, Any] | None:
    code6 = normalize_stock_code(str(row.get("dm") or row.get("code") or row.get("symbol") or ""))
    if not code6:
        return None
    prev_close = float(row.get("yc") or 0.0)
    open_price = float(row.get("o") or 0.0)
    last_price = float(row.get("p") or row.get("c") or 0.0)
    auction_price = open_price if open_price > 0 else last_price
    auction_amount_yuan = float(row.get("cje") or 0.0)
    open_board_count = row.get("zbc")
    try:
        open_board_count = int(float(open_board_count)) if open_board_count not in (None, "") else None
    except Exception:
        open_board_count = None
    return {
        "code": code6,
        "time": str(row.get("t") or "").strip(),
        "prev_close": round(prev_close, 2),
        "open_price": round(open_price, 2) if open_price > 0 else 0.0,
        "last_price": round(last_price, 2) if last_price > 0 else 0.0,
        "auction_price": round(auction_price, 2) if auction_price > 0 else 0.0,
        "auction_price_field": "o" if open_price > 0 else ("p" if last_price > 0 else ""),
        "auction_amount_yuan": auction_amount_yuan,
        "auction_amount_yi": round(auction_amount_yuan / 1e8, 2) if auction_amount_yuan > 0 else 0.0,
        "open_board_count": open_board_count,
        "raw": row,
    }


def _fetch_realtime_quotes(codes: list[str], *, fallback_quotes: dict[str, Any] | None = None) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    normalized_codes = [normalize_stock_code(code) for code in codes if normalize_stock_code(code)]
    uniq_codes = sorted(dict.fromkeys(normalized_codes))
    diagnostics: dict[str, Any] = {
        "requested": len(uniq_codes),
        "received": 0,
        "remote_received": 0,
        "fallback_used": 0,
        "missing": [],
        "source": "remote",
        "as_of": "",
        "error": "",
        "request_window": "09:25-09:30",
    }
    quotes_map: dict[str, dict[str, Any]] = {}

    if _should_request_realtime_quotes():
        try:
            cfg = load_config_from_env()
            client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=12, retries=0)
            step = 20
            for i in range(0, len(uniq_codes), step):
                batch = uniq_codes[i : i + step]
                rows = fetch_stocks_realtime(client, ",".join(batch)) if batch else []
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    quote = _normalize_realtime_quote(row)
                    if not quote or not _is_entry_window_time(str(quote.get("time") or "")):
                        continue
                    if quote.get("time") and not diagnostics["as_of"]:
                        diagnostics["as_of"] = quote["time"]
                    quotes_map[quote["code"]] = quote
            diagnostics["remote_received"] = len(quotes_map)
        except Exception as exc:
            diagnostics["error"] = str(exc)
    else:
        diagnostics["source"] = "window_closed"
        diagnostics["error"] = "仅允许在 09:25-09:30 请求批量竞价接口，当前时段跳过远端请求。"

    fallback_map = fallback_quotes if isinstance(fallback_quotes, dict) else {}
    if fallback_map:
        for code6 in uniq_codes:
            if code6 in quotes_map:
                continue
            raw = fallback_map.get(code6)
            if not isinstance(raw, dict):
                continue
            quote = _normalize_realtime_quote(raw)
            if not quote or not _is_entry_window_time(str(quote.get("time") or "")):
                continue
            quotes_map[code6] = quote
            diagnostics["fallback_used"] += 1
            if quote.get("time") and not diagnostics["as_of"]:
                diagnostics["as_of"] = quote["time"]

    if not quotes_map and diagnostics["fallback_used"] > 0:
        diagnostics["source"] = "cache.raw.quotes"
    elif quotes_map and diagnostics["fallback_used"] > 0:
        diagnostics["source"] = "remote+cache.raw.quotes"
    elif not quotes_map and diagnostics["source"] != "window_closed":
        diagnostics["source"] = "unavailable"

    diagnostics["received"] = len(quotes_map)
    diagnostics["missing"] = [code for code in uniq_codes if code not in quotes_map]
    return quotes_map, diagnostics


def _signal_rank(status: str) -> int:
    if status == "super":
        return 0
    if status == "expected":
        return 1
    if status == "pending":
        return 2
    if status == "reject":
        return 3
    return 4


def _evaluate_realtime_signal(record: dict[str, Any], quote: dict[str, Any] | None) -> dict[str, Any]:
    exp = record.get("expectation") or {}
    expected_range = exp.get("expected_range")
    super_gap_min = exp.get("super_gap_min")
    auction_amount_min_yi = float(exp.get("auction_amount_min_yi") or 0.0)
    seal_amount_min_yi = float(exp.get("seal_amount_min_yi") or 0.0)
    open_board_limit = exp.get("super_requires_open_board_limit")
    requires_reseal = bool(exp.get("super_requires_reseal"))
    base = {
        "date10": record.get("date10"),
        "code": record.get("code"),
        "name": record.get("name"),
        "bucket": record.get("bucket"),
        "bucket_label": record.get("bucket_label"),
        "score": record.get("score"),
        "main_line": record.get("main_line"),
        "reason_text": record.get("reason_text"),
        "expected_text": exp.get("expected_text") or "",
        "super_text": exp.get("super_text") or "",
        "quote_time": str((quote or {}).get("time") or "").strip(),
        "auction_amount_need_yi": round(auction_amount_min_yi, 2),
        "seal_amount_need_yi": round(seal_amount_min_yi, 2),
        "requires_reseal": requires_reseal,
        "open_board_limit": open_board_limit,
    }
    if not isinstance(quote, dict):
        return {
            **base,
            "decision_status": "unavailable",
            "decision_label": "报价缺失",
            "signal_status": "unavailable",
            "signal_label": "无法判断",
            "note": "未拿到 9:25 实时报价，当前不生成买入信号。",
        }

    prev_close = float(quote.get("prev_close") or 0.0)
    auction_price = float(quote.get("auction_price") or 0.0)
    auction_amount_yi = float(quote.get("auction_amount_yi") or 0.0)
    gap_pct = round((auction_price - prev_close) / prev_close * 100.0, 2) if prev_close > 0 and auction_price > 0 else None
    base.update(
        {
            "prev_close": round(prev_close, 2) if prev_close > 0 else None,
            "auction_price": round(auction_price, 2) if auction_price > 0 else None,
            "auction_price_field": quote.get("auction_price_field") or "",
            "auction_amount_yi": round(auction_amount_yi, 2),
            "open_board_count": quote.get("open_board_count"),
            "gap_pct": gap_pct,
        }
    )
    if prev_close <= 0 or auction_price <= 0 or auction_amount_yi <= 0:
        return {
            **base,
            "decision_status": "unavailable",
            "decision_label": "价格/量能不完整",
            "signal_status": "unavailable",
            "signal_label": "无法判断",
            "note": "9:25 价格或竞价成交额缺失，暂不纳入买入列表。",
        }

    super_gap_ok = super_gap_min is not None and gap_pct is not None and gap_pct >= float(super_gap_min)
    expected_ok = expected_range is not None and gap_pct is not None and expected_range[0] <= gap_pct <= expected_range[1]
    auction_ok = auction_amount_yi >= auction_amount_min_yi if auction_amount_min_yi > 0 else True

    pending_reasons: list[str] = []
    if requires_reseal:
        pending_reasons.append("需要回封确认")
    if seal_amount_min_yi > 0:
        pending_reasons.append(f"需要封单回补≥{seal_amount_min_yi:.2f}亿")
    if open_board_limit is not None:
        pending_reasons.append(f"需要开板≤{open_board_limit}")

    if super_gap_ok and auction_ok and not pending_reasons:
        return {
            **base,
            "decision_status": "buy",
            "decision_label": "直接买入",
            "signal_status": "super",
            "signal_label": "超预期",
            "rule_text": exp.get("super_text") or "",
            "note": f"高开 {gap_pct:+.2f}% 且竞价成交额 {auction_amount_yi:.2f} 亿，满足 9:25 可执行超预期条件。",
        }

    if super_gap_ok and auction_ok and pending_reasons:
        return {
            **base,
            "decision_status": "pending",
            "decision_label": "待盘中确认",
            "signal_status": "pending",
            "signal_label": "超预期待确认",
            "rule_text": exp.get("super_text") or "",
            "pending_reasons": pending_reasons,
            "note": "竞价价格和量能已到位，但策略还要求盘中确认条件，9:25 不直接买入。",
        }

    if expected_ok:
        return {
            **base,
            "decision_status": "buy",
            "decision_label": "直接买入",
            "signal_status": "expected",
            "signal_label": "符合预期",
            "rule_text": exp.get("expected_text") or "",
            "note": f"开盘缺口 {gap_pct:+.2f}% 落在预期区间内，按计划列入开盘买入列表。",
        }

    if super_gap_ok and not auction_ok:
        return {
            **base,
            "decision_status": "reject",
            "decision_label": "量能不达标",
            "signal_status": "reject",
            "signal_label": "未达买点",
            "rule_text": exp.get("super_text") or "",
            "note": f"高开达到超预期，但竞价成交额 {auction_amount_yi:.2f} 亿，小于阈值 {auction_amount_min_yi:.2f} 亿。",
        }

    return {
        **base,
        "decision_status": "reject",
        "decision_label": "未达买点",
        "signal_status": "reject",
        "signal_label": "未达买点",
        "rule_text": exp.get("low_text") or exp.get("expected_text") or "",
        "note": "9:25 缺口未落在符合预期或可直接执行的超预期区间内。",
    }


def _build_realtime_buy_payload(rows: list[dict[str, Any]], *, latest_date10: str) -> dict[str, Any]:
    latest_rows = [dict(row) for row in rows if row.get("date10") == latest_date10]
    if not _should_request_realtime_quotes():
        preserved = _load_preserved_realtime_buy(latest_date10)
        if isinstance(preserved, dict):
            diagnostics = preserved.get("diagnostics") if isinstance(preserved.get("diagnostics"), dict) else {}
            preserved["diagnostics"] = {
                **diagnostics,
                "source": "preserved_snapshot",
                "request_window": "09:25-09:30",
                "preserved_note": "当前不在 09:25-09:30，复用已落地的竞价观察结果，不重复请求远端接口。",
            }
            return preserved

    latest_raw = _load_latest_stock_research_snapshot(latest_date10)
    raw_quotes = latest_raw.get("raw", {}).get("quotes", {}).get("items", {}) if isinstance(latest_raw.get("raw"), dict) else {}
    codes = [str(row.get("code") or "").strip() for row in latest_rows if str(row.get("code") or "").strip()]
    quotes_map, quote_diag = _fetch_realtime_quotes(codes, fallback_quotes=raw_quotes if isinstance(raw_quotes, dict) else None)

    decisions = [_evaluate_realtime_signal(row, quotes_map.get(str(row.get("code") or "").strip())) for row in latest_rows]
    decisions.sort(key=lambda x: (_signal_rank(str(x.get("signal_status") or "")), -int(x.get("score") or 0), str(x.get("code") or "")))

    buy_list = [row for row in decisions if row.get("decision_status") == "buy"]
    pending_list = [row for row in decisions if row.get("decision_status") == "pending"]
    rejected_list = [row for row in decisions if row.get("decision_status") == "reject"]
    unavailable_list = [row for row in decisions if row.get("decision_status") == "unavailable"]
    direct_super = [row for row in buy_list if row.get("signal_status") == "super"]
    direct_expected = [row for row in buy_list if row.get("signal_status") == "expected"]

    return {
        "reference_date": latest_date10,
        "entry_window": "09:25-09:30",
        "quote_time": quote_diag.get("as_of") or _now_bj().strftime("%Y-%m-%d %H:%M:%S"),
        "source_module": "ztAnalysis.relay/watch",
        "quote_source": "biying hsrl/ssjy_more 实时行情（失败时回退 raw.quotes）",
        "candidate_count": len(latest_rows),
        "quoted_count": quote_diag.get("received", 0),
        "buy_count": len(buy_list),
        "direct_super_count": len(direct_super),
        "direct_expected_count": len(direct_expected),
        "pending_count": len(pending_list),
        "rejected_count": len(rejected_list),
        "unavailable_count": len(unavailable_list),
        "buy_list": buy_list,
        "pending_list": pending_list,
        "rejected_list": rejected_list,
        "unavailable_list": unavailable_list,
        "diagnostics": quote_diag,
    }


def _classify_open_window(record: dict[str, Any], entry_bar: dict[str, Any]) -> dict[str, Any]:
    prev_close = float(entry_bar.get("prev_close") or 0.0)
    entry_open = float(entry_bar.get("open") or 0.0)
    gap_pct = round((entry_open - prev_close) / prev_close * 100.0, 2) if prev_close > 0 else 0.0

    exp = record.get("expectation") or {}
    expected_range = exp.get("expected_range")
    super_gap_min = exp.get("super_gap_min")
    super_requires_reseal = bool(exp.get("super_requires_reseal"))
    expected_text = str(exp.get("expected_text") or "")
    super_text = str(exp.get("super_text") or "")

    if expected_range and expected_range[0] <= gap_pct <= expected_range[1]:
        return {
            "status": "expected",
            "label": "符合预期",
            "gap_pct": gap_pct,
            "note": expected_text or "开盘缺口落在预期区间内",
            "can_enter": True,
        }
    if super_gap_min is not None and gap_pct >= super_gap_min and not super_requires_reseal:
        return {
            "status": "super",
            "label": "超预期开盘",
            "gap_pct": gap_pct,
            "note": super_text or "开盘缺口达到超预期阈值",
            "can_enter": True,
        }
    if super_gap_min is not None and gap_pct >= super_gap_min and super_requires_reseal:
        return {
            "status": "wait_reseal",
            "label": "高开但需回封确认",
            "gap_pct": gap_pct,
            "note": super_text or "超预期条件要求回封，9:25-9:30 不能直接确认",
            "can_enter": False,
        }
    return {
        "status": "reject",
        "label": "低预期/未确认",
        "gap_pct": gap_pct,
        "note": str(exp.get("low_text") or "开盘未落在预期/超预期可执行区间"),
        "can_enter": False,
    }


def _evaluate_one(record: dict[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
    future = [bar for bar in bars if bar["date"] > record["date10"]]
    if not future:
        missing = {"status": "missing", "label": "无后续价格", "note": "推荐日后没有可用交易日价格"}
        return {
            "open_check": missing,
            "next_day": {"status": "missing", "label": "隔日收益", "note": "推荐日后没有可用交易日价格"},
            "hold_3d": {"status": "missing", "label": "3日收益", "note": "推荐日后没有可用交易日价格"},
            "hold_5d": {"status": "missing", "label": "5日收益", "note": "推荐日后没有可用交易日价格"},
        }

    entry = future[0]
    open_check = _classify_open_window(record, entry)
    if not open_check.get("can_enter"):
        skipped = {
            "status": "skipped",
            "label": "未入场",
            "note": open_check.get("note") or "开盘窗口未满足条件",
            "gap_pct": open_check.get("gap_pct"),
        }
        return {
            "open_check": open_check,
            "next_day": skipped,
            "hold_3d": skipped,
            "hold_5d": skipped,
        }

    perf: dict[str, Any] = {"open_check": open_check}
    for key, label, offset in STRATEGIES:
        if len(future) < offset:
            perf[key] = {
                "status": "pending",
                "label": label,
                "entry_date": entry["date"],
                "note": f"当前仅拿到 {len(future)} 个后续交易日，尚不足以计算 T+{offset}",
            }
            continue
        exit_bar = future[offset - 1]
        entry_open = float(entry["open"])
        exit_close = float(exit_bar["close"])
        return_pct = round((exit_close - entry_open) / entry_open * 100.0, 2) if entry_open > 0 else 0.0
        perf[key] = {
            "status": "covered",
            "label": label,
            "entry_date": entry["date"],
            "exit_date": exit_bar["date"],
            "entry_open": round(entry_open, 2),
            "exit_close": round(exit_close, 2),
            "return_pct": return_pct,
            "win": return_pct > 0,
            "flat": return_pct == 0,
            "loss": return_pct < 0,
            "days_after_pick": offset,
        }
    return perf


def _summarize_strategy(records: list[dict[str, Any]], key: str, label: str) -> dict[str, Any]:
    eligible = [r for r in records if (r.get("performance") or {}).get("open_check", {}).get("can_enter")]
    covered_rows = [r for r in eligible if (r.get("performance") or {}).get(key, {}).get("status") == "covered"]
    pending_rows = [r for r in eligible if (r.get("performance") or {}).get(key, {}).get("status") == "pending"]
    missing_rows = [r for r in eligible if (r.get("performance") or {}).get(key, {}).get("status") == "missing"]
    skipped_rows = [r for r in records if (r.get("performance") or {}).get(key, {}).get("status") == "skipped"]
    returns = [float(r["performance"][key]["return_pct"]) for r in covered_rows]
    wins = [r for r in covered_rows if r["performance"][key]["return_pct"] > 0]
    flats = [r for r in covered_rows if r["performance"][key]["return_pct"] == 0]
    losses = [r for r in covered_rows if r["performance"][key]["return_pct"] < 0]

    by_open_status: dict[str, Any] = {}
    for open_status in ("super", "expected"):
        rows = [r for r in covered_rows if (r.get("performance") or {}).get("open_check", {}).get("status") == open_status]
        row_returns = [float(r["performance"][key]["return_pct"]) for r in rows]
        by_open_status[open_status] = {
            "covered": len(rows),
            "win_rate": _pct(sum(1 for x in row_returns if x > 0), len(rows)),
            "avg_return": _avg(row_returns),
        }

    return {
        "key": key,
        "label": label,
        "status": "ready" if covered_rows else ("partial" if pending_rows else "missing"),
        "covered": len(covered_rows),
        "total": len(records),
        "eligible": len(eligible),
        "coverage": _pct(len(covered_rows), len(eligible)),
        "pending": len(pending_rows),
        "missing": len(missing_rows),
        "skipped": len(skipped_rows),
        "win_count": len(wins),
        "flat_count": len(flats),
        "loss_count": len(losses),
        "win_rate": _pct(len(wins), len(covered_rows)),
        "avg_return": _avg(returns),
        "avg_win_return": _avg([float(r["performance"][key]["return_pct"]) for r in wins]),
        "avg_loss_return": _avg([float(r["performance"][key]["return_pct"]) for r in losses]),
        "by_open_status": by_open_status,
        "top_winners": [
            {
                "date": r["date10"],
                "code": r["code"],
                "name": r["name"],
                "bucket": r["bucket"],
                "open_status": r["performance"]["open_check"]["status"],
                "return_pct": r["performance"][key]["return_pct"],
            }
            for r in sorted(covered_rows, key=lambda x: x["performance"][key]["return_pct"], reverse=True)[:6]
        ],
        "top_losers": [
            {
                "date": r["date10"],
                "code": r["code"],
                "name": r["name"],
                "bucket": r["bucket"],
                "open_status": r["performance"]["open_check"]["status"],
                "return_pct": r["performance"][key]["return_pct"],
            }
            for r in sorted(covered_rows, key=lambda x: x["performance"][key]["return_pct"])[:6]
        ],
        "note": "只统计 ztAnalysis 同源推荐；仅在次日 09:25-09:30 开盘信号满足符合预期或超预期开口径时记为入场。",
    }


def build_stock_research_backtest_payload() -> dict[str, Any]:
    rows, generated_from = _load_stock_research_rows()
    if not rows:
        raise ValueError("No ztAnalysis stock research rows found in cache/market_data-*.json")

    unique_codes = sorted({r["code"] for r in rows if r["code"]})
    date_list = sorted({r["date10"] for r in rows})
    latest_date10 = date_list[-1]
    histories, price_diag = _get_price_histories(unique_codes, st8=date_list[0].replace("-", ""), et8=_now_bj().strftime("%Y%m%d"))
    realtime_buy = _build_realtime_buy_payload(rows, latest_date10=latest_date10)

    enriched_rows: list[dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        rec["performance"] = _evaluate_one(rec, histories.get(rec["code"], []))
        enriched_rows.append(rec)

    total = len(enriched_rows)
    eligible_rows = [r for r in enriched_rows if (r.get("performance") or {}).get("open_check", {}).get("can_enter")]
    super_rows = [r for r in enriched_rows if (r.get("performance") or {}).get("open_check", {}).get("status") == "super"]
    expected_rows = [r for r in enriched_rows if (r.get("performance") or {}).get("open_check", {}).get("status") == "expected"]
    wait_reseal_rows = [r for r in enriched_rows if (r.get("performance") or {}).get("open_check", {}).get("status") == "wait_reseal"]
    rejected_rows = [r for r in enriched_rows if (r.get("performance") or {}).get("open_check", {}).get("status") == "reject"]

    by_bucket = Counter(r["bucket"] for r in enriched_rows)
    by_open_status = Counter((r.get("performance") or {}).get("open_check", {}).get("status") or "unknown" for r in enriched_rows)
    by_mainline = Counter(r["main_line"] for r in enriched_rows if r["main_line"])
    by_date_status: dict[str, dict[str, int]] = defaultdict(lambda: {"super": 0, "expected": 0, "wait_reseal": 0, "reject": 0})
    for row in enriched_rows:
        status = (row.get("performance") or {}).get("open_check", {}).get("status") or "reject"
        if status not in by_date_status[row["date10"]]:
            by_date_status[row["date10"]][status] = 0
        by_date_status[row["date10"]][status] += 1

    metrics = {
        "next_day": _summarize_strategy(enriched_rows, "next_day", "隔日收益"),
        "hold_3d": _summarize_strategy(enriched_rows, "hold_3d", "3日收益"),
        "hold_5d": _summarize_strategy(enriched_rows, "hold_5d", "5日收益"),
    }

    return {
        "meta": {
            "title": "个股研究开盘回测",
            "subtitle": "同源读取 ztAnalysis 接力/观察推荐；首屏先看最新推荐在 09:25-09:30 的实时买入列表，历史样本继续用于开盘回测复盘。",
            "dates": date_list,
            "generated_at_bj": _now_bj().strftime("%Y-%m-%d %H:%M:%S"),
            "generated_from": generated_from,
            "price_source": "biying hsstock/history + 本地 recommendation_price_history 缓存",
            "entry_window": "09:25-09:30",
            "source_module": "ztAnalysis.relay/watch",
            "latest_recommendation_date": latest_date10,
        },
        "summary": {
            "total_samples": total,
            "eligible_samples": len(eligible_rows),
            "expected_count": len(expected_rows),
            "super_count": len(super_rows),
            "wait_reseal_count": len(wait_reseal_rows),
            "rejected_count": len(rejected_rows),
            "unique_codes": len(unique_codes),
            "trade_days": len(date_list),
            "priced_codes": len(histories),
            "missing_price_codes": price_diag["missing"],
            "realtime_candidate_count": realtime_buy["candidate_count"],
            "realtime_buy_count": realtime_buy["buy_count"],
            "realtime_pending_count": realtime_buy["pending_count"],
            "realtime_unavailable_count": realtime_buy["unavailable_count"],
        },
        "assumptions": [
            "样本池只取 cache/market_data-YYYYMMDD.json 中 ztAnalysis.relay 与 ztAnalysis.watch 这组同源推荐。",
            "最新推荐日的 9:25 买入列表只允许在北京时区 09:25-09:30 请求 biying 批量竞价接口；窗口外只复用已落地结果，不因页面刷新重复取数。",
            "如果当前环境拿不到远端数据，只会展示待补齐/报价缺失，不会伪造买点。",
            "入场窗口限定为次日 09:25-09:30；只有开盘缺口满足“符合预期”或可在开盘窗口确认“超预期”时，才记为买入样本。",
            "若超预期文案要求“回封/封单回补/开板≤1”等开盘后行为，当前历史回测会保守记为 wait_reseal，不在开盘窗口直接入场。",
            "当前仓库没有历史竞价成交额与逐分钟封单回补明细，因此超预期中的竞价量能条件暂按开盘缺口代理，不把它当成完全等价的实盘复刻。",
            "收益口径仍按次日开盘买入、目标交易日收盘卖出；未扣除手续费、滑点，也未处理一字板无法成交的真实约束。",
        ],
        "breakdowns": {
            "by_bucket": [{"name": k, "count": v} for k, v in by_bucket.items()],
            "by_open_status": [{"name": k, "count": v} for k, v in by_open_status.items()],
            "by_mainline": [{"name": k, "count": v} for k, v in by_mainline.most_common(10)],
            "by_date_status": [{"date": k, **v} for k, v in sorted(by_date_status.items())],
        },
        "metrics": metrics,
        "realtimeBuy": realtime_buy,
        "records": enriched_rows,
        "spotlight": {
            "super_candidates": sorted(super_rows, key=lambda x: (-x["score"], x["date"], x["code"]))[:10],
            "expected_candidates": sorted(expected_rows, key=lambda x: (-x["score"], x["date"], x["code"]))[:10],
            "best_t3_trades": metrics["hold_3d"]["top_winners"],
            "worst_t3_trades": metrics["hold_3d"]["top_losers"],
        },
        "diagnostics": {
            "price_history": price_diag,
            "realtime_buy": realtime_buy.get("diagnostics", {}),
        },
    }


def main() -> None:
    payload = build_stock_research_backtest_payload()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    OUT_JSON.write_text(json_text, encoding="utf-8")
    OUT_JS.write_text(f"window.__STOCK_RESEARCH_BACKTEST__ = {json_text};\n", encoding="utf-8")
    print(str(OUT_JSON))
    print(str(OUT_JS))


if __name__ == "__main__":
    main()
