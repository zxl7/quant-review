#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"
ONLINE_DIR = ROOT / "cache_online"
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
TONGHUASHUN_OUTPUT_DIR = ROOT / "daily_review" / "output" / "tonghuashun"

MARKET_DATA_RE = re.compile(r"^market_data-(\d{8})(?:-intraday)?\.json$")
DATE8_FILE_PATTERNS = {
    "abnormal_event_history": re.compile(r"^abnormal_event_history-(\d{8})\.json$"),
    "dragon_tiger": re.compile(r"^dragon_tiger-(\d{8})\.json$"),
    "stock_research_realtime_quotes": re.compile(r"^stock_research_realtime_quotes-(\d{8})\.json$"),
    "intraday_snapshots": re.compile(r"^intraday_snapshots-(\d{8})\.json$"),
    "intraday_slices": re.compile(r"^intraday_slices-(\d{8})\.json$"),
    "watchlist_cache": re.compile(r"^watchlist_cache-(\d{8})\.json$"),
    "xuangubao_abnormal": re.compile(r"^xuangubao_abnormal-(\d{8})\.json$"),
    "xuangubao_surge_plates": re.compile(r"^xuangubao_surge_plates-(\d{8})\.json$"),
    "eastmoney_tomorrow_themes": re.compile(r"^eastmoney_tomorrow_themes-(\d{8})\.json$"),
    "eastmoney_theme_stocks": re.compile(r"^eastmoney_theme_stocks-(\d{8})\.json$"),
    "ths_newhigh": re.compile(r"^ths_newhigh-(\d{8})\.json$"),
    "intraday_resonance": re.compile(r"^intraday_resonance-(\d{8})\.json$"),
}
DATE10_OUTPUT_RE = re.compile(r"^sync-(\d{4}-\d{2}-\d{2})\.txt$")
LOG_PREFIX_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2}\]")
CACHE_LOCAL_DATE_KEYS = {
    "abnormal_event_history",
    "dragon_tiger",
    "stock_research_realtime_quotes",
    "intraday_snapshots",
    "intraday_slices",
}


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


