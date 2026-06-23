from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

from daily_review.contracts import MarketData, PreservedResearchSnapshot
from daily_review.data.biying import normalize_stock_code


def load_latest_valid_zt_analysis(*, root: Path, current_date: str) -> dict | None:
    cache_dir = root / "cache"
    current_d8 = str(current_date or "").replace("-", "")
    candidates = []
    for fp in cache_dir.glob("market_data-*.json"):
        stem = fp.stem
        if not stem.startswith("market_data-"):
            continue
        d8 = stem.replace("market_data-", "")
        if not (len(d8) == 8 and d8.isdigit()):
            continue
        if current_d8 and d8 >= current_d8:
            continue
        candidates.append((d8, fp))

    for _, fp in sorted(candidates, reverse=True):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        zt_analysis = data.get("ztAnalysis") if isinstance(data, dict) else None
        if not isinstance(zt_analysis, dict):
            continue
        relay = zt_analysis.get("relay") if isinstance(zt_analysis.get("relay"), list) else []
        watch = zt_analysis.get("watch") if isinstance(zt_analysis.get("watch"), list) else []
        if relay or watch:
            out = dict(zt_analysis)
            meta = out.get("meta") if isinstance(out.get("meta"), dict) else {}
            out["meta"] = {
                **meta,
                "preservedFromDate": data.get("date") or fp.stem.replace("market_data-", ""),
                "preserveReason": "盘中仅更新实时情绪，明日接力/观察沿用上一份收盘推演",
            }
            return out
    return None


def load_latest_valid_research_snapshot(*, root: Path, current_date: str) -> PreservedResearchSnapshot | None:
    cache_dir = root / "cache"
    current_d8 = str(current_date or "").replace("-", "")
    candidates = []
    for fp in cache_dir.glob("market_data-*.json"):
        stem = fp.stem
        if not stem.startswith("market_data-"):
            continue
        d8 = stem.replace("market_data-", "")
        if not (len(d8) == 8 and d8.isdigit()):
            continue
        if current_d8 and d8 >= current_d8:
            continue
        candidates.append((d8, fp))

    keep_keys = (
        "date",
        "meta",
        "mood",
        "moodStage",
        "planGuide",
        "themePanels",
        "leaders",
        "plateRankTop10",
        "ztgc",
        "zt_code_themes",
        "ztAnalysis",
        "watchlist",
        "watchlist_stock_index",
        "picks_advisor",
        "stockResearchBacktest",
        "tideSignal",
        "coreTideSignal",
        "theme_alias_map",
    )

    for _, fp in sorted(candidates, reverse=True):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue

        zt_analysis = data.get("ztAnalysis") if isinstance(data.get("ztAnalysis"), dict) else {}
        relay = zt_analysis.get("relay") if isinstance(zt_analysis.get("relay"), list) else []
        watch = zt_analysis.get("watch") if isinstance(zt_analysis.get("watch"), list) else []
        if not (relay or watch):
            continue

        snapshot: MarketData = {key: data.get(key) for key in keep_keys if key in data}
        meta = snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {}
        snapshot["meta"] = {
            **meta,
            "preservedFromDate": data.get("date") or fp.stem.replace("market_data-", ""),
            "preserveReason": "盘中不重算个股研究，沿用上一份收盘结果",
        }
        return {
            "marketData": snapshot,
            "preservedFromDate": snapshot["meta"]["preservedFromDate"],
            "preserveReason": snapshot["meta"]["preserveReason"],
        }
    return None


def collect_research_codes_from_snapshot(snapshot: PreservedResearchSnapshot | None) -> list[str]:
    market_data = snapshot.get("marketData") if isinstance(snapshot, dict) and isinstance(snapshot.get("marketData"), dict) else {}
    zt_analysis = market_data.get("ztAnalysis") if isinstance(market_data.get("ztAnalysis"), dict) else {}
    codes: list[str] = []
    for bucket in ("relay", "watch"):
        rows = zt_analysis.get(bucket) if isinstance(zt_analysis.get(bucket), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            code6 = normalize_stock_code(str(row.get("code") or row.get("dm") or ""))
            if code6:
                codes.append(code6)
    return codes


def apply_preserved_research_snapshot(
    *,
    root: Path,
    current_date: str,
    market_data: MarketData,
    log_fn: Callable[[str], None] | None = None,
) -> None:
    preserved_research = load_latest_valid_research_snapshot(root=root, current_date=current_date)
    if preserved_research:
        market_data["preservedResearch"] = preserved_research
        if log_fn:
            log_fn(f"个股研究已保留上一份收盘快照 ({preserved_research.get('preservedFromDate')})")
    else:
        market_data.pop("preservedResearch", None)


def apply_zt_analysis(
    *,
    root: Path,
    current_date: str,
    market_data: MarketData,
    preserve_zt_analysis: bool,
    log_fn: Callable[[str], None] | None = None,
) -> None:
    if preserve_zt_analysis:
        preserved = load_latest_valid_zt_analysis(root=root, current_date=current_date)
        if preserved:
            market_data["ztAnalysis"] = preserved
            if log_fn:
                log_fn(f"ztAnalysis 已保留上一份收盘推演 ({preserved.get('meta', {}).get('preservedFromDate')})")
            return

    from daily_review.metrics.zt_analysis import build_zt_analysis

    market_data["ztAnalysis"] = build_zt_analysis(market_data=market_data)
    if log_fn:
        if preserve_zt_analysis:
            log_fn("未找到可沿用 ztAnalysis，已按当前数据重算")
        else:
            log_fn("ztAnalysis 已按最新环境姿态重算")


def attach_stock_research_backtest(
    *,
    market_data: MarketData,
    sync_source: bool,
    query_tag: str = "",
    log_fn: Callable[[str], None] | None = None,
) -> None:
    from scripts.build_stock_research_backtest import build_stock_research_backtest_payload

    if sync_source:
        from scripts.build_stock_research_backtest import sync_stock_research_backtest_source

        sync_stock_research_backtest_source(market_data=market_data)
    previous_disable_history_fetch = os.environ.get("QR_DISABLE_STOCK_RESEARCH_HISTORY_FETCH")
    if previous_disable_history_fetch is None:
        os.environ["QR_DISABLE_STOCK_RESEARCH_HISTORY_FETCH"] = "1"
    try:
        market_data["stockResearchBacktest"] = build_stock_research_backtest_payload(
            current_market_data=market_data,
            query_tag=query_tag,
            sync_source_from_market_data=False,
        )
    finally:
        if previous_disable_history_fetch is None:
            os.environ.pop("QR_DISABLE_STOCK_RESEARCH_HISTORY_FETCH", None)
    if log_fn:
        log_fn(f"stockResearchBacktest 已按个股研究推送历史源派生{f' (tag={query_tag})' if query_tag else ''}")
