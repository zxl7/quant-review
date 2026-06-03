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
OUT_JSON = OUT_DIR / "preview_data.json"
OUT_JS = OUT_DIR / "preview_data.js"
PRICE_CACHE = ROOT / "cache_online" / "recommendation_price_history.json"
TZ_BJ = timezone(timedelta(hours=8))

STRATEGIES = (
    ("next_day", "隔日胜率", 1),
    ("hold_3d", "3日胜率", 3),
    ("hold_5d", "5日胜率", 5),
)

ATTACK_SCORE_BANDS = {"强候选", "重点候选", "条件触发"}


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


def _bucket_score(score: float) -> str:
    if score >= 80:
        return "80+"
    if score >= 70:
        return "70-79"
    if score >= 60:
        return "60-69"
    return "<60"


def _top_counter(counter: Counter[str], limit: int = 8) -> list[dict[str, Any]]:
    return [{"name": k, "count": v} for k, v in counter.most_common(limit)]


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


def _strip_html(text: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", str(text or ""))
    return re.sub(r"\s+", " ", plain).strip()


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


def _tone_from_band(score_band: str) -> tuple[str, str]:
    band = str(score_band or "").strip()
    if band in ATTACK_SCORE_BANDS:
        return "buy", "进攻候选"
    return "watch", "观察"


def _load_relay_rows() -> tuple[list[dict[str, Any]], list[str]]:
    files = sorted(CACHE_DIR.glob("market_data-*.json"))
    rows: list[dict[str, Any]] = []
    used_files: list[str] = []

    for fp in files:
        raw = _load_json(fp)
        date10 = str(raw.get("date") or "")
        if len(date10) != 10:
            continue
        relay_rows = ((raw.get("ztAnalysis") or {}).get("relay") or [])
        if not relay_rows:
            continue
        used_files.append(fp.name)
        date8 = date10.replace("-", "")
        for item in relay_rows:
            if not isinstance(item, dict):
                continue
            tone, side_label = _tone_from_band(str(item.get("scoreBand") or ""))
            tags = item.get("tags") or []
            cautions = [str(tag.get("text") or "") for tag in tags if isinstance(tag, dict) and "warn" in str(tag.get("cls") or "")]
            reasons = [part.strip() for part in _strip_html(item.get("reason") or "").split("·") if part.strip()]
            rows.append(
                {
                    "date": date8,
                    "date10": date10,
                    "side": tone,
                    "side_label": side_label,
                    "main_line": str(item.get("predTheme") or "").strip(),
                    "line_confidence": 0.0,
                    "code": str(item.get("code") or "").strip(),
                    "name": str(item.get("name") or "").strip(),
                    "score": int(float(item.get("score") or 0)),
                    "score_band": str(item.get("scoreBand") or "").strip(),
                    "style_tag": str(item.get("qualityLabel") or "").strip(),
                    "lbc": int(float(item.get("lbc") or 0)),
                    "cje_yi": round(float(item.get("cjeYi") or 0.0), 2),
                    "turnover": round(float(item.get("capacityFactorScore") or 0.0), 2),
                    "tide_status": str(((item.get("marketGate") or {}).get("label")) or "").strip(),
                    "reasons": reasons[:4],
                    "cautions": cautions[:4],
                    "next_step": str(item.get("nextStep") or "").strip(),
                    "plate_name": str(item.get("plateName") or "").strip(),
                    "hy": str(item.get("hy") or "").strip(),
                    "factor_hint": str(item.get("factorHint") or "").strip(),
                }
            )

    rows.sort(key=lambda x: (x["date"], -x["score"], x["code"]))
    return rows, used_files


def _evaluate_one(record: dict[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
    future = [bar for bar in bars if bar["date"] > record["date10"]]
    perf: dict[str, Any] = {}
    for key, label, offset in STRATEGIES:
        if not future:
            perf[key] = {"status": "missing", "label": label, "note": "推荐日后没有可用交易日价格"}
            continue
        if len(future) < offset:
            perf[key] = {
                "status": "pending",
                "label": label,
                "entry_date": future[0]["date"],
                "note": f"当前仅拿到 {len(future)} 个后续交易日，尚不足以计算 T+{offset}",
            }
            continue
        entry = future[0]
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
    covered_rows = [r for r in records if (r.get("performance") or {}).get(key, {}).get("status") == "covered"]
    pending_rows = [r for r in records if (r.get("performance") or {}).get(key, {}).get("status") == "pending"]
    missing_rows = [r for r in records if (r.get("performance") or {}).get(key, {}).get("status") == "missing"]
    returns = [float(r["performance"][key]["return_pct"]) for r in covered_rows]
    wins = [r for r in covered_rows if r["performance"][key]["return_pct"] > 0]
    flats = [r for r in covered_rows if r["performance"][key]["return_pct"] == 0]
    losses = [r for r in covered_rows if r["performance"][key]["return_pct"] < 0]

    by_side: dict[str, Any] = {}
    for side in ("buy", "watch"):
        side_rows = [r for r in covered_rows if r["side"] == side]
        side_returns = [float(r["performance"][key]["return_pct"]) for r in side_rows]
        side_wins = sum(1 for x in side_returns if x > 0)
        by_side[side] = {
            "covered": len(side_rows),
            "win_rate": _pct(side_wins, len(side_rows)),
            "avg_return": _avg(side_returns),
        }

    return {
        "key": key,
        "label": label,
        "status": "ready" if covered_rows else ("partial" if pending_rows else "missing"),
        "covered": len(covered_rows),
        "total": len(records),
        "coverage": _pct(len(covered_rows), len(records)),
        "pending": len(pending_rows),
        "missing": len(missing_rows),
        "win_count": len(wins),
        "flat_count": len(flats),
        "loss_count": len(losses),
        "win_rate": _pct(len(wins), len(covered_rows)),
        "avg_return": _avg(returns),
        "avg_win_return": _avg([float(r["performance"][key]["return_pct"]) for r in wins]),
        "avg_loss_return": _avg([float(r["performance"][key]["return_pct"]) for r in losses]),
        "by_side": by_side,
        "top_winners": [
            {
                "date": r["date10"],
                "code": r["code"],
                "name": r["name"],
                "side": r["side"],
                "return_pct": r["performance"][key]["return_pct"],
            }
            for r in sorted(covered_rows, key=lambda x: x["performance"][key]["return_pct"], reverse=True)[:5]
        ],
        "top_losers": [
            {
                "date": r["date10"],
                "code": r["code"],
                "name": r["name"],
                "side": r["side"],
                "return_pct": r["performance"][key]["return_pct"],
            }
            for r in sorted(covered_rows, key=lambda x: x["performance"][key]["return_pct"])[:5]
        ],
        "note": "仅统计接力池信号；买入价取下一交易日开盘，卖出价取目标交易日收盘。",
    }


def _build_multi_trade(records: list[dict[str, Any]], basis_key: str = "hold_3d") -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        grouped[row["code"]].append(row)
    repeated = {code: rows for code, rows in grouped.items() if len(rows) >= 2}
    repeat_instances: list[dict[str, Any]] = []
    top_repeat_codes: list[dict[str, Any]] = []

    for code, rows in repeated.items():
        covered = [r for r in rows if (r.get("performance") or {}).get(basis_key, {}).get("status") == "covered"]
        returns = [float(r["performance"][basis_key]["return_pct"]) for r in covered]
        repeat_instances.extend(covered)
        top_repeat_codes.append(
            {
                "code": code,
                "name": rows[0]["name"],
                "times": len(rows),
                "covered": len(covered),
                "win_rate": _pct(sum(1 for x in returns if x > 0), len(covered)),
                "avg_return": _avg(returns),
                "dates": [r["date10"] for r in rows],
            }
        )

    repeat_returns = [float(r["performance"][basis_key]["return_pct"]) for r in repeat_instances]
    repeat_wins = sum(1 for x in repeat_returns if x > 0)
    top_repeat_codes.sort(key=lambda x: (-x["times"], -x["avg_return"], x["code"]))
    return {
        "key": "multi_trade",
        "label": "多次交易表现",
        "status": "ready" if repeat_instances else "partial",
        "basis": basis_key,
        "basis_label": next((label for k, label, _ in STRATEGIES if k == basis_key), basis_key),
        "repeat_codes": len(repeated),
        "repeat_instances": len(repeat_instances),
        "win_rate": _pct(repeat_wins, len(repeat_instances)),
        "avg_return": _avg(repeat_returns),
        "top_repeat_codes": top_repeat_codes[:8],
        "note": "同一接力票被多次纳入接力池时，按每次信号独立统计，默认采用 T+3 收盘收益口径。",
    }


def main() -> None:
    rows, generated_from = _load_relay_rows()
    if not rows:
        raise SystemExit("No relay rows found in cache/market_data-*.json")

    unique_codes = sorted({r["code"] for r in rows if r["code"]})
    date_list = sorted({r["date10"] for r in rows})
    histories, price_diag = _get_price_histories(unique_codes, st8=date_list[0].replace("-", ""), et8=_now_bj().strftime("%Y%m%d"))

    enriched_rows: list[dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        rec["performance"] = _evaluate_one(rec, histories.get(rec["code"], []))
        enriched_rows.append(rec)

    total = len(enriched_rows)
    attack_rows = [r for r in enriched_rows if r["side"] == "buy"]
    observe_rows = [r for r in enriched_rows if r["side"] == "watch"]
    by_side = Counter(r["side"] for r in enriched_rows)
    by_mainline = Counter(r["main_line"] for r in enriched_rows if r["main_line"])
    by_style = Counter(r["style_tag"] for r in enriched_rows if r["style_tag"])
    by_tide = Counter(r["tide_status"] for r in enriched_rows if r["tide_status"])
    by_score_bucket = Counter(_bucket_score(r["score"]) for r in enriched_rows)
    by_date_side: dict[str, dict[str, int]] = defaultdict(lambda: {"buy": 0, "watch": 0})
    for row in enriched_rows:
        by_date_side[row["date10"]][row["side"]] += 1

    metrics = {
        "next_day": _summarize_strategy(enriched_rows, "next_day", "隔日胜率"),
        "hold_3d": _summarize_strategy(enriched_rows, "hold_3d", "3日胜率"),
        "hold_5d": _summarize_strategy(enriched_rows, "hold_5d", "5日胜率"),
        "multi_trade": _build_multi_trade(enriched_rows),
    }

    payload = {
        "meta": {
            "title": "接力池胜率预览",
            "subtitle": "仅统计 ztAnalysis.relay 接力池样本，并接入真实历史日K做短线回放。",
            "dates": date_list,
            "generated_at_bj": _now_bj().strftime("%Y-%m-%d %H:%M:%S"),
            "generated_from": generated_from,
            "price_source": "biying hsstock/history + 本地 recommendation_price_history 缓存",
        },
        "summary": {
            "total_samples": total,
            "unique_codes": len(unique_codes),
            "trade_days": len(date_list),
            "buy_count": len(attack_rows),
            "watch_count": len(observe_rows),
            "buy_ratio": _pct(len(attack_rows), total),
            "watch_ratio": _pct(len(observe_rows), total),
            "avg_score": _avg([float(r["score"]) for r in enriched_rows], 1),
            "avg_buy_score": _avg([float(r["score"]) for r in attack_rows], 1),
            "avg_watch_score": _avg([float(r["score"]) for r in observe_rows], 1),
            "priced_codes": len(histories),
            "missing_price_codes": price_diag["missing"],
        },
        "assumptions": [
            "样本池只取 cache/market_data-YYYYMMDD.json 中 ztAnalysis.relay 的接力池记录。",
            "信号按收盘后生成处理，买入价统一采用下一交易日开盘价，卖出价采用目标交易日收盘价。",
            "使用前复权日K；未扣除手续费、滑点，也未处理一字板无法买入的真实成交约束。",
        ],
        "breakdowns": {
            "by_date": [{"date": k, **v} for k, v in sorted(by_date_side.items())],
            "by_side": [{"name": k, "count": v} for k, v in by_side.items()],
            "by_mainline": _top_counter(by_mainline, 10),
            "by_style": _top_counter(by_style, 8),
            "by_tide": _top_counter(by_tide, 8),
            "by_score_bucket": [{"name": k, "count": by_score_bucket.get(k, 0)} for k in ["80+", "70-79", "60-69", "<60"]],
        },
        "metrics": metrics,
        "records": enriched_rows,
        "spotlight": {
            "best_buy_candidates": sorted(attack_rows, key=lambda x: (-x["score"], x["date"], x["code"]))[:8],
            "high_attention_watch": sorted(observe_rows, key=lambda x: (-x["score"], x["date"], x["code"]))[:10],
            "best_t3_trades": metrics["hold_3d"]["top_winners"][:6],
            "worst_t3_trades": metrics["hold_3d"]["top_losers"][:6],
        },
        "diagnostics": {
            "price_history": price_diag,
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    OUT_JSON.write_text(json_text, encoding="utf-8")
    OUT_JS.write_text(f"window.__PREVIEW_DATA__ = {json_text};\n", encoding="utf-8")
    print(str(OUT_JSON))
    print(str(OUT_JS))


if __name__ == "__main__":
    main()
