#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CLI 入口（后续会逐步替代 gen_report_v4.py 的脚本式入口）

当前阶段策略：
- 先提供一个稳定入口，后续把 monolith 逻辑逐步迁移到 daily_review/* 模块。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path

from daily_review.modules_v2 import ALL_MODULES
from daily_review.metrics.scoring import blend_sentiment_score
from daily_review.pipeline.context import Context
from daily_review.pipeline.runner import Runner
from daily_review.render.render_html import render_html_template, build_plate_rank_top10
from daily_review.cache_io import read_json, write_json
from daily_review.config import load_config_from_env
from daily_review.config import DEFAULT_CONFIG
from daily_review.data.biying import (
    fetch_indices_realtime,
    fetch_index_history_k,
    fetch_pool,
    fetch_stock_themes,
    fetch_stocks_realtime,
    get_trading_days_from_index_k,
    normalize_stock_code,
    resolve_trade_date,
    resolve_trade_date_intraday,
)
from daily_review.features.build_features import build_mood_inputs, default_chart_palette
from daily_review.data.plate_rotate_fetcher import PlateRotateFetcher


def _workspace_root() -> Path:
    # /workspace/daily_review/cli.py -> /workspace
    return Path(__file__).resolve().parent.parent


def _now_bj_date8() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))).strftime("%Y%m%d")


def _display_float(v, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        if isinstance(v, str):
            return float(v.replace("%", "").replace("亿", "").replace(",", "").strip())
        return float(v)
    except Exception:
        return default


def _fmt_index_pct(v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return ""
        if s.endswith("%"):
            return f"{_display_float(s):+.2f}%"
        try:
            return f"{float(s):+.2f}%"
        except Exception:
            return s
    return f"{_display_float(v):+.2f}%"


def _fmt_index_val(v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return ""
        try:
            return f"{float(s):.2f}"
        except Exception:
            return s
    return f"{_display_float(v):.2f}"


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


def _load_latest_valid_zt_analysis(*, root: Path, current_date: str) -> dict | None:
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
        za = data.get("ztAnalysis") if isinstance(data, dict) else None
        if not isinstance(za, dict):
            continue
        relay = za.get("relay") if isinstance(za.get("relay"), list) else []
        watch = za.get("watch") if isinstance(za.get("watch"), list) else []
        if relay or watch:
            out = dict(za)
            meta = out.get("meta") if isinstance(out.get("meta"), dict) else {}
            out["meta"] = {
                **meta,
                "preservedFromDate": data.get("date") or fp.stem.replace("market_data-", ""),
                "preserveReason": "盘中仅更新实时情绪，明日接力/观察沿用上一份收盘推演",
            }
            return out
    return None


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
    for key in ("raw", "compat", "v2", "v3", "dragon", "height_module", "sector"):
        market_data.pop(key, None)
    meta = market_data.get("meta") if isinstance(market_data.get("meta"), dict) else {}
    if isinstance(meta, dict):
        meta.pop("algo", None)
        if meta.get("default_page") == "v3":
            meta.pop("default_page", None)
        market_data["meta"] = meta


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}", flush=True)


def run_full(date: str | None) -> int:
    """
    全量更新（收口阶段）：
    1) 在线取数（data 层）+ 落盘 raw/cache（有成本）
    2) 生成 market_data 基础快照（含 raw + features）
    3) 离线跑 v2 pipeline 重建 market_data，并渲染 tab-v1 HTML
    """
    return run_fetch_and_rebuild(date)


def run_fetch_and_rebuild(date: str | None) -> int:
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

    # 交易日序列（用于缓存裁剪/昨日）
    trade_days = get_trading_days_from_index_k(client, date=actual_date, n=7) or [actual_date]
    if actual_date not in trade_days:
        trade_days = trade_days + [actual_date]
    trade_days = sorted(set(trade_days))[-7:]

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
                rows = fetch_pool(client, pool_name=pn, date=d)
                pools[pn][d] = rows

    # 当日强制刷新（zt/dt/zb/qsgc）
    for pn in ("ztgc", "dtgc", "zbgc", "qsgc"):
        pools.setdefault(pn, {})
        pools[pn][actual_date] = fetch_pool(client, pool_name=pn, date=actual_date)

    # 裁剪
    keep = set(trade_days)
    for pn in ("ztgc", "dtgc", "zbgc", "qsgc"):
        pools[pn] = {d: v for d, v in (pools.get(pn) or {}).items() if d in keep}
    pools_cache = {"version": 1, "pools": pools}
    write_json(pools_path, pools_cache)
    _log("涨停池/跌停池/炸板池/强势池 已获取并落盘")

    # theme_cache.json：只补齐"当日出现的 code6"，避免无限增长
    themes_path = cache_dir / "theme_cache.json"
    theme_cache_disk = read_json(themes_path, default={})
    codes_map = (theme_cache_disk.get("codes") or {}) if isinstance(theme_cache_disk, dict) else {}
    if not isinstance(codes_map, dict):
        codes_map = {}
    today_zt = pools["ztgc"].get(actual_date) or []
    today_zb = pools["zbgc"].get(actual_date) or []
    today_dt = pools["dtgc"].get(actual_date) or []
    all_today = []
    for arr in (today_zt, today_zb, today_dt):
        if isinstance(arr, list):
            all_today.extend(arr)
    for s in all_today:
        code6 = normalize_stock_code(str(s.get("dm") or s.get("code") or ""))
        if not code6 or code6 in codes_map:
            continue
        raw_list = fetch_stock_themes(client, code6=code6)
        # 只做最轻的清洗：保留 name 字段
        names = []
        for it in raw_list:
            if not isinstance(it, dict):
                continue
            nm = str(it.get("name") or "").strip()
            if nm:
                # 清洗：剔除噪音前缀与噪音题材（与 gen_report_v4 的口径一致）
                if nm in DEFAULT_CONFIG.exclude_theme_names:
                    continue
                if nm in DEFAULT_CONFIG.noise_themes:
                    continue
                bad = False
                for pfx in DEFAULT_CONFIG.noise_prefixes:
                    if nm.startswith(pfx):
                        bad = True
                        break
                if bad:
                    continue
                if nm.startswith("A股-热门概念-"):
                    nm = nm.replace("A股-热门概念-", "")
                names.append(nm)
        # 去重保序
        seen = set()
        uniq = []
        for nm in names:
            if nm in seen:
                continue
            seen.add(nm)
            uniq.append(nm)
        codes_map[code6] = uniq
    write_json(themes_path, {"version": 1, "codes": codes_map})
    _log(f"题材缓存已更新 (共 {len(codes_map)} 只股票)")

    # theme_trend_cache.json：主线题材近 5 日持续性（只用已缓存的 code2themes，不额外请求）
    theme_trend_path = cache_dir / "theme_trend_cache.json"
    trend_disk = read_json(theme_trend_path, default={})
    by_day = (trend_disk.get("by_day") or {}) if isinstance(trend_disk, dict) else {}
    if not isinstance(by_day, dict):
        by_day = {}

    def count_day_themes(day_rows: list[dict[str, Any]]) -> dict[str, int]:
        cnt: dict[str, int] = {}
        for s in day_rows or []:
            code6 = normalize_stock_code(str(s.get("dm") or s.get("code") or ""))
            if not code6:
                continue
            ths = codes_map.get(code6) or []
            if not isinstance(ths, list):
                continue
            for t in ths:
                name = str(t or "").strip()
                if not name:
                    continue
                cnt[name] = cnt.get(name, 0) + 1
        return cnt

    # 仅更新最近 5 个交易日（含当天），避免文件无限增长
    last5 = trade_days[-5:] if len(trade_days) >= 5 else trade_days
    for d in last5:
        rows = pools.get("ztgc", {}).get(d) or []
        rows = rows if isinstance(rows, list) else []
        by_day[d] = count_day_themes([x for x in rows if isinstance(x, dict)])

    # 裁剪：只保留近 7 个交易日
    by_day = {k: v for k, v in by_day.items() if k in keep}

    write_json(theme_trend_path, {"version": 1, "as_of": actual_date, "by_day": by_day})
    _log("主线趋势已计算 (近5日)")

    # index_kline_cache.json：缓存指数日K
    # - 用 history 拉更长序列（便于 MA5/MA20 等技术指标在 v3 右侧交易中使用）
    # - 仍保留占位过滤（sf=1 / a<=0 / v<=0）
    index_k_path = cache_dir / "index_kline_cache.json"
    idx_disk = read_json(index_k_path, default={})
    codes_entry = (idx_disk.get("codes") or {}) if isinstance(idx_disk, dict) else {}
    if not isinstance(codes_entry, dict):
        codes_entry = {}
    for code in ("000001.SH", "399001.SZ", "399006.SZ"):
        et = actual_date.replace("-", "")
        import datetime as _dt
        st_dt = (_dt.datetime.strptime(actual_date, "%Y-%m-%d") - _dt.timedelta(days=120)).strftime("%Y%m%d")
        items = fetch_index_history_k(client, code=code, st=st_dt, et=et)
        if not isinstance(items, list):
            items = []
        # 过滤占位
        cleaned = []
        for it in items:
            if not isinstance(it, dict):
                continue
            if int(it.get("sf", 0) or 0) == 1:
                continue
            if float(it.get("a", 0) or 0) <= 0 or float(it.get("v", 0) or 0) <= 0:
                continue
            cleaned.append(it)
        codes_entry[code] = {"as_of": actual_date, "items": cleaned[-80:]}
    write_json(index_k_path, {"version": 1, "codes": codes_entry})
    _log("指数日K已缓存 (近120日)")

    # height_trend_cache.json：近 7 日高度趋势（只缓存历史日，不缓存当天）
    # 口径对齐 gen_report_v4：main=最高板、sub=次高、gem=创业板最高（300*）
    def calc_height_trend_row(day: str, day_data: list[dict[str, Any]]) -> dict:
        data = day_data or []
        lbs = [int((s.get("lbc", 1) or 1)) for s in data if isinstance(s, dict)]
        main_max = max(lbs) if lbs else 0
        gem_data = [s for s in data if str(s.get("dm", "")).startswith("300")]
        gem_max = max((int((s.get("lbc", 1) or 1)) for s in gem_data), default=0)
        sorted_lb = sorted(set(lbs), reverse=True)
        sub_max = sorted_lb[1] if len(sorted_lb) > 1 else 0
        top_stock = max(data, key=lambda x: int((x.get("lbc", 0) or 0)), default={})
        top_name = (str(top_stock.get("mc", "") or "")[:4]).strip()
        sub_stock = next((s for s in data if int((s.get("lbc", 0) or 0)) == sub_max), {})
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

    ht_path = cache_dir / "height_trend_cache.json"
    ht_disk = read_json(ht_path, default={})
    ht_days = (ht_disk.get("days") or {}) if isinstance(ht_disk, dict) else {}
    if not isinstance(ht_days, dict):
        ht_days = {}
    for d in trade_days:
        if d == actual_date:
            continue
        day_data = pools.get("ztgc", {}).get(d) or []
        if isinstance(day_data, list):
            ht_days[d] = calc_height_trend_row(d, [x for x in day_data if isinstance(x, dict)])
    # 裁剪：只保留近 7 个交易日
    ht_days = {d: v for d, v in ht_days.items() if d in keep}
    write_json(ht_path, {"version": 1, "days": ht_days})
    _log("高度趋势已计算 (近7日)")

    # indices（实时）：仅用于 asOf 展示（HH:MM:SS）
    indices_rt, indices_asof = fetch_indices_realtime(
        client,
        codes=[("000001.SH", "上证指数"), ("399001.SZ", "深证成指"), ("399006.SZ", "创业板指")],
    )
    # indices（报告口径）：用指数日K按“收盘价 vs 前收”计算，确保与 actual_date 一致
    def _norm_k_date(t: str) -> str:
        t = (t or "").strip()
        if len(t) >= 10:
            return t[:10]
        if len(t) == 8 and t.isdigit():
            return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
        return t

    def _kline_index(code: str) -> tuple[float, float] | None:
        items = (codes_entry.get(code) or {}).get("items") or []
        if not isinstance(items, list):
            return None
        for it in items:
            if not isinstance(it, dict):
                continue
            t = _norm_k_date(str(it.get("t") or ""))
            if t == actual_date and int(it.get("sf", 0) or 0) != 1:
                c = float(it.get("c", 0) or 0)
                pc = float(it.get("pc", 0) or 0)
                return (c, pc)
        return None

    def _calc_ma(code: str, *, n: int) -> float | None:
        items = (codes_entry.get(code) or {}).get("items") or []
        if not isinstance(items, list):
            return None
        closes = []
        for it in items:
            if not isinstance(it, dict):
                continue
            t = _norm_k_date(str(it.get("t") or ""))
            if t and t <= actual_date and int(it.get("sf", 0) or 0) != 1:
                closes.append(float(it.get("c", 0) or 0))
        closes = [c for c in closes if c > 0]
        if len(closes) < n:
            return None
        seg = closes[-n:]
        return sum(seg) / float(n) if seg else None

    indices_for_report = []
    for code, name in [("000001.SH", "上证指数"), ("399001.SZ", "深证成指"), ("399006.SZ", "创业板指")]:
        r = _kline_index(code)
        if not r:
            continue
        c, pc = r
        chg = ((c - pc) / pc * 100.0) if pc else 0.0
        indices_for_report.append(
            {
                "name": name,
                "code": code,
                "val": f"{c:.2f}",
                "chg": f"{chg:+.2f}%",
                # v3 右侧交易用（技术信号）
                "price": c,
                "ma5": _calc_ma(code, n=5),
                "ma20": _calc_ma(code, n=20),
            }
        )

    # 构造 raw.pools（给 pipeline 使用）
    yest = trade_days[-2] if len(trade_days) >= 2 else ""
    raw_pools = {
        "ztgc": pools["ztgc"].get(actual_date) or [],
        "dtgc": pools["dtgc"].get(actual_date) or [],
        "zbgc": pools["zbgc"].get(actual_date) or [],
        "qsgc": pools["qsgc"].get(actual_date) or [],
        "yest_ztgc": pools["ztgc"].get(yest) or [],
        "yest_dtgc": pools["dtgc"].get(yest) or [],
        "yest_zbgc": pools["zbgc"].get(yest) or [],
        "yest_date": yest,
    }

    # market_data 初始化骨架（保证模板字段存在）
    import datetime as _dt
    gen_time = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    market_data: dict = {
        "date": actual_date,
        "dateNote": date_note,
        "meta": {
            "asOf": {"indices": indices_asof, "pools": gen_time[11:19], "themes": gen_time[11:19]},
            "version": "1.0",
            "generatedAt": gen_time,
        },
        "indices": indices_for_report or [
            {
                "name": i.get("name", ""),
                "code": i.get("code", ""),
                "val": _fmt_index_val(i.get("val", "")),
                "chg": _fmt_index_pct(i.get("chg", "")),
                "cje": i.get("cje", 0),
            }
            for i in (indices_rt or [])
            if isinstance(i, dict) and i.get("name")
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
        "actionGuideV2": {"confirm": [], "retreat": []},
        "summary3": {},
        "learningNotes": {},
        "leaders": [],
        "ztgc": [],
        "zt_code_themes": {},
        "features": {},
        "raw": {},
    }

    market_data["raw"] = {
        "pools": raw_pools,
        "themes": {"code2themes": codes_map},
        "index_klines": {"codes": codes_entry},
        "indices_realtime": {"as_of": indices_asof, "items": indices_rt or []},
        "theme_trend_cache": {"as_of": actual_date, "by_day": by_day},
    }

    # === v3 增强：批量个股实时行情（让 v3 输出更“厚”） ===
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
        # 去重 + 限制长度（控制成本与响应时间）
        uniq = []
        seen = set()
        for c6 in codes:
            if c6 in seen:
                continue
            seen.add(c6)
            uniq.append(c6)
        uniq = uniq[:180]
        # 分批（避免 URL 过长/接口限制）
        quotes_map: dict[str, Any] = {}
        # ssjy_more 单次可承载的 codes 数量较小（实测 10 以内较稳）
        step = 10
        for i in range(0, len(uniq), step):
            batch = uniq[i : i + step]
            if not batch:
                continue
            quotes_list = fetch_stocks_realtime(client, ",".join(batch)) if batch else []
            if isinstance(quotes_list, list):
                for it in quotes_list:
                    if not isinstance(it, dict):
                        continue
                    c6 = normalize_stock_code(str(it.get("dm") or it.get("code") or it.get("symbol") or ""))
                    if c6:
                        quotes_map[c6] = it
        market_data["raw"]["quotes"] = {"as_of": indices_asof, "items": quotes_map, "count": len(quotes_map)}
        # meta 标记：有实时行情增强
        meta = market_data.get("meta") if isinstance(market_data.get("meta"), dict) else {}
        if not isinstance(meta, dict):
            meta = {}
        meta.setdefault("asOf", {})
        if isinstance(meta.get("asOf"), dict):
            meta["asOf"]["quotes"] = indices_asof
        market_data["meta"] = meta
        _log(f"个股实时行情已获取 ({len(quotes_map)} 只)")
    except Exception:
        pass

    # features：最小可用版
    mood_inputs = build_mood_inputs(pools=raw_pools, quotes=quotes_map)
    market_data["features"]["mood_inputs"] = mood_inputs
    market_data["features"]["chart_palette"] = default_chart_palette()

    # 写 market_data 缓存（供 rebuild/partial 使用）
    date_compact = actual_date.replace("-", "")
    market_path = cache_dir / f"market_data-{date_compact}.json"
    write_json(market_path, market_data)
    _log(f"market_data 缓存已写入: {market_path.name}")

    # 离线重建（pipeline）并渲染 tab-v1
    _log("开始离线重建 pipeline...")
    rc = run_rebuild(actual_date, allow_network=True)

    # 同步生成盯盘快照：每次 fetch 都追加一条盘中切片 + 发布 latest_intraday*.json
    # 注意：run_rebuild 会将完整 market_data（含 volume/plateRankTop10/mood_inputs）写回缓存文件
    # 快照构建需从缓存文件重新读取，确保拿到 rebuild 后的完整数据
    try:
        import datetime as _dt
        from daily_review.watch_runtime import (
            _purge_previous_day_slices,
            _purge_previous_day_published,
            append_intraday_slice,
            publish_runtime_files,
        )
        # 从 rebuild 后的缓存重新读取完整 market_data
        rebuilt_data = json.loads(market_path.read_text(encoding="utf-8")) if market_path.exists() else market_data
        rebuilt_mi = (rebuilt_data.get("features") or {}).get("mood_inputs") or mood_inputs
        # 跨日清理：确保只保留当日数据（用当前北京时间日期，而非数据日期）
        now_bj_date = _dt.datetime.now(
            _dt.timezone(_dt.timedelta(hours=8))
        ).strftime("%Y-%m-%d")
        _purge_previous_day_slices(root=root, keep_date10=now_bj_date)
        _purge_previous_day_published(root=root, keep_date10=now_bj_date)
        now_bj = _dt.datetime.now(
            _dt.timezone(_dt.timedelta(hours=8))
        ).strftime("%Y-%m-%d %H:%M:%S")
        # lianban_count：优先用 rebuild 注入值，兜底从 lb_2+lb_3+lb_4p+lb_5p 计算
        lb_cnt = int(rebuilt_mi.get("lianban_count", 0) or 0)
        if not lb_cnt:
            lb_cnt = (
                int(rebuilt_mi.get("lb_2", 0) or 0)
                + int(rebuilt_mi.get("lb_3", 0) or 0)
                + int(rebuilt_mi.get("lb_4p", 0) or 0)
                + int(rebuilt_mi.get("lb_5p", 0) or 0)
            )
        max_lb = int(rebuilt_mi.get("max_lb", 0) or 0)
        # volume/amount：从 rebuild 后的 market_data 获取
        vol_total = rebuilt_data.get("volume", {}).get("total", "") or ""
        # concepts：优先 plateRankTop10，其次 conceptFundFlowTop
        concepts_src = (
            rebuilt_data.get("plateRankTop10")
            or rebuilt_data.get("conceptFundFlowTop")
            or []
        )
        watch_snap = {
            "source": market_data.get("meta", {}).get("source", {}).get("indices", "fetch"),
            "ts_bj": now_bj,
            "date": now_bj_date,
            "market": {
                "zt": int(rebuilt_mi.get("zt_count", 0) or 0),
                "dt": int(rebuilt_mi.get("dt_count", 0) or 0),
                "zab": int(rebuilt_mi.get("zb_count", 0) or 0),
                "zab_rate": float(rebuilt_mi.get("zb_rate", 0) or 0.0),
                "lianban": lb_cnt,
                "max_lianban": max_lb,
                "amount": str(vol_total),
            },
            "concepts": [
                {"name": c.get("name"), "lead": c.get("lead"), "chg_pct": c.get("chg_pct")}
                for c in concepts_src[:5]
                if isinstance(c, dict) and c.get("name")
            ],
            "alerts": [],
        }
        slices_payload = append_intraday_slice(root=root, snapshot=watch_snap)
        publish_runtime_files(root=root, latest_snapshot=watch_snap, slices_payload=slices_payload)
        print("✅ 盯盘快照已追加并发布")
    except Exception as e:
        print(f"⚠️ 盯盘快照生成失败（不影响主流程）: {e}")

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
    trade_days = get_trading_days_from_index_k(client, date=actual_date, n=3) or [actual_date]
    if actual_date not in trade_days:
        trade_days = trade_days + [actual_date]
    trade_days = sorted(set(trade_days))[-3:]

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
        pools[pn][actual_date] = fetch_pool(client, pool_name=pn, date=actual_date)
    # 裁剪：只保留近 3 个交易日（watch 模式 trade_days 最多 3 天）
    watch_keep = set(trade_days)
    for pn in ("ztgc", "dtgc", "zbgc", "qsgc"):
        pools[pn] = {d: v for d, v in (pools.get(pn) or {}).items() if d in watch_keep}
    write_json(pools_path, {"version": 1, "pools": pools})
    _log("盘中数据池已获取")

    # theme_cache：只处理当日涨停股
    themes_path = cache_dir / "theme_cache.json"
    theme_cache_disk = read_json(themes_path, default={})
    codes_map = (theme_cache_disk.get("codes") or {}) if isinstance(theme_cache_disk, dict) else {}
    today_zt = pools["ztgc"].get(actual_date) or []
    today_zb = pools["zbgc"].get(actual_date) or []
    today_dt = pools["dtgc"].get(actual_date) or []
    all_today = []
    for arr in (today_zt, today_zb, today_dt):
        if isinstance(arr, list):
            all_today.extend(arr)
    for s in all_today:
        code6 = normalize_stock_code(str(s.get("dm") or s.get("code") or ""))
        if not code6 or code6 in codes_map:
            continue
        raw_list = fetch_stock_themes(client, code6=code6)
        names = []
        for it in raw_list:
            if not isinstance(it, dict):
                continue
            nm = str(it.get("name") or "").strip()
            if not nm:
                continue
            if nm in DEFAULT_CONFIG.exclude_theme_names:
                continue
            if nm in DEFAULT_CONFIG.noise_themes:
                continue
            bad = False
            for pfx in DEFAULT_CONFIG.noise_prefixes:
                if nm.startswith(pfx):
                    bad = True
                    break
            if bad:
                continue
            if nm.startswith("A股-热门概念-"):
                nm = nm.replace("A股-热门概念-", "")
            names.append(nm)
        seen = set()
        uniq = []
        for nm in names:
            if nm in seen:
                continue
            seen.add(nm)
            uniq.append(nm)
        codes_map[code6] = uniq
    write_json(themes_path, {"version": 1, "codes": codes_map})

    # 构造 market_data 骨架（标记为 intraday 模式）
    gen_time = now.strftime("%Y-%m-%d %H:%M:%S")

    raw_pools = {
        "ztgc": pools["ztgc"].get(actual_date) or [],
        "dtgc": pools["dtgc"].get(actual_date) or [],
        "zbgc": pools["zbgc"].get(actual_date) or [],
        "qsgc": pools["qsgc"].get(actual_date) or [],
        "yest_ztgc": [],
        "yest_dtgc": [],
        "yest_zbgc": [],
        "yest_date": "",
    }

    market_data: dict = {
        "date": actual_date,
        "dateNote": f"{date_note or ''} 【盘中快照 {now_str}】",
        "meta": {
            "asOf": {"indices": now_str, "pools": now_str, "themes": now_str},
            "version": "1.0-intraday",
            "mode": "intraday",
            "generatedAt": gen_time,
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
        "actionGuideV2": {"confirm": [], "retreat": []},
        "summary3": {},
        "learningNotes": {},
        "leaders": [],
        "ztgc": [],
        "zt_code_themes": {},
        "features": {},
        "raw": {},
    }

    market_data["raw"] = {
        "pools": raw_pools,
        "themes": {"code2themes": codes_map},
        "index_klines": {"codes": {}},
        "theme_trend_cache": {"as_of": actual_date, "by_day": {}},
    }

    mood_inputs = build_mood_inputs(pools=raw_pools)
    market_data["features"]["mood_inputs"] = mood_inputs
    market_data["features"]["chart_palette"] = default_chart_palette()

    # 写缓存
    date_compact = actual_date.replace("-", "")
    market_path = cache_dir / f"market_data-{date_compact}-intraday.json"
    write_json(market_path, market_data)
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
        _append_intraday_snapshot(root=root, date=_now10_snap, market_data=snap_md)
        _log("快照记录已追加")
    except Exception:
        pass

    # 第二次：把"半小时快照列表"注入页面后再渲染一次（离线，成本很低）
    _log("pipeline 二次重建（含快照注入）...")
    run_rebuild(actual_date, suffix="intraday", source_market_path=market_path, allow_network=True)

    # 在输出 HTML 中注入盘中快照标记
    out_dir = root / "html"
    out_path = out_dir / f"复盘日记-{date_compact}-intra.html"
    if out_path.exists():
        content = out_path.read_text(encoding="utf-8")
        content = content.replace(
            "</title>",
            f"</title><!-- INTRADAY_SNAPSHOT:{now_str} -->",
        )
        out_path.write_text(content, encoding="utf-8")
        print(f"✅ 盘中快照输出: {out_path}")

    return 0


def _normalize_date(date: str) -> str:
    """统一日期格式：'20260508' → '2026-05-08'，已经是 YYYY-MM-DD 则原样返回。"""
    d = str(date or "").strip().replace("/", "-")
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return d


def run_rebuild(
    date: str,
    modules: list[str] | None = None,
    suffix: str = "",
    source_market_path: Path | None = None,
    allow_network: bool = False,
) -> int:
    """
    离线重建（不请求接口）：
    - 从 cache/market_data-YYYYMMDD.json 读取
    - 注入 raw（pools/theme/index_kline/height_trend 等缓存）
    - 跑 v2 pipeline（modules=None 表示全量重建）
    - 写回 market_data 缓存 + 渲染 tab-v1 HTML
    """
    root = _workspace_root()
    cache_dir = root / "cache"
    date_compact = date.replace("-", "")

    # 如果指定了 source_market_path（盘中快照模式），直接用它
    if source_market_path and source_market_path.exists():
        market_path = source_market_path
    else:
        market_path = cache_dir / f"market_data-{date_compact}.json"

    if not market_path.exists():
        raise FileNotFoundError(f"找不到缓存 marketData：{market_path}（请先跑一次 ./qr.sh fetch {date}）")

    market_data = json.loads(market_path.read_text(encoding="utf-8"))
    _log(f"缓存已加载: {market_path.name}")

    ctx = Context.from_market_data(market_data)

    # 注入 raw：复用 partial 的离线缓存注入逻辑
    pools_today = _load_pools_for_date(root, date)
    yest = _prev_trade_date(pools_today.get("all_dates") or [], date)
    pools_yest = _load_pools_for_date(root, yest) if yest else {"ztgc": [], "dtgc": [], "zbgc": []}
    ctx.raw.setdefault("pools", {})
    ctx.raw["pools"].update(
        {
            "ztgc": pools_today.get("ztgc") or [],
            "dtgc": pools_today.get("dtgc") or [],
            "zbgc": pools_today.get("zbgc") or [],
            "qsgc": pools_today.get("qsgc") or [],
            "yest_ztgc": pools_yest.get("ztgc") or [],
            "yest_dtgc": pools_yest.get("dtgc") or [],
            "yest_zbgc": pools_yest.get("zbgc") or [],
            "yest_date": yest or "",
        }
    )
    # 注入近7天涨停池（离线）：供“近7天2连板题材聚合”等跨日模块使用
    ctx.raw["pools"]["ztgc_by_day"] = _load_ztgc_by_day_window(root=root, date=date, n=7)
    ctx.raw.setdefault("themes", {})
    ctx.raw["themes"]["code2themes"] = _load_theme_cache(root)
    ctx.raw["index_klines"] = _load_index_klines_cache(root)
    ctx.raw["height_trend_cache"] = _load_height_trend_cache(root)
    ctx.raw["theme_trend_cache"] = _load_theme_trend_cache(root)
    _log("离线数据已注入 (pools/themes/klines/height_trend/theme_trend)")

    # 修复：三大指数涨幅在离线重建中可能残留为 +0.00%
    # 这里用指数日K缓存按“报告日收盘价 vs 前收”重算，确保与报告日期一致。
    try:
        codes = ((ctx.raw.get("index_klines") or {}).get("codes") or {}) if isinstance(ctx.raw, dict) else {}
        if isinstance(codes, dict) and date:
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
                        pc = float(it.get("pc", 0) or 0)  # 前收
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
                r = _pick_exact(code)
                if not r:
                    continue
                c, pc = r
                chg = ((c - pc) / pc * 100.0) if pc else 0.0
                if abs(chg) < 0.005:
                    chg = 0.0
                inds.append(
                    {
                        "name": name,
                        "code": code,
                        "val": f"{c:.2f}",
                        "chg": f"{chg:+.2f}%",
                        "price": c,
                        "ma5": _calc_ma(code, n=5),
                        "ma20": _calc_ma(code, n=20),
                    }
                )
            if inds:
                ctx.market_data["indices"] = inds
                meta = ctx.market_data.get("meta") if isinstance(ctx.market_data.get("meta"), dict) else {}
                if isinstance(meta, dict):
                    asof = meta.get("asOf") if isinstance(meta.get("asOf"), dict) else {}
                    if isinstance(asof, dict):
                        asof["indices"] = "收盘"
                        meta["asOf"] = asof
                        ctx.market_data["meta"] = meta
    except Exception:
        pass

    # === 关键：离线重建时同步重算 features（避免缓存字段缺失导致页面“—/0”）===
    # features 应由 raw 推导，不能长期依赖旧 cache/market_data 里残留的 features。
    try:
        pools_for_feat = ctx.raw.get("pools") or {}
        quotes_items = (((ctx.raw.get("quotes") or {}) if isinstance(ctx.raw, dict) else {}).get("items") or {})
        mood_inputs = build_mood_inputs(pools=pools_for_feat, quotes=quotes_items)
        feats = ctx.market_data.get("features") if isinstance(ctx.market_data.get("features"), dict) else {}
        if not isinstance(feats, dict):
            feats = {}
        feats["mood_inputs"] = mood_inputs
        feats.setdefault("chart_palette", default_chart_palette())
        ctx.market_data["features"] = feats
        ctx.features = feats  # runner 使用 ctx.features 读取 features.*
    except Exception:
        pass

    _log("features 已重算")

    runner = Runner(ALL_MODULES)
    runner.run(ctx, targets=(modules or None))
    market_data = ctx.market_data
    _log("pipeline 已执行")

    try:
        _apply_realtime_indices_display(market_data)
        _normalize_indices_display(market_data)
        _apply_intraday_volume_from_realtime_indices(market_data)
    except Exception:
        pass

    # === 注入盘中快照列表（供"实时盯盘"页面展示）===
    try:
        import datetime as _dt2
        _now10 = _dt2.datetime.now(_dt2.timezone(_dt2.timedelta(hours=8))).strftime("%Y-%m-%d")
        _inject_intraday_snapshots(root=root, date=date, market_data=market_data, now_date10=_now10)
        _log(f"盘中快照已注入 ({len(market_data.get('intradaySnapshots', {}).get('snapshots', []))} 条)")
    except Exception:
        pass

    # 补齐元信息：避免页面“数据更新时间”显示为 00:00:00 / 空
    try:
        import datetime as _dt

        meta = market_data.get("meta") if isinstance(market_data.get("meta"), dict) else {}
        if not isinstance(meta, dict):
            meta = {}
        asof = meta.get("asOf") if isinstance(meta.get("asOf"), dict) else {}
        if not isinstance(asof, dict):
            asof = {}

        # 生成时间：离线重建默认用当前时间（避免 '-'）
        gen_time = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        meta.setdefault("generatedAt", gen_time)

        # indices 的 asOf 若是日K占位“00:00:00”，更符合用户直觉的是“收盘”
        idx = str(asof.get("indices") or "").strip()
        if not idx or idx == "00:00:00":
            asof["indices"] = "收盘"
        # pools/themes 若缺失，用“收盘/缓存”占位，避免显示空
        if not str(asof.get("pools") or "").strip():
            asof["pools"] = "收盘"
        if not str(asof.get("themes") or "").strip():
            asof["themes"] = "收盘"
        meta["asOf"] = asof
        market_data["meta"] = meta
    except Exception:
        pass

    # 补齐“情绪周期趋势/昨日对比”所需数据（用于前端 sparkline、Δ、K线增强等）
    # - 不请求网络；只读取本地 cache/market_data-*.json
    # - 仅在字段缺失/为空时注入，避免覆盖后端已算出的更准口径
    try:
        _inject_mood_history_and_delta(root=root, date=date, market_data=market_data)
        _log("情绪历史趋势/昨日对比 已注入")
    except Exception:
        pass

    # actionAdvisor：依赖“历史趋势/昨日对比”等注入字段，故在注入后再计算，保证口径一致
    try:
        from daily_review.metrics.action_advisor import build_action_advisor

        market_data["actionAdvisor"] = build_action_advisor(market_data=market_data)
        _log("actionAdvisor 已生成")
    except Exception:
        pass

    # ztAnalysis：明日接力/观察是收盘后推演；盘中只刷新实时情绪时，沿用上一份有效收盘推演。
    preserve_zt = str(os.environ.get("PRESERVE_ZT_ANALYSIS") or "").strip().lower() in {"1", "true", "yes", "on"}
    try:
        if preserve_zt:
            preserved = _load_latest_valid_zt_analysis(root=root, current_date=date)
            if preserved:
                market_data["ztAnalysis"] = preserved
                _log(f"ztAnalysis 已保留上一份收盘推演 ({preserved.get('meta', {}).get('preservedFromDate')})")
            else:
                from daily_review.metrics.zt_analysis import build_zt_analysis

                market_data["ztAnalysis"] = build_zt_analysis(market_data=market_data)
                _log("未找到可沿用 ztAnalysis，已按当前数据重算")
        else:
            from daily_review.metrics.zt_analysis import build_zt_analysis

            market_data["ztAnalysis"] = build_zt_analysis(market_data=market_data)
            _log("ztAnalysis 已按最新环境姿态重算")
    except Exception:
        pass

    # summary3（二句话）：依赖“历史趋势/昨日对比”等注入字段，故在注入后再重算一次，保证口径一致
    try:
        from daily_review.render.render_html import build_market_overview_7d, build_sentiment_explain_dims, build_summary3

        market_data["summary3"] = build_summary3(market_data=market_data)
        market_data["marketOverview7d"] = build_market_overview_7d(market_data=market_data)
        market_data["sentimentExplainDims"] = build_sentiment_explain_dims(market_data=market_data)
        _log("summary3 / marketOverview7d / sentimentExplainDims 已生成")
    except Exception:
        pass

    # PRD v2：核心派生字段（必须可复算）
    # - sectorHeatmap（多板块情绪热力图）
    # - threeQuadrants（盘面三象限）
    try:
        _inject_prd_v2_metrics(root=root, date=date, market_data=market_data, allow_network=allow_network)
        _log("PRD v2 指标已注入 (sectorHeatmap/threeQuadrants)")
    except Exception:
        pass

    # 清理前端已不用的大字段：统一视图/compat 兼容层已下线，同时下沉 planGuide
    try:
        _prune_frontend_unused_fields(market_data)
        _log("前端冗余字段已清理")
    except Exception:
        pass

    # 渲染 tab-v1（render 阶段还会补充部分展示专用派生字段）
    template_path = root / "templates" / "report_template.html"
    out_dir = root / "html"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix_part = f"-{suffix}" if suffix else ""
    # 文件名使用北京时间更新时间，报告正文仍保留 report_date 作为内容日期
    update_date8 = _now_bj_date8()
    out_path = out_dir / f"复盘日记-{update_date8}{suffix_part}-tab-v1.html"

    render_html_template(
        template_path=template_path,
        output_path=out_path,
        market_data=market_data,
        report_date=date,
        date_note=market_data.get("dateNote", ""),
    )
    _log(f"HTML 已渲染: {out_path.name}")
    # 回写最终 market_data：确保 render 阶段补齐的展示字段也能稳定落盘
    market_path.write_text(json.dumps(market_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ rebuild 输出: {out_path}")
    return 0


def _intraday_slices_path(root: Path, date: str) -> Path:
    cache_dir = root / "cache"
    d8 = date.replace("-", "")
    return cache_dir / f"intraday_slices-{d8}.json"


def _intraday_snapshots_path(root: Path, date: str) -> Path:
    cache_dir = root / "cache"
    d8 = date.replace("-", "")
    return cache_dir / f"intraday_snapshots-{d8}.json"


def _to_num(v, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        if isinstance(v, str):
            return float(v.replace("%", "").strip())
        return float(v)
    except Exception:
        return default


def _intraday_shift_label(score: float) -> str:
    if score >= 72:
        return "走强"
    if score >= 60:
        return "修复"
    if score >= 48:
        return "分歧"
    if score >= 36:
        return "走弱"
    return "退潮"


def _normalize_intraday_snapshot(row: dict) -> dict:
    rec = dict(row or {})
    heat = _to_num(rec.get("heat"), None)
    risk = _to_num(rec.get("risk"), None)
    if heat is not None and risk is not None:
        score = int(blend_sentiment_score(heat=heat, risk=risk))
        rec["shift_score"] = score
        label = str(rec.get("shift_label") or "").strip()
        if not label or label.replace(".", "", 1).isdigit():
            rec["shift_label"] = _intraday_shift_label(score)
    return rec


def _load_intraday_snapshots(*, root: Path, date: str, now_date10: str | None = None) -> list[dict]:
    """加载盘中切片：严格按报告日期读取，避免历史页混入其他交易日快照。"""
    dates_to_try = [date]
    for d in dates_to_try:
        for p in (_intraday_slices_path(root, d), _intraday_snapshots_path(root, d)):
            if not p.exists():
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return [_normalize_intraday_snapshot(x) for x in data if isinstance(x, dict)]
                if isinstance(data, dict) and isinstance(data.get("snapshots"), list):
                    return [_normalize_intraday_snapshot(x) for x in (data.get("snapshots") or []) if isinstance(x, dict)]
            except Exception:
                continue
    return []


def _write_intraday_snapshots(*, root: Path, date: str, snapshots: list[dict], simulated: bool = False) -> None:
    """与 watch_runtime 一致：落盘为 envelope，便于线上/本地共用同一时间轴 JSON。"""
    p = _intraday_slices_path(root, date)
    env = {
        "date": date,
        "count": len(snapshots),
        "snapshots": snapshots,
        "simulated": simulated,
        "interval_min": None,
        "latest": snapshots[-1] if snapshots else None,
    }
    p.write_text(json.dumps(env, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_intraday_snapshot(*, root: Path, date: str, market_data: dict) -> None:
    """
    追加一条盘中快照（半小时级）。
    只保存“盯盘所需最小信息”，避免文件膨胀。
    """
    meta = market_data.get("meta") or {}
    gen_at = str(meta.get("generatedAt") or "").strip()
    snap_t = str(meta.get("snapshotTime") or meta.get("asOf", {}).get("pools") or "").strip()
    ts_bj = gen_at if len(gen_at) >= 19 else (f"{date} {snap_t}" if snap_t else "")
    if not ts_bj:
        return
    t_label = ts_bj[11:19] if len(ts_bj) >= 19 else (ts_bj[11:16] if len(ts_bj) >= 16 else snap_t[:8] if snap_t else "")

    mi = (market_data.get("features") or {}).get("mood_inputs") or {}
    mood = market_data.get("mood") or {}
    ms = market_data.get("moodSignals") or {}
    hm2 = market_data.get("hm2Compare") or {}
    panorama = market_data.get("panorama") or {}
    volume = market_data.get("volume") if isinstance(market_data.get("volume"), dict) else {}

    rec = {
        "time": t_label,
        "ts_bj": ts_bj,
        "date": date,
        "source": "intraday_live",
        "headline": ms.get("headline") or "",
        "heat": mood.get("heat"),
        "risk": mood.get("risk"),
        "fb": mi.get("fb_rate"),
        "jj": mi.get("jj_rate"),
        "zb": mi.get("zb_rate"),
        "dt": panorama.get("limitDown"),
        "bf": mi.get("bf_count"),
        "max_lb": mi.get("max_lb"),
        "amount": volume.get("total") or "",
        "loss": mi.get("loss"),
        "hm2": hm2.get("score"),
        "pos": ms.get("pos") or [],
        "riskSignals": ms.get("risk") or [],
    }
    shift_score = int(_to_num(mood.get("score"), 0))
    rec["shift_score"] = shift_score
    rec["shift_label"] = _intraday_shift_label(shift_score)

    snaps = _load_intraday_snapshots(root=root, date=date)
    # 去重：同一 ts_bj 只保留最新一条（与 watch_runtime 节点键一致）
    snaps = [s for s in snaps if str(s.get("ts_bj") or "") != ts_bj]
    snaps.append(rec)
    snaps.sort(key=lambda x: str(x.get("ts_bj") or f"{date} {x.get('time') or '00:00:00'}"))
    snaps = snaps[-96:]
    _write_intraday_snapshots(root=root, date=date, snapshots=snaps, simulated=False)



def _inject_intraday_snapshots(*, root: Path, date: str, market_data: dict, now_date10: str | None = None) -> None:
    market_data.pop("intradaySnapshots", None)
    snaps = _load_intraday_snapshots(root=root, date=date, now_date10=now_date10)
    if not snaps:
        return
    # 过滤掉残留的模拟数据
    snaps = [s for s in snaps if isinstance(s, dict) and str(s.get("source") or "") != "simulated_close"]
    if not snaps:
        return
    market_data["intradaySnapshots"] = {
        "date": snaps[0].get("date") or date,
        "count": len(snaps),
        "snapshots": snaps,
        "simulated": False,
        "interval_min": None,
        "latest": snaps[-1] if snaps else None,
    }


def _inject_mood_history_and_delta(*, root: Path, date: str, market_data: dict) -> None:
    """
    离线增强（UI/图表需要）：
    1) features.mood_inputs.hist_* / trend_*：用于 sparkline 与情绪K线
    2) prev / delta：用于“vs昨日”对比箭头与 Δ badge
    """

    cache_dir = root / "cache"
    date8 = date.replace("-", "")
    if len(date8) != 8:
        return

    # 收集 <= date 的缓存文件（按日期排序）
    items: list[tuple[str, Path]] = []
    for fp in cache_dir.glob("market_data-*.json"):
        stem = fp.stem  # market_data-YYYYMMDD
        if not stem.startswith("market_data-"):
            continue
        d8 = stem.replace("market_data-", "")
        if len(d8) != 8 or not d8.isdigit():
            continue
        if d8 <= date8:
            items.append((d8, fp))
    items.sort(key=lambda x: x[0])
    if not items:
        return

    # ===== 1) hist_* / trend_* =====
    feats = market_data.setdefault("features", {})
    mi = feats.setdefault("mood_inputs", {})
    hist_days = mi.get("hist_days")

    # 先注入当天可直接计算的指标，供后续 delta / 维度解释使用
    try:
        mp = market_data.get("marketPanorama") or {}
        kpis = mp.get("kpis") or {}
        mi.setdefault("lianban_count", int(kpis.get("link_board", 0) or 0))
    except Exception:
        pass
    try:
        raw = market_data.get("raw") or {}
        quotes = raw.get("quotes") or {}
        items0 = quotes.get("items") or {}
        if isinstance(items0, dict):
            up0 = 0
            down0 = 0
            for _, it in items0.items():
                if not isinstance(it, dict):
                    continue
                pc = it.get("pc")
                try:
                    pc = float(pc)
                except Exception:
                    continue
                if pc > 0:
                    up0 += 1
                elif pc < 0:
                    down0 += 1
            mi.setdefault("up_count", up0)
            mi.setdefault("down_count", down0)
    except Exception:
        pass

    need_hist = not (isinstance(hist_days, list) and len(hist_days) >= 2)
    if need_hist:
        try:
            # 默认近 7 日：用于“情绪温度（解释版）”五线趋势（涨停/连板/跌停/封板率/晋级率）
            hist_n = int(os.getenv("MOOD_HIST_DAYS", "7") or "7")
        except Exception:
            hist_n = 5
        hist_n = max(3, min(hist_n, 10))
        slice_items = items[-hist_n:]

        rows = []
        for d8, fp in slice_items:
            try:
                snap = json.loads(fp.read_text(encoding="utf-8"))
                s_feats = snap.get("features") or {}
                s_mi = s_feats.get("mood_inputs") or {}
                # 兜底：max_lb 优先用 mood_inputs，其次用 ladder 最高 badge 数字
                max_lb = int(s_mi.get("max_lb", 0) or 0)
                if not max_lb:
                    lbs = []
                    for it in (snap.get("ladder") or []):
                        try:
                            lbs.append(int(str(it.get("badge", "")).replace("板", "").replace("板+", "")[:2] or 0))
                        except Exception:
                            pass
                    max_lb = max(lbs) if lbs else 0

                def _to_num(v, d=0.0):
                    try:
                        if v is None:
                            return d
                        if isinstance(v, str):
                            v = v.replace("%", "").strip()
                        return float(v)
                    except Exception:
                        return d

                def _breadth_from_snap(snap_dict: dict) -> tuple[int, int]:
                    """
                    纯函数：从 raw.quotes.items 计算上涨/下跌家数。
                    """
                    raw = snap_dict.get("raw") or {}
                    quotes = raw.get("quotes") or {}
                    items = quotes.get("items") or {}
                    if not isinstance(items, dict):
                        return 0, 0
                    up = 0
                    down = 0
                    for _, it in items.items():
                        if not isinstance(it, dict):
                            continue
                        pc = it.get("pc")
                        try:
                            pc = float(pc)
                        except Exception:
                            continue
                        if pc > 0:
                            up += 1
                        elif pc < 0:
                            down += 1
                    return up, down

                up_cnt, down_cnt = _breadth_from_snap(snap)
                # 连板家数：优先用 marketPanorama.kpis.link_board，其次用 lb_2/lb_3/lb_4p/lb_5p 兜底
                mp = snap.get("marketPanorama") or {}
                kpis = mp.get("kpis") or {}
                lianban = int(_to_num(kpis.get("link_board", 0), 0))
                if not lianban:
                    lianban = int(
                        _to_num(s_mi.get("lb_2", 0), 0)
                        + _to_num(s_mi.get("lb_3", 0), 0)
                        + _to_num(s_mi.get("lb_4p", 0), 0)
                        + _to_num(s_mi.get("lb_5p", 0), 0)
                    )

                rows.append(
                    {
                        "date": f"{d8[0:4]}-{d8[4:6]}-{d8[6:8]}",
                        "max_lb": max_lb,
                        "fb_rate": _to_num(s_mi.get("fb_rate", 0), 0),
                        "jj_rate": _to_num(s_mi.get("jj_rate_adj", s_mi.get("jj_rate", 0)), 0),
                        "broken_lb_rate": _to_num(s_mi.get("broken_lb_rate_adj", s_mi.get("broken_lb_rate", 0)), 0),
                        "zb_rate": _to_num(s_mi.get("zb_rate", 0), 0),
                        "zt_early_ratio": _to_num(s_mi.get("zt_early_ratio", 0), 0),
                        "loss": _to_num(s_mi.get("loss", _to_num(s_mi.get("bf_count", 0), 0) + _to_num(s_mi.get("dt_count", 0), 0)), 0),
                        "zt": int(_to_num((snap.get("panorama") or {}).get("limitUp", 0), 0)),
                        "dt": int(_to_num((snap.get("panorama") or {}).get("limitDown", 0), 0)),
                        "lianban": lianban,
                        "up": up_cnt,
                        "down": down_cnt,
                    }
                )
            except Exception:
                continue

        if len(rows) >= 2:
            first, last = rows[0], rows[-1]
            mi["hist_days"] = [r["date"] for r in rows]
            mi["hist_max_lb"] = [r["max_lb"] for r in rows]
            mi["hist_fb_rate"] = [round(r["fb_rate"], 1) for r in rows]
            mi["hist_jj_rate"] = [round(r["jj_rate"], 1) for r in rows]
            mi["hist_broken_lb_rate"] = [round(r["broken_lb_rate"], 1) for r in rows]
            mi["hist_zb_rate"] = [round(r["zb_rate"], 1) for r in rows]
            mi["hist_zt_early_ratio"] = [round(r["zt_early_ratio"], 1) for r in rows]
            mi["hist_loss"] = [round(r["loss"], 1) for r in rows]
            mi["hist_zt"] = [int(r.get("zt", 0)) for r in rows]
            mi["hist_dt"] = [int(r.get("dt", 0)) for r in rows]
            mi["hist_lianban"] = [int(r.get("lianban", 0)) for r in rows]
            mi["hist_up"] = [int(r.get("up", 0)) for r in rows]
            mi["hist_down"] = [int(r.get("down", 0)) for r in rows]
            mi["hist_zt_dt_spread"] = [int(r.get("zt", 0)) - int(r.get("dt", 0)) for r in rows]
            mi["trend_max_lb"] = round(float(last["max_lb"]) - float(first["max_lb"]), 2)
            mi["trend_fb_rate"] = round(float(last["fb_rate"]) - float(first["fb_rate"]), 2)
            mi["trend_jj_rate"] = round(float(last["jj_rate"]) - float(first["jj_rate"]), 2)
            mi["trend_broken_lb_rate"] = round(float(last["broken_lb_rate"]) - float(first["broken_lb_rate"]), 2)
            mi["trend_zb_rate"] = round(float(last["zb_rate"]) - float(first["zb_rate"]), 2)
            mi["trend_zt_early_ratio"] = round(float(last["zt_early_ratio"]) - float(first["zt_early_ratio"]), 2)
            mi["trend_loss"] = round(float(last["loss"]) - float(first["loss"]), 2)
            mi["trend_zt"] = int(last.get("zt", 0)) - int(first.get("zt", 0))
            mi["trend_dt"] = int(last.get("dt", 0)) - int(first.get("dt", 0))
            mi["trend_lianban"] = int(last.get("lianban", 0)) - int(first.get("lianban", 0))
            mi["trend_up"] = int(last.get("up", 0)) - int(first.get("up", 0))
            mi["trend_down"] = int(last.get("down", 0)) - int(first.get("down", 0))

    # ===== 2) prev / delta =====
    if len(items) < 2:
        return

    prev_fp = items[-2][1]
    try:
        prev_data = json.loads(prev_fp.read_text(encoding="utf-8"))
    except Exception:
        return

    market_data["prev"] = {
        "date": prev_data.get("date", ""),
        "panorama": prev_data.get("panorama") or {},
        "mood": prev_data.get("mood") or {},
        "moodStage": prev_data.get("moodStage") or {},
        "volume": prev_data.get("volume") or {},
        "features": (prev_data.get("features") or {}),
    }

    def _num(v, d=0.0):
        try:
            if v is None:
                return d
            if isinstance(v, str):
                v = v.replace("%", "").replace("亿", "").strip()
            return float(v)
        except Exception:
            return d

    cur_pan = market_data.get("panorama") or {}
    prv_pan = (prev_data.get("panorama") or {}) if isinstance(prev_data, dict) else {}

    cur_feats = market_data.get("features") or {}
    cur_mi = cur_feats.get("mood_inputs") or {}
    prv_feats = (prev_data.get("features") or {}) if isinstance(prev_data, dict) else {}
    prv_mi = (prv_feats.get("mood_inputs") or {}) if isinstance(prv_feats, dict) else {}

    # 用于 UI 的 Δ（单位由前端决定：pp/只）
    market_data["delta"] = {
        "zt": int(_num(cur_pan.get("limitUp"), 0) - _num(prv_pan.get("limitUp"), 0)),
        "zb": int(_num(cur_pan.get("broken"), 0) - _num(prv_pan.get("broken"), 0)),
        "dt": int(_num(cur_pan.get("limitDown"), 0) - _num(prv_pan.get("limitDown"), 0)),
        "fb_rate": round(_num(cur_mi.get("fb_rate"), 0) - _num(prv_mi.get("fb_rate"), 0), 2),
        "jj_rate": round(_num(cur_mi.get("jj_rate_adj", cur_mi.get("jj_rate")), 0) - _num(prv_mi.get("jj_rate_adj", prv_mi.get("jj_rate")), 0), 2),
        "zb_rate": round(_num(cur_mi.get("zb_rate"), 0) - _num(prv_mi.get("zb_rate"), 0), 2),
        "max_lb": round(_num(cur_mi.get("max_lb"), 0) - _num(prv_mi.get("max_lb"), 0), 2),
        "bf_count": round(_num(cur_mi.get("bf_count"), 0) - _num(prv_mi.get("bf_count"), 0), 2),
        "lianban": int(_num(cur_mi.get("lianban_count"), 0) - _num(prv_mi.get("lianban_count"), 0)),
        "up": int(_num(cur_mi.get("up_count"), 0) - _num(prv_mi.get("up_count"), 0)),
        "down": int(_num(cur_mi.get("down_count"), 0) - _num(prv_mi.get("down_count"), 0)),
        "heat": round(_num((market_data.get("mood") or {}).get("heat"), 0) - _num((prev_data.get("mood") or {}).get("heat"), 0), 2),
        "risk": round(_num((market_data.get("mood") or {}).get("risk"), 0) - _num((prev_data.get("mood") or {}).get("risk"), 0), 2),
    }


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

    def _net_big_order_flow_yi(client: Any, *, date8: str, code6: str) -> float | None:
        """
        使用资金流向接口：特大单+大单 主买 - 主卖（单位：亿）。

        端点（同 divergenceEngine 使用口径）：
        hsstock/history/transaction/{code}.{SZ|SH}/{token}?st=YYYYMMDD&et=YYYYMMDD&lt=1
        """
        code = _code_with_market(code6)
        if not code:
            return None
        url = f"{client.base_url}/hsstock/history/transaction/{code}/{client.token}?st={date8}&et={date8}&lt=1"
        data = client.get_json(url)
        if not isinstance(data, list) or not data:
            return None
        it = data[-1] if isinstance(data[-1], dict) else {}
        buy = _to_num(it.get("zmbtdcje"), 0) + _to_num(it.get("zmbddcje"), 0)
        sell = _to_num(it.get("zmstdcje"), 0) + _to_num(it.get("zmsddcje"), 0)
        return round((buy - sell) / 1e8, 2)  # 元 -> 亿

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

        zt_by_day = _load_ztgc_by_day_window(root=root, date=date, n=7)
        if not zt_by_day:
            return
        code2themes = _load_theme_cache(root)
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

        # 3) 批量补齐缺失的 (day, code) 资金流向
        for day8, c6 in sorted(list(pairs)):
            day_map = by_day.get(day8) or {}
            if not isinstance(day_map, dict):
                day_map = {}
            if c6 in day_map:
                continue
            v = _net_big_order_flow_yi(client, date8=day8, code6=c6)
            if v is None:
                continue
            day_map[c6] = v
            by_day[day8] = day_map

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

    # 4) divergenceEngine（分歧与承接）— 资金维度需精确：调用资金流向接口（样本口径）
    if not isinstance(market_data.get("divergenceEngine"), dict):
        try:
            from daily_review.config import load_config_from_env
            from daily_review.http import HttpClient

            cfg = load_config_from_env()
            client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=30)
        except Exception:
            client = None
        market_data["divergenceEngine"] = build_divergence_engine(market_data, date=date, client=client)

    # 4.1) sectorFlow7d（近7天2连板题材的资金流入聚合）— 需要 token 才能精确计算
    try:
        # divergenceEngine 已存在时，本函数可能没有初始化 client；这里独立兜底一次
        if "client" not in locals() or client is None:
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
    # - 优先读取本地缓存（离线可重建）
    # - 若缓存缺失且 report_date=北京时间今天，则允许用 AkShare 在线补齐（不依赖 BIYING_TOKEN）
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

        # 缓存中无精确数据 → 在线补齐（AkShare，不需要 token）
        if allow_network and not by_day.get(date8):
            try:
                _log("概念资金流缓存无精确数据，在线抓取...")
                rows = _fetch_concept_fund_flow_top(topn=60)
                if rows:
                    by_day[date8] = rows
                    keep8 = {d.replace("-", "") for d in trade_days}
                    by_day = {k: v for k, v in by_day.items() if k in keep8}
                    cache["by_day"] = by_day
                    _write_concept_fund_flow_cache(root=root, data=cache)
            except Exception:
                pass

        if isinstance(rows, list) and rows:
            market_data["conceptFundFlowTop"] = rows[:20]
            meta = market_data.get("meta") if isinstance(market_data.get("meta"), dict) else {}
            if isinstance(meta, dict):
                meta.setdefault("asOf", {})
                if isinstance(meta.get("asOf"), dict):
                    meta["asOf"]["concept_fund_flow"] = meta.get("asOf", {}).get("pools", "")
                market_data["meta"] = meta
    except Exception:
        pass

    # 5) highPositionRisk（高位风险预警）— 未触发也输出结构化结果
    if not isinstance(market_data.get("highPositionRisk"), dict):
        try:
            from daily_review.config import load_config_from_env
            from daily_review.http import HttpClient

            cfg = load_config_from_env()
            hp_client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=30)
        except Exception:
            hp_client = None
        market_data["highPositionRisk"] = build_high_position_risk(market_data, date=date, client=hp_client, trigger_lb=4)

    # 6) structureV2（结构拆解 v2：3结论卡 + 证据链）
    if not isinstance(market_data.get("structureV2"), dict):
        market_data["structureV2"] = build_structure_v2(market_data, date=date)

    # 7) actionSheet（操作单：具体买卖条件，替代泛泛的行动指南）
    if not isinstance(market_data.get("actionSheet"), dict):
        market_data["actionSheet"] = build_action_sheet(market_data)


def _load_pools_for_date(root: Path, date: str) -> dict:
    """
    读取本地 cache/pools_cache.json，返回 {ztgc, dtgc, zbgc}。
    """
    cache_path = root / "cache" / "pools_cache.json"
    if not cache_path.exists():
        return {"ztgc": [], "dtgc": [], "zbgc": []}
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    pools = data.get("pools") or {}
    return {
        "ztgc": ((pools.get("ztgc") or {}).get(date)) or [],
        "dtgc": ((pools.get("dtgc") or {}).get(date)) or [],
        "zbgc": ((pools.get("zbgc") or {}).get(date)) or [],
        "qsgc": ((pools.get("qsgc") or {}).get(date)) or [],
        "all_dates": sorted(set((pools.get("ztgc") or {}).keys()) | set((pools.get("dtgc") or {}).keys()) | set((pools.get("zbgc") or {}).keys())),
    }


def _load_ztgc_by_day_window(*, root: Path, date: str, n: int = 7) -> dict[str, list[dict]]:
    """
    读取本地 cache/pools_cache.json，提取「<= date 的最近 n 个交易日」涨停池（ztgc）明细。

    设计目的：
    - 支持“近7天 2连板去重汇总/按题材聚合”等需要跨日统计的模块
    - 不做任何网络请求（完全离线）

    返回：
    - { "YYYY-MM-DD": [ {dm, mc, lbc, ...}, ... ], ... }
    """
    try:
        cache_path = root / "cache" / "pools_cache.json"
        if not cache_path.exists():
            return {}
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        pools = data.get("pools") or {}
        zt_by_day = pools.get("ztgc") or {}
        if not isinstance(zt_by_day, dict):
            return {}

        # 仅取 <= date 的最近 n 天（日期字符串本身可字典序排序）
        days = sorted([d for d in zt_by_day.keys() if isinstance(d, str) and d <= date])
        days = days[-max(1, int(n or 7)) :]
        out: dict[str, list[dict]] = {}
        for d in days:
            rows = zt_by_day.get(d) or []
            out[d] = [x for x in rows if isinstance(x, dict)] if isinstance(rows, list) else []
        return out
    except Exception:
        return {}

def _load_theme_cache(root: Path) -> dict:
    """
    读取本地 cache/theme_cache.json，返回 {code6 -> [themes]} 映射。
    """
    p = root / "cache" / "theme_cache.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return (data.get("codes") or {}) if isinstance(data, dict) else {}
    except Exception:
        return {}

def _load_index_klines_cache(root: Path) -> dict:
    """
    读取本地 cache/index_kline_cache.json（指数日K缓存）。
    """
    p = root / "cache" / "index_kline_cache.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_height_trend_cache(root: Path) -> dict:
    """
    读取本地 cache/height_trend_cache.json（高度趋势缓存）。
    """
    p = root / "cache" / "height_trend_cache.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _load_theme_trend_cache(root: Path) -> dict:
    """
    读取本地 cache/theme_trend_cache.json（主线题材近5日持续性缓存）。
    """
    p = root / "cache" / "theme_trend_cache.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _prev_trade_date(all_dates: list[str], date: str) -> str | None:
    """
    用缓存里已有日期序列推断上一交易日。
    """
    ds = sorted([d for d in (all_dates or []) if isinstance(d, str)])
    if date in ds:
        i = ds.index(date)
        return ds[i - 1] if i > 0 else None
    past = [d for d in ds if d < date]
    return past[-1] if past else None


def run_partial(date: str, modules: list[str]) -> int:
    """
    部分更新：读取缓存的 market_data，然后只重算指定模块，并用模板重新渲染。
    """
    root = _workspace_root()
    cache_dir = root / "cache"
    date_compact = date.replace("-", "")
    market_path = cache_dir / f"market_data-{date_compact}.json"
    if not market_path.exists():
        raise FileNotFoundError(f"找不到缓存 marketData：{market_path}（请先跑一次全量更新）")

    market_data = json.loads(market_path.read_text(encoding="utf-8"))
    _log(f"partial 缓存已加载: {market_path.name}  modules={modules}")

    # 构造 Context（兼容旧缓存：features 已在 market_data 里）
    ctx = Context.from_market_data(market_data)

    # 注入 raw.pools（支持 panorama/ladder 等模块从原始池子重算）
    pools_today = _load_pools_for_date(root, date)
    yest = _prev_trade_date(pools_today.get("all_dates") or [], date)
    pools_yest = _load_pools_for_date(root, yest) if yest else {"ztgc": [], "dtgc": [], "zbgc": []}
    ctx.raw.setdefault("pools", {})
    ctx.raw["pools"].update(
        {
            "ztgc": pools_today.get("ztgc") or [],
            "dtgc": pools_today.get("dtgc") or [],
            "zbgc": pools_today.get("zbgc") or [],
            "qsgc": pools_today.get("qsgc") or [],
            "yest_ztgc": pools_yest.get("ztgc") or [],
            "yest_dtgc": pools_yest.get("dtgc") or [],
            "yest_zbgc": pools_yest.get("zbgc") or [],
            "yest_date": yest or "",
        }
    )
    # 注入近7天涨停池（离线）：供“近7天2连板题材聚合”等跨日模块使用
    ctx.raw["pools"]["ztgc_by_day"] = _load_ztgc_by_day_window(root=root, date=date, n=7)

    # 注入题材缓存：供 theme_panels 模块统计（不做任何网络请求）
    ctx.raw.setdefault("themes", {})
    ctx.raw["themes"]["code2themes"] = _load_theme_cache(root)

    # 注入指数日K缓存：供 volume 模块离线重算
    ctx.raw["index_klines"] = _load_index_klines_cache(root)

    # 注入高度趋势缓存：供 height_trend 模块离线重算
    ctx.raw["height_trend_cache"] = _load_height_trend_cache(root)

    # 注入题材持续性缓存：供 theme_trend 模块离线重算
    ctx.raw["theme_trend_cache"] = _load_theme_trend_cache(root)

    # partial 同样用指数日K修正三大指数涨幅（与报告日一致）
    try:
        codes = ((ctx.raw.get("index_klines") or {}).get("codes") or {}) if isinstance(ctx.raw, dict) else {}
        if isinstance(codes, dict) and date:
            def _pick_exact(code: str) -> tuple[float, float] | None:
                items = (codes.get(code) or {}).get("items") or []
                if not isinstance(items, list):
                    return None
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    t = str(it.get("t") or "")
                    if len(t) >= 10 and t[:10] == date and int(it.get("sf", 0) or 0) != 1:
                        c = float(it.get("c", 0) or 0)
                        pc = float(it.get("pc", 0) or 0)
                        return (c, pc)
                return None

            mapping = [("000001.SH", "上证指数"), ("399001.SZ", "深证成指"), ("399006.SZ", "创业板指")]
            inds = []
            for code, name in mapping:
                r = _pick_exact(code)
                if not r:
                    continue
                c, pc = r
                chg = ((c - pc) / pc * 100.0) if pc else 0.0
                if abs(chg) < 0.005:
                    chg = 0.0
                inds.append({"name": name, "val": f"{c:.2f}", "chg": f"{chg:+.2f}%"})
            if inds:
                ctx.market_data["indices"] = inds
    except Exception:
        pass

    # partial 同样重算 features（至少 mood_inputs），避免局部更新时 UI 读到旧/缺字段
    try:
        pools_for_feat = ctx.raw.get("pools") or {}
        quotes_items = (((ctx.raw.get("quotes") or {}) if isinstance(ctx.raw, dict) else {}).get("items") or {})
        mood_inputs = build_mood_inputs(pools=pools_for_feat, quotes=quotes_items)
        feats = ctx.market_data.get("features") if isinstance(ctx.market_data.get("features"), dict) else {}
        if not isinstance(feats, dict):
            feats = {}
        feats["mood_inputs"] = mood_inputs
        feats.setdefault("chart_palette", default_chart_palette())
        ctx.market_data["features"] = feats
        ctx.features = feats
    except Exception:
        pass

    runner = Runner(ALL_MODULES)
    runner.run(ctx, targets=modules)
    market_data = ctx.market_data

    # partial 也补齐趋势/昨日对比，并重算展示层摘要，避免局部调参后页面保留旧文案
    try:
        _inject_mood_history_and_delta(root=root, date=date, market_data=market_data)
    except Exception:
        pass

    try:
        from daily_review.metrics.action_advisor import build_action_advisor

        market_data["actionAdvisor"] = build_action_advisor(market_data=market_data)
    except Exception:
        pass

    try:
        from daily_review.metrics.zt_analysis import build_zt_analysis

        market_data["ztAnalysis"] = build_zt_analysis(market_data=market_data)
    except Exception:
        pass

    try:
        from daily_review.render.render_html import build_market_overview_7d, build_sentiment_explain_dims, build_summary3

        market_data["summary3"] = build_summary3(market_data=market_data)
        market_data["marketOverview7d"] = build_market_overview_7d(market_data=market_data)
        market_data["sentimentExplainDims"] = build_sentiment_explain_dims(market_data=market_data)
    except Exception:
        pass

    # 清理前端已不用的大字段：避免 partial 更新时把旧 compat/default_page 等写回
    try:
        _prune_frontend_unused_fields(market_data)
    except Exception:
        pass

    template_path = root / "templates" / "report_template.html"
    out_dir = root / "html"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "-".join(modules)
    update_date8 = _now_bj_date8()
    out_path = out_dir / f"复盘日记-{update_date8}-partial-{suffix}.html"

    render_html_template(
        template_path=template_path,
        output_path=out_path,
        market_data=market_data,
        report_date=date,
        date_note=market_data.get("dateNote", ""),
    )
    # 与 rebuild 保持一致：render 阶段补齐后的展示字段需要稳定写回 cache
    market_path.write_text(json.dumps(market_data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✅ partial 输出: {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="报告日期 YYYY-MM-DD（缺省则走全量模式的默认逻辑）")
    ap.add_argument("--require-python", default="", help="强制要求使用指定 Python 解释器路径（例如 /usr/local/bin/python3）")
    ap.add_argument("--require-py", default="", help="强制要求 Python 版本前缀（例如 3.14）")
    ap.add_argument("--rebuild", action="store_true", help="离线重建（不请求接口）：重算并输出 tab-v1 HTML")
    ap.add_argument("--fetch", action="store_true", help="在线取数并生成缓存，然后离线重建输出 tab-v1（有成本）")
    ap.add_argument("--allow-network", action="store_true", help="允许 rebuild 在缺失缓存时在线补齐部分数据源")
    ap.add_argument(
        "--only",
        nargs="+",
        help="部分更新：指定模块名，可选：panorama, ladder, ztgc, theme_panels, volume, height_trend, top10, mood, leader, action_guide, zt_analysis, summary3, learning_notes",
    )
    ap.add_argument(
        "--mode",
        choices=["eod", "intraday"],
        default="eod",
        help="运行模式：eod=收盘版（默认），intraday=盘中快照版（数据截止当前时刻）",
    )
    args = ap.parse_args(argv)

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
        return run_rebuild(args.date, allow_network=args.allow_network)

    if args.fetch:
        return run_fetch_and_rebuild(args.date)

    # 盘中快照模式
    if args.mode == "intraday":
        return run_intraday_snapshot(args.date)

    return run_full(args.date)


if __name__ == "__main__":
    raise SystemExit(main())
