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
TZ_BJ = timezone(timedelta(hours=8))

STRATEGIES = (
    ("next_day", "隔日收益", 1),
    ("hold_2d", "2日收益", 2),
    ("hold_3d", "3日收益", 3),
)

DIRECT_BUY_RANK_LIMIT = 3
CAUTION_GAP_PCT = 5.0


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


def _source_history_path() -> Path:
    return CACHE_DIR / "stock_research_backtest_source.json"


def _trade_days_cache_path_candidates() -> list[Path]:
    return [
        CACHE_DIR / "trade_days_cache.json",
        ROOT / "cache_online" / "trade_days_cache.json",
    ]


def _load_trade_days() -> list[str]:
    for path in _trade_days_cache_path_candidates():
        data = _load_json(path, default={})
        if not isinstance(data, dict):
            continue
        days = data.get("days")
        if not isinstance(days, list):
            continue
        cleaned = [str(day).strip() for day in days if isinstance(day, str) and len(str(day).strip()) == 10]
        if cleaned:
            return sorted(dict.fromkeys(cleaned))
    return []


def _next_weekday(date10: str) -> str:
    current = datetime.strptime(date10, "%Y-%m-%d")
    probe = current + timedelta(days=1)
    while probe.weekday() >= 5:
        probe += timedelta(days=1)
    return probe.strftime("%Y-%m-%d")


def _resolve_next_trade_date(date10: str) -> str:
    days = _load_trade_days()
    if days:
        future = [day for day in days if day > date10]
        if future:
            return future[0]
    return _next_weekday(date10)


def _is_open_session(now: datetime | None = None) -> bool:
    current = now or _now_bj()
    total = current.hour * 3600 + current.minute * 60 + current.second
    return 9 * 3600 + 30 * 60 <= total < 15 * 3600


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


def _parse_surge_threshold(text: str) -> float | None:
    m = re.search(r"盘中冲高确认（竞价价\+≥([\d.]+)%）", text)
    if not m:
        return None
    return float(m.group(1))


def _parse_volume_expand_ratio(text: str) -> float | None:
    m = re.search(r"量能.*≥竞价量×([\d.]+)", text)
    if not m:
        return None
    return float(m.group(1))


def _extract_expectation(reason_html: str) -> dict[str, Any]:
    flat = _strip_html(reason_html)
    expected_match = re.search(r"预期\s*(.+?)(?=\s*超预期|\s*低预期|$)", flat)
    super_match = re.search(r"超预期\s*(.+?)(?=\s*低预期|$)", flat)
    low_match = re.search(r"低预期\s*(.+?)$", flat)
    expected_text = expected_match.group(1).strip(" ：:;") if expected_match else ""
    super_text = super_match.group(1).strip(" ：:;") if super_match else ""
    low_text = low_match.group(1).strip(" ：:;") if low_match else ""
    # 新版条件（冲高/量能）优先；旧版（回封/封单/开板）向后兼容
    has_new_conditions = "冲高确认" in super_text or "量能" in super_text
    return {
        "expected_text": expected_text,
        "super_text": super_text,
        "low_text": low_text,
        "expected_range": _parse_expected_range(expected_text),
        "super_gap_min": _parse_super_open_threshold(super_text),
        "auction_amount_min_yi": _parse_amount_threshold_yi(super_text, r"竞价成交额≥\s*([0-9]+(?:\.[0-9]+)?)亿"),
        # 新版：冲高/量能确认条件
        "surge_pct_min": _parse_surge_threshold(super_text) if has_new_conditions else None,
        "volume_expand_ratio": _parse_volume_expand_ratio(super_text) if has_new_conditions else None,
        # 旧版兼容：回封/封单/开板
        "super_requires_reseal": "回封" in super_text if not has_new_conditions else False,
        "super_requires_open_board_limit": _parse_open_board_limit(super_text) if not has_new_conditions else None,
        "seal_amount_min_yi": _parse_amount_threshold_yi(super_text, r"(?:封单回补|回封后封单)≥\s*([0-9]+(?:\.[0-9]+)?)亿") if not has_new_conditions else None,
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


def _load_source_history() -> dict[str, Any]:
    data = _load_json(_source_history_path(), default={})
    if not isinstance(data, dict):
        return {"schema": "stock_research_backtest_source_v1", "dates": {}}
    data.setdefault("schema", "stock_research_backtest_source_v1")
    data.setdefault("dates", {})
    return data


def _save_source_history(payload: dict[str, Any]) -> None:
    payload["updated_at_bj"] = _now_bj().strftime("%Y-%m-%d %H:%M:%S")
    _write_json(_source_history_path(), payload)


def sync_stock_research_backtest_source(*, market_data: dict[str, Any]) -> bool:
    if not isinstance(market_data, dict):
        return False
    date10 = str(market_data.get("date") or "").strip()
    if len(date10) != 10:
        return False
    meta = market_data.get("meta") if isinstance(market_data.get("meta"), dict) else {}
    if str(meta.get("mode") or "").strip() == "intraday":
        return False
    zt = market_data.get("ztAnalysis") if isinstance(market_data.get("ztAnalysis"), dict) else {}
    relay = zt.get("relay") if isinstance(zt.get("relay"), list) else []
    watch = zt.get("watch") if isinstance(zt.get("watch"), list) else []
    if not relay and not watch:
        return False

    rows = [_row_from_item(item, date10=date10, bucket="relay") for item in relay if isinstance(item, dict)]
    rows.extend(_row_from_item(item, date10=date10, bucket="watch") for item in watch if isinstance(item, dict))
    if not rows:
        return False
    trade_date10 = _resolve_next_trade_date(date10)
    for row in rows:
        row["trade_date10"] = trade_date10

    history = _load_source_history()
    dates = history.setdefault("dates", {})
    dates[trade_date10] = {
        "date": trade_date10,
        "recommendation_date": date10,
        "source": "ztAnalysis.relay/watch.close_push",
        "generated_at_bj": str(meta.get("generatedAt") or "").strip(),
        "pushed_at_bj": _now_bj().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": rows,
    }
    _save_source_history(history)
    return True


def _load_stock_research_rows() -> tuple[list[dict[str, Any]], list[str]]:
    history = _load_source_history()
    dates = history.get("dates") if isinstance(history.get("dates"), dict) else {}

    rows: list[dict[str, Any]] = []
    used_sources: list[str] = []
    for date10 in sorted(dates.keys()):
        item = dates.get(date10)
        if not isinstance(item, dict):
            continue
        day_rows = item.get("rows") if isinstance(item.get("rows"), list) else []
        if not day_rows:
            continue
        used_sources.append(str(item.get("source") or f"stock_research_backtest_source:{date10}"))
        rows.extend(day_rows)
    rows.sort(key=lambda x: (x["date"], -x["score"], x["code"]))
    return rows, used_sources


def _attach_daily_rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("date10") or "")].append(dict(row))

    ranked_rows: list[dict[str, Any]] = []
    for date10 in sorted(grouped.keys()):
        day_rows = grouped[date10]
        day_rows.sort(key=lambda x: (-int(x.get("score") or 0), str(x.get("code") or "")))
        for idx, row in enumerate(day_rows, start=1):
            row["daily_rank"] = idx
            row["direct_buy_rank_limit"] = DIRECT_BUY_RANK_LIMIT
            ranked_rows.append(row)

    ranked_rows.sort(key=lambda x: (x["date"], -x["score"], x["code"]))
    return ranked_rows


