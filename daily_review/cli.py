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
    fetch_pool,
    fetch_stock_themes,
    get_trading_days_from_index_k,
    normalize_stock_code,
    resolve_trade_date,
)
from daily_review.features.build_features import build_mood_inputs, build_style_inputs, default_chart_palette
from daily_review.modules.style_radar import rebuild_style_radar


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

    # index_kline_cache.json：缓存最近 5 根（日K）
    index_k_path = cache_dir / "index_kline_cache.json"
    idx_disk = read_json(index_k_path, default={})
    codes_entry = (idx_disk.get("codes") or {}) if isinstance(idx_disk, dict) else {}
    if not isinstance(codes_entry, dict):
        codes_entry = {}
    for code in ("000001.SH", "399001.SZ"):
        items = fetch_index_latest_k(client, code=code, lt=5)
        codes_entry[code] = {"as_of": actual_date, "items": items[-5:] if isinstance(items, list) else []}
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

    # indices（实时）
    indices_rt, indices_asof = fetch_indices_realtime(
        client,
        codes=[("000001.SH", "上证指数"), ("399001.SZ", "深证成指"), ("399006.SZ", "创业板指")],
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
        "indices": [
            {"name": i["name"], "val": f"{float(i['val']):.2f}", "chg": f"{float(i['chg']):+.2f}%"}
            for i in (indices_rt or [])
        ],
        "panorama": {},
        "volume": {},
        "sectors": [],
        "themePanels": {},
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
        "styleRadar": {},
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
    }

    # features：最小可用版
    mood_inputs = build_mood_inputs(pools=raw_pools)
    market_data["features"]["mood_inputs"] = mood_inputs
    market_data["features"]["chart_palette"] = default_chart_palette()
    market_data["features"]["style_inputs"] = build_style_inputs(mood_inputs=mood_inputs, theme_panels=market_data.get("themePanels") or {})

    # 写 market_data 缓存（供 rebuild/partial 使用）
    date_compact = actual_date.replace("-", "")
    market_path = cache_dir / f"market_data-{date_compact}.json"
    write_json(market_path, market_data)

    # 离线重建（pipeline）并渲染 tab-v1
    return run_rebuild(actual_date)


def run_rebuild(date: str, modules: list[str] | None = None) -> int:
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

    runner = Runner(ALL_MODULES)
    runner.run(ctx, targets=(modules or None))
    market_data = ctx.market_data

    # 后处理：features/style_inputs 依赖 themePanels，而 themePanels 由 pipeline 产出
    # 为保证“主线集中度/风格雷达”一致性，rebuild 后再补一遍 style_inputs，并刷新 styleRadar。
    try:
        feats = market_data.get("features") or {}
        mi = feats.get("mood_inputs") or {}
        tp = market_data.get("themePanels") or {}
        feats["style_inputs"] = build_style_inputs(mood_inputs=mi, theme_panels=tp)
        market_data["features"] = feats
        # 重新生成 styleRadar（纯函数，安全）
        market_data["styleRadar"] = rebuild_style_radar(market_data)["styleRadar"]
    except Exception:
        pass

    # 写回缓存（让离线 render/partial 都读到最新重建结果）
    market_path.write_text(json.dumps(market_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 渲染 tab-v1
    template_path = root / "templates" / "report_template.html"
    out_dir = root / "html"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"复盘日记-{date_compact}-tab-v1.html"

    render_html_template(
        template_path=template_path,
        output_path=out_path,
        market_data=market_data,
        report_date=date,
        date_note=market_data.get("dateNote", ""),
    )
    print(f"✅ rebuild 输出: {out_path}")
    return 0


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

    runner = Runner(ALL_MODULES)
    runner.run(ctx, targets=modules)
    market_data = ctx.market_data

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
    ap.add_argument("--rebuild", action="store_true", help="离线重建（不请求接口）：重算并输出 tab-v1 HTML")
    ap.add_argument("--fetch", action="store_true", help="在线取数并生成缓存，然后离线重建输出 tab-v1（有成本）")
    ap.add_argument(
        "--only",
        nargs="+",
        help="部分更新：指定模块名，可选：panorama, ladder, ztgc, theme_panels, volume, height_trend, top10, mood, style_radar, leader, action_guide, summary3, learning_notes",
    )
    args = ap.parse_args(argv)

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

    return run_full(args.date)


if __name__ == "__main__":
    raise SystemExit(main())