def _extract_date8(name: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.match(name)
    if not match:
        return None
    return str(match.group(1))


def _extract_output_date8(name: str) -> str | None:
    match = DATE10_OUTPUT_RE.match(name)
    if not match:
        return None
    return match.group(1).replace("-", "")


def _dated_group_dir(key: str) -> Path:
    return CACHE_DIR if key in CACHE_LOCAL_DATE_KEYS else ONLINE_DIR


def build_retention_date_window(keep_days: int) -> list[str]:
    market_dates = ls_market_dates()
    if market_dates:
        return market_dates[-keep_days:]

    dates: set[str] = set()
    for path in CACHE_DIR.glob("market_data-*.json"):
        date8 = _extract_date8(path.name, MARKET_DATA_RE)
        if date8:
            dates.add(date8)
    for key, pattern in DATE8_FILE_PATTERNS.items():
        base_dir = _dated_group_dir(key)
        for path in base_dir.iterdir() if base_dir.exists() else ():
            if not path.is_file():
                continue
            date8 = _extract_date8(path.name, pattern)
            if date8:
                dates.add(date8)
    if TONGHUASHUN_OUTPUT_DIR.exists():
        for path in TONGHUASHUN_OUTPUT_DIR.glob("sync-*.txt"):
            date8 = _extract_output_date8(path.name)
            if date8:
                dates.add(date8)
    return sorted(dates)[-keep_days:]


def keep_dates_window(
    files: Iterable[Path],
    *,
    keep_dates: set[str],
    extractor,
) -> tuple[list[Path], list[Path], list[Path]]:
    dated: list[tuple[str, Path]] = []
    undated: list[Path] = []
    for path in sorted(files, key=lambda p: p.name):
        date8 = extractor(path.name)
        if date8:
            dated.append((date8, path))
        else:
            undated.append(path)
    if not dated:
        return [], [], undated
    kept = [path for date8, path in dated if date8 in keep_dates]
    dropped = [path for date8, path in dated if date8 not in keep_dates]
    return kept, dropped, undated


def _classify_dated_group(
    *,
    keep: list[CacheRule],
    drop: list[CacheRule],
    files: Iterable[Path],
    keep_dates: set[str],
    extractor,
    keep_reason: str,
    drop_reason: str,
) -> set[Path]:
    kept, dropped, undated = keep_dates_window(files, keep_dates=keep_dates, extractor=extractor)
    for path in kept:
        keep.append(CacheRule(path, "keep", keep_reason))
    for path in dropped:
        drop.append(CacheRule(path, "drop", drop_reason))
    return set(kept + dropped + undated)


def _trim_recommendation_price_history(path: Path, keep_dates: set[str]) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0, 0
    if not isinstance(data, dict):
        return 0, 0
    codes = data.get("codes")
    if not isinstance(codes, dict):
        return 0, 0

    all_dates: set[str] = set()
    for payload in codes.values():
        if not isinstance(payload, dict):
            continue
        bars = payload.get("bars")
        if not isinstance(bars, list):
            continue
        for bar in bars:
            if not isinstance(bar, dict):
                continue
            date10 = str(bar.get("date") or "").strip()
            if len(date10) == 10:
                all_dates.add(date10)
    if not keep_dates:
        return 0, 0

    if all_dates and all_dates.issubset(keep_dates):
        return 0, 0

    keep_date10s = {f"{date8[:4]}-{date8[4:6]}-{date8[6:8]}" for date8 in keep_dates}
    removed_bars = 0
    removed_codes = 0
    for code in list(codes.keys()):
        payload = codes.get(code)
        if not isinstance(payload, dict):
            continue
        bars = payload.get("bars")
        if not isinstance(bars, list):
            continue
        trimmed = [
            bar
            for bar in bars
            if isinstance(bar, dict) and str(bar.get("date") or "").strip() in keep_date10s
        ]
        removed_bars += max(0, len(bars) - len(trimmed))
        if trimmed:
            payload["bars"] = trimmed
        else:
            codes.pop(code, None)
            removed_codes += 1
    if removed_bars or removed_codes:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return removed_bars, removed_codes


def _trim_timestamped_log(path: Path, keep_dates: set[str]) -> int:
    if not path.exists():
        return 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return 0
    dated_lines: list[tuple[str, str]] = []
    for line in lines:
        match = LOG_PREFIX_RE.match(line)
        if not match:
            continue
        dated_lines.append((match.group(1), line))
    if not keep_dates:
        return 0
    keep_date10s = {f"{date8[:4]}-{date8[4:6]}-{date8[6:8]}" for date8 in keep_dates}
    if dated_lines and {date10 for date10, _ in dated_lines}.issubset(keep_date10s):
        return 0
    kept_lines = []
    removed = 0
    for line in lines:
        match = LOG_PREFIX_RE.match(line)
        if not match:
            kept_lines.append(line)
            continue
        if match.group(1) in keep_date10s:
            kept_lines.append(line)
        else:
            removed += 1
    if removed > 0:
        payload = "\n".join(kept_lines)
        if payload:
            payload += "\n"
        path.write_text(payload, encoding="utf-8")
    return removed


def apply_retention_side_effects(*, keep_days: int) -> list[str]:
    notes: list[str] = []
    keep_dates = set(build_retention_date_window(keep_days))
    removed_bars, removed_codes = _trim_recommendation_price_history(
        ONLINE_DIR / "recommendation_price_history.json",
        keep_dates,
    )
    if removed_bars or removed_codes:
        notes.append(
            f"recommendation_price_history.json 已裁剪（删除 {removed_bars} 条 bars / {removed_codes} 个空 code）"
        )
    for log_path in sorted(LOG_DIR.glob("*.log")):
        removed_lines = _trim_timestamped_log(log_path, keep_dates)
        if removed_lines > 0:
            notes.append(f"{log_path.name} 已裁剪（删除 {removed_lines} 行 7 天前日志）")
    return notes


def classify_cache(*, keep_days: int = 7) -> tuple[list[CacheRule], list[CacheRule]]:
    """
    返回：
    - keep_rules: 应保留
    - drop_rules: 可清理
    """
    keep: list[CacheRule] = []
    drop: list[CacheRule] = []
    known_paths: set[Path] = set()
    keep_dates = set(build_retention_date_window(keep_days))

    cache_keep = {
        CACHE_DIR / "pools_cache.json": "离线重建涨停/跌停/炸板池必需",
        CACHE_DIR / "theme_cache.json": "题材映射必需",
        CACHE_DIR / "plate_rotate_cache.json": "板块轮动明细必需",
        CACHE_DIR / "index_kline_cache.json": "指数K线/量能模块依赖",
        CACHE_DIR / "height_trend_cache.json": "高度趋势模块依赖",
        CACHE_DIR / "theme_trend_cache.json": "题材持续性模块依赖",
        CACHE_DIR / "concept_fund_flow_cache.json": "板块排行兜底数据",
        CACHE_DIR / "money_flow_cache.json": "板块流入聚合依赖",
        CACHE_DIR / "learning_notes_history.json": "学习语录去重历史",
        CACHE_DIR / "trade_days_cache.json": "交易日缓存（gen_report_v4 兼容）",
        CACHE_DIR / "stock_research_backtest_source.json": "个股回测 pushed source 历史源数据，会长期保留",
        CACHE_DIR / "account_nav_history.jsonl": "账户净值账本历史，会长期保留",
        CACHE_DIR / "backtest_history.json": "历史回测归档，先保守长期保留",
        CACHE_DIR / "recommendation_tracker.json": "手工推荐跟踪记录，会长期保留",
    }
    online_keep = {
        ONLINE_DIR / "pools_cache.json": "线上/本地复用的三池缓存",
        ONLINE_DIR / "theme_cache.json": "线上/本地复用的题材映射缓存",
        ONLINE_DIR / "plate_rotate_cache.json": "线上/本地复用的轮动缓存",
        ONLINE_DIR / "trade_days_cache.json": "线上/本地复用的交易日缓存",
        ONLINE_DIR / "manifest.json": "线上同步 manifest，会覆盖更新",
        ONLINE_DIR / "recommendation_price_history.json": "价格历史缓存文件保留，但内部会裁到最近 7 个交易日",
    }
    data_keep = {
        DATA_DIR / "account_nav_history.jsonl": "账户净值主账本，会长期保留",
    }
    for path_map in (cache_keep, online_keep, data_keep):
        for path, reason in path_map.items():
            if path.exists():
                keep.append(CacheRule(path, "keep", reason))
                known_paths.add(path)

    known_paths |= _classify_dated_group(
        keep=keep,
        drop=drop,
        files=CACHE_DIR.glob("market_data-*.json"),
        keep_dates=keep_dates,
        extractor=lambda name: _extract_date8(name, MARKET_DATA_RE),
        keep_reason=f"保留最近 {keep_days} 天 market_data 快照",
        drop_reason=f"超出最近 {keep_days} 天的 market_data 快照",
    )
    for key, pattern in DATE8_FILE_PATTERNS.items():
        target_dir = _dated_group_dir(key)
        label = key.replace("_", " ")
        known_paths |= _classify_dated_group(
            keep=keep,
            drop=drop,
            files=target_dir.glob(pattern.pattern.split("^", 1)[1].split("(")[0] + "*"),
            keep_dates=keep_dates,
            extractor=lambda name, _pattern=pattern: _extract_date8(name, _pattern),
            keep_reason=f"保留最近 {keep_days} 天 {label} 缓存",
            drop_reason=f"超出最近 {keep_days} 天的 {label} 缓存",
        )
    if TONGHUASHUN_OUTPUT_DIR.exists():
        known_paths |= _classify_dated_group(
            keep=keep,
            drop=drop,
            files=TONGHUASHUN_OUTPUT_DIR.glob("sync-*.txt"),
            keep_dates=keep_dates,
            extractor=_extract_output_date8,
            keep_reason=f"保留最近 {keep_days} 天同花顺同步输出",
            drop_reason=f"超出最近 {keep_days} 天的同花顺同步输出",
        )

    # v3_quality markdown：当前无代码消费，按临时分析产物处理
    for p in sorted(CACHE_DIR.glob("v3_quality-*.md")):
        drop.append(CacheRule(p, "drop", "未被代码消费的临时分析产物"))
        known_paths.add(p)

    for path in sorted(LOG_DIR.glob("*.log")):
        keep.append(CacheRule(path, "keep", "工作流日志文件保留，但 apply 时会裁到最近 7 天"))
        known_paths.add(path)

    for directory in (CACHE_DIR, ONLINE_DIR, DATA_DIR, LOG_DIR, TONGHUASHUN_OUTPUT_DIR):
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            if path in known_paths:
                continue
            keep.append(CacheRule(path, "keep", "未知文件，保守保留"))
            known_paths.add(path)

    return keep, drop


def sync_online_cache(date10: str, *, mode: str = "minimal") -> tuple[list[Path], Path]:
    date8 = date10.replace("-", "")
    ONLINE_DIR.mkdir(parents=True, exist_ok=True)
    # 这些文件是本地脚本直接写入 cache_online/ 的自有产物，不应在同步时被误删。
    preserve_prefixes = (
        "watchlist_cache-",
        "xuangubao_abnormal-",
        "xuangubao_surge_plates-",
        "eastmoney_tomorrow_themes-",
        "eastmoney_theme_stocks-",
        "ths_newhigh-",
        "intraday_resonance-",
    )
    preserve_names = {
        "recommendation_price_history.json",
        "account_nav_history.jsonl",
    }
    for p in ONLINE_DIR.iterdir():
        if p.is_file():
            if p.name in preserve_names or any(p.name.startswith(prefix) for prefix in preserve_prefixes):
                continue
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


def write_report(keep: list[CacheRule], drop: list[CacheRule], date10: str, mode: str, keep_days: int) -> Path:
    report = ROOT / "cache-cleanup-report.md"
    lines = [
        "# Cache 清理与线上同步报告",
        "",
        f"- 最新报告日期：`{date10}`",
        f"- 线上目录模式：`{mode}`",
        f"- 默认缓存保留天数：`{keep_days}`",
        "",
        "## 当前自动清理策略",
        "",
        f"- `manage_cache.py --apply` 会把 `cache/`、`cache_online/`、`daily_review/output/tonghuashun/` 的日期型缓存统一裁到最近 `{keep_days}` 天。",
        "- `v3_quality-*.md` 这类临时分析产物会直接删除。",
        "- `recommendation_price_history.json` 与 `logs/*.log` 不按文件名滚动，但会在 `--apply` 时做内部裁剪。",
        "- 个股回测 pushed source、净值账本、题材/交易日基础缓存这类长期依赖文件不会按 7 天误删。",
        "",
        "## 当前保留",
        "",
    ]
    for r in sorted(keep, key=lambda x: str(x.path)):
        try:
            display = r.path.relative_to(ROOT)
        except ValueError:
            display = r.path
        lines.append(f"- `{display}`：{r.reason}")
    lines += ["", "## 当前可清理", ""]
    if drop:
        for r in sorted(drop, key=lambda x: str(x.path)):
            try:
                display = r.path.relative_to(ROOT)
            except ValueError:
                display = r.path
            lines.append(f"- `{display}`：{r.reason}")
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
    ap.add_argument("--retention-days", type=int, default=7, help="日期型缓存保留天数")
    ap.add_argument("--apply", action="store_true", help="实际删除建议清理的文件")
    args = ap.parse_args()
    keep_days = max(1, int(args.retention_days or 7))

    d8 = args.date.replace("-", "") if args.date else latest_date8()
    if not d8:
        raise SystemExit("未找到 market_data-*.json，无法确定日期")
    date10 = f"{d8[:4]}-{d8[4:6]}-{d8[6:8]}"

    keep, drop = classify_cache(keep_days=keep_days)
    report = write_report(keep, drop, date10, args.mode, keep_days)

    print(f"报告: {report}")
    print("建议清理：")
    for r in drop:
        print(f" - {r.path}: {r.reason}")

    if args.apply:
        for r in drop:
            if r.path.exists():
                r.path.unlink()
        notes = apply_retention_side_effects(keep_days=keep_days)
        print("已执行清理。")
        for note in notes:
            print(f" - {note}")
        keep, drop = classify_cache(keep_days=keep_days)
        report = write_report(keep, drop, date10, args.mode, keep_days)

    copied, manifest = sync_online_cache(date10, mode=args.mode)
    print(f"线上目录: {ONLINE_DIR}")
    print(f"manifest: {manifest}")
    print("已同步文件：")
    for p in copied:
        print(f" - {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
