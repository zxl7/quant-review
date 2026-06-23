from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from daily_review.cache_io import read_json, write_json
from daily_review.contracts import MarketData
from daily_review.data.biying import (
    fetch_index_history_k,
    normalize_stock_code,
)
from daily_review.features.build_features import build_mood_inputs, default_chart_palette
from daily_review.application.index_formatters import format_index_pct, format_index_val

INDEX_KLINE_LOOKBACK_DAYS = 20
INDEX_KLINE_MAX_ITEMS = 10


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _to_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def collect_pool_theme_codes(*, pools: dict, actual_date: str) -> list[str]:
    rows: list[dict[str, Any]] = []
    for key in ("ztgc", "zbgc", "dtgc"):
        arr = pools.get(key, {}).get(actual_date) or []
        if isinstance(arr, list):
            rows.extend(arr)
    out: list[str] = []
    for stock in rows:
        code6 = normalize_stock_code(str(stock.get("dm") or stock.get("code") or ""))
        if code6 and code6 not in out:
            out.append(code6)
    return out


def update_theme_cache(
    *,
    root: Path,
    pools: dict,
    actual_date: str,
    clean_theme_names,
    fetch_stock_labels_batch_fn,
) -> dict[str, list[str]]:
    themes_path = root / "cache" / "theme_cache.json"
    theme_cache_disk = read_json(themes_path, default={})
    codes_map = (theme_cache_disk.get("codes") or {}) if isinstance(theme_cache_disk, dict) else {}
    if not isinstance(codes_map, dict):
        codes_map = {}
    all_codes = collect_pool_theme_codes(pools=pools, actual_date=actual_date)
    new_codes = [code for code in all_codes if code not in codes_map]
    if new_codes:
        labels_batch = fetch_stock_labels_batch_fn(new_codes)
        for code6 in new_codes:
            raw_names = labels_batch.get(code6) or []
            names = clean_theme_names(raw_names)
            if names:
                codes_map[code6] = names
    write_json(themes_path, {"version": 1, "codes": codes_map})
    return codes_map


def build_theme_trend_cache(*, root: Path, pools: dict, trade_days: list[str], actual_date: str, codes_map: dict[str, list[str]]) -> dict[str, dict[str, int]]:
    theme_trend_path = root / "cache" / "theme_trend_cache.json"
    trend_disk = read_json(theme_trend_path, default={})
    by_day = (trend_disk.get("by_day") or {}) if isinstance(trend_disk, dict) else {}
    if not isinstance(by_day, dict):
        by_day = {}

    def count_day_themes(day_rows: list[dict[str, Any]]) -> dict[str, int]:
        count: dict[str, int] = {}
        for stock in day_rows or []:
            code6 = normalize_stock_code(str(stock.get("dm") or stock.get("code") or ""))
            if not code6:
                continue
            themes = codes_map.get(code6) or []
            if not isinstance(themes, list):
                continue
            for theme in themes:
                name = str(theme or "").strip()
                if not name:
                    continue
                count[name] = count.get(name, 0) + 1
        return count

    last5 = trade_days[-5:] if len(trade_days) >= 5 else trade_days
    for day in last5:
        rows = pools.get("ztgc", {}).get(day) or []
        rows = rows if isinstance(rows, list) else []
        by_day[day] = count_day_themes([row for row in rows if isinstance(row, dict)])

    keep = set(trade_days)
    by_day = {day: rows for day, rows in by_day.items() if day in keep}
    write_json(theme_trend_path, {"version": 1, "as_of": actual_date, "by_day": by_day})
    return by_day


def update_index_kline_cache(*, root: Path, client, actual_date: str) -> dict[str, dict[str, Any]]:
    index_k_path = root / "cache" / "index_kline_cache.json"
    idx_disk = read_json(index_k_path, default={})
    codes_entry = (idx_disk.get("codes") or {}) if isinstance(idx_disk, dict) else {}
    if not isinstance(codes_entry, dict):
        codes_entry = {}
    existing_codes_entry = dict(codes_entry)

    import datetime as _dt

    codes = ("000001.SH", "399001.SZ", "399006.SZ")

    def _fetch_one(code: str) -> tuple[str, list[dict[str, Any]] | None]:
        end_date = actual_date.replace("-", "")
        start_date = (
            _dt.datetime.strptime(actual_date, "%Y-%m-%d") - _dt.timedelta(days=INDEX_KLINE_LOOKBACK_DAYS)
        ).strftime("%Y%m%d")
        try:
            items = fetch_index_history_k(client, code=code, st=start_date, et=end_date)
            if not isinstance(items, list):
                items = []
            cleaned = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                if _to_int(item.get("sf"), 0) == 1:
                    continue
                if _to_float(item.get("a"), 0.0) <= 0 or _to_float(item.get("v"), 0.0) <= 0:
                    continue
                cleaned.append(item)
            if cleaned:
                return code, cleaned[-INDEX_KLINE_MAX_ITEMS:]
        except Exception:
            return code, None
        return code, None

    with ThreadPoolExecutor(max_workers=len(codes)) as executor:
        future_map = {executor.submit(_fetch_one, code): code for code in codes}
        for future in as_completed(future_map):
            code = future_map[future]
            try:
                resolved_code, cleaned = future.result()
            except Exception:
                resolved_code, cleaned = code, None
            if cleaned:
                codes_entry[resolved_code] = {"as_of": actual_date, "items": cleaned}
                continue

            cached = existing_codes_entry.get(resolved_code)
            if isinstance(cached, dict):
                codes_entry[resolved_code] = cached
            else:
                codes_entry[resolved_code] = {"as_of": actual_date, "items": []}

    write_json(index_k_path, {"version": 1, "codes": codes_entry})
    return codes_entry


