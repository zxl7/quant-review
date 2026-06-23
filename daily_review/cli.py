#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CLI 入口。

当前职责：
- 提供稳定的数据生产 / 重建 / 盘中快照入口
- 编排 daily_review/* 模块与 web 数据注入前置步骤
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from daily_review.application.fetch_service import (
    attach_quotes_and_features,
    build_base_market_data,
    build_height_trend_cache,
    build_intraday_market_data,
    build_raw_pools,
    build_report_indices,
    build_theme_trend_cache,
    update_index_kline_cache,
    update_theme_cache,
    write_market_data,
)
from daily_review.application.index_formatters import (
    display_float as _display_float,
    format_index_pct as _fmt_index_pct,
    format_index_val as _fmt_index_val,
)
from daily_review.application.mood_history_service import inject_mood_history_and_delta
from daily_review.application.rebuild_service import (
    build_rebuild_context,
    load_theme_cache as app_load_theme_cache,
    load_ztgc_by_day_window as app_load_ztgc_by_day_window,
)
from daily_review.application.stock_research_service import (
    apply_preserved_research_snapshot,
    apply_zt_analysis,
    attach_stock_research_backtest,
    collect_research_codes_from_snapshot,
    load_latest_valid_research_snapshot,
)
from daily_review.application.watch_snapshot_service import (
    append_intraday_snapshot,
    append_watch_runtime_slice,
    inject_intraday_snapshots,
)
from daily_review.cache_io import read_json, write_json
from daily_review.config import DEFAULT_CONFIG
from daily_review.config import load_config_from_env
from daily_review.data.biying import (
    extract_money_flow_day_map,
    fetch_indices_realtime,
    fetch_index_history_k,
    fetch_pool,
    fetch_stock_money_flow,
    fetch_stocks_realtime_map,
    get_trading_days_from_index_k,
    normalize_stock_code,
    resolve_trade_date,
    resolve_trade_date_intraday,
)
from daily_review.data.plate_rotate_fetcher import PlateRotateFetcher
from daily_review.data.ths_newhigh import save_newhigh_snapshot
from daily_review.data.xuangubao import fetch_stock_labels_batch
from daily_review.features.build_features import build_mood_inputs, default_chart_palette
from daily_review.modules_v2 import ALL_MODULES
from daily_review.pipeline.context import Context
from daily_review.pipeline.runner import Runner
from daily_review.render.render_html import build_plate_rank_top10


def _workspace_root() -> Path:
    # /workspace/daily_review/cli.py -> /workspace
    return Path(__file__).resolve().parent.parent


def _now_bj_date8() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))).strftime("%Y%m%d")


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_prd_v2_network_allowed(*, allow_network: bool) -> bool:
    if not allow_network:
        return False
    return not _env_truthy("QR_DISABLE_PRD_V2_NETWORK")


def _stock_research_backtest_refresh_enabled() -> bool:
    return not _env_truthy("QR_DISABLE_STOCK_RESEARCH_BACKTEST_REFRESH")


def _daily_snapshot_limit_enabled() -> bool:
    return _env_truthy("QR_LIMIT_DAILY_SNAPSHOT")


def _same_day_stock_research_backtest(payload: Any, trade_date10: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    backtest = payload.get("stockResearchBacktest")
    if not isinstance(backtest, dict):
        return None
    realtime_buy = backtest.get("realtimeBuy")
    if not isinstance(realtime_buy, dict):
        return None
    if str(realtime_buy.get("trade_date") or "").strip() != str(trade_date10 or "").strip():
        return None
    return json.loads(json.dumps(backtest, ensure_ascii=False))


def collect_core_realtime_quote_codes_for_full_publish(raw_pools: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()

    def _append_rows(rows: Any, *, min_lbc: int = 0) -> None:
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            if min_lbc > 0:
                try:
                    if int(float(row.get("lbc") or 0)) < min_lbc:
                        continue
                except Exception:
                    continue
            code6 = normalize_stock_code(str(row.get("dm") or row.get("code") or ""))
            if not code6 or code6 in seen:
                continue
            seen.add(code6)
            codes.append(code6)

    _append_rows(raw_pools.get("ztgc") or [])
    _append_rows(raw_pools.get("yest_ztgc") or [], min_lbc=2)
    return codes


def _load_trade_days_from_local_cache(*, cache_dir: Path, limit: int) -> list[str]:
    out: set[str] = set()

    trade_days_path = cache_dir / "trade_days_cache.json"
    trade_days_payload = read_json(trade_days_path, default={})
    days = trade_days_payload.get("days") if isinstance(trade_days_payload, dict) else None
    if isinstance(days, list):
        for day in days:
            if isinstance(day, str) and len(day) == 10:
                out.add(day)

    pools_path = cache_dir / "pools_cache.json"
    pools_payload = read_json(pools_path, default={})
    pools = pools_payload.get("pools") if isinstance(pools_payload, dict) else None
    if isinstance(pools, dict):
        for pool_name in ("ztgc", "dtgc", "zbgc", "qsgc"):
            pool_rows = pools.get(pool_name)
            if not isinstance(pool_rows, dict):
                continue
            for day in pool_rows.keys():
                if isinstance(day, str) and len(day) == 10:
                    out.add(day)

    for fp in cache_dir.glob("market_data-*.json"):
        name = fp.name
        if not name.startswith("market_data-") or not name.endswith(".json"):
            continue
        day8 = name[len("market_data-") : -len(".json")]
        if len(day8) == 8 and day8.isdigit():
            out.add(f"{day8[:4]}-{day8[4:6]}-{day8[6:8]}")

    ordered = sorted(out)
    return ordered[-limit:] if limit > 0 else ordered


def _resolve_trade_days_with_local_fallback(*, client: Any, cache_dir: Path, actual_date: str, n: int) -> list[str]:
    try:
        trade_days = get_trading_days_from_index_k(client, date=actual_date, n=n) or []
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
        _log(f"⚠️ 交易日序列在线获取失败: {e}，回退到本地缓存")
        trade_days = []

    if not trade_days:
        trade_days = _load_trade_days_from_local_cache(cache_dir=cache_dir, limit=n)
        if trade_days:
            _log(f"↪ 使用本地交易日缓存兜底: {trade_days[-1]} (共 {len(trade_days)} 天)")

    if actual_date not in trade_days:
        trade_days = trade_days + [actual_date]
    return sorted(set(trade_days))[-n:]


_ABNORMAL_EVENT_TYPES_ALL = [10001, 10002, 10003, 10004, 10005, 10006, 10007, 10008, 10009, 10010, 10012, 10014, 11000, 11001]
_ABNORMAL_EVENT_TYPES_DEFAULT = [11000, 11001, 10005, 10009, 10010]


def _clean_theme_names(raw_names: list[str]) -> list[str]:
    """清洗并去重题材名（与 gen_report_v4 口径一致）。"""
    names: list[str] = []
    for nm in raw_names:
        nm = str(nm or "").strip()
        if not nm:
            continue
        if nm in DEFAULT_CONFIG.exclude_theme_names:
            continue
        if nm in DEFAULT_CONFIG.noise_themes:
            continue
        if any(nm.startswith(pfx) for pfx in DEFAULT_CONFIG.noise_prefixes):
            continue
        if nm.startswith("A股-热门概念-"):
            nm = nm.replace("A股-热门概念-", "")
        names.append(nm)
    seen: set[str] = set()
    uniq: list[str] = []
    for nm in names:
        if nm in seen:
            continue
        seen.add(nm)
        uniq.append(nm)
    return uniq


def _abnormal_event_sample_path(root: Path, date: str) -> Path:
    cache_dir = root / "cache"
    d8 = str(date or "").replace("-", "")
    return cache_dir / f"abnormal_event_history-{d8}.json"


def _fetch_abnormal_event_history_sample(*, count: int = 100, types: list[int] | None = None, timeout: int = 20) -> dict[str, Any]:
    query = [f"count={int(count)}"]
    if types:
        query.append("types=" + ",".join(str(int(x)) for x in types))
    query.append(f"_ts={int(time.time() * 1000)}")
    url = "https://flash-api.xuangubao.cn/api/event/history?" + "&".join(query)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(body) if body else {}
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
        return {
            "url": url,
            "count": 0,
            "data": {},
            "error": str(e),
        }
    rows = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), list) else []
    return {
        "url": url,
        "count": len(rows),
        "data": data,
    }


def _save_abnormal_event_history_sample(*, root: Path, date: str, mode: str, note: str = "") -> Path | None:
    path = _abnormal_event_sample_path(root, date)
    prev = read_json(path, default={})
    existing_runs = prev.get("runs") if isinstance(prev, dict) and isinstance(prev.get("runs"), list) else []

    import datetime as _dt

    now_bj = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    combined = _fetch_abnormal_event_history_sample(count=120, types=_ABNORMAL_EVENT_TYPES_ALL)
    focused = _fetch_abnormal_event_history_sample(count=120, types=_ABNORMAL_EVENT_TYPES_DEFAULT)

    run = {
        "saved_at_bj": now_bj,
        "mode": mode,
        "note": note,
        "recognized_types": _ABNORMAL_EVENT_TYPES_ALL,
        "default_focus_types": _ABNORMAL_EVENT_TYPES_DEFAULT,
        "combined": combined,
        "focused": focused,
    }
    runs = (existing_runs + [run])[-40:]
    payload = {
        "schema": "abnormal_event_history_v1",
        "date": date,
        "updated_at_bj": now_bj,
        "run_count": len(runs),
        "latest": run,
        "runs": runs,
    }
    write_json(path, payload)
    return path


def _normalize_indices_display(market_data: dict) -> None:
    rows = market_data.get("indices")
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        if "val" in row:
            row["val"] = _fmt_index_val(row.get("val"))
        if "chg" in row:
            row["chg"] = _fmt_index_pct(row.get("chg"))


def _realtime_index_items(market_data: dict) -> list[dict]:
    raw = market_data.get("raw") if isinstance(market_data.get("raw"), dict) else {}
    realtime = raw.get("indices_realtime") if isinstance(raw.get("indices_realtime"), dict) else {}
    items = realtime.get("items") if isinstance(realtime.get("items"), list) else []
    if items:
        return [x for x in items if isinstance(x, dict)]

    # final cache 会清理 raw；保留在 indices 里的 cje 可作为同一次 fetch 后的轻量兜底。
    rows = market_data.get("indices") if isinstance(market_data.get("indices"), list) else []
    return [x for x in rows if isinstance(x, dict) and _display_float(x.get("cje"), 0.0) > 0]


def _apply_realtime_indices_display(market_data: dict) -> None:
    items = _realtime_index_items(market_data)
    if not items:
        return

    current = market_data.get("indices") if isinstance(market_data.get("indices"), list) else []
    by_code = {str(x.get("code") or ""): x for x in current if isinstance(x, dict) and x.get("code")}
    by_name = {str(x.get("name") or ""): x for x in current if isinstance(x, dict) and x.get("name")}
    rows = []
    for item in items:
        code = str(item.get("code") or "").strip()
        name = str(item.get("name") or "").strip()
        val = _display_float(item.get("val"), 0.0)
        if not name or val <= 0:
            continue
        base = dict(by_code.get(code) or by_name.get(name) or {})
        base.update(
            {
                "name": name,
                "code": code,
                "val": _fmt_index_val(item.get("val")),
                "chg": _fmt_index_pct(item.get("chg")),
                "price": val,
            }
        )
        cje = _display_float(item.get("cje"), 0.0)
        if cje > 0:
            base["cje"] = cje
        rows.append(base)

    if rows:
        market_data["indices"] = rows


def _two_market_amount_yi_from_realtime_indices(items: list[dict]) -> float:
    total_yuan = 0.0
    matched = 0
    for item in items:
        code = str(item.get("code") or "").strip().upper()
        name = str(item.get("name") or "").strip()
        is_two_market = code in {"000001.SH", "399001.SZ"} or name in {"上证指数", "深证成指"}
        if not is_two_market:
            continue
        cje = _display_float(item.get("cje"), 0.0)
        if cje <= 0:
            continue
        total_yuan += cje
        matched += 1
    if matched < 2 or total_yuan <= 0:
        return 0.0
    return round(total_yuan / 1e8, 2)


def _apply_intraday_volume_from_realtime_indices(market_data: dict) -> None:
    live_yi = _two_market_amount_yi_from_realtime_indices(_realtime_index_items(market_data))
    if live_yi <= 0:
        return

    date10 = str(market_data.get("date") or "")
    label = date10[5:] if len(date10) >= 10 else date10
    volume = market_data.get("volume") if isinstance(market_data.get("volume"), dict) else {}
    dates = [str(x) for x in (volume.get("dates") or []) if str(x)]
    values = [_display_float(x, 0.0) for x in (volume.get("values") or [])]
    n = min(len(dates), len(values))
    dates = dates[:n]
    values = values[:n]

    if label:
        if label in dates:
            values[dates.index(label)] = live_yi
        else:
            dates.append(label)
            values.append(live_yi)
    if len(dates) > 7:
        dates = dates[-7:]
        values = values[-7:]

    prev = values[-2] if len(values) >= 2 else 0.0
    chg_pct = ((live_yi - prev) / prev * 100.0) if prev else 0.0
    diff = live_yi - prev
    direction_text = "放量" if diff >= 0 else "缩量"
    magnitude_text = "大幅" if abs(chg_pct) >= 5 else "小幅"

    market_data["volume"] = {
        **volume,
        "total": f"{live_yi:.2f}亿",
        "change": f"{chg_pct:+.2f}%",
        "increase": f"{magnitude_text}{direction_text} {abs(diff):.2f}亿",
        "dates": dates,
        "values": values,
    }


def _fetch_realtime_quotes_map(client: HttpClient, codes: list[str], *, limit: int = 220, batch_size: int = 20) -> dict[str, Any]:
    quotes_map, _ = fetch_stocks_realtime_map(client, codes, limit=limit, batch_size=batch_size)
    return quotes_map


def _build_plan_guide(market_data: dict) -> dict | None:
    """
    为前端生成轻量版“明日行动指南”字段，避免模板直接依赖 v2/v3 大对象。
    优先级：v3 -> v2 -> 顶层兜底。
    """
    md = market_data if isinstance(market_data, dict) else {}
    mood = md.get("mood") if isinstance(md.get("mood"), dict) else {}
    canonical_score = mood.get("score", "-")

    def _fallback_mainline() -> str:
        plate_rank = md.get("plateRankTop10") if isinstance(md.get("plateRankTop10"), list) else []
        if plate_rank and isinstance(plate_rank[0], dict) and plate_rank[0].get("name"):
            return str(plate_rank[0].get("name") or "")
        theme_panels = md.get("themePanels") if isinstance(md.get("themePanels"), dict) else {}
        zt_top = theme_panels.get("ztTop") if isinstance(theme_panels.get("ztTop"), list) else []
        if zt_top and isinstance(zt_top[0], dict) and zt_top[0].get("name"):
            return str(zt_top[0].get("name") or "")
        return ""

    def _rightside_text(right: dict) -> str:
        if right.get("allowed") is True or right.get("can_enter") is True:
            return "允许"
        decision = str(right.get("decision") or "").strip()
        if decision == "forbid" or right.get("can_enter") is False:
            return "禁止"
        if decision == "wait":
            return "等确认"
        if right.get("allowed") is False:
            return "等确认"
        return "-"

    v3 = md.get("v3") if isinstance(md.get("v3"), dict) else {}
    if v3:
        sent = v3.get("sentiment") if isinstance(v3.get("sentiment"), dict) else {}
        right = v3.get("rightside") if isinstance(v3.get("rightside"), dict) else {}
        mainline = (((v3.get("mainstream") or {}) if isinstance(v3.get("mainstream"), dict) else {}).get("mainline") or {})
        trading_nature = (((v3.get("tradingNature") or {}) if isinstance(v3.get("tradingNature"), dict) else {}).get("nature") or {})
        full_pos = v3.get("fullPosition") if isinstance(v3.get("fullPosition"), dict) else {}
        pos = v3.get("positionV3") if isinstance(v3.get("positionV3"), dict) else {}
        return {
            "phase": sent.get("phase") or "-",
            "score": canonical_score,
            "position": pos.get("capital_pct_adjusted", "-"),
            "advice": right.get("advice") or "",
            "rightsideText": _rightside_text(right),
            "mainline": right.get("mainline_name") or mainline.get("top_sector") or _fallback_mainline(),
            "nature": trading_nature.get("label") or "",
            "resonance": (
                f"{full_pos.get('passed_count')}/3"
                if full_pos.get("passed_count") is not None
                else ""
            ),
            "warnings": sent.get("warnings") if isinstance(sent.get("warnings"), list) else [],
        }

    v2 = md.get("v2") if isinstance(md.get("v2"), dict) else {}
    if v2:
        sent = v2.get("sentiment") if isinstance(v2.get("sentiment"), dict) else {}
        strategy = v2.get("strategy") if isinstance(v2.get("strategy"), dict) else {}
        right = v2.get("rightside") if isinstance(v2.get("rightside"), dict) else {}
        sector = v2.get("sector") if isinstance(v2.get("sector"), dict) else {}
        mainline = sector.get("mainline") if isinstance(sector.get("mainline"), dict) else {}
        trade_nature = v2.get("trade_nature") if isinstance(v2.get("trade_nature"), dict) else {}
        resonance = v2.get("resonance") if isinstance(v2.get("resonance"), dict) else {}
        warnings = []
        if isinstance(strategy.get("warnings"), list):
            warnings.extend(strategy.get("warnings") or [])
        if isinstance(strategy.get("iron_rules"), list):
            warnings.extend(strategy.get("iron_rules") or [])
        return {
            "phase": sent.get("phase") or strategy.get("tone") or "-",
            "score": canonical_score,
            "position": ((strategy.get("position") or {}) if isinstance(strategy.get("position"), dict) else {}).get("recommended_max", "-"),
            "advice": strategy.get("overall_advice") or "",
            "rightsideText": "允许" if right.get("can_enter") is True else ("禁止" if right.get("can_enter") is False else "-"),
            "mainline": mainline.get("top_sector") or "",
            "nature": trade_nature.get("label") or "",
            "resonance": (
                f"{resonance.get('passed_count')}/3"
                if resonance.get("passed_count") is not None
                else ""
            ),
            "warnings": warnings[:6],
        }

    top_sent = md.get("sentiment") if isinstance(md.get("sentiment"), dict) else {}
    mood_stage = md.get("moodStage") if isinstance(md.get("moodStage"), dict) else {}
    return {
        "phase": top_sent.get("phase") or mood_stage.get("title") or "-",
        "score": canonical_score,
        "position": "-",
        "advice": "",
        "rightsideText": "-",
        "mainline": "",
        "nature": "",
        "resonance": "",
        "warnings": [],
    }


def _prune_frontend_unused_fields(market_data: dict) -> None:
    """
    删除当前页面不再消费、但体积较大的遗留字段，减小 cache/html 注入体积。
    注意：此函数应在所有依赖这些字段的派生计算完成之后调用。
    """
    market_data["planGuide"] = _build_plan_guide(market_data)
    try:
        market_data["plateRankTop10"] = build_plate_rank_top10(market_data)
    except Exception:
        pass
    try:
        ztgc = market_data.get("ztgc")
        if isinstance(ztgc, list):
            keep = ("dm", "mc", "lbc", "cje", "zsz", "zj", "zbc", "hs", "fbt", "hy")
            market_data["ztgc"] = [{k: row.get(k) for k in keep if isinstance(row, dict)} for row in ztgc if isinstance(row, dict)]
    except Exception:
        pass
    try:
        code2themes = market_data.get("zt_code_themes")
        if isinstance(code2themes, dict):
            compact = {}
            for code, themes in code2themes.items():
                if not isinstance(code, str):
                    continue
                if isinstance(themes, list):
                    compact[code] = [str(t).strip() for t in themes if str(t).strip()][:4]
                else:
                    compact[code] = []
            market_data["zt_code_themes"] = compact
    except Exception:
        pass
    try:
        details = market_data.get("plateRotateDetailByCode")
        if isinstance(details, dict):
            compact = {}
            for code, row in details.items():
                if not isinstance(row, dict):
                    continue
                compact[str(code)] = {
                    "date": row.get("date") or [],
                    "strengthSeries": row.get("strengthSeries") or [],
                    "volumeSeries": row.get("volumeSeries") or [],
                }
            market_data["plateRotateDetailByCode"] = compact
    except Exception:
        pass
    for key in ("raw", "compat", "v2", "v3", "dragon", "height_module", "sector", "features", "actionGuideV2", "summary3"):
        market_data.pop(key, None)
    meta = market_data.get("meta") if isinstance(market_data.get("meta"), dict) else {}
    if isinstance(meta, dict):
        meta.pop("algo", None)
        if meta.get("default_page") == "v3":
            meta.pop("default_page", None)
        market_data["meta"] = meta


def _inject_ai_analysis(root: Path, date: str, market_data: dict) -> None:
    """AI 分析注入：读取 cache/ai_analysis-YYYYMMDD.json，覆盖 Python 固定模板文本。

    如果 AI 分析缓存不存在，静默跳过，保持 Python 生成的文本不变。
    架构：数据加工 Layer 2（AI 分析）→ Layer 3（Vue3 渲染）
    """
    date8 = str(date).replace("-", "")
    ai_path = root / "cache" / f"ai_analysis-{date8}.json"
    if not ai_path.exists():
        return
    try:
        ai = json.loads(ai_path.read_text(encoding="utf-8"))
    except Exception:
        return

    # learningNotes
    tips = ai.get("learning_tips") if isinstance(ai.get("learning_tips"), list) else []
    quote = ai.get("learning_quote") if isinstance(ai.get("learning_quote"), str) else ""
    if tips or quote:
        ln = market_data.get("learningNotes") or {}
        if isinstance(ln, dict):
            if tips:
                ln["tips"] = tips
            if quote:
                ln["quotes"] = [quote]
            ln["source"] = "ai"
            market_data["learningNotes"] = ln

    # actionAdvisor.summary
    if isinstance(ai.get("action_summary"), str) and ai["action_summary"]:
        aa = market_data.get("actionAdvisor") or {}
        if isinstance(aa, dict):
            aa["summary"] = ai["action_summary"]
            aa["source"] = "ai"
            market_data["actionAdvisor"] = aa

    _log("AI 分析已注入 (learningNotes/actionAdvisor)")


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}", flush=True)


def _fetch_pool_with_cache_fallback(
    client,
    *,
    pool_name: str,
    date: str,
    pools: dict,
    fallback_dates: list[str] | None = None,
) -> list[dict]:
    """
    线上接口偶发 5xx/超时，不能让整条 workflow 因单个池子失败直接中断。
    """
    try:
        rows = fetch_pool(client, pool_name=pool_name, date=date)
        if isinstance(rows, list):
            return rows
    except Exception as e:
        if isinstance(e, urllib.error.HTTPError):
            _log(f"⚠️ {pool_name}@{date} 在线抓取失败: HTTP {e.code}，尝试使用缓存兜底")
        else:
            _log(f"⚠️ {pool_name}@{date} 在线抓取失败: {e}，尝试使用缓存兜底")

    pool_cache = pools.get(pool_name) if isinstance(pools.get(pool_name), dict) else {}
    same_day = pool_cache.get(date) if isinstance(pool_cache, dict) else None
    if isinstance(same_day, list) and same_day:
        _log(f"↪ 使用缓存兜底: {pool_name}@{date} ({len(same_day)} 条)")
        return same_day

    for d in reversed(fallback_dates or []):
        rows = pool_cache.get(d) if isinstance(pool_cache, dict) else None
        if isinstance(rows, list) and rows:
            _log(f"↪ 使用最近缓存兜底: {pool_name}@{d} -> {date} ({len(rows)} 条)")
            return rows
    return []


def run_full(date: str | None) -> int:
    """
    全量更新（收口阶段）：
    1) 在线取数（data 层）+ 落盘 raw/cache（有成本）
    2) 生成 market_data 基础快照（含 raw + features）
    3) 离线跑 v2 pipeline 重建 market_data，并渲染 tab-v1 HTML
    """
    return run_fetch_and_rebuild(date)


def run_fetch_and_rebuild(date: str | None, stock_research_query_tag: str = "") -> int:
    """
    FULL 新入口：在线取数 + 生成 cache/market_data-YYYYMMDD.json + rebuild（离线）
    """
    root = _workspace_root()
    cache_dir = root / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    _log(f"开始在线取数 (请求日期: {date or '自动'})")

    cfg = load_config_from_env()
    from daily_review.http import HttpClient

    client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=30)
    req_date = date
    actual_date, date_note = resolve_trade_date(client, req_date)
    _log(f"交易日确认: {actual_date} ({date_note})")
    refresh_stock_research_backtest = _stock_research_backtest_refresh_enabled()

    import datetime as _dt
    now = _dt.datetime.now()
    is_trading_hour = (9 <= now.hour < 16) and not (
        now.hour == 11 and now.minute >= 30 or now.hour == 12
    )

    # 交易日序列（用于缓存裁剪/昨日）
    trade_days = _resolve_trade_days_with_local_fallback(
        client=client,
        cache_dir=cache_dir,
        actual_date=actual_date,
        n=7,
    )

    # pools_cache.json：预热历史 + 强制刷新当日
    pools_path = cache_dir / "pools_cache.json"
    pools_cache = read_json(pools_path, default={})
    pools = (pools_cache.get("pools") or {}) if isinstance(pools_cache, dict) else {}
    pools.setdefault("ztgc", {})
    pools.setdefault("dtgc", {})
    pools.setdefault("zbgc", {})
    pools.setdefault("qsgc", {})

    # 预热历史
    for d in trade_days:
        if d == actual_date:
            continue
        for pn in ("ztgc", "dtgc", "zbgc"):
            if d not in (pools.get(pn) or {}):
                prev_days = [x for x in trade_days if x < d]
                rows = _fetch_pool_with_cache_fallback(
                    client,
                    pool_name=pn,
                    date=d,
                    pools=pools,
                    fallback_dates=prev_days,
                )
                pools[pn][d] = rows

    # 当日强制刷新（zt/dt/zb/qsgc）
    for pn in ("ztgc", "dtgc", "zbgc", "qsgc"):
        pools.setdefault(pn, {})
        prev_days = [x for x in trade_days if x < actual_date]
        pools[pn][actual_date] = _fetch_pool_with_cache_fallback(
            client,
            pool_name=pn,
            date=actual_date,
            pools=pools,
            fallback_dates=prev_days,
        )

    # 开盘首条自动快照偶发会遇到三池接口短暂空窗，这时全市场数据会异常接近 0。
    # 仅在“涨停/跌停/炸板/强势池同时为空”时做一次短暂重试，避免第一条线上快照失真。
    zt_rows = pools["ztgc"].get(actual_date) or []
    dt_rows = pools["dtgc"].get(actual_date) or []
    zb_rows = pools["zbgc"].get(actual_date) or []
    qs_rows = pools["qsgc"].get(actual_date) or []
    should_retry_open = (
        is_trading_hour
        and now.hour == 9
        and now.minute <= 40
        and not zt_rows
        and not dt_rows
        and not zb_rows
        and not qs_rows
    )
    if should_retry_open:
        _log("开盘首条快照疑似空窗，10秒后重试一次三池数据")
        time.sleep(10)
        for pn in ("ztgc", "dtgc", "zbgc", "qsgc"):
            prev_days = [x for x in trade_days if x < actual_date]
            pools[pn][actual_date] = _fetch_pool_with_cache_fallback(
                client,
                pool_name=pn,
                date=actual_date,
                pools=pools,
                fallback_dates=prev_days,
            )

    # 裁剪
    keep = set(trade_days)
    for pn in ("ztgc", "dtgc", "zbgc", "qsgc"):
        pools[pn] = {d: v for d, v in (pools.get(pn) or {}).items() if d in keep}
    pools_cache = {"version": 1, "pools": pools}
    write_json(pools_path, pools_cache)
    _log("涨停池/跌停池/炸板池/强势池 已获取并落盘")

    # theme_cache.json：只补齐"当日出现的 code6"，避免无限增长
    codes_map = update_theme_cache(
        root=root,
        pools=pools,
        actual_date=actual_date,
        clean_theme_names=_clean_theme_names,
        fetch_stock_labels_batch_fn=fetch_stock_labels_batch,
    )
    _log(f"题材缓存已更新 (共 {len(codes_map)} 只股票)")

    # theme_trend_cache.json：主线题材近 5 日持续性（只用已缓存的 code2themes，不额外请求）
    by_day = build_theme_trend_cache(
        root=root,
        pools=pools,
        trade_days=trade_days,
        actual_date=actual_date,
        codes_map=codes_map,
    )
    _log("主线趋势已计算 (近5日)")

    if not _daily_snapshot_limit_enabled():
        try:
            sample_path = _save_abnormal_event_history_sample(
                root=root,
                date=actual_date,
                mode="fetch",
                note="收盘/全量流程自动留样，供周末异动模块复盘与算法优化使用",
            )
            if sample_path:
                _log(f"异动原始样本已落盘: {sample_path.name}")
        except Exception as e:
            _log(f"异动原始样本保存失败（不影响主流程）: {e}")
    else:
        _log("每日快照限量模式：跳过异动原始样本留存")

    # index_kline_cache.json：缓存指数日K
    # - 用 history 拉更长序列（便于 MA5/MA20 等技术指标在 v3 右侧交易中使用）
    # - 仍保留占位过滤（sf=1 / a<=0 / v<=0）
    codes_entry = update_index_kline_cache(root=root, client=client, actual_date=actual_date)
    _log("指数日K已缓存 (近120日)")

    # height_trend_cache.json：近 7 日高度趋势（只缓存历史日，不缓存当天）
    build_height_trend_cache(root=root, pools=pools, trade_days=trade_days, actual_date=actual_date)
    _log("高度趋势已计算 (近7日)")

    if not _daily_snapshot_limit_enabled():
        try:
            ths_newhigh_path = save_newhigh_snapshot(
                root=root,
                date=actual_date,
                mode="fetch",
                note="收盘/全量流程自动抓取同花顺创新高榜单，供个股强度确认使用",
            )
            _log(f"同花顺创新高榜单已缓存: {ths_newhigh_path.name}")
        except Exception as e:
            _log(f"同花顺创新高榜单抓取失败（不影响主流程）: {e}")
    else:
        _log("每日快照限量模式：跳过同花顺创新高榜单抓取")

    # indices（实时）：仅用于 asOf 展示（HH:MM:SS）
    indices_rt, indices_asof = fetch_indices_realtime(
        client,
        codes=[("000001.SH", "上证指数"), ("399001.SZ", "深证成指"), ("399006.SZ", "创业板指")],
    )
    # indices（报告口径）：用指数日K按“收盘价 vs 前收”计算，确保与 actual_date 一致
    indices_for_report = build_report_indices(actual_date=actual_date, codes_entry=codes_entry)

    # 构造 raw.pools（给 pipeline 使用）
    yest = trade_days[-2] if len(trade_days) >= 2 else ""
    raw_pools = build_raw_pools(pools=pools, actual_date=actual_date, yest=yest)

    # market_data 初始化骨架（保证模板字段存在）
    import datetime as _dt
    gen_time = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    market_data = build_base_market_data(
        actual_date=actual_date,
        date_note=date_note,
        indices_asof=indices_asof,
        generated_at=gen_time,
        indices_for_report=indices_for_report,
        indices_rt=indices_rt,
        raw_pools=raw_pools,
        codes_map=codes_map,
        codes_entry=codes_entry,
        theme_trend_by_day=by_day,
    )

    if not refresh_stock_research_backtest:
        preserved_today_backtest = _same_day_stock_research_backtest(
            read_json(cache_dir / f"market_data-{actual_date.replace('-', '')}.json", default={}),
            actual_date,
        )
        if preserved_today_backtest:
            market_data["stockResearchBacktest"] = preserved_today_backtest
            _log("沿用当日已存在 stockResearchBacktest，跳过非早盘刷新")

    # === v3 增强：批量个股实时行情（让 v3 输出更“厚”） ===
    quotes_map: dict[str, Any] = {}
    try:
        codes = collect_core_realtime_quote_codes_for_full_publish(raw_pools)
        quotes_map = _fetch_realtime_quotes_map(client, codes, limit=len(codes) or None, batch_size=20)
        attach_quotes_and_features(
            market_data=market_data,
            raw_pools=raw_pools,
            quotes_asof=indices_asof,
            quotes_map=quotes_map,
        )
        _log(f"个股实时行情已获取 ({len(quotes_map)} 只)")
    except Exception:
        pass

    # features：最小可用版
    mood_inputs = (market_data.get("features") or {}).get("mood_inputs") or build_mood_inputs(pools=raw_pools, quotes=quotes_map)
    if not (market_data.get("features") or {}).get("mood_inputs"):
        market_data["features"]["mood_inputs"] = mood_inputs
        market_data["features"]["chart_palette"] = default_chart_palette()

    # 写 market_data 缓存（供 rebuild/partial 使用）
    market_path = write_market_data(root=root, market_data=market_data, actual_date=actual_date)
    _log(f"market_data 缓存已写入: {market_path.name}")

    # 离线重建（pipeline）并渲染 tab-v1
    _log("开始离线重建 pipeline...")
    rc = run_rebuild(
        actual_date,
        allow_network=True,
        stock_research_query_tag=stock_research_query_tag,
        refresh_stock_research_backtest=refresh_stock_research_backtest,
    )

    # 同步生成盯盘快照：每次 fetch 都追加一条盘中切片
    # 注意：run_rebuild 会将完整 market_data（含 volume/plateRankTop10/mood_inputs）写回缓存文件
    # 快照构建需从缓存文件重新读取，确保拿到 rebuild 后的完整数据
    try:
        append_watch_runtime_slice(
            root=root,
            market_path=market_path,
            fallback_market_data=market_data,
            fallback_mood_inputs=mood_inputs,
            log_fn=_log,
        )
    except Exception as e:
        print(f"⚠️ 盯盘快照生成失败（不影响主流程）: {e}")

    # fetch 主流程会在 rebuild 之后继续追加一条最新盯盘切片。
    # 这里需要把“追加后的切片 + 可能复用到的 09:25 实时快照”同步回最终 market_data，
    # 否则后续发布仍可能拿到缺少最新时间节点/误判快照缺失的半成品。
    try:
        final_market_data = json.loads(market_path.read_text(encoding="utf-8")) if market_path.exists() else {}
        if isinstance(final_market_data, dict):
            inject_intraday_snapshots(root=root, date=actual_date, market_data=final_market_data)
            if refresh_stock_research_backtest:
                attach_stock_research_backtest(
                    market_data=final_market_data,
                    sync_source=True,
                    query_tag=stock_research_query_tag,
                    log_fn=lambda msg: _log(f"[final-sync] {msg}"),
                )
                _log("最终 market_data 已同步最新盯盘切片/个股回测快照")
            else:
                preserved_today_backtest = _same_day_stock_research_backtest(final_market_data, actual_date)
                if preserved_today_backtest:
                    final_market_data["stockResearchBacktest"] = preserved_today_backtest
                _log("最终 market_data 已同步最新盯盘切片，保留同日财富密码快照")
            market_path.write_text(json.dumps(final_market_data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"⚠️ 最终 market_data 同步失败（不影响主流程）: {e}")

    return rc


def run_intraday_snapshot(date: str | None) -> int:
    """
    盘中快照模式：
    - 数据截止"当前时刻"（API实时返回）
    - 输出文件名带 -intraday 后缀
    - 量能自动估算全天
    - 部分指标标注"盘中估"
    """
    import datetime as _dt

    root = _workspace_root()
    cache_dir = root / "cache"

    # 先跑一次 fetch（获取当前时刻数据）
    # 复用 run_fetch_and_rebuild 的取数逻辑，但标记为 intraday
    cfg = load_config_from_env()
    from daily_review.http import HttpClient

    client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=30)
    req_date = date
    actual_date, date_note = resolve_trade_date_intraday(client, req_date)
    _log(f"盘中交易日: {actual_date} ({date_note})")

    # 当前时间（用于量能估算和标记）
    now = _dt.datetime.now()
    now_str = now.strftime("%H:%M:%S")

    # 判断是否在交易时间内
    is_trading_hour = (9 <= now.hour < 16) and not (
        now.hour == 11 and now.minute >= 30 or now.hour == 12
    )

    if not is_trading_hour:
        print(f"⚠️ 当前时间 {now_str} 不在交易时段内（9:00-15:30），数据可能为上一交易日收盘数据。")

    _log(f"盘中快照模式启动 (请求日期: {date or '自动'})")

    # ===== 取数逻辑与 fetch 相同，但不强制刷新历史缓存 =====
    trade_days = _resolve_trade_days_with_local_fallback(
        client=client,
        cache_dir=cache_dir,
        actual_date=actual_date,
        n=3,
    )

    pools_path = cache_dir / "pools_cache.json"
    pools_cache = read_json(pools_path, default={})
    pools = (pools_cache.get("pools") or {}) if isinstance(pools_cache, dict) else {}
    pools.setdefault("ztgc", {})
    pools.setdefault("dtgc", {})
    pools.setdefault("zbgc", {})
    pools.setdefault("qsgc", {})

    # 只取当日数据（不预取历史，加快速度）
    for pn in ("ztgc", "dtgc", "zbgc", "qsgc"):
        pools.setdefault(pn, {})
        prev_days = [x for x in trade_days if x < actual_date]
        pools[pn][actual_date] = _fetch_pool_with_cache_fallback(
            client,
            pool_name=pn,
            date=actual_date,
            pools=pools,
            fallback_dates=prev_days,
        )

    # 开盘首条盘中快照偶发会遇到三池接口短暂空窗。
    # intraday 模式同样补一次短暂重试，避免自动盘中首轮与手动触发口径不一致。
    zt_rows = pools["ztgc"].get(actual_date) or []
    dt_rows = pools["dtgc"].get(actual_date) or []
    zb_rows = pools["zbgc"].get(actual_date) or []
    qs_rows = pools["qsgc"].get(actual_date) or []
    should_retry_open = (
        is_trading_hour
        and now.hour == 9
        and now.minute <= 40
        and not zt_rows
        and not dt_rows
        and not zb_rows
        and not qs_rows
    )
    if should_retry_open:
        _log("盘中首条快照疑似空窗，10秒后重试一次三池数据")
        time.sleep(10)
        for pn in ("ztgc", "dtgc", "zbgc", "qsgc"):
            prev_days = [x for x in trade_days if x < actual_date]
            pools[pn][actual_date] = _fetch_pool_with_cache_fallback(
                client,
                pool_name=pn,
                date=actual_date,
                pools=pools,
                fallback_dates=prev_days,
            )
    # 裁剪：只保留近 3 个交易日（watch 模式 trade_days 最多 3 天）
    watch_keep = set(trade_days)
    for pn in ("ztgc", "dtgc", "zbgc", "qsgc"):
        pools[pn] = {d: v for d, v in (pools.get(pn) or {}).items() if d in watch_keep}
    write_json(pools_path, {"version": 1, "pools": pools})
    _log("盘中数据池已获取")

    # theme_cache：只处理当日涨停股
    codes_map = update_theme_cache(
        root=root,
        pools=pools,
        actual_date=actual_date,
        clean_theme_names=_clean_theme_names,
        fetch_stock_labels_batch_fn=fetch_stock_labels_batch,
    )

    try:
        sample_path = _save_abnormal_event_history_sample(
            root=root,
            date=actual_date,
            mode="intraday",
            note="盘中流程自动留样，供周末异动模块复盘与算法优化使用",
        )
        if sample_path:
            _log(f"异动原始样本已落盘: {sample_path.name}")
    except Exception as e:
        _log(f"异动原始样本保存失败（不影响主流程）: {e}")

    # 构造 market_data 骨架（标记为 intraday 模式）
    gen_time = now.strftime("%Y-%m-%d %H:%M:%S")

    raw_pools = build_raw_pools(pools=pools, actual_date=actual_date, yest="")
    market_data = build_intraday_market_data(
        actual_date=actual_date,
        date_note=date_note,
        now_str=now_str,
        generated_at=gen_time,
        raw_pools=raw_pools,
        codes_map=codes_map,
    )

    quotes_map: dict[str, Any] = {}
    try:
        codes = []
        for arr in (raw_pools.get("ztgc") or [], raw_pools.get("qsgc") or [], raw_pools.get("zbgc") or [], raw_pools.get("dtgc") or []):
            if not isinstance(arr, list):
                continue
            for s in arr[:80]:
                if not isinstance(s, dict):
                    continue
                code6 = normalize_stock_code(str(s.get("dm") or s.get("code") or ""))
                if code6:
                    codes.append(code6)
        preserved_research = load_latest_valid_research_snapshot(root=root, current_date=actual_date)
        codes.extend(collect_research_codes_from_snapshot(preserved_research))
        quotes_map = _fetch_realtime_quotes_map(client, codes, limit=220, batch_size=20)
        attach_quotes_and_features(
            market_data=market_data,
            raw_pools=raw_pools,
            quotes_asof=now_str,
            quotes_map=quotes_map,
        )
        _log(f"盘中个股实时行情已获取 ({len(quotes_map)} 只)")
    except Exception:
        pass

    if not (market_data.get("features") or {}).get("mood_inputs"):
        mood_inputs = build_mood_inputs(pools=raw_pools, quotes=((market_data.get("raw") or {}).get("quotes") or {}).get("items") or {})
        market_data["features"]["mood_inputs"] = mood_inputs
        market_data["features"]["chart_palette"] = default_chart_palette()

    # 写缓存
    market_path = write_market_data(root=root, market_data=market_data, actual_date=actual_date, suffix="intraday")
    _log(f"盘中缓存已写入: {market_path.name}")

    # 跑 pipeline + 渲染（复用 rebuild 的大部分逻辑）
    # 第一次：先把计算结果写回 intraday market_data（用于生成快照记录）
    _log("pipeline 初次重建...")
    run_rebuild(actual_date, suffix="intraday", source_market_path=market_path, allow_network=True)

    # 追加快照记录（写入 cache/intraday_snapshots-YYYYMMDD.json）
    try:
        import datetime as _dt3
        _now10_snap = _dt3.datetime.now(_dt3.timezone(_dt3.timedelta(hours=8))).strftime("%Y-%m-%d")
        snap_md = json.loads(market_path.read_text(encoding="utf-8"))
        append_intraday_snapshot(root=root, date=_now10_snap, market_data=snap_md)
        _log("快照记录已追加")
    except Exception:
        pass

    # 第二次：把"半小时快照列表"注入页面后再重建一次（离线，成本很低）
    _log("pipeline 二次重建（含快照注入）...")
    run_rebuild(actual_date, suffix="intraday", source_market_path=market_path, allow_network=True)

    return 0


def _normalize_date(date: str) -> str:
    """统一日期格式：'20260508' → '2026-05-08'，已经是 YYYY-MM-DD 则原样返回。"""
    d = str(date or "").strip().replace("/", "-")
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return d


def _prepare_indices_from_cache(ctx: Context, *, date: str, full_fields: bool) -> None:
    """用指数日K缓存修正报告日指数显示。"""
    try:
        codes = ((ctx.raw.get("index_klines") or {}).get("codes") or {}) if isinstance(ctx.raw, dict) else {}
        if not isinstance(codes, dict) or not date:
            return

        def _norm_k_date(t: str) -> str:
            t = (t or "").strip()
            if len(t) >= 10:
                return t[:10]
            if len(t) == 8 and t.isdigit():
                return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
            return t

        def _pick_exact(code: str) -> tuple[float, float] | None:
            items = (codes.get(code) or {}).get("items") or []
            if not isinstance(items, list):
                return None
            for it in items:
                if not isinstance(it, dict):
                    continue
                t = _norm_k_date(str(it.get("t") or ""))
                if t == date and int(it.get("sf", 0) or 0) != 1:
                    c = float(it.get("c", 0) or 0)
                    pc = float(it.get("pc", 0) or 0)
                    return (c, pc)
            return None

        def _calc_ma(code: str, *, n: int) -> float | None:
            items = (codes.get(code) or {}).get("items") or []
            if not isinstance(items, list):
                return None
            closes = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                t = _norm_k_date(str(it.get("t") or ""))
                if t and t <= date and int(it.get("sf", 0) or 0) != 1:
                    closes.append(float(it.get("c", 0) or 0))
            closes = [c for c in closes if c > 0]
            if len(closes) < n:
                return None
            seg = closes[-n:]
            return sum(seg) / float(n) if seg else None

        mapping = [("000001.SH", "上证指数"), ("399001.SZ", "深证成指"), ("399006.SZ", "创业板指")]
        inds = []
        for code, name in mapping:
            result = _pick_exact(code)
            if not result:
                continue
            close, prev_close = result
            chg = ((close - prev_close) / prev_close * 100.0) if prev_close else 0.0
            if abs(chg) < 0.005:
                chg = 0.0
            row = {
                "name": name,
                "code": code,
                "val": f"{close:.2f}",
                "chg": f"{chg:+.2f}%",
            }
            if full_fields:
                row["price"] = close
                row["ma5"] = _calc_ma(code, n=5)
                row["ma20"] = _calc_ma(code, n=20)
            inds.append(row)
        if inds:
            ctx.market_data["indices"] = inds
            if full_fields:
                meta = ctx.market_data.get("meta") if isinstance(ctx.market_data.get("meta"), dict) else {}
                if isinstance(meta, dict):
                    asof = meta.get("asOf") if isinstance(meta.get("asOf"), dict) else {}
                    if isinstance(asof, dict):
                        asof["indices"] = "收盘"
                        meta["asOf"] = asof
                        ctx.market_data["meta"] = meta
    except Exception:
        return


def _postprocess_market_data(
    *,
    root: Path,
    date: str,
    market_data: dict,
    allow_network: bool,
    prd_v2_allow_network: bool,
    include_intraday_snapshots: bool,
    preserve_zt_analysis: bool,
    apply_runtime_display: bool,
    normalize_meta: bool,
    sync_stock_research_source: bool,
    refresh_stock_research_backtest: bool,
    stock_research_query_tag: str = "",
    include_prd_v2: bool,
    log_prefix: str = "",
) -> None:
    if apply_runtime_display:
        try:
            _apply_realtime_indices_display(market_data)
            _normalize_indices_display(market_data)
            _apply_intraday_volume_from_realtime_indices(market_data)
        except Exception:
            pass

    if include_intraday_snapshots:
        try:
            inject_intraday_snapshots(root=root, date=date, market_data=market_data)
            _log(f"{log_prefix}盘中快照已注入 ({len(market_data.get('intradaySnapshots', {}).get('snapshots', []))} 条)")
        except Exception:
            pass

    if normalize_meta:
        try:
            import datetime as _dt

            meta = market_data.get("meta") if isinstance(market_data.get("meta"), dict) else {}
            if not isinstance(meta, dict):
                meta = {}
            asof = meta.get("asOf") if isinstance(meta.get("asOf"), dict) else {}
            if not isinstance(asof, dict):
                asof = {}
            gen_time = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            meta.setdefault("generatedAt", gen_time)
            idx = str(asof.get("indices") or "").strip()
            if not idx or idx == "00:00:00":
                asof["indices"] = "收盘"
            if not str(asof.get("pools") or "").strip():
                asof["pools"] = "收盘"
            if not str(asof.get("themes") or "").strip():
                asof["themes"] = "收盘"
            meta["asOf"] = asof
            market_data["meta"] = meta
        except Exception:
            pass

    try:
        inject_mood_history_and_delta(root=root, date=date, market_data=market_data)
        _log(f"{log_prefix}情绪历史趋势/昨日对比 已注入")
    except Exception:
        pass

    try:
        from daily_review.metrics.action_advisor import build_action_advisor

        market_data["actionAdvisor"] = build_action_advisor(market_data=market_data)
        _log(f"{log_prefix}actionAdvisor 已生成")
    except Exception:
        pass

    if preserve_zt_analysis:
        try:
            apply_preserved_research_snapshot(
                root=root,
                current_date=date,
                market_data=market_data,
                log_fn=lambda msg: _log(f"{log_prefix}{msg}"),
            )
        except Exception:
            pass

    try:
        apply_zt_analysis(
            root=root,
            current_date=date,
            market_data=market_data,
            preserve_zt_analysis=preserve_zt_analysis,
            log_fn=lambda msg: _log(f"{log_prefix}{msg}"),
        )
    except Exception:
        pass

    if refresh_stock_research_backtest:
        try:
            attach_stock_research_backtest(
                market_data=market_data,
                sync_source=sync_stock_research_source,
                query_tag=stock_research_query_tag,
                log_fn=lambda msg: _log(f"{log_prefix}{msg}"),
            )
        except Exception:
            pass

    try:
        from daily_review.render.render_html import build_market_overview_7d, build_sentiment_explain_dims

        market_data["marketOverview7d"] = build_market_overview_7d(market_data=market_data)
        market_data["sentimentExplainDims"] = build_sentiment_explain_dims(market_data=market_data)
        _log(f"{log_prefix}marketOverview7d / sentimentExplainDims 已生成")
    except Exception:
        pass

    if include_prd_v2:
        try:
            if allow_network and not prd_v2_allow_network:
                _log(f"{log_prefix}PRD v2 二次联网已禁用，仅读取本地缓存")
            _inject_prd_v2_metrics(
                root=root,
                date=date,
                market_data=market_data,
                allow_network=prd_v2_allow_network,
            )
            _log(f"{log_prefix}PRD v2 指标已注入 (sectorHeatmap/threeQuadrants)")
        except Exception:
            pass

    try:
        _prune_frontend_unused_fields(market_data)
        _log(f"{log_prefix}前端冗余字段已清理")
    except Exception:
        pass


def run_rebuild(
    date: str,
    modules: list[str] | None = None,
    suffix: str = "",
    source_market_path: Path | None = None,
    allow_network: bool = False,
    prd_v2_allow_network: bool | None = None,
    stock_research_query_tag: str = "",
    refresh_stock_research_backtest: bool | None = None,
) -> int:
    """
    离线重建（不请求接口）：
    - 从 cache/market_data-YYYYMMDD.json 读取
    - 注入 raw（pools/theme/index_kline/height_trend 等缓存）
    - 跑 v2 pipeline（modules=None 表示全量重建）
    - 写回 market_data 缓存
    """
    root = _workspace_root()
    bundle = build_rebuild_context(root=root, date=date, source_market_path=source_market_path)
    ctx = bundle.ctx
    market_data = bundle.market_data
    market_path = bundle.market_path
    _log(f"缓存已加载: {market_path.name}")
    _log("离线数据已注入 (pools/themes/klines/height_trend/theme_trend/catalyst)")
    _prepare_indices_from_cache(ctx, date=date, full_fields=True)
    _log("features 已重算")

    runner = Runner(ALL_MODULES)
    runner.run(ctx, targets=(modules or None))
    market_data = ctx.market_data
    _log("pipeline 已执行")
    preserve_zt = _env_truthy("PRESERVE_ZT_ANALYSIS")
    resolved_refresh_stock_research_backtest = (
        _stock_research_backtest_refresh_enabled()
        if refresh_stock_research_backtest is None
        else bool(refresh_stock_research_backtest)
    )
    resolved_prd_v2_allow_network = (
        _resolve_prd_v2_network_allowed(allow_network=allow_network)
        if prd_v2_allow_network is None
        else bool(prd_v2_allow_network)
    )
    _postprocess_market_data(
        root=root,
        date=date,
        market_data=market_data,
        allow_network=allow_network,
        prd_v2_allow_network=resolved_prd_v2_allow_network,
        include_intraday_snapshots=True,
        preserve_zt_analysis=preserve_zt,
        apply_runtime_display=True,
        normalize_meta=True,
        sync_stock_research_source=True,
        refresh_stock_research_backtest=resolved_refresh_stock_research_backtest,
        stock_research_query_tag=stock_research_query_tag,
        include_prd_v2=True,
    )

    # 回写 market_data 缓存（Layer 2 → Layer 3 的数据接口）
    # HTML 渲染由 qr.sh 调用 npm run build + inject_data.py 完成
    market_path.write_text(json.dumps(market_data, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"market_data 已回写: {market_path.name}")
    print(f"✅ rebuild 输出: {market_path}")
    return 0


def _inject_prd_v2_metrics(*, root: Path, date: str, market_data: dict, allow_network: bool = False) -> None:
    """
    PRD v2 派生字段注入：
    - 严格使用现有 marketData + raw.pools + 缓存历史文件复算
    - 输出字段写入 market_data，供前端直接渲染
    """

    from daily_review.metrics.sector_heatmap import build_sector_heatmap
    from daily_review.metrics.three_quadrants import build_three_quadrants
    from daily_review.metrics.risk_diffusion import build_risk_engine
    from daily_review.metrics.divergence import build_divergence_engine
    from daily_review.metrics.high_position_risk import build_high_position_risk
    from daily_review.metrics.structure_v2 import build_structure_v2
    from daily_review.metrics.action_sheet import build_action_sheet

    def _concept_fund_flow_cache_path(*, root: Path) -> Path:
        """
        纯函数：概念级资金流向缓存路径（AkShare/东财口径）。
        """
        return root / "cache" / "concept_fund_flow_cache.json"

    def _load_concept_fund_flow_cache(*, root: Path) -> dict:
        """
        读取概念资金流缓存。
        结构：
        {
          "version": 1,
          "by_day": { "YYYYMMDD": [ {name, net, inflow, outflow, chg_pct, lead, lead_chg_pct, companies}, ... ] }
        }
        """
        p = _concept_fund_flow_cache_path(root=root)
        data = read_json(p, default={})
        if not isinstance(data, dict):
            return {"version": 1, "by_day": {}}
        by_day = data.get("by_day") or {}
        if not isinstance(by_day, dict):
            by_day = {}
        return {"version": 1, "by_day": by_day}

    def _write_concept_fund_flow_cache(*, root: Path, data: dict) -> None:
        """
        写回概念资金流缓存（副作用）。
        """
        p = _concept_fund_flow_cache_path(root=root)
        write_json(p, data)

    def _plate_rotate_cache_path(*, root: Path) -> Path:
        """
        纯函数：短线侠板块轮动缓存路径。
        """
        return root / "cache" / "plate_rotate_cache.json"

    def _load_plate_rotate_cache(*, root: Path) -> dict:
        """
        读取短线侠板块轮动缓存。
        结构：
        {
          "version": 1,
          "by_day": {
            "YYYYMMDD": {
              "rows": [ {rank, name, strength}, ... ],
              "leaders": [..]
            }
          }
        }
        """
        p = _plate_rotate_cache_path(root=root)
        data = read_json(p, default={})
        if not isinstance(data, dict):
            return {"version": 1, "by_day": {}}
        by_day = data.get("by_day") or {}
        if not isinstance(by_day, dict):
            by_day = {}
        return {"version": 1, "by_day": by_day}

    def _write_plate_rotate_cache(*, root: Path, data: dict) -> None:
        p = _plate_rotate_cache_path(root=root)
        write_json(p, data)

    def _refresh_plate_rotate_cache(*, root: Path) -> dict:
        """
        在线刷新短线侠板块轮动缓存：
        - 抓最近 20 日窗口
        - 为窗口内每一天写入 top10 + 当天龙头 + 量能/强度
        """
        fetcher = PlateRotateFetcher()
        payload = fetcher.fetch_kaipan_days(days=20)
        by_day = payload.get("by_day") or {}
        cache = {"version": 2, "by_day": by_day, "source": payload.get("source") or ""}
        _write_plate_rotate_cache(root=root, data=cache)
        return cache

    def _should_refresh_plate_rotate_cache(*, cache: dict, report_date: str) -> bool:
        """
        是否允许在线刷新板块轮动缓存：
        - 历史日期：不刷新，只读本地
        - 非北京时间今天：不刷新
        - 今天但未收盘：不刷新
        - 今天且已收盘：若今天数据不存在/不完整，则刷新一次
        """
        try:
            bj = datetime.now(_SH_TZ)
            today = bj.strftime("%Y-%m-%d")
            if str(report_date or "") != today:
                return False
            # 收盘后再抓，给一点缓冲，默认 15:10 之后
            hm = int(bj.strftime("%H%M"))
            if hm < 1510:
                return False
            by_day = cache.get("by_day") if isinstance(cache, dict) else {}
            if not isinstance(by_day, dict):
                by_day = {}
            day_obj = by_day.get(today) or by_day.get(today.replace("-", "")) or {}
            if not isinstance(day_obj, dict):
                return True
            rows = day_obj.get("rows")
            if not isinstance(rows, list) or len(rows) < 10:
                return True
            # 已有 10 条，并且前几条含明细，则认为今天已抓过
            sample = rows[:3]
            has_detail = any(isinstance(x, dict) and (x.get("lead") or x.get("volume") is not None) for x in sample)
            return not has_detail
        except Exception:
            return False

    def _now_bj_date10() -> str:
        """
        纯函数：返回北京时间今天 YYYY-MM-DD（用于判定是否允许在线拉取概念资金流）。
        """
        import datetime as _dt
        from datetime import timezone, timedelta

        bj = timezone(timedelta(hours=8))
        return _dt.datetime.now(bj).strftime("%Y-%m-%d")

    def _fetch_concept_fund_flow_top(*, topn: int = 40) -> list[dict]:
        """
        在线抓取“概念/题材级资金流向榜”（AkShare -> 东财）。

        说明：
        - 这是板块/概念级数据源，比“个股资金流再聚合”更接近你要的“板块流入”
        - AkShare 不需要 BIYING_TOKEN，但需要联网
        - 返回字段尽量收敛为可渲染的结构（单位按数据源原样保留）
        """
        try:
            import akshare as ak  # type: ignore
        except Exception:
            return []

        try:
            df = ak.stock_fund_flow_concept()
        except Exception:
            return []

        if df is None or getattr(df, "empty", True):
            return []

        def pick(row: dict) -> dict:
            """
            纯函数：行 -> 规范化 dict。
            """
            name = str(row.get("行业") or row.get("板块") or row.get("名称") or "").strip()
            return {
                "name": name,
                "index": row.get("行业指数"),
                "chg_pct": row.get("行业-涨跌幅"),
                "inflow": row.get("流入资金"),
                "outflow": row.get("流出资金"),
                "net": row.get("净额"),
                "companies": row.get("公司家数"),
                "lead": row.get("领涨股") or row.get("领涨股票") or "",
                "lead_chg_pct": row.get("领涨股-涨跌幅") or row.get("领涨股票-涨跌幅"),
                "price": row.get("当前价"),
            }

        # 兼容列名：AkShare 当前使用中文列
        rows = []
        for _, r in df.head(max(int(topn), 1)).iterrows():
            if hasattr(r, "to_dict"):
                it = pick(r.to_dict())
                if it.get("name"):
                    rows.append(it)
        return rows

    def _code_with_market(code6: str) -> str:
        """
        纯函数：6位代码 -> 带市场后缀（SH/SZ）。
        """
        c = "".join([x for x in str(code6 or "") if x.isdigit()])[-6:]
        if not c:
            return ""
        return f"{c}.SH" if c.startswith("6") else f"{c}.SZ"

    def _to_num(v: Any, d: float = 0.0) -> float:
        """
        纯函数：安全转 float（兼容 %/亿 等字符串）。
        """
        try:
            if v is None:
                return d
            if isinstance(v, str):
                s = v.replace("%", "").replace("亿", "").strip()
                return float(s) if s else d
            return float(v)
        except Exception:
            return d

    def _money_flow_cache_path(*, root: Path) -> Path:
        """
        纯函数：资金流向缓存路径。
        """
        return root / "cache" / "money_flow_cache.json"

    def _load_money_flow_cache(*, root: Path) -> dict:
        """
        读取资金流向缓存（离线复用）。
        结构：
        {
          "version": 1,
          "by_day": { "YYYYMMDD": { "000001": 1.23, ... }, ... }
        }
        """
        p = _money_flow_cache_path(root=root)
        data = read_json(p, default={})
        if not isinstance(data, dict):
            return {"version": 1, "by_day": {}}
        by_day = data.get("by_day") or {}
        if not isinstance(by_day, dict):
            by_day = {}
        return {"version": 1, "by_day": by_day}

    def _write_money_flow_cache(*, root: Path, data: dict) -> None:
        """
        写回资金流向缓存（副作用）。
        """
        p = _money_flow_cache_path(root=root)
        write_json(p, data)

    def _fetch_money_flow_day_map(client: Any, *, code6: str, st8: str, et8: str) -> dict[str, float]:
        """
        区间拉取单股资金流后拆成按日映射，避免 7 日窗口内同一股票重复请求。
        """
        code = _code_with_market(code6)
        if not code:
            return {}
        rows = fetch_stock_money_flow(client, code=code, st=st8, et=et8)
        if not isinstance(rows, list) or not rows:
            return {}
        return extract_money_flow_day_map(rows)

    def _inject_sector_flow_7d(*, root: Path, date: str, market_data: dict, client: Any) -> None:
        """
        板块流入（近7日累计，口径=大单净流入）：
        - 近7日：从 pools_cache 的日期序列中截取 <=date 的最近7个交易日
        - 股票集合：近7日中所有“2连板(lbc=2)”出现过的股票（按 code6 去重，但按出现日计算资金流）
        - 题材归属：theme_cache.json 的 code6->themes（已清洗）
        - 分摊：一只股票多个题材时，用 1/k 分摊到每个题材
        - 输出：写回 marketData.sectors[*].flow7d_yi，用于 UI 展示
        """
        md = market_data or {}
        sectors = md.get("sectors") or []
        if not isinstance(sectors, list) or not sectors:
            return

        # 只对当前要展示的题材做流入计算（控制接口调用规模）
        target_themes = [str(s.get("name") or "").strip() for s in sectors if isinstance(s, dict)]
        target_themes = [t for t in target_themes if t]
        if not target_themes:
            return
        target_set = set(target_themes)

        zt_by_day = app_load_ztgc_by_day_window(root=root, date=date, n=7)
        if not zt_by_day:
            return
        code2themes = app_load_theme_cache(root)
        if not isinstance(code2themes, dict) or not code2themes:
            return

        # 1) 生成“(day, code)-> 题材分摊权重”列表
        allocs: list[tuple[str, str, str, float]] = []
        pairs: set[tuple[str, str]] = set()
        days = sorted([d for d in zt_by_day.keys() if isinstance(d, str) and d <= date])[-7:]
        for d in days:
            rows = zt_by_day.get(d) or []
            if not isinstance(rows, list):
                continue
            day8 = d.replace("-", "")
            for r in rows:
                if not isinstance(r, dict):
                    continue
                if int(r.get("lbc", 0) or 0) != 2:
                    continue
                c6 = "".join([x for x in str(r.get("dm") or r.get("code") or "") if x.isdigit()])[-6:]
                if not c6:
                    continue
                ths0 = code2themes.get(c6) or []
                ths = [str(x).strip() for x in ths0 if str(x or "").strip()]
                if not ths:
                    continue
                hit = [t for t in ths if t in target_set]
                if not hit:
                    continue
                w = 1.0 / float(len(ths))  # 多题材 1/k 分摊（用全集，避免人为偏置）
                for t in hit:
                    allocs.append((day8, c6, t, w))
                pairs.add((day8, c6))

        if not allocs:
            return

        # 2) 拉取/复用资金流向缓存
        cache = _load_money_flow_cache(root=root)
        by_day = cache.get("by_day") or {}
        if not isinstance(by_day, dict):
            by_day = {}

        # 3) 按股票一次性补齐近 7 日区间资金流，再拆回 day->code 缓存。
        window_start8 = days[0].replace("-", "")
        window_end8 = days[-1].replace("-", "")
        need_codes: set[str] = set()
        for day8, c6 in sorted(list(pairs)):
            day_map = by_day.get(day8) or {}
            if not isinstance(day_map, dict) or c6 not in day_map:
                need_codes.add(c6)

        for c6 in sorted(need_codes):
            day_map_full = _fetch_money_flow_day_map(client, code6=c6, st8=window_start8, et8=window_end8)
            if not day_map_full:
                continue
            for day8, value in day_map_full.items():
                if day8 not in {d.replace("-", "") for d in days}:
                    continue
                current_day_map = by_day.get(day8) or {}
                if not isinstance(current_day_map, dict):
                    current_day_map = {}
                current_day_map[c6] = value
                by_day[day8] = current_day_map

        cache["by_day"] = by_day
        # 裁剪：只保留近 7 个交易日（day8 格式 YYYYMMDD）
        keep8 = {d.replace("-", "") for d in trade_days}
        cache["by_day"] = {k: v for k, v in by_day.items() if k in keep8}
        _write_money_flow_cache(root=root, data=cache)

        # 4) 聚合到题材：7日累计净流入（亿）
        flow_by_theme: dict[str, float] = {t: 0.0 for t in target_themes}
        miss = 0
        for day8, c6, theme, w in allocs:
            day_map = by_day.get(day8) or {}
            v = day_map.get(c6) if isinstance(day_map, dict) else None
            if v is None:
                miss += 1
                continue
            flow_by_theme[theme] = float(flow_by_theme.get(theme, 0.0) or 0.0) + float(v) * float(w)

        # 5) 写回 sectors（用于板块题材tab展示）
        for s in sectors:
            if not isinstance(s, dict):
                continue
            name = str(s.get("name") or "").strip()
            if not name or name not in flow_by_theme:
                continue
            fy = round(float(flow_by_theme.get(name, 0.0) or 0.0), 2)
            s["flow7d_yi"] = fy
            # 给前端一个颜色参考（也可直接用 signedClass）
            s["flow7d_class"] = "red-text" if fy > 0 else ("green-text" if fy < 0 else "text-muted")

        # 写 meta，便于你排查“为何没数据/覆盖率”
        md.setdefault("meta", {})
        if isinstance(md.get("meta"), dict):
            md["meta"]["sectorFlow7d"] = {
                "precision": "big_order_net",
                "window_days": days,
                "pairs": len(pairs),
                "allocs": len(allocs),
                "missing_allocs": miss,
                "cache_file": str(_money_flow_cache_path(root=root).name),
            }

    # 1) sectorHeatmap（优先使用 python 统一口径）
    # - 若历史缓存已存在旧结构（无 meta），则刷新一次以补齐口径信息
    sh = market_data.get("sectorHeatmap")
    if (not isinstance(sh, dict)) or ("meta" not in sh):
        market_data["sectorHeatmap"] = build_sector_heatmap(market_data)

    # 2) threeQuadrants（含近5日轨迹）
    tq = build_three_quadrants(market_data)

    # 轨迹：读取 cache/market_data-*.json，取最近5个交易日
    cache_dir = root / "cache"
    date8 = date.replace("-", "")
    items: list[tuple[str, Path]] = []
    for fp in cache_dir.glob("market_data-*.json"):
        stem = fp.stem
        if not stem.startswith("market_data-"):
            continue
        d8 = stem.replace("market_data-", "")
        if len(d8) != 8 or not d8.isdigit():
            continue
        if d8 <= date8:
            items.append((d8, fp))
    items.sort(key=lambda x: x[0])
    hist = []
    # 最近 7 个交易日：用于“情绪温度（解释版）”五线趋势（涨停/连板/跌停/封板率/晋级率）
    for d8, fp in items[-7:]:
        try:
            snap = json.loads(fp.read_text(encoding="utf-8"))
            pt = build_three_quadrants(snap)
            pos = pt.get("position") or {}
            bub = pt.get("bubble") or {}
            hist.append(
                {
                    "date": f"{d8[4:6]}-{d8[6:8]}",
                    "x": pos.get("x"),
                    "y": pos.get("y"),
                    "z": pos.get("z"),
                    "size": bub.get("size"),
                    "zone": (pt.get("interpretation") or {}).get("zone", ""),
                }
            )
        except Exception:
            continue
    if isinstance(tq.get("history"), list):
        tq["history"] = hist
    market_data["threeQuadrants"] = tq

    # 3) riskEngine（风险与亏钱扩散）
    if not isinstance(market_data.get("riskEngine"), dict):
        market_data["riskEngine"] = build_risk_engine(market_data, date=date)

    client = None

    # 4) divergenceEngine（分歧与承接）— 资金维度需精确：调用资金流向接口（样本口径）
    if not isinstance(market_data.get("divergenceEngine"), dict):
        if allow_network:
            try:
                from daily_review.config import load_config_from_env
                from daily_review.http import HttpClient

                cfg = load_config_from_env()
                client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=30)
            except Exception:
                client = None
        market_data["divergenceEngine"] = build_divergence_engine(market_data, date=date, client=client)

    # 4.1) sectorFlow7d（近7天2连板题材的资金流入聚合）— 需要 token 才能精确计算
    if allow_network:
        try:
            # divergenceEngine 已存在时，本函数可能没有初始化 client；这里独立兜底一次
            if client is None:
                try:
                    from daily_review.config import load_config_from_env
                    from daily_review.http import HttpClient

                    cfg = load_config_from_env()
                    if (cfg.token or "").strip():
                        client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=30)
                except Exception:
                    client = None
            if client is not None:
                _inject_sector_flow_7d(root=root, date=date, market_data=market_data, client=client)
        except Exception:
            pass

    # 4.2) plateRotateTop（短线侠板块轮动强度）：
    # - 优先读取本地缓存
    # - 缓存没有报告日期的数据则在线刷新
    # - 命中后直接替换"板块题材排行 TOP10"模块的数据源
    try:
        plate_cache = _load_plate_rotate_cache(root=root)
        plate_by_day = plate_cache.get("by_day") if isinstance(plate_cache, dict) else {}
        if not isinstance(plate_by_day, dict):
            plate_by_day = {}
        date8 = date.replace("-", "")
        # 精确匹配 date / date8，回退到最近可用日期
        plate_day = plate_by_day.get(date) or plate_by_day.get(date8) or {}
        if not (isinstance(plate_day, dict) and plate_day.get("rows")):
            all_keys = sorted(plate_by_day.keys(), reverse=True)
            for k in all_keys:
                if k <= date and k <= date8:
                    candidate = plate_by_day[k]
                    if isinstance(candidate, dict) and candidate.get("rows"):
                        plate_day = candidate
                        break
        # 缓存中无精确匹配数据 → 在线刷新
        exact_match = plate_by_day.get(date) or plate_by_day.get(date8) or {}
        if allow_network and not (isinstance(exact_match, dict) and exact_match.get("rows")):
            try:
                _log("板块轮动缓存无精确数据，在线刷新...")
                plate_cache = _refresh_plate_rotate_cache(root=root)
                plate_by_day = plate_cache.get("by_day") if isinstance(plate_cache, dict) else {}
                if not isinstance(plate_by_day, dict):
                    plate_by_day = {}
                plate_day = plate_by_day.get(date) or plate_by_day.get(date8) or {}
                if not (isinstance(plate_day, dict) and plate_day.get("rows")):
                    all_keys2 = sorted(plate_by_day.keys(), reverse=True)
                    for k in all_keys2:
                        if k <= date and k <= date8:
                            candidate = plate_by_day[k]
                            if isinstance(candidate, dict) and candidate.get("rows"):
                                plate_day = candidate
                                break
            except Exception:
                pass
        if isinstance(plate_day, dict):
            plate_rows = plate_day.get("rows")
            if isinstance(plate_rows, list) and plate_rows:
                detail_by_code = plate_day.get("detailByCode")
                enriched_rows = []
                for r in plate_rows[:20]:
                    row = dict(r) if isinstance(r, dict) else {}
                    code = str(row.get("code") or "")
                    detail = detail_by_code.get(code) if isinstance(detail_by_code, dict) else {}
                    leaders_by_date = (detail.get("leadersByDate") or {}) if isinstance(detail, dict) else {}
                    leaders_today = leaders_by_date.get(date) or row.get("leaders") or []
                    if leaders_today and not row.get("lead"):
                        row["lead"] = str((leaders_today[0] or {}).get("name") or "")
                    if leaders_today and not row.get("leadCode"):
                        row["leadCode"] = str((leaders_today[0] or {}).get("code") or "")
                    if row.get("volume") is None and isinstance(detail, dict):
                        vol_by_date = detail.get("volumeByDate") or {}
                        if isinstance(vol_by_date, dict):
                            row["volume"] = vol_by_date.get(date)
                    if row.get("strengthByDate") is None and isinstance(detail, dict):
                        st_by_date = detail.get("strengthByDate") or {}
                        if isinstance(st_by_date, dict):
                            row["strengthByDate"] = st_by_date.get(date)
                    if leaders_today and not row.get("leaders"):
                        row["leaders"] = leaders_today
                    enriched_rows.append(row)
                market_data["plateRotateTop"] = enriched_rows
                if isinstance(detail_by_code, dict) and detail_by_code:
                    market_data["plateRotateDetailByCode"] = detail_by_code
                if enriched_rows and isinstance(enriched_rows[0].get("leaders"), list):
                    market_data["plateRotateLeaders"] = enriched_rows[0].get("leaders")[:10]
                meta = market_data.get("meta") if isinstance(market_data.get("meta"), dict) else {}
                if isinstance(meta, dict):
                    meta.setdefault("asOf", {})
                    if isinstance(meta.get("asOf"), dict):
                        meta["asOf"]["plate_rotate"] = date
                    market_data["meta"] = meta
    except Exception:
        pass

    # 4.3) conceptFundFlow（概念级资金流向榜）：
    # - 仅读本地缓存（不上线抓取；AkShare 单次 >2min 不应阻塞 pipeline）
    # - 前端已有 surge_stock/plates（选股宝实时）和 plateRotateTop（短线侠缓存）兜底
    try:
        cache = _load_concept_fund_flow_cache(root=root)
        by_day = cache.get("by_day") or {}
        if not isinstance(by_day, dict):
            by_day = {}
        date8 = date.replace("-", "")
        rows = by_day.get(date8)

        # 回退到最近可用日期
        if not isinstance(rows, list) or not rows:
            all_keys = sorted(by_day.keys(), reverse=True)
            for k in all_keys:
                if k <= date8:
                    candidate = by_day[k]
                    if isinstance(candidate, list) and candidate:
                        rows = candidate
                        break

        if isinstance(rows, list) and rows:
            market_data["conceptFundFlowTop"] = rows[:20]
    except Exception:
        pass

    # 5) highPositionRisk（高位风险预警）— 未触发也输出结构化结果
    if not isinstance(market_data.get("highPositionRisk"), dict):
        hp_client = None
        if allow_network:
            try:
                if client is None:
                    from daily_review.config import load_config_from_env
                    from daily_review.http import HttpClient

                    cfg = load_config_from_env()
                    client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=30)
                hp_client = client
            except Exception:
                hp_client = None
        market_data["highPositionRisk"] = build_high_position_risk(market_data, date=date, client=hp_client, trigger_lb=4)

    # 6) structureV2（结构拆解 v2：3结论卡 + 证据链）
    if not isinstance(market_data.get("structureV2"), dict):
        market_data["structureV2"] = build_structure_v2(market_data, date=date)

    # 7) actionSheet（操作单：具体买卖条件，替代泛泛的行动指南）
    if not isinstance(market_data.get("actionSheet"), dict):
        market_data["actionSheet"] = build_action_sheet(market_data)
def run_partial(date: str, modules: list[str]) -> int:
    """
    部分更新：读取缓存的 market_data，然后只重算指定模块，并用模板重新渲染。
    """
    root = _workspace_root()
    bundle = build_rebuild_context(root=root, date=date)
    ctx = bundle.ctx
    market_data = bundle.market_data
    market_path = bundle.market_path
    _log(f"partial 缓存已加载: {market_path.name}  modules={modules}")
    _prepare_indices_from_cache(ctx, date=date, full_fields=False)

    runner = Runner(ALL_MODULES)
    runner.run(ctx, targets=modules)
    market_data = ctx.market_data
    _postprocess_market_data(
        root=root,
        date=date,
        market_data=market_data,
        allow_network=False,
        prd_v2_allow_network=False,
        include_intraday_snapshots=False,
        preserve_zt_analysis=False,
        apply_runtime_display=False,
        normalize_meta=False,
        sync_stock_research_source=False,
        refresh_stock_research_backtest=False,
        include_prd_v2=False,
        log_prefix="partial ",
    )

    # 回写 market_data 缓存
    market_path.write_text(json.dumps(market_data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✅ partial 输出: {market_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="报告日期 YYYY-MM-DD（缺省则走全量模式的默认逻辑）")
    ap.add_argument("--require-python", default="", help="强制要求使用指定 Python 解释器路径（例如 /usr/local/bin/python3）")
    ap.add_argument("--require-py", default="", help="强制要求 Python 版本前缀（例如 3.14）")
    ap.add_argument("--rebuild", action="store_true", help="离线重建（不请求接口）：重算并回写 market_data")
    ap.add_argument("--fetch", action="store_true", help="在线取数并生成缓存，然后离线重建 market_data（有成本）")
    ap.add_argument("--allow-network", action="store_true", help="允许 rebuild 在缺失缓存时在线补齐部分数据源")
    ap.add_argument(
        "--only",
        nargs="+",
        help="部分更新：指定模块名，可选：panorama, ladder, ztgc, theme_panels, volume, height_trend, top10, mood, leader, zt_analysis, learning_notes",
    )
    ap.add_argument(
        "--mode",
        choices=["eod", "intraday"],
        default="eod",
        help="运行模式：eod=收盘版（默认），intraday=盘中快照版（数据截止当前时刻）",
    )
    ap.add_argument("--stock-research-query-tag", default="", help="个股研究竞价查询 tag，例如 fore 表示忽略 09:25 时间窗强制按当前行情匹配")
    args = ap.parse_args(argv)

    stock_research_query_tag = str(args.stock_research_query_tag or "").strip().lower()
    if stock_research_query_tag:
        os.environ["STOCK_RESEARCH_QUERY_TAG"] = stock_research_query_tag

    # === 入口日志 ===
    if args.fetch:
        print(f"▶ [fetch] 在线取数 + 离线重建  date={args.date or '自动'}")
    elif args.rebuild:
        print(f"▶ [rebuild] 离线重建  date={args.date}")
    elif args.only:
        print(f"▶ [partial] 部分更新  modules={args.only}  date={args.date}")
    elif args.mode == "intraday":
        print(f"▶ [intraday] 盘中快照  date={args.date or '自动'}")
    else:
        print(f"▶ [full] 全量模式  date={args.date or '自动'}")

    # === Python 环境校验（可选） ===
    if args.require_python or args.require_py:
        import sys
        if args.require_python and sys.executable != args.require_python:
            raise SystemExit(f"请使用指定解释器运行：{args.require_python}（当前：{sys.executable}）")
        if args.require_py and (not sys.version.startswith(args.require_py)):
            raise SystemExit(f"请使用 Python {args.require_py} 运行（当前：{sys.version.split()[0]}，解释器：{sys.executable}）")

    # 传递 mode 到全局上下文
    if args.mode == "intraday":
        os.environ["REPORT_MODE"] = "intraday"
    if args.only:
        if not args.date:
            raise SystemExit("--only 模式必须指定 --date")
        return run_partial(args.date, args.only)

    if args.rebuild:
        if not args.date:
            raise SystemExit("--rebuild 模式必须指定 --date")
        return run_rebuild(
            args.date,
            allow_network=args.allow_network,
            stock_research_query_tag=stock_research_query_tag,
        )

    if args.fetch:
        return run_fetch_and_rebuild(args.date, stock_research_query_tag=stock_research_query_tag)

    # 盘中快照模式
    if args.mode == "intraday":
        return run_intraday_snapshot(args.date)

    return run_full(args.date)


if __name__ == "__main__":
    raise SystemExit(main())
