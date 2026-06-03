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
from daily_review.data.biying import fetch_stock_history_k
from daily_review.http import HttpClient


CACHE_DIR = ROOT / "cache"
OUT_DIR = ROOT / "html" / "recommendation-preview"
OUT_JSON = OUT_DIR / "stock_research_backtest.json"
OUT_JS = OUT_DIR / "stock_research_backtest.js"
PRICE_CACHE = ROOT / "cache_online" / "recommendation_price_history.json"
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


def _load_stock_research_rows() -> tuple[list[dict[str, Any]], list[str]]:
    files = sorted(CACHE_DIR.glob("market_data-*.json"))
    rows: list[dict[str, Any]] = []
    used_files: list[str] = []

    for fp in files:
        raw = _load_json(fp)
        date10 = str(raw.get("date") or "")
        if len(date10) != 10:
            continue
        zt = raw.get("ztAnalysis") if isinstance(raw.get("ztAnalysis"), dict) else {}
        relay = zt.get("relay") if isinstance(zt.get("relay"), list) else []
        watch = zt.get("watch") if isinstance(zt.get("watch"), list) else []
        if not relay and not watch:
            continue
        used_files.append(fp.name)
        for item in relay:
            if isinstance(item, dict):
                rows.append(_row_from_item(item, date10=date10, bucket="relay"))
        for item in watch:
            if isinstance(item, dict):
                rows.append(_row_from_item(item, date10=date10, bucket="watch"))

    rows.sort(key=lambda x: (x["date"], -x["score"], x["code"]))
    return rows, used_files


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
    histories, price_diag = _get_price_histories(unique_codes, st8=date_list[0].replace("-", ""), et8=_now_bj().strftime("%Y%m%d"))

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
            "subtitle": "同源读取 ztAnalysis 接力/观察推荐，只在次日 09:25-09:30 满足符合预期或超预期开口径时，按开盘价记为入场。",
            "dates": date_list,
            "generated_at_bj": _now_bj().strftime("%Y-%m-%d %H:%M:%S"),
            "generated_from": generated_from,
            "price_source": "biying hsstock/history + 本地 recommendation_price_history 缓存",
            "entry_window": "09:25-09:30",
            "source_module": "ztAnalysis.relay/watch",
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
        },
        "assumptions": [
            "样本池只取 cache/market_data-YYYYMMDD.json 中 ztAnalysis.relay 与 ztAnalysis.watch 这组同源推荐。",
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
        "records": enriched_rows,
        "spotlight": {
            "super_candidates": sorted(super_rows, key=lambda x: (-x["score"], x["date"], x["code"]))[:10],
            "expected_candidates": sorted(expected_rows, key=lambda x: (-x["score"], x["date"], x["code"]))[:10],
            "best_t3_trades": metrics["hold_3d"]["top_winners"],
            "worst_t3_trades": metrics["hold_3d"]["top_losers"],
        },
        "diagnostics": {
            "price_history": price_diag,
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