def build_height_trend_cache(*, root: Path, pools: dict, trade_days: list[str], actual_date: str) -> None:
    def calc_height_trend_row(day: str, day_data: list[dict[str, Any]]) -> dict:
        data = day_data or []
        lbs = [int((stock.get("lbc", 1) or 1)) for stock in data if isinstance(stock, dict)]
        main_max = max(lbs) if lbs else 0
        gem_data = [stock for stock in data if str(stock.get("dm", "")).startswith("300")]
        gem_max = max((int((stock.get("lbc", 1) or 1)) for stock in gem_data), default=0)
        sorted_lb = sorted(set(lbs), reverse=True)
        sub_max = sorted_lb[1] if len(sorted_lb) > 1 else 0
        top_stock = max(data, key=lambda x: int((x.get("lbc", 0) or 0)), default={})
        top_name = (str(top_stock.get("mc", "") or "")[:4]).strip()
        sub_stock = next((stock for stock in data if int((stock.get("lbc", 0) or 0)) == sub_max), {})
        sub_name = (str(sub_stock.get("mc", "") or "")[:4]).strip()
        gem_stock = max(gem_data, key=lambda x: int((x.get("lbc", 0) or 0)), default={}) if gem_data else {}
        gem_name = (str(gem_stock.get("mc", "") or "")[:4]).strip()
        return {
            "day": day,
            "main": main_max,
            "sub": sub_max,
            "gem": gem_max,
            "label_main": top_name if main_max >= 3 else "",
            "label_sub": sub_name if sub_max >= 2 else "",
            "label_gem": gem_name if gem_max >= 1 else "",
        }

    ht_path = root / "cache" / "height_trend_cache.json"
    ht_disk = read_json(ht_path, default={})
    ht_days = (ht_disk.get("days") or {}) if isinstance(ht_disk, dict) else {}
    if not isinstance(ht_days, dict):
        ht_days = {}
    for day in trade_days:
        if day == actual_date:
            continue
        day_data = pools.get("ztgc", {}).get(day) or []
        if isinstance(day_data, list):
            ht_days[day] = calc_height_trend_row(day, [row for row in day_data if isinstance(row, dict)])
    keep = set(trade_days)
    ht_days = {day: row for day, row in ht_days.items() if day in keep}
    write_json(ht_path, {"version": 1, "days": ht_days})


def build_report_indices(*, actual_date: str, codes_entry: dict[str, dict[str, Any]]) -> list[dict]:
    def norm_k_date(text: str) -> str:
        text = (text or "").strip()
        if len(text) >= 10:
            return text[:10]
        if len(text) == 8 and text.isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        return text

    def pick_exact(code: str) -> tuple[float, float] | None:
        items = (codes_entry.get(code) or {}).get("items") or []
        if not isinstance(items, list):
            return None
        for item in items:
            if not isinstance(item, dict):
                continue
            date_text = norm_k_date(str(item.get("t") or ""))
            if date_text == actual_date and _to_int(item.get("sf"), 0) != 1:
                return float(item.get("c", 0) or 0), float(item.get("pc", 0) or 0)
        return None

    def calc_ma(code: str, *, n: int) -> float | None:
        items = (codes_entry.get(code) or {}).get("items") or []
        if not isinstance(items, list):
            return None
        closes = []
        for item in items:
            if not isinstance(item, dict):
                continue
            date_text = norm_k_date(str(item.get("t") or ""))
            if date_text and date_text <= actual_date and _to_int(item.get("sf"), 0) != 1:
                closes.append(float(item.get("c", 0) or 0))
        closes = [close for close in closes if close > 0]
        if len(closes) < n:
            return None
        seg = closes[-n:]
        return sum(seg) / float(n) if seg else None

    out = []
    for code, name in [("000001.SH", "上证指数"), ("399001.SZ", "深证成指"), ("399006.SZ", "创业板指")]:
        result = pick_exact(code)
        if not result:
            continue
        close, prev_close = result
        chg = ((close - prev_close) / prev_close * 100.0) if prev_close else 0.0
        out.append(
            {
                "name": name,
                "code": code,
                "val": f"{close:.2f}",
                "chg": f"{chg:+.2f}%",
                "price": close,
                "ma5": calc_ma(code, n=5),
                "ma20": calc_ma(code, n=20),
            }
        )
    return out


