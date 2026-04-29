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
import os
import sys
from pathlib import Path

from daily_review.modules_v2 import ALL_MODULES
from daily_review.pipeline.context import Context
from daily_review.pipeline.runner import Runner
from daily_review.render.render_html import render_html_template
from daily_review.cache_io import read_json, write_json
from daily_review.config import load_config_from_env
from daily_review.config import DEFAULT_CONFIG
from daily_review.data.biying import (
    fetch_indices_realtime,
    fetch_index_latest_k,
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


def _workspace_root() -> Path:
    # /workspace/daily_review/cli.py -> /workspace
    return Path(__file__).resolve().parent.parent


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

    cfg = load_config_from_env()
    from daily_review.http import HttpClient

    client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=30)
    req_date = date
    actual_date, date_note = resolve_trade_date(client, req_date)

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

    # theme_cache.json：只补齐“当日出现的 code6”，避免无限增长
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

    # 裁剪：只保留最近 30 天
    keep_days = set(trade_days)
    for k in sorted(list(by_day.keys())):
        if isinstance(k, str) and k not in keep_days and len(by_day) > 40:
            by_day.pop(k, None)

    write_json(theme_trend_path, {"version": 1, "as_of": actual_date, "by_day": by_day})

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
    write_json(ht_path, {"version": 1, "days": ht_days})

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
            {"name": i["name"], "val": f"{float(i['val']):.2f}", "chg": f"{float(i['chg']):+.2f}%"} for i in (indices_rt or [])
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
    except Exception:
        pass

    # features：最小可用版
    mood_inputs = build_mood_inputs(pools=raw_pools)
    market_data["features"]["mood_inputs"] = mood_inputs
    market_data["features"]["chart_palette"] = default_chart_palette()

    # 写 market_data 缓存（供 rebuild/partial 使用）
    date_compact = actual_date.replace("-", "")
    market_path = cache_dir / f"market_data-{date_compact}.json"
    write_json(market_path, market_data)

    # 离线重建（pipeline）并渲染 tab-v1
    return run_rebuild(actual_date)


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

    # 当前时间（用于量能估算和标记）
    now = _dt.datetime.now()
    now_str = now.strftime("%H:%M:%S")

    # 判断是否在交易时间内
    is_trading_hour = (9 <= now.hour < 16) and not (
        now.hour == 11 and now.minute >= 30 or now.hour == 12
    )

    if not is_trading_hour:
        print(f"⚠️ 当前时间 {now_str} 不在交易时段内（9:00-15:30），数据可能为上一交易日收盘数据。")

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
    write_json(pools_path, {"version": 1, "pools": pools})

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
    yest = actual_date  # 盘中时昨日用上一个交易日

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

    # 跑 pipeline + 渲染（复用 rebuild 的大部分逻辑）
    # 第一次：先把计算结果写回 intraday market_data（用于生成快照记录）
    run_rebuild(actual_date, suffix="intraday", source_market_path=market_path)

    # 追加快照记录（写入 cache/intraday_snapshots-YYYYMMDD.json）
    try:
        snap_md = json.loads(market_path.read_text(encoding="utf-8"))
        _append_intraday_snapshot(root=root, date=actual_date, market_data=snap_md)
    except Exception:
        pass

    # 第二次：把“半小时快照列表”注入页面后再渲染一次（离线，成本很低）
    run_rebuild(actual_date, suffix="intraday", source_market_path=market_path)

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


