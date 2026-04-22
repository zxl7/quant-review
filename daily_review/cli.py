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


def _workspace_root() -> Path:
    # /workspace/daily_review/cli.py -> /workspace
    return Path(__file__).resolve().parent.parent


def run_full(date: str | None) -> int:
    """
    全量更新（收口阶段）：
    1) 仍复用 gen_report_v4.py 做在线取数与缓存落盘（有成本）
    2) 然后离线跑 v2 pipeline 重建 market_data，并渲染 tab-v1 HTML
    """
    script = _workspace_root() / "gen_report_v4.py"
    cmd = [sys.executable, str(script)]
    if date:
        cmd.append(date)
    import subprocess

    rc = subprocess.call(cmd)
    if rc != 0:
        return rc

    # gen_report_v4 会写入 cache/market_data-YYYYMMDD.json；统一再走一遍 pipeline 产出 tab-v1
    if date:
        return run_rebuild(date)
    return 0


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

    return run_full(args.date)


if __name__ == "__main__":
    raise SystemExit(main())
