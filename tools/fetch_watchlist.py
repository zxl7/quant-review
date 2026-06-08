#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
fetch_watchlist.py — 板块/题材梯队推测的统一编排入口

数据流：
    M1+M2 (data/) 拉外部接口 → cache_online/{xuangubao,eastmoney}_*.json
              │
              ▼
    M3 (features/sector_resolver) 归一化、跨源融合
              │
              ▼
    M4 (features/ladder_builder)   梯队 + 主线置信度
              │
              ▼
    cache_online/watchlist_cache-YYYYMMDD.json

使用：
    python3 tools/fetch_watchlist.py                       # 默认 mode=full
    python3 tools/fetch_watchlist.py --mode intraday       # 仅拉异动事件
    python3 tools/fetch_watchlist.py --mode eod            # 收盘后全量拉取
    python3 tools/fetch_watchlist.py --date 2026-05-26     # 指定日期
    python3 tools/fetch_watchlist.py --skip-fetch          # 跳过拉接口，仅用本地缓存重算
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from daily_review.cache_io import read_json, write_json   # noqa: E402
from daily_review.data.xuangubao import (                  # noqa: E402
    save_abnormal_snapshot,
    save_surge_plates_snapshot,
)
from daily_review.data.eastmoney_theme import save_tomorrow_snapshot  # noqa: E402
from daily_review.features.sector_resolver import resolve  # noqa: E402
from daily_review.features.ladder_builder import build_ladder  # noqa: E402
from daily_review.features.stock_ranker import build_picks_advisor  # noqa: E402
from daily_review.metrics.core_tide import build_core_tide_signal  # noqa: E402
from daily_review.metrics.tide import build_tide_signal  # noqa: E402


def _now_bj_date() -> str:
    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))).strftime("%Y-%m-%d")


def _now_bj_str() -> str:
    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def _fetch_all(*, date: str, mode: str, root: Path) -> dict[str, Any]:
    """
    根据 mode 决定拉哪些接口。

    - intraday  : 异动事件 + 热点板块（高频，~5min）
    - eod       : 异动 + 板块 + 明日主题 + 主题成份股（每日 1 次）
    - full      : 同 eod（别名）
    """
    out: dict[str, Any] = {"mode": mode, "fetched": []}
    note = f"fetch_watchlist.{mode}"

    p1 = save_abnormal_snapshot(root=root, date=date, mode=mode, note=note)
    out["fetched"].append(str(p1.relative_to(root)))

    p2 = save_surge_plates_snapshot(root=root, date=date, mode=mode, note=note)
    out["fetched"].append(str(p2.relative_to(root)))

    if mode in ("eod", "full"):
        p3, p4 = save_tomorrow_snapshot(root=root, date=date, mode=mode, note=note, max_themes_for_stocks=15)
        out["fetched"].append(str(p3.relative_to(root)))
        if p4:
            out["fetched"].append(str(p4.relative_to(root)))
    return out


def _build_payload(
    *,
    root: Path,
    date: str,
    pools_date: str,
) -> dict[str, Any]:
    """
    跑 M3 + M4，组装最终 payload。

    Args:
        date:       接口数据所在日期（cache_online/*-{date}.json）
        pools_date: pools_cache.ztgc 内取哪一天的涨停数据，通常是上一交易日
    """
    pools_cache = read_json(root / "cache_online" / "pools_cache.json", default={})
    theme_trend_cache = read_json(root / "cache_online" / "theme_trend_cache.json", default=None)
    if not isinstance(theme_trend_cache, dict) or not isinstance(theme_trend_cache.get("by_day"), dict):
        theme_trend_cache = read_json(root / "cache" / "theme_trend_cache.json", default={})
    plate_rotate_cache = read_json(root / "cache_online" / "plate_rotate_cache.json", default={})

    # market_data 必须锚定 pools_date，避免历史重算时误读 cache_online 最新交易日。
    market_data = _load_market_data_for_date(root=root, pools_date=pools_date)

    resolution = resolve(root=root, date=date, pools_cache=pools_cache, min_confidence=0.3)
    ladder = build_ladder(
        resolution=resolution,
        pools_cache=pools_cache,
        date=pools_date,
        market_data=market_data,
    )
    tide_signal = build_tide_signal(
        market_data=market_data,
        theme_trend_cache=theme_trend_cache if isinstance(theme_trend_cache, dict) else {},
        plate_rotate_cache=plate_rotate_cache if isinstance(plate_rotate_cache, dict) else {},
    )
    catalyst_data = _load_catalyst_data(root=root, date=date)
    core_tide_signal = build_core_tide_signal(
        market_data=market_data,
        tide_signal=tide_signal,
        catalyst_data=catalyst_data,
    )
    picks_advisor = build_picks_advisor(
        ladder=ladder,
        market_data=market_data,
        tide_signal=tide_signal,
        core_tide_signal=core_tide_signal,
        top_k_lines=4,
        buy_n=3,
        watch_n=5,
        min_main_line_conf=0.40,
    )

    return {
        "schema": "watchlist_v2",
        "generated_at_bj": _now_bj_str(),
        "data_date": date,                # 接口数据日期
        "pools_date": pools_date,         # 涨停池快照日期
        "sector_resolution": resolution.to_dict(),
        "ladder": ladder.to_dict(),
        "tide_signal": tide_signal,
        "core_tide_signal": core_tide_signal,
        "picks_advisor": picks_advisor.to_dict(),
    }