def run_rebuild(date: str, modules: list[str] | None = None, suffix: str = "", source_market_path: Path | None = None) -> int:
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
    ctx.raw.setdefault("themes", {})
    ctx.raw["themes"]["code2themes"] = _load_theme_cache(root)
    ctx.raw["index_klines"] = _load_index_klines_cache(root)
    ctx.raw["height_trend_cache"] = _load_height_trend_cache(root)
    ctx.raw["theme_trend_cache"] = _load_theme_trend_cache(root)

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
        mood_inputs = build_mood_inputs(pools=pools_for_feat)
        feats = ctx.market_data.get("features") if isinstance(ctx.market_data.get("features"), dict) else {}
        if not isinstance(feats, dict):
            feats = {}
        feats["mood_inputs"] = mood_inputs
        feats.setdefault("chart_palette", default_chart_palette())
        ctx.market_data["features"] = feats
        ctx.features = feats  # runner 使用 ctx.features 读取 features.*
    except Exception:
        pass

    runner = Runner(ALL_MODULES)
    runner.run(ctx, targets=(modules or None))
    market_data = ctx.market_data

    # === 注入盘中快照列表（供“实时盯盘”页面展示）===
    try:
        snaps = _load_intraday_snapshots(root=root, date=date)
        if snaps:
            market_data["intradaySnapshots"] = {
                "date": date,
                "count": len(snaps),
                "snapshots": snaps,
            }
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
    except Exception:
        pass

    # PRD v2：核心派生字段（必须可复算）
    # - sectorHeatmap（多板块情绪热力图）
    # - threeQuadrants（盘面三象限）
    try:
        _inject_prd_v2_metrics(root=root, date=date, market_data=market_data)
    except Exception:
        pass

    # 写回缓存（让离线 render/partial 都读到最新重建结果）
    # compat：统一输出层（v1/v2/v3 → marketData.compat.*）
    try:
        from daily_review.compat import build_compat

        prefer_algo = os.environ.get("REPORT_ALGO", "").strip().lower() or "auto"
        if prefer_algo not in ("auto", "v1", "v2", "v3"):
            prefer_algo = "auto"
        market_data["compat"] = build_compat(market_data, prefer=prefer_algo)  # type: ignore[arg-type]
        meta = market_data.get("meta") if isinstance(market_data.get("meta"), dict) else {}
        if not isinstance(meta, dict):
            meta = {}
        meta["algo"] = market_data.get("compat", {}).get("algo", prefer_algo)
        market_data["meta"] = meta
    except Exception:
        pass

    market_path.write_text(json.dumps(market_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 渲染 tab-v1
    template_path = root / "templates" / "report_template.html"
    out_dir = root / "html"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix_part = f"-{suffix}" if suffix else ""
    out_path = out_dir / f"复盘日记-{date_compact}{suffix_part}-tab-v1.html"

    render_html_template(
        template_path=template_path,
        output_path=out_path,
        market_data=market_data,
        report_date=date,
        date_note=market_data.get("dateNote", ""),
    )
    print(f"✅ rebuild 输出: {out_path}")
    return 0


def _intraday_snapshots_path(root: Path, date: str) -> Path:
    cache_dir = root / "cache"
    d8 = date.replace("-", "")
    return cache_dir / f"intraday_snapshots-{d8}.json"


def _load_intraday_snapshots(*, root: Path, date: str) -> list[dict]:
    p = _intraday_snapshots_path(root, date)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        return []
    except Exception:
        return []


def _write_intraday_snapshots(*, root: Path, date: str, snapshots: list[dict]) -> None:
    p = _intraday_snapshots_path(root, date)
    p.write_text(json.dumps(snapshots, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_intraday_snapshot(*, root: Path, date: str, market_data: dict) -> None:
    """
    追加一条盘中快照（半小时级）。
    只保存“盯盘所需最小信息”，避免文件膨胀。
    """
    meta = market_data.get("meta") or {}
    t = str(meta.get("snapshotTime") or meta.get("asOf", {}).get("pools") or "")
    t = t[:5] if len(t) >= 5 else t
    if not t:
        return

    mi = (market_data.get("features") or {}).get("mood_inputs") or {}
    mood = market_data.get("mood") or {}
    ms = market_data.get("moodSignals") or {}
    hm2 = market_data.get("hm2Compare") or {}

    rec = {
        "time": t,
        "headline": ms.get("headline") or "",
        "heat": mood.get("heat"),
        "risk": mood.get("risk"),
        "fb": mi.get("fb_rate"),
        "jj": mi.get("jj_rate"),
        "zb": mi.get("zb_rate"),
        "loss": mi.get("loss"),
        "hm2": hm2.get("score"),
        "pos": ms.get("pos") or [],
        "riskSignals": ms.get("risk") or [],
    }

    snaps = _load_intraday_snapshots(root=root, date=date)
    # 去重：同一时间点只保留最新一条
    snaps = [s for s in snaps if str(s.get("time") or "") != t]
    snaps.append(rec)
    # 按时间排序（HH:MM）
    snaps.sort(key=lambda x: str(x.get("time") or ""))
    # 限制条数（一天最多几十条）
    snaps = snaps[-60:]
    _write_intraday_snapshots(root=root, date=date, snapshots=snaps)


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

    need_hist = not (isinstance(hist_days, list) and len(hist_days) >= 2)
    if need_hist:
        try:
            hist_n = int(os.getenv("MOOD_HIST_DAYS", "5") or "5")
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

                rows.append(
                    {
                        "date": f"{d8[0:4]}-{d8[4:6]}-{d8[6:8]}",
                        "max_lb": max_lb,
                        "fb_rate": _to_num(s_mi.get("fb_rate", 0), 0),
                        "jj_rate": _to_num(s_mi.get("jj_rate_adj", s_mi.get("jj_rate", 0)), 0),
                        "broken_lb_rate": _to_num(s_mi.get("broken_lb_rate_adj", s_mi.get("broken_lb_rate", 0)), 0),
                        "zt": int(_to_num((snap.get("panorama") or {}).get("limitUp", 0), 0)),
                        "dt": int(_to_num((snap.get("panorama") or {}).get("limitDown", 0), 0)),
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
            mi["hist_zt"] = [int(r.get("zt", 0)) for r in rows]
            mi["hist_dt"] = [int(r.get("dt", 0)) for r in rows]
            mi["hist_zt_dt_spread"] = [int(r.get("zt", 0)) - int(r.get("dt", 0)) for r in rows]
            mi["trend_max_lb"] = round(float(last["max_lb"]) - float(first["max_lb"]), 2)
            mi["trend_fb_rate"] = round(float(last["fb_rate"]) - float(first["fb_rate"]), 2)
            mi["trend_jj_rate"] = round(float(last["jj_rate"]) - float(first["jj_rate"]), 2)
            mi["trend_broken_lb_rate"] = round(float(last["broken_lb_rate"]) - float(first["broken_lb_rate"]), 2)

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
        "heat": round(_num((market_data.get("mood") or {}).get("heat"), 0) - _num((prev_data.get("mood") or {}).get("heat"), 0), 2),
        "risk": round(_num((market_data.get("mood") or {}).get("risk"), 0) - _num((prev_data.get("mood") or {}).get("risk"), 0), 2),
    }


def _inject_prd_v2_metrics(*, root: Path, date: str, market_data: dict) -> None:
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
    for d8, fp in items[-5:]:
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
                inds.append({"name": name, "val": f"{c:.2f}", "chg": f"{chg:+.2f}%"})
            if inds:
                ctx.market_data["indices"] = inds
    except Exception:
        pass

    # partial 同样重算 features（至少 mood_inputs），避免局部更新时 UI 读到旧/缺字段
    try:
        pools_for_feat = ctx.raw.get("pools") or {}
        mood_inputs = build_mood_inputs(pools=pools_for_feat)
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

    # compat：统一输出层（partial 也需要，避免模板读不到）
    try:
        from daily_review.compat import build_compat

        prefer_algo = os.environ.get("REPORT_ALGO", "").strip().lower() or "auto"
        if prefer_algo not in ("auto", "v1", "v2", "v3"):
            prefer_algo = "auto"
        market_data["compat"] = build_compat(market_data, prefer=prefer_algo)  # type: ignore[arg-type]
        meta = market_data.get("meta") if isinstance(market_data.get("meta"), dict) else {}
        if not isinstance(meta, dict):
            meta = {}
        meta["algo"] = market_data.get("compat", {}).get("algo", prefer_algo)
        market_data["meta"] = meta
    except Exception:
        pass

    template_path = root / "templates" / "report_template.html"
    out_dir = root / "html"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "-".join(modules)
    out_path = out_dir / f"复盘日记-{date_compact}-partial-{suffix}.html"

    render_html_template(
        template_path=template_path,
        output_path=out_path,
        market_data=market_data,
        report_date=date,
        date_note=market_data.get("dateNote", ""),
    )

    print(f"✅ partial 输出: {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="报告日期 YYYY-MM-DD（缺省则走全量模式的默认逻辑）")
    ap.add_argument("--require-python", default="", help="强制要求使用指定 Python 解释器路径（例如 /usr/local/bin/python3）")
    ap.add_argument("--require-py", default="", help="强制要求 Python 版本前缀（例如 3.14）")
    ap.add_argument("--algo", default="auto", choices=["auto", "v1", "v2", "v3"], help="选择算法口径：auto=优先v3→v2→v1；或强制指定 v1/v2/v3")
    ap.add_argument("--rebuild", action="store_true", help="离线重建（不请求接口）：重算并输出 tab-v1 HTML")
    ap.add_argument("--fetch", action="store_true", help="在线取数并生成缓存，然后离线重建输出 tab-v1（有成本）")
    ap.add_argument(
        "--only",
        nargs="+",
        help="部分更新：指定模块名，可选：panorama, ladder, ztgc, theme_panels, volume, height_trend, top10, mood, leader, action_guide, summary3, learning_notes",
    )
    ap.add_argument(
        "--mode",
        choices=["eod", "intraday"],
        default="eod",
        help="运行模式：eod=收盘版（默认），intraday=盘中快照版（数据截止当前时刻）",
    )
    args = ap.parse_args(argv)

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
    # 传递 algo（供 compat 层决定口径）
    os.environ["REPORT_ALGO"] = (args.algo or "auto")

    if args.only:
        if not args.date:
            raise SystemExit("--only 模式必须指定 --date")
        return run_partial(args.date, args.only)

    if args.rebuild:
        if not args.date:
            raise SystemExit("--rebuild 模式必须指定 --date")
        return run_rebuild(args.date)

    if args.fetch:
        return run_fetch_and_rebuild(args.date)

    # 盘中快照模式
    if args.mode == "intraday":
        return run_intraday_snapshot(args.date)

    return run_full(args.date)


if __name__ == "__main__":
    raise SystemExit(main())
