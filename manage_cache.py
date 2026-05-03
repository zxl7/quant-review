#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"
ONLINE_DIR = ROOT / "cache_online"


@dataclass
class CacheRule:
    path: Path
    action: str
    reason: str


def ls_market_dates() -> list[str]:
    out: list[str] = []
    for p in CACHE_DIR.glob("market_data-*.json"):
        name = p.stem.replace("market_data-", "")
        if len(name) == 8 and name.isdigit():
            out.append(name)
    return sorted(set(out))


def latest_date8() -> str | None:
    ds = ls_market_dates()
    return ds[-1] if ds else None


def keep_latest(files: Iterable[Path], n: int) -> tuple[list[Path], list[Path]]:
    arr = sorted(files, key=lambda p: p.name)
    if len(arr) <= n:
        return arr, []
    return arr[-n:], arr[:-n]


def classify_cache() -> tuple[list[CacheRule], list[CacheRule]]:
    """
    返回：
    - keep_rules: 应保留
    - drop_rules: 可清理
    """
    keep: list[CacheRule] = []
    drop: list[CacheRule] = []

    core_keep = {
        "pools_cache.json": "离线重建涨停/跌停/炸板池必需",
        "theme_cache.json": "题材映射必需",
        "plate_rotate_cache.json": "板块轮动明细必需",
        "index_kline_cache.json": "指数K线/量能模块依赖",
        "height_trend_cache.json": "高度趋势模块依赖",
        "theme_trend_cache.json": "题材持续性模块依赖",
        "concept_fund_flow_cache.json": "板块排行兜底数据",
        "money_flow_cache.json": "板块流入聚合依赖",
        "learning_notes_history.json": "学习语录去重历史",
        "trade_days_cache.json": "交易日缓存（gen_report_v4 兼容）",
    }

    for name, reason in core_keep.items():
        p = CACHE_DIR / name
        if p.exists():
            keep.append(CacheRule(p, "keep", reason))

    # market_data 只保留最近 7 个
    kept_market, dropped_market = keep_latest(CACHE_DIR.glob("market_data-*.json"), 7)
    for p in kept_market:
        keep.append(CacheRule(p, "keep", "最近 7 个 market_data 快照"))
    for p in dropped_market:
        drop.append(CacheRule(p, "drop", "超出最近 7 个 market_data 快照"))

    # intraday snapshots：兼容旧文件名，只保留最近 2 个
    kept_snap, dropped_snap = keep_latest(CACHE_DIR.glob("intraday_snapshots-*.json"), 2)
    for p in kept_snap:
        keep.append(CacheRule(p, "keep", "保留最近 2 个盘中快照"))
    for p in dropped_snap:
        drop.append(CacheRule(p, "drop", "过旧盘中快照"))

    # intraday slices：新盘中切片文件，只保留最近 2 个
    kept_slices, dropped_slices = keep_latest(CACHE_DIR.glob("intraday_slices-*.json"), 2)
    for p in kept_slices:
        keep.append(CacheRule(p, "keep", "保留最近 2 个盘中切片"))
    for p in dropped_slices:
        drop.append(CacheRule(p, "drop", "过旧盘中切片"))

    # v3_quality markdown：当前无代码消费，按临时分析产物处理
    for p in sorted(CACHE_DIR.glob("v3_quality-*.md")):
        drop.append(CacheRule(p, "drop", "未被代码消费的临时分析产物"))

    # 其他未知文件先保守保留
    known = {r.path.name for r in keep + drop}
    for p in sorted(CACHE_DIR.iterdir()):
        if p.name in known:
            continue
        keep.append(CacheRule(p, "keep", "未知文件，保守保留"))

    return keep, drop


def sync_online_cache(date10: str, *, mode: str = "minimal") -> tuple[list[Path], Path]:
    date8 = date10.replace("-", "")
    ONLINE_DIR.mkdir(parents=True, exist_ok=True)
    for p in ONLINE_DIR.iterdir():
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p)

    required = [
        CACHE_DIR / f"market_data-{date8}.json",
        CACHE_DIR / "pools_cache.json",
        CACHE_DIR / "theme_cache.json",
        CACHE_DIR / "plate_rotate_cache.json",
        CACHE_DIR / "trade_days_cache.json",
    ]
    optional = [
        CACHE_DIR / "index_kline_cache.json",
        CACHE_DIR / "height_trend_cache.json",
        CACHE_DIR / "theme_trend_cache.json",
        CACHE_DIR / "concept_fund_flow_cache.json",
        CACHE_DIR / "money_flow_cache.json",
    ]
    files = required + (optional if mode == "full" else [])

    copied: list[Path] = []
    for src in files:
        if src.exists():
            dst = ONLINE_DIR / src.name
            shutil.copy2(src, dst)
            copied.append(dst)

    manifest = {
        "date": date10,
        "mode": mode,
        "files": [p.name for p in copied],
    }
    manifest_path = ONLINE_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return copied, manifest_path


def write_report(keep: list[CacheRule], drop: list[CacheRule], date10: str, mode: str) -> Path:
    report = ROOT / "cache-cleanup-report.md"
    lines = [
        "# Cache 清理与线上同步报告",
        "",
        f"- 最新报告日期：`{date10}`",
        f"- 线上目录模式：`{mode}`",
        "",
        "## 当前脚本自动清理现状",
        "",
        "- `qr.sh` 目前只会自动删除：旧的 `market_data-*.json`（保留最近 7 个）和历史 HTML。",
        "- `qr.sh` 目前不会自动删除：`intraday_snapshots-*`、`intraday_slices-*`、`v3_quality-*.md`、`learning_notes_history.json`、`trade_days_cache.json` 等。",
        "",
        "## 建议保留",
        "",
    ]
    for r in sorted(keep, key=lambda x: x.path.name):
        lines.append(f"- `{r.path.name}`：{r.reason}")
    lines += ["", "## 建议清理", ""]
    if drop:
        for r in sorted(drop, key=lambda x: x.path.name):
            lines.append(f"- `{r.path.name}`：{r.reason}")
    else:
        lines.append("- 无")
    lines += [
        "",
        "## 线上依赖目录",
        "",
        "- 目录：`cache_online/`",
        "- 只放远端 `render/deploy` 需要上传的缓存文件",
        "- 可直接整体上传，而不是从 `cache/` 手工挑文件",
        "",
    ]
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="清理 cache 并同步线上依赖目录")
    ap.add_argument("--date", default=None, help="报告日期 YYYY-MM-DD；默认使用最新 market_data 日期")
    ap.add_argument("--mode", choices=["minimal", "full"], default="minimal")
    ap.add_argument("--apply", action="store_true", help="实际删除建议清理的文件")
    args = ap.parse_args()

    d8 = args.date.replace("-", "") if args.date else latest_date8()
    if not d8:
        raise SystemExit("未找到 market_data-*.json，无法确定日期")
    date10 = f"{d8[:4]}-{d8[4:6]}-{d8[6:8]}"

    keep, drop = classify_cache()
    report = write_report(keep, drop, date10, args.mode)

    print(f"报告: {report}")
    print("建议清理：")
    for r in drop:
        print(f" - {r.path.name}: {r.reason}")

    if args.apply:
        for r in drop:
            if r.path.exists():
                r.path.unlink()
        print("已执行清理。")
        keep, drop = classify_cache()

    copied, manifest = sync_online_cache(date10, mode=args.mode)
    print(f"线上目录: {ONLINE_DIR}")
    print(f"manifest: {manifest}")
    print("已同步文件：")
    for p in copied:
        print(f" - {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