def _load_catalyst_data(*, root: Path, date: str) -> dict[str, Any]:
    """读取消息面缓存并交给纯算法；这里是 I/O 边界，算法层不碰文件。"""
    d8 = str(date or "").replace("-", "")
    cache_dir = root / "cache_online"
    return {
        "abnormal": read_json(cache_dir / f"xuangubao_abnormal-{d8}.json", default={}),
        "surge_plates": read_json(cache_dir / f"xuangubao_surge_plates-{d8}.json", default={}),
        "tomorrow_themes": read_json(cache_dir / f"eastmoney_tomorrow_themes-{d8}.json", default={}),
    }


def _load_market_data_for_date(*, root: Path, pools_date: str) -> dict[str, Any]:
    """按涨停池基准日读取 market_data；历史日期不再回退到最新交易日。"""
    d8 = str(pools_date or "").replace("-", "")
    candidates = [
        root / "cache_online" / f"market_data-{d8}.json",
        root / "cache" / f"market_data-{d8}.json",
    ]
    for path in candidates:
        if path.exists():
            return read_json(path, default={})
    return {}


def _resolve_pools_date(root: Path, prefer_date: str) -> str:
    """
    pools_cache.ztgc 中选择基准日：
    - 若有 prefer_date → 用它
    - 否则取最近一天（<= prefer_date）
    """
    pools = read_json(root / "cache_online" / "pools_cache.json", default={})
    ztgc = pools.get("pools", {}).get("ztgc", {}) if isinstance(pools, dict) else {}
    if isinstance(ztgc, dict):
        if prefer_date in ztgc:
            return prefer_date
        past = sorted(d for d in ztgc.keys() if d <= prefer_date)
        if past:
            return past[-1]
    return prefer_date


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="板块/题材梯队推测编排")
    parser.add_argument("--mode", choices=["intraday", "eod", "full"], default="full")
    parser.add_argument("--date", default="", help="数据日期 YYYY-MM-DD（默认今天 BJ）")
    parser.add_argument(
        "--pools-date",
        default="",
        help="涨停池基准日 YYYY-MM-DD（默认从 pools_cache 推断为 <= date 的最近一天）",
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="跳过拉接口，仅用 cache_online 中已有的快照重算",
    )
    parser.add_argument(
        "--output",
        default="",
        help="自定义输出路径；默认 cache_online/watchlist_cache-YYYYMMDD.json",
    )
    args = parser.parse_args(argv)

    date = args.date or _now_bj_date()
    fetch_result: dict[str, Any] | None = None

    if not args.skip_fetch:
        try:
            fetch_result = _fetch_all(date=date, mode=args.mode, root=ROOT)
        except Exception as e:
            print(f"⚠ 接口拉取失败（将尝试用本地缓存）: {e}", file=sys.stderr)
            fetch_result = {"mode": args.mode, "fetched": [], "error": str(e)}

    pools_date = args.pools_date or _resolve_pools_date(ROOT, date)
    payload = _build_payload(root=ROOT, date=date, pools_date=pools_date)
    if fetch_result is not None:
        payload["fetch"] = fetch_result

    output = args.output or f"cache_online/watchlist_cache-{date.replace('-', '')}.json"
    output_path = Path(output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    write_json(output_path, payload)

    # 简明 stdout 摘要
    diag = payload["ladder"]["diagnostics"]
    main_lines = payload["ladder"]["main_lines"]
    try:
        display_path = output_path.relative_to(ROOT)
    except ValueError:
        display_path = output_path
    print(f"✅ watchlist 已写入: {display_path}")
    print(f"   数据日: {date}  /  涨停池日: {pools_date}")
    print(f"   涨停股: {diag['zt_total']}  /  主线数: {diag['main_lines_total']}")
    print(f"   主线 Top3:")
    for ml in main_lines[:3]:
        sig = ml["signals"]
        flag = "🔥" if ml["has_em_hot"] else "★"
        print(
            f"     {flag} {ml['name']:<10}  conf={ml['confidence']:.2f}  "
            f"(biying={sig['biying']:.2f} em={sig['em']:.2f} xgb={sig['xgb']:.2f})  "
            f"zt_total={ml['em_zt_total']}"
        )
    # 算法建议摘要
    pa = payload.get("picks_advisor", {})
    print(f"   算法建议: buy={pa.get('diagnostics',{}).get('total_buy',0)} watch={pa.get('diagnostics',{}).get('total_watch',0)}")
    for ml_picks in pa.get("main_line_picks", []):
        buy_names = " / ".join(s["name"] for s in ml_picks["buy"])
        watch_names = " · ".join(s["name"] for s in ml_picks["watch"][:3])
        print(f"     · {ml_picks['main_line']:<10} 买入 {buy_names}  | 观察 {watch_names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