def build_raw_pools(*, pools: dict, actual_date: str, yest: str) -> dict:
    return {
        "ztgc": pools["ztgc"].get(actual_date) or [],
        "dtgc": pools["dtgc"].get(actual_date) or [],
        "zbgc": pools["zbgc"].get(actual_date) or [],
        "qsgc": pools["qsgc"].get(actual_date) or [],
        "yest_ztgc": pools["ztgc"].get(yest) or [],
        "yest_dtgc": pools["dtgc"].get(yest) or [],
        "yest_zbgc": pools["zbgc"].get(yest) or [],
        "yest_date": yest,
    }


def build_base_market_data(
    *,
    actual_date: str,
    date_note: str,
    indices_asof: str,
    generated_at: str,
    indices_for_report: list[dict],
    indices_rt: list[dict],
    raw_pools: dict,
    codes_map: dict[str, list[str]],
    codes_entry: dict[str, dict[str, Any]],
    theme_trend_by_day: dict[str, dict[str, int]],
) -> MarketData:
    market_data: MarketData = {
        "date": actual_date,
        "dateNote": date_note,
        "meta": {
            "asOf": {"indices": indices_asof, "pools": generated_at[11:19], "themes": generated_at[11:19]},
            "version": "1.0",
            "generatedAt": generated_at,
        },
        "indices": indices_for_report or [
            {
                "name": row.get("name", ""),
                "code": row.get("code", ""),
                "val": format_index_val(row.get("val", "")),
                "chg": format_index_pct(row.get("chg", "")),
                "cje": row.get("cje", 0),
            }
            for row in (indices_rt or [])
            if isinstance(row, dict) and row.get("name")
        ],
        "panorama": {},
        "volume": {},
        "sectors": [],
        "themePanels": {},
        "themeTrend": {"dates": [], "series": [], "palette": default_chart_palette()},
        "heightTrend": {},
        "ladder": [],
        "top10": [],
        "top10Summary": {},
        "mood": {},
        "moodStage": {},
        "moodCards": [],
        "learningNotes": {},
        "leaders": [],
        "ztgc": [],
        "zt_code_themes": {},
        "features": {},
        "raw": {
            "pools": raw_pools,
            "themes": {"code2themes": codes_map},
            "index_klines": {"codes": codes_entry},
            "indices_realtime": {"as_of": indices_asof, "items": indices_rt or []},
            "theme_trend_cache": {"as_of": actual_date, "by_day": theme_trend_by_day},
        },
    }
    return market_data


def build_intraday_market_data(
    *,
    actual_date: str,
    date_note: str,
    now_str: str,
    generated_at: str,
    raw_pools: dict,
    codes_map: dict[str, list[str]],
) -> MarketData:
    return {
        "date": actual_date,
        "dateNote": f"{date_note or ''} 【盘中快照 {now_str}】",
        "meta": {
            "asOf": {"indices": now_str, "pools": now_str, "themes": now_str},
            "version": "1.0-intraday",
            "mode": "intraday",
            "generatedAt": generated_at,
            "snapshotTime": now_str,
        },
        "indices": [],
        "panorama": {},
        "volume": {},
        "sectors": [],
        "themePanels": {},
        "themeTrend": {"dates": [], "series": [], "palette": default_chart_palette()},
        "heightTrend": {},
        "ladder": [],
        "top10": [],
        "top10Summary": {},
        "mood": {},
        "moodStage": {},
        "moodCards": [],
        "learningNotes": {},
        "leaders": [],
        "ztgc": [],
        "zt_code_themes": {},
        "features": {},
        "raw": {
            "pools": raw_pools,
            "themes": {"code2themes": codes_map},
            "index_klines": {"codes": {}},
            "theme_trend_cache": {"as_of": actual_date, "by_day": {}},
        },
    }


def attach_quotes_and_features(
    *,
    market_data: MarketData,
    raw_pools: dict,
    quotes_asof: str,
    quotes_map: dict[str, dict],
) -> None:
    market_data["raw"]["quotes"] = {"as_of": quotes_asof, "items": quotes_map, "count": len(quotes_map)}
    meta = market_data.get("meta") if isinstance(market_data.get("meta"), dict) else {}
    if not isinstance(meta, dict):
        meta = {}
    meta.setdefault("asOf", {})
    if isinstance(meta.get("asOf"), dict):
        meta["asOf"]["quotes"] = quotes_asof
    market_data["meta"] = meta
    mood_inputs = build_mood_inputs(pools=raw_pools, quotes=quotes_map)
    market_data["features"]["mood_inputs"] = mood_inputs
    market_data["features"]["chart_palette"] = default_chart_palette()


def write_market_data(*, root: Path, market_data: MarketData, actual_date: str, suffix: str = "") -> Path:
    cache_dir = root / "cache"
    date_compact = actual_date.replace("-", "")
    suffix_text = f"-{suffix}" if suffix else ""
    market_path = cache_dir / f"market_data-{date_compact}{suffix_text}.json"
    write_json(market_path, market_data)
    return market_path