def _pick_active_trade_date(rows: list[dict[str, Any]], *, now: datetime | None = None) -> str:
    trade_dates = sorted({str(row.get("trade_date10") or "") for row in rows if str(row.get("trade_date10") or "")})
    if not trade_dates:
        return ""
    current = now or _now_bj()
    today10 = current.strftime("%Y-%m-%d")
    if _is_open_session(current) and today10 in trade_dates:
        return today10
    recommendation_dates = sorted({str(row.get("date10") or "") for row in rows if str(row.get("date10") or "")})
    latest_recommendation_date = recommendation_dates[-1] if recommendation_dates else ""
    if latest_recommendation_date:
        target_trade_date = _resolve_next_trade_date(latest_recommendation_date)
        if target_trade_date in trade_dates:
            return target_trade_date
    future_or_today = [date10 for date10 in trade_dates if date10 >= today10]
    if future_or_today:
        return future_or_today[0]
    return trade_dates[-1]


def _seconds_since_midnight(current: datetime) -> int:
    return current.hour * 3600 + current.minute * 60 + current.second


def _build_lifecycle(
    *,
    latest_recommendation_date10: str,
    active_trade_date10: str,
    latest_backtest_date10: str,
    current_pool_rows: list[dict[str, Any]],
    backtest_rows: list[dict[str, Any]],
    realtime_buy: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or _now_bj()
    today10 = current.strftime("%Y-%m-%d")
    now_seconds = _seconds_since_midnight(current)
    quote_time = str(realtime_buy.get("quote_time") or "").strip()
    quoted_count = int(realtime_buy.get("quoted_count") or 0)
    candidate_count = int(realtime_buy.get("candidate_count") or 0)
    has_current_plan = bool(current_pool_rows)
    has_historical_records = bool(backtest_rows)
    has_realtime_snapshot = bool(realtime_buy.get("reference_date")) and quoted_count > 0 and _is_entry_window_time(quote_time)

    quote_state = "pending_source"
    quote_state_label = "等待推送"
    quote_state_note = "当前还没有落地到可读的竞价引用日。"

    if has_realtime_snapshot:
        quote_state = "ready"
        quote_state_label = "快照已落地"
        quote_state_note = f"9:25 竞价快照已生成，时间 {quote_time or '-'}。"
    elif has_current_plan:
        if active_trade_date10 and active_trade_date10 > today10:
            quote_state = "waiting_trade_day"
            quote_state_label = "等待明日竞价"
            quote_state_note = f"盘后样本已经推到推荐日 {latest_recommendation_date10 or '-'}，等待 {active_trade_date10} 的 09:25-09:30 竞价快照。"
        elif active_trade_date10 and active_trade_date10 == today10:
            if now_seconds < 9 * 3600 + 25 * 60:
                quote_state = "waiting_window"
                quote_state_label = "等待开盘窗口"
                quote_state_note = f"今天要验证 {active_trade_date10}，需等 09:25-09:30 才能落地真实竞价结果。"
            elif _should_request_realtime_quotes(current):
                quote_state = "window_live"
                quote_state_label = "窗口进行中"
                quote_state_note = "当前正处于 09:25-09:30，可直接抓取实时竞价结果。"
            else:
                quote_state = "missing"
                quote_state_label = "快照缺失"
                quote_state_note = f"{active_trade_date10} 的 09:25 竞价窗口已过，但没有拿到有效快照，当前只保留待验证池。"
        else:
            quote_state = "missing" if candidate_count > 0 else "pending_source"
            quote_state_label = "快照缺失" if candidate_count > 0 else "等待推送"
            quote_state_note = "当前待验证池存在，但缺少可用的 9:25 竞价快照。"
    elif has_historical_records:
        quote_state = "historical_only"
        quote_state_label = "仅历史统计"
        quote_state_note = "当前没有待验证池，仅保留历史胜率和样本明细。"

    stage = "empty"
    stage_label = "暂无数据"
    stage_note = "当前还没有可展示的个股回测样本。"
    if has_current_plan and has_realtime_snapshot:
        stage = "auction_snapshot_ready"
        stage_label = "竞价结果已落地"
        stage_note = f"推荐日 {latest_recommendation_date10 or '-'} 的待验证池已匹配到 {active_trade_date10 or '-'} 9:25 竞价结果，历史统计与当前快照都可同时查看。"
    elif has_current_plan:
        if quote_state in {"waiting_trade_day", "waiting_window", "window_live"}:
            stage = "post_close_wait_auction"
            stage_label = "盘后待验证"
            stage_note = f"收盘后样本已经更新到推荐日 {latest_recommendation_date10 or '-'}，当前先展示待验证池；到 {active_trade_date10 or '-'} 09:25-09:30 再补真实竞价结果。"
        else:
            stage = "auction_snapshot_missing"
            stage_label = "竞价快照缺失"
            stage_note = f"待验证池已经存在，但 {active_trade_date10 or '-'} 的 9:25 快照没有成功落地，胜率统计只会停留在历史样本。"
    elif has_historical_records:
        stage = "historical_only"
        stage_label = "仅历史统计"
        stage_note = "当前没有新待验证池，页面仅展示历史样本和策略表现。"

    return {
        "stage": stage,
        "stage_label": stage_label,
        "stage_note": stage_note,
        "quote_state": quote_state,
        "quote_state_label": quote_state_label,
        "quote_state_note": quote_state_note,
        "has_current_plan": has_current_plan,
        "has_historical_records": has_historical_records,
        "has_realtime_snapshot": has_realtime_snapshot,
        "latest_recommendation_date": latest_recommendation_date10,
        "active_trade_date": active_trade_date10,
        "latest_historical_recommendation_date": latest_backtest_date10,
        "realtime_reference_date": str(realtime_buy.get("reference_date") or "").strip(),
        "quote_time": quote_time,
    }


def upgrade_stock_research_backtest_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if str(payload.get("schema") or "") != "stock_research_backtest_v2":
        return payload

    upgraded = json.loads(json.dumps(payload, ensure_ascii=False))
    meta = upgraded.get("meta") if isinstance(upgraded.get("meta"), dict) else {}
    realtime_buy = upgraded.get("realtimeBuy") if isinstance(upgraded.get("realtimeBuy"), dict) else {}
    current_pool_rows = upgraded.get("currentPoolRecords") if isinstance(upgraded.get("currentPoolRecords"), list) else []
    backtest_rows = upgraded.get("records") if isinstance(upgraded.get("records"), list) else []
    latest_recommendation_date10 = str(meta.get("latest_recommendation_date") or realtime_buy.get("reference_date") or "").strip()
    active_trade_date10 = str(meta.get("active_trade_date") or realtime_buy.get("trade_date") or "").strip()
    historical_dates = sorted({str(row.get("date10") or "").strip() for row in backtest_rows if str(row.get("date10") or "").strip()})
    latest_backtest_date10 = historical_dates[-1] if historical_dates else ""

    upgraded["meta"] = meta
    meta.setdefault("is_empty", not current_pool_rows and not backtest_rows)
    metrics = upgraded.get("metrics") if isinstance(upgraded.get("metrics"), dict) else {}
    upgraded["metrics"] = metrics
    for key in ("next_day", "hold_2d", "hold_3d"):
        item = metrics.get(key)
        if not isinstance(item, dict):
            continue
        scopes = item.get("scopes") if isinstance(item.get("scopes"), dict) else {}
        if "tradable" not in scopes:
            tradable_scope = json.loads(json.dumps(item, ensure_ascii=False))
            tradable_scope.pop("scopes", None)
            scopes["tradable"] = tradable_scope
        if "all" not in scopes:
            all_scope = json.loads(json.dumps(scopes["tradable"], ensure_ascii=False))
            all_scope["base_total"] = int(item.get("total") or all_scope.get("total") or 0)
            scopes["all"] = all_scope
        item["scopes"] = scopes
    upgraded["lifecycle"] = _build_lifecycle(
        latest_recommendation_date10=latest_recommendation_date10,
        active_trade_date10=active_trade_date10,
        latest_backtest_date10=latest_backtest_date10,
        current_pool_rows=current_pool_rows,
        backtest_rows=backtest_rows,
        realtime_buy=realtime_buy,
    )
    return upgraded


def _empty_backtest_payload(*, generated_from: list[str] | None = None) -> dict[str, Any]:
    return {
        "schema": "stock_research_backtest_v2",
        "meta": {
            "title": "个股研究开盘回测",
            "subtitle": "回测数据只读取收盘后由个股研究推送进单一历史 JSON 的样本；当前没有可用样本时只展示空结果。",
            "dates": [],
            "generated_at_bj": _now_bj().strftime("%Y-%m-%d %H:%M:%S"),
            "generated_from": list(generated_from or []),
            "price_source": "biying hsstock/history + 本地 recommendation_price_history 缓存",
            "entry_window": "09:25-09:30",
            "source_module": "ztAnalysis.relay/watch",
            "latest_recommendation_date": "",
            "active_trade_date": "",
            "is_empty": True,
        },
        "summary": {
            "total_samples": 0,
            "source_samples": 0,
            "filtered_non_backtest_samples": 0,
            "eligible_samples": 0,
            "expected_count": 0,
            "super_count": 0,
            "pending_count": 0,
            "wait_reseal_count": 0,
            "rejected_count": 0,
            "unique_codes": 0,
            "trade_days": 0,
            "priced_codes": 0,
            "missing_price_codes": [],
            "realtime_candidate_count": 0,
            "realtime_buy_count": 0,
            "realtime_pending_count": 0,
            "realtime_unavailable_count": 0,
        },
        "assumptions": [
            "回测数据只读取收盘后由个股研究推送进专用历史源的样本，不再扫描其他 market_data 缓存。",
            "所有交易日样本都沉淀在同一个 JSON 内，页面只按时间规则选择当前应读取的交易日分桶。",
            "没有同源研究样本时不补造数据，页面只展示空结果。",
        ],
        "breakdowns": {
            "by_bucket": [],
            "by_open_status": [],
            "by_mainline": [],
            "by_date_status": [],
        },
        "metrics": {},
        "lifecycle": {
            "stage": "empty",
            "stage_label": "暂无数据",
            "stage_note": "当前还没有可展示的个股回测样本。",
            "quote_state": "pending_source",
            "quote_state_label": "等待推送",
            "quote_state_note": "当前还没有落地到可读的竞价引用日。",
            "has_current_plan": False,
            "has_historical_records": False,
            "has_realtime_snapshot": False,
            "latest_recommendation_date": "",
            "active_trade_date": "",
            "latest_historical_recommendation_date": "",
            "realtime_reference_date": "",
            "quote_time": "",
        },
        "realtimeBuy": {
            "reference_date": "",
            "trade_date": "",
            "entry_window": "09:25-09:30",
            "quote_time": "",
            "source_module": "ztAnalysis.relay/watch",
            "quote_source": "biying hsrl/ssjy_more 实时行情（失败时回退 raw.quotes）",
            "candidate_count": 0,
            "quoted_count": 0,
            "buy_count": 0,
            "direct_super_count": 0,
            "direct_expected_count": 0,
            "pending_count": 0,
            "rejected_count": 0,
            "unavailable_count": 0,
            "buy_list": [],
            "pending_list": [],
            "rejected_list": [],
            "unavailable_list": [],
            "diagnostics": {"source": "empty"},
        },
        "currentPoolRecords": [],
        "records": [],
        "diagnostics": {
            "price_history": {"source": "empty", "fetched": 0, "cached": 0, "missing": []},
            "realtime_buy": {"source": "empty"},
        },
    }


def _market_data_snapshot_candidates(*, date10: str = "") -> list[Path]:
    candidates: list[tuple[str, int, Path]] = []
    for fp in CACHE_DIR.glob("market_data-*.json"):
        match = re.match(r"^market_data-(\d{8})(-intraday)?$", fp.stem)
        if not match:
            continue
        d8 = match.group(1)
        if date10 and d8 != date10.replace("-", ""):
            continue
        # 同日优先使用 intraday 快照，避免 9:25 的盘中结果后续无法复用。
        priority = 1 if match.group(2) else 0
        candidates.append((d8, priority, fp))
    return [fp for _, _, fp in sorted(candidates, reverse=True)]


def _load_latest_stock_research_snapshot(date10: str) -> dict[str, Any]:
    if len(date10) != 10:
        return {}
    for fp in _market_data_snapshot_candidates(date10=date10):
        raw = _load_json(fp, default={})
        if isinstance(raw, dict):
            return raw
    return {}


def _extract_raw_quotes_items(market_data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(market_data, dict):
        return {}
    raw = market_data.get("raw") if isinstance(market_data.get("raw"), dict) else {}
    quotes = raw.get("quotes") if isinstance(raw.get("quotes"), dict) else {}
    items = quotes.get("items")
    return items if isinstance(items, dict) else {}


def _research_quotes_cache_path(date10: str) -> Path:
    return CACHE_DIR / f"stock_research_realtime_quotes-{date10.replace('-', '')}.json"


def load_prefetched_realtime_quotes(date10: str) -> dict[str, Any]:
    if len(date10) != 10:
        return {}
    data = _load_json(_research_quotes_cache_path(date10), default={})
    return data if isinstance(data, dict) else {}


def save_prefetched_realtime_quotes(*, date10: str, items: dict[str, Any], as_of: str, source: str) -> Path:
    payload = {
        "schema": "stock_research_realtime_quotes_v1",
        "date": date10,
        "as_of": as_of,
        "source": source,
        "count": len(items),
        "items": items,
        "saved_at_bj": _now_bj().strftime("%Y-%m-%d %H:%M:%S"),
    }
    path = _research_quotes_cache_path(date10)
    _write_json(path, payload)
    return path


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
    for fp in _market_data_snapshot_candidates():
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


def _upgrade_preserved_realtime_buy_payload(realtime_buy: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(realtime_buy, dict):
        return {}

    upgraded_rows: list[dict[str, Any]] = []
    migrated_high_gap = 0
    migrated_rank_limited = 0
    for bucket in ("buy_list", "pending_list", "rejected_list", "unavailable_list"):
        for raw_row in realtime_buy.get(bucket) or []:
            if not isinstance(raw_row, dict):
                continue
            row = json.loads(json.dumps(raw_row, ensure_ascii=False))
            decision_status = str(row.get("decision_status") or "")
            gap_pct = row.get("gap_pct")
            try:
                gap_pct_value = float(gap_pct) if gap_pct is not None else None
            except Exception:
                gap_pct_value = None
            rank = int(row.get("daily_rank") or 0)

            if decision_status == "buy" and rank > DIRECT_BUY_RANK_LIMIT:
                row["decision_status"] = "pending"
                row["decision_label"] = "观察"
                row["signal_status"] = "pending"
                row["signal_label"] = "排名靠后"
                row["note"] = f"竞价涨幅 {gap_pct_value:+.2f}% 达到计划条件，但当前评分排名第 {rank}，固定买入只做前三，先观察承接。"
                migrated_rank_limited += 1
            elif decision_status == "buy" and gap_pct_value is not None and gap_pct_value > CAUTION_GAP_PCT:
                row["decision_status"] = "pending"
                row["decision_label"] = "观察"
                row["signal_status"] = "pending"
                row["signal_label"] = "谨慎接力"
                row["note"] = f"竞价涨幅 {gap_pct_value:+.2f}% 大于 {CAUTION_GAP_PCT:.0f}% ，高开偏猛，先观察承接，不直接买入。"
                migrated_high_gap += 1
            upgraded_rows.append(row)

    upgraded_rows.sort(key=lambda x: (_signal_rank(str(x.get("signal_status") or "")), -int(x.get("score") or 0), str(x.get("code") or "")))
    buy_list = [row for row in upgraded_rows if row.get("decision_status") == "buy"]
    pending_list = [row for row in upgraded_rows if row.get("decision_status") == "pending"]
    rejected_list = [row for row in upgraded_rows if row.get("decision_status") == "reject"]
    unavailable_list = [row for row in upgraded_rows if row.get("decision_status") == "unavailable"]
    direct_super = [row for row in buy_list if row.get("signal_status") == "super"]
    direct_expected = [row for row in buy_list if row.get("signal_status") == "expected"]

    upgraded = json.loads(json.dumps(realtime_buy, ensure_ascii=False))
    diagnostics = upgraded.get("diagnostics") if isinstance(upgraded.get("diagnostics"), dict) else {}
    diagnostics["upgraded_rules"] = {
        "migrated_high_gap_buy_to_pending": migrated_high_gap,
        "migrated_rank_limited_buy_to_pending": migrated_rank_limited,
    }
    upgraded.update(
        {
            "candidate_count": len(upgraded_rows),
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
            "diagnostics": diagnostics,
        }
    )
    return upgraded


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


def _fetch_realtime_quotes(codes: list[str], *, fallback_quotes: dict[str, Any] | None = None, force: bool = False) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
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

    if force or _should_request_realtime_quotes():
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

    if diagnostics["source"] == "window_closed" and diagnostics["fallback_used"] > 0:
        diagnostics["source"] = "cache.raw.quotes"
    elif not quotes_map and diagnostics["fallback_used"] > 0:
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
    base = {
        "date10": record.get("date10"),
        "code": record.get("code"),
        "name": record.get("name"),
        "bucket": record.get("bucket"),
        "bucket_label": record.get("bucket_label"),
        "score": record.get("score"),
        "daily_rank": int(record.get("daily_rank") or 0),
        "direct_buy_rank_limit": DIRECT_BUY_RANK_LIMIT,
        "main_line": record.get("main_line"),
        "reason_text": record.get("reason_text"),
        "expected_text": exp.get("expected_text") or "",
        "super_text": exp.get("super_text") or "",
        "low_text": exp.get("low_text") or "",
        "quote_time": str((quote or {}).get("time") or "").strip(),
        "auction_amount_need_yi": round(auction_amount_min_yi, 2),
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
            "auction_amount_yi": round(auction_amount_yi, 2),
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
    rank = int(record.get("daily_rank") or 0)
    rank_limited = rank > DIRECT_BUY_RANK_LIMIT
    high_gap_caution = gap_pct is not None and gap_pct > CAUTION_GAP_PCT

    # 超预期：涨幅达标 + 量能达标 → 直接买入
    if super_gap_ok and auction_ok:
        if rank_limited:
            return {
                **base,
                "decision_status": "pending",
                "decision_label": "仅观察",
                "signal_status": "pending",
                "signal_label": "排名靠后",
                "rule_text": exp.get("super_text") or "",
                "note": f"竞价涨幅 {gap_pct:+.2f}% 达到超预期，但当前评分排名第 {rank}，固定买入只做前三，先观察承接再决定是否接力。",
            }
        if high_gap_caution:
            return {
                **base,
                "decision_status": "pending",
                "decision_label": "观察",
                "signal_status": "pending",
                "signal_label": "谨慎接力",
                "rule_text": exp.get("super_text") or "",
                "note": f"竞价涨幅 {gap_pct:+.2f}% 大于 {CAUTION_GAP_PCT:.0f}% ，属于高开过猛，先观察承接，不直接买入。",
            }
        return {
            **base,
            "decision_status": "buy",
            "decision_label": "直接买入",
            "signal_status": "super",
            "signal_label": "超预期",
            "rule_text": exp.get("super_text") or "",
            "note": f"竞价涨幅 {gap_pct:+.2f}% ≥ 超预期阈值 {super_gap_min:+.2f}%，竞价成交额 {auction_amount_yi:.2f}亿 ≥ {auction_amount_min_yi:.2f}亿，直接买入。",
        }

    # 符合预期：涨幅落在预期区间内 → 直接买入
    if expected_ok:
        if rank_limited:
            return {
                **base,
                "decision_status": "pending",
                "decision_label": "仅观察",
                "signal_status": "pending",
                "signal_label": "排名靠后",
                "rule_text": exp.get("expected_text") or "",
                "note": f"竞价涨幅 {gap_pct:+.2f}% 落在预期区间，但当前评分排名第 {rank}，固定买入只做前三，先观察承接。",
            }
        if high_gap_caution:
            return {
                **base,
                "decision_status": "pending",
                "decision_label": "观察",
                "signal_status": "pending",
                "signal_label": "谨慎接力",
                "rule_text": exp.get("expected_text") or "",
                "note": f"竞价涨幅 {gap_pct:+.2f}% 大于 {CAUTION_GAP_PCT:.0f}% ，虽然符合预期，但不直接买入，先看承接。",
            }
        return {
            **base,
            "decision_status": "buy",
            "decision_label": "直接买入",
            "signal_status": "expected",
            "signal_label": "符合预期",
            "rule_text": exp.get("expected_text") or "",
            "note": f"竞价涨幅 {gap_pct:+.2f}% 落在预期区间 {expected_range[0]:+.2f}%~{expected_range[1]:+.2f}%，按计划买入。",
        }

    # 超预期涨幅达标但量能不达标 → 低于预期
    if super_gap_ok and not auction_ok:
        return {
            **base,
            "decision_status": "reject",
            "decision_label": "量能不达标",
            "signal_status": "reject",
            "signal_label": "低于预期",
            "rule_text": exp.get("low_text") or exp.get("super_text") or "",
            "note": f"竞价涨幅 {gap_pct:+.2f}% 达标，但成交额 {auction_amount_yi:.2f}亿 < {auction_amount_min_yi:.2f}亿，量能不达标。",
        }

    # 涨幅不达标 → 低于预期
    return {
        **base,
        "decision_status": "reject",
        "decision_label": "未达买点",
        "signal_status": "reject",
        "signal_label": "低于预期",
        "rule_text": exp.get("low_text") or exp.get("expected_text") or "",
        "note": f"竞价涨幅 {gap_pct:+.2f}%，未落在预期区间或超预期范围。",
    }


def _build_realtime_buy_payload(
    rows: list[dict[str, Any]],
    *,
    latest_date10: str,
    trade_date10: str = "",
    current_market_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latest_rows = [dict(row) for row in rows if row.get("date10") == latest_date10]
    in_window = _should_request_realtime_quotes()
    if not in_window:
        preserved = _load_preserved_realtime_buy(latest_date10)
        if isinstance(preserved, dict):
            preserved = _upgrade_preserved_realtime_buy_payload(preserved)
            diagnostics = preserved.get("diagnostics") if isinstance(preserved.get("diagnostics"), dict) else {}
            preserved["diagnostics"] = {
                **diagnostics,
                "source": "preserved_snapshot",
                "request_window": "09:25-09:30",
                "preserved_note": "当前不在 09:25-09:30，复用已落地的竞价观察结果，不重复请求远端接口。",
            }
            return preserved

    raw_quotes: dict[str, Any] = {}
    latest_raw = _load_latest_stock_research_snapshot(latest_date10)
    raw_quotes.update(_extract_raw_quotes_items(latest_raw))
    raw_quotes.update(_extract_raw_quotes_items(current_market_data))
    prefetched = load_prefetched_realtime_quotes(latest_date10)
    items = prefetched.get("items")
    if isinstance(items, dict):
        raw_quotes.update(items)
    prefetched_as_of = str(prefetched.get("as_of") or "").strip() if isinstance(prefetched, dict) else ""
    codes = [str(row.get("code") or "").strip() for row in latest_rows if str(row.get("code") or "").strip()]

    if not in_window:
        # 窗口外：不从远端拉（ssjy_more 的 t 字段不会落在 9:25-9:30，全被过滤）
        # 直接从缓存构建 quotes_map
        quotes_map: dict[str, dict[str, Any]] = {}
        as_of = prefetched_as_of
        for code6 in codes:
            raw = raw_quotes.get(code6)
            if not isinstance(raw, dict):
                continue
            quote = _normalize_realtime_quote(raw)
            if not quote or not _is_entry_window_time(str(quote.get("time") or "")):
                continue
            quotes_map[code6] = quote
            if quote.get("time") and not as_of:
                as_of = str(quote.get("time") or "").strip()
        quote_diag: dict[str, Any] = {
            "requested": len(codes),
            "received": len(quotes_map),
            "remote_received": 0,
            "fallback_used": len(quotes_map),
            "missing": [c for c in codes if c not in quotes_map],
            "source": "cache.raw.quotes" if quotes_map else "unavailable",
            "as_of": as_of,
            "error": "窗口外无 preserved 快照，使用本地缓存数据（无远端请求）" if quotes_map else "窗口外无 preserved 快照且无可用缓存数据",
            "request_window": "09:25-09:30",
        }
    else:
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
        "trade_date": trade_date10,
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
    expected_text = str(exp.get("expected_text") or "")
    super_text = str(exp.get("super_text") or "")
    rank = int(record.get("daily_rank") or 0)
    rank_limited = rank > DIRECT_BUY_RANK_LIMIT
    high_gap_caution = gap_pct > CAUTION_GAP_PCT

    def _pending(label: str, note: str) -> dict[str, Any]:
        return {
            "status": "pending",
            "label": label,
            "gap_pct": gap_pct,
            "note": note,
            "can_enter": False,
        }

    if expected_range and expected_range[0] <= gap_pct <= expected_range[1]:
        if rank_limited:
            return _pending("仅观察", f"开盘涨幅落在预期区间，但评分排名第 {rank}，固定买入只做前三，先观察承接。")
        if high_gap_caution:
            return _pending("谨慎接力", f"开盘高开 {gap_pct:+.2f}% 大于 {CAUTION_GAP_PCT:.0f}% ，先观察承接，不按固定买入直接入场。")
        return {
            "status": "expected",
            "label": "符合预期",
            "gap_pct": gap_pct,
            "note": expected_text or "开盘涨幅落在预期区间内",
            "can_enter": True,
        }
    if super_gap_min is not None and gap_pct >= super_gap_min:
        if rank_limited:
            return _pending("仅观察", f"开盘达到超预期，但评分排名第 {rank}，固定买入只做前三，先观察承接。")
        if high_gap_caution:
            return _pending("谨慎接力", f"开盘高开 {gap_pct:+.2f}% 大于 {CAUTION_GAP_PCT:.0f}% ，先观察承接，不按固定买入直接入场。")
        return {
            "status": "super",
            "label": "超预期",
            "gap_pct": gap_pct,
            "note": super_text or "开盘涨幅达到超预期阈值",
            "can_enter": True,
        }
    return {
        "status": "reject",
        "label": "低于预期",
        "gap_pct": gap_pct,
        "note": str(exp.get("low_text") or "开盘涨幅未落在预期/超预期可执行区间"),
        "can_enter": False,
    }


def _evaluate_one(record: dict[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
    future = [bar for bar in bars if bar["date"] > record["date10"]]
    if not future:
        missing = {"status": "missing", "label": "无后续价格", "note": "推荐日后没有可用交易日价格"}
        return {
            "open_check": missing,
            "next_day": {"status": "missing", "label": "隔日收益", "note": "推荐日后没有可用交易日价格"},
            "hold_2d": {"status": "missing", "label": "2日收益", "note": "推荐日后没有可用交易日价格"},
            "hold_3d": {"status": "missing", "label": "3日收益", "note": "推荐日后没有可用交易日价格"},
        }

    entry = future[0]
    open_check = _classify_open_window(record, entry)
    # 高开砸盘检测：高开但当日收阴且放量
    gap_pct = open_check.get("gap_pct") or 0.0
    entry_open_price = float(entry.get("open") or 0.0)
    entry_close = float(entry.get("close") or 0.0)
    entry_prev_close = float(entry.get("prev_close") or 0.0)
    gap_trap = bool(
        gap_pct > 0
        and entry_close < entry_open_price
        and entry_prev_close > 0
    )
    open_check["gap_trap"] = gap_trap

    if not open_check.get("can_enter"):
        skipped = {
            "status": "skipped",
            "label": "未入场",
            "note": open_check.get("note") or "开盘窗口未满足条件",
            "gap_pct": open_check.get("gap_pct"),
            "gap_trap": gap_trap,
        }
        return {
            "open_check": open_check,
            "next_day": skipped,
            "hold_2d": skipped,
            "hold_3d": skipped,
        }

    perf: dict[str, Any] = {"open_check": open_check}
    for key, label, offset in STRATEGIES:
        if len(future) < offset:
            perf[key] = {
                "status": "pending",
                "label": label,
                "entry_date": entry["date"],
                "note": f"当前仅拿到 {len(future)} 个后续交易日，尚不足以计算 T+{offset}",
                "gap_trap": gap_trap,
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
    def summarize_scope(scope_rows: list[dict[str, Any]], *, denominator_rows: list[dict[str, Any]]) -> dict[str, Any]:
        covered_rows = [r for r in scope_rows if (r.get("performance") or {}).get(key, {}).get("status") == "covered"]
        pending_rows = [r for r in scope_rows if (r.get("performance") or {}).get(key, {}).get("status") == "pending"]
        missing_rows = [r for r in scope_rows if (r.get("performance") or {}).get(key, {}).get("status") == "missing"]
        skipped_rows = [r for r in scope_rows if (r.get("performance") or {}).get(key, {}).get("status") == "skipped"]
        returns = [float(r["performance"][key]["return_pct"]) for r in covered_rows]
        wins = [r for r in covered_rows if r["performance"][key]["return_pct"] > 0]
        flats = [r for r in covered_rows if r["performance"][key]["return_pct"] == 0]
        losses = [r for r in covered_rows if r["performance"][key]["return_pct"] < 0]

        by_open_status: dict[str, Any] = {}
        for open_status in ("super", "expected", "reject"):
            rows = [r for r in covered_rows if (r.get("performance") or {}).get("open_check", {}).get("status") == open_status]
            row_returns = [float(r["performance"][key]["return_pct"]) for r in rows]
            by_open_status[open_status] = {
                "covered": len(rows),
                "win_rate": _pct(sum(1 for x in row_returns if x > 0), len(rows)),
                "avg_return": _avg(row_returns),
            }

        return {
            "status": "ready" if covered_rows else ("partial" if pending_rows else "missing"),
            "covered": len(covered_rows),
            "total": len(scope_rows),
            "base_total": len(denominator_rows),
            "eligible": len(scope_rows),
            "coverage": _pct(len(covered_rows), len(scope_rows)),
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
        }

    tradable_rows = [r for r in records if (r.get("performance") or {}).get("open_check", {}).get("can_enter")]
    all_scope = summarize_scope(records, denominator_rows=records)
    tradable_scope = summarize_scope(tradable_rows, denominator_rows=records)

    return {
        "key": key,
        "label": label,
        "status": tradable_scope["status"],
        "covered": tradable_scope["covered"],
        "total": len(records),
        "eligible": tradable_scope["eligible"],
        "coverage": tradable_scope["coverage"],
        "pending": tradable_scope["pending"],
        "missing": tradable_scope["missing"],
        "skipped": tradable_scope["skipped"],
        "win_count": tradable_scope["win_count"],
        "flat_count": tradable_scope["flat_count"],
        "loss_count": tradable_scope["loss_count"],
        "win_rate": tradable_scope["win_rate"],
        "avg_return": tradable_scope["avg_return"],
        "avg_win_return": tradable_scope["avg_win_return"],
        "avg_loss_return": tradable_scope["avg_loss_return"],
        "by_open_status": tradable_scope["by_open_status"],
        "scopes": {
            "all": all_scope,
            "tradable": tradable_scope,
        },
        "note": "只统计 ztAnalysis 同源推荐；策略表现同时提供全样本口径与可交易样本口径，默认主展示为可交易样本。",
    }


def _is_backtest_ready_record(record: dict[str, Any]) -> bool:
    performance = record.get("performance") if isinstance(record.get("performance"), dict) else {}
    open_check = performance.get("open_check") if isinstance(performance.get("open_check"), dict) else {}
    return str(open_check.get("status") or "") != "missing"


def _pick_realtime_reference_date(rows: list[dict[str, Any]], *, current_market_data: dict[str, Any] | None = None) -> str:
    dates = sorted({str(row.get("date10") or "") for row in rows if str(row.get("date10") or "")})
    return dates[-1] if dates else ""


def _merge_current_pool_with_realtime(rows: list[dict[str, Any]], realtime_buy: dict[str, Any]) -> list[dict[str, Any]]:
    decision_map: dict[str, dict[str, Any]] = {}
    for bucket in ("buy_list", "pending_list", "rejected_list", "unavailable_list"):
        for row in realtime_buy.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            code = str(row.get("code") or "").strip()
            if code:
                decision_map[code] = row

    merged_rows: list[dict[str, Any]] = []
    for row in rows:
        rec = json.loads(json.dumps(row, ensure_ascii=False))
        code = str(rec.get("code") or "").strip()
        decision = decision_map.get(code)
        if not decision:
            merged_rows.append(rec)
            continue

        performance = rec.get("performance") if isinstance(rec.get("performance"), dict) else {}
        open_check = performance.get("open_check") if isinstance(performance.get("open_check"), dict) else {}
        if str(open_check.get("status") or "") == "missing":
            signal_status = str(decision.get("signal_status") or "")
            performance["open_check"] = {
                "status": signal_status or ("expected" if decision.get("decision_status") == "buy" else "reject"),
                "label": decision.get("signal_label") or decision.get("decision_label") or "待判断",
                "gap_pct": decision.get("gap_pct"),
                "note": decision.get("note") or "已按 9:25 实时竞价补齐开盘判断。",
                "can_enter": str(decision.get("decision_status") or "") == "buy",
            }
            for key, label, _ in STRATEGIES:
                item = performance.get(key) if isinstance(performance.get(key), dict) else {}
                if str(item.get("status") or "") == "missing":
                    performance[key] = {
                        "status": "pending",
                        "label": label,
                        "note": "已拿到 9:25 开盘判断，待收盘后补齐收益表现。",
                    }
        rec["performance"] = performance
        merged_rows.append(rec)
    return merged_rows


def build_stock_research_backtest_payload(*, current_market_data: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(current_market_data, dict):
        sync_stock_research_backtest_source(market_data=current_market_data)
    rows, generated_from = _load_stock_research_rows()
    if not rows:
        return _empty_backtest_payload(generated_from=generated_from)
    rows = _attach_daily_rank(rows)

    unique_codes = sorted({r["code"] for r in rows if r["code"]})
    source_date_list = sorted({r["date10"] for r in rows})
    latest_source_date10 = source_date_list[-1] if source_date_list else ""
    histories, price_diag = _get_price_histories(unique_codes, st8=source_date_list[0].replace("-", ""), et8=_now_bj().strftime("%Y%m%d"))

    enriched_rows: list[dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        rec["performance"] = _evaluate_one(rec, histories.get(rec["code"], []))
        enriched_rows.append(rec)

    active_trade_date10 = _pick_active_trade_date(enriched_rows)
    current_pool_rows = [r for r in enriched_rows if str(r.get("trade_date10") or "") == active_trade_date10]
    reference_date10 = _pick_realtime_reference_date(current_pool_rows, current_market_data=current_market_data)
    realtime_buy = _build_realtime_buy_payload(
        current_pool_rows or enriched_rows,
        latest_date10=reference_date10,
        trade_date10=active_trade_date10,
        current_market_data=current_market_data,
    ) if reference_date10 else _empty_backtest_payload()["realtimeBuy"]
    current_pool_rows = _merge_current_pool_with_realtime(current_pool_rows, realtime_buy)

    backtest_rows = [r for r in enriched_rows if _is_backtest_ready_record(r)]
    latest_backtest_date10 = ""
    if backtest_rows:
        latest_backtest_date10 = sorted({r["date10"] for r in backtest_rows})[-1]
    lifecycle = _build_lifecycle(
        latest_recommendation_date10=latest_source_date10,
        active_trade_date10=active_trade_date10,
        latest_backtest_date10=latest_backtest_date10,
        current_pool_rows=current_pool_rows,
        backtest_rows=backtest_rows,
        realtime_buy=realtime_buy,
    )
    if not backtest_rows:
        payload = _empty_backtest_payload(generated_from=generated_from)
        payload["summary"]["source_samples"] = len(enriched_rows)
        payload["summary"]["filtered_non_backtest_samples"] = len(enriched_rows)
        payload["meta"]["latest_recommendation_date"] = latest_source_date10
        payload["meta"]["active_trade_date"] = active_trade_date10
        payload["meta"]["is_empty"] = False
        payload["lifecycle"] = lifecycle
        payload["realtimeBuy"] = realtime_buy
        payload["currentPoolRecords"] = current_pool_rows
        payload["assumptions"].append("当天尚未走完次日开盘验证的数据会被清洗掉，不混入回测统计。")
        payload["diagnostics"]["filtered_non_backtest_codes"] = [r["code"] for r in enriched_rows if r.get("code")]
        return payload

    date_list = sorted({r["date10"] for r in backtest_rows})

    total = len(backtest_rows)
    eligible_rows = [r for r in backtest_rows if (r.get("performance") or {}).get("open_check", {}).get("can_enter")]
    super_rows = [r for r in backtest_rows if (r.get("performance") or {}).get("open_check", {}).get("status") == "super"]
    expected_rows = [r for r in backtest_rows if (r.get("performance") or {}).get("open_check", {}).get("status") == "expected"]
    pending_rows_bk = [r for r in backtest_rows if (r.get("performance") or {}).get("open_check", {}).get("status") in ("pending", "wait_reseal")]
    rejected_rows = [r for r in backtest_rows if (r.get("performance") or {}).get("open_check", {}).get("status") == "reject"]

    by_bucket = Counter(r["bucket"] for r in backtest_rows)
    by_open_status = Counter((r.get("performance") or {}).get("open_check", {}).get("status") or "unknown" for r in backtest_rows)
    by_mainline = Counter(r["main_line"] for r in backtest_rows if r["main_line"])
    by_date_status: dict[str, dict[str, int]] = defaultdict(lambda: {"super": 0, "expected": 0, "pending": 0, "reject": 0})
    for row in backtest_rows:
        status = (row.get("performance") or {}).get("open_check", {}).get("status") or "reject"
        if status not in by_date_status[row["date10"]]:
            by_date_status[row["date10"]][status] = 0
        by_date_status[row["date10"]][status] += 1

    metrics = {
        "next_day": _summarize_strategy(backtest_rows, "next_day", "隔日收益"),
        "hold_2d": _summarize_strategy(backtest_rows, "hold_2d", "2日收益"),
        "hold_3d": _summarize_strategy(backtest_rows, "hold_3d", "3日收益"),
    }

    return {
        "schema": "stock_research_backtest_v2",
        "meta": {
            "title": "个股研究开盘回测",
            "subtitle": "回测结果只读取收盘后由个股研究推送过来的专用历史源；JSON 内沉淀每天数据，页面按时间规则选择当前要读的回测日。",
            "dates": date_list,
            "generated_at_bj": _now_bj().strftime("%Y-%m-%d %H:%M:%S"),
            "generated_from": generated_from,
            "price_source": "biying hsstock/history + 本地 recommendation_price_history 缓存",
            "entry_window": "09:25-09:30",
            "source_module": "ztAnalysis.relay/watch",
            "latest_recommendation_date": latest_source_date10 or latest_backtest_date10,
            "active_trade_date": active_trade_date10,
        },
        "summary": {
            "total_samples": total,
            "source_samples": len(enriched_rows),
            "filtered_non_backtest_samples": len(enriched_rows) - total,
            "eligible_samples": len(eligible_rows),
            "expected_count": len(expected_rows),
            "super_count": len(super_rows),
            "pending_count": len(pending_rows_bk),
            "wait_reseal_count": len(pending_rows_bk),
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
            f"固定买入优先只做评分前三的票；超过第 {DIRECT_BUY_RANK_LIMIT} 名的样本默认先观察，不直接纳入固定买入口径。",
            f"若次日高开超过 {CAUTION_GAP_PCT:.0f}% ，统一提示谨慎接力，先观察承接，不直接按开盘价买入；历史胜率回测同步排除这类样本的直接入场。",
            "当天尚未走完次日开盘验证的数据会被清洗掉，不混入回测统计或策略表现。",
            "样本源只认收盘后的个股研究推送结果；盘中缓存、旧页面快照、其他补充入口都不作为回测样本源。",
            "这个 JSON 内会按回测交易日沉淀每天数据；开盘前优先读取最新收盘后推出来的下一交易日，开盘后优先读取当天交易日。",
            "最新推荐日的 9:25 买入列表只允许在北京时区 09:25-09:30 请求 biying 批量竞价接口；窗口外只复用已落地结果，不因页面刷新重复取数。",
            "如果当前环境拿不到远端数据，只会展示待补齐/报价缺失，不会伪造买点。",
            "入场窗口限定为次日 09:25-09:30；只有开盘缺口满足“符合预期”或可在开盘窗口确认“超预期”时，才记为买入样本。",
            "若超预期文案要求'盘中冲高确认/量能放大'等开盘后行为，当前历史回测会保守记为待确认（pending），不在开盘窗口直接入场。旧版数据中的回封/封单/开板条件同理。",
            "盘中确认条件（冲高/量能）可用日K高点和成交量事后验证是否达成；达成则记为入场，未达成则记为跳过。较之前 wait_reseal 一律跳过更精细。",
            "收益口径仍按次日开盘买入、目标交易日收盘卖出；未扣除手续费、滑点，也未处理一字板无法成交的真实约束。",
        ],
        "breakdowns": {
            "by_bucket": [{"name": k, "count": v} for k, v in by_bucket.items()],
            "by_open_status": [{"name": k, "count": v} for k, v in by_open_status.items()],
            "by_mainline": [{"name": k, "count": v} for k, v in by_mainline.most_common(10)],
            "by_date_status": [{"date": k, **v} for k, v in sorted(by_date_status.items())],
        },
        "metrics": metrics,
        "lifecycle": lifecycle,
        "realtimeBuy": realtime_buy,
        "currentPoolRecords": current_pool_rows,
        "records": backtest_rows,
        "diagnostics": {
            "price_history": price_diag,
            "realtime_buy": realtime_buy.get("diagnostics", {}),
            "filtered_non_backtest_codes": [r["code"] for r in enriched_rows if not _is_backtest_ready_record(r) and r.get("code")],
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
