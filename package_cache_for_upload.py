#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"


@dataclass
class CheckItem:
    name: str
    path: Path
    required: bool
    ok: bool
    note: str


def read_json_safe(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def date10_to_date8(date10: str) -> str:
    return date10.replace("-", "")


def build_required_files(date10: str, mode: str) -> list[tuple[str, Path, bool]]:
    date8 = date10_to_date8(date10)
    base: list[tuple[str, Path, bool]] = [
        (f"market_data-{date8}.json", CACHE_DIR / f"market_data-{date8}.json", True),
        ("pools_cache.json", CACHE_DIR / "pools_cache.json", True),
        ("theme_cache.json", CACHE_DIR / "theme_cache.json", True),
        ("plate_rotate_cache.json", CACHE_DIR / "plate_rotate_cache.json", True),
        ("trade_days_cache.json", CACHE_DIR / "trade_days_cache.json", True),
    ]
    optional: list[tuple[str, Path, bool]] = [
        ("index_kline_cache.json", CACHE_DIR / "index_kline_cache.json", False),
        ("theme_trend_cache.json", CACHE_DIR / "theme_trend_cache.json", False),
        ("height_trend_cache.json", CACHE_DIR / "height_trend_cache.json", False),
        ("concept_fund_flow_cache.json", CACHE_DIR / "concept_fund_flow_cache.json", False),
        ("money_flow_cache.json", CACHE_DIR / "money_flow_cache.json", False),
    ]
    return base + (optional if mode == "full" else [])


def check_market_data(path: Path) -> tuple[bool, str]:
    data = read_json_safe(path)
    if not isinstance(data, dict):
        return False, "JSON 解析失败"
    ladder = data.get("ladder") or []
    plate_top = data.get("plateRotateTop") or []
    ok_ladder = isinstance(ladder, list) and any(isinstance(x, dict) and x.get("qualityScore") is not None for x in ladder[:5])
    ok_plate = isinstance(plate_top, list) and any(isinstance(x, dict) and (x.get("lead") or x.get("volume") is not None) for x in plate_top[:3])
    if ok_ladder and ok_plate:
        return True, "包含天梯质量分与板块轮动明细"
    if ok_ladder:
        return True, "包含天梯质量分；板块轮动明细可能依赖本地 plate_rotate_cache 回填"
    return False, "缺少新增功能关键字段（qualityScore / plateRotateTop 明细）"


def check_pools_cache(path: Path, date10: str) -> tuple[bool, str]:
    data = read_json_safe(path)
    if not isinstance(data, dict):
        return False, "JSON 解析失败"
    pools = data.get("pools") or {}
    zt = ((pools.get("ztgc") or {}).get(date10) if isinstance(pools, dict) else None) or []
    yest_keys = list((pools.get("ztgc") or {}).keys()) if isinstance(pools, dict) else []
    if isinstance(zt, list) and zt:
        return True, f"当日涨停池存在；缓存交易日 {len(yest_keys)} 个"
    return False, "缺少当日 ztgc 数据"


def check_theme_cache(path: Path) -> tuple[bool, str]:
    data = read_json_safe(path)
    if not isinstance(data, dict):
        return False, "JSON 解析失败"
    codes = data.get("codes") or {}
    if isinstance(codes, dict) and len(codes) >= 10:
        return True, f"题材映射 {len(codes)} 只"
    return False, "题材映射数量过少"


def check_plate_rotate_cache(path: Path, date10: str) -> tuple[bool, str]:
    data = read_json_safe(path)
    if not isinstance(data, dict):
        return False, "JSON 解析失败"
    by_day = data.get("by_day") or {}
    day = (by_day.get(date10) if isinstance(by_day, dict) else None) or {}
    rows = day.get("rows") if isinstance(day, dict) else None
    if isinstance(rows, list) and len(rows) >= 10:
        head = rows[0] if rows and isinstance(rows[0], dict) else {}
        lead = head.get("lead") or "-"
        volume = head.get("volume")
        return True, f"当日 TOP10 存在；首项领涨 {lead}，量能 {volume}"
    return False, "缺少当日板块轮动 TOP10"


def generic_check(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "文件不存在"
    if path.stat().st_size <= 2:
        return False, "文件为空"
    return True, f"大小 {path.stat().st_size} bytes"


def run_checks(date10: str, mode: str) -> list[CheckItem]:
    out: list[CheckItem] = []
    for name, path, required in build_required_files(date10, mode):
        if not path.exists():
            out.append(CheckItem(name=name, path=path, required=required, ok=False, note="文件不存在"))
            continue
        if name.startswith("market_data-"):
            ok, note = check_market_data(path)
        elif name == "pools_cache.json":
            ok, note = check_pools_cache(path, date10)
        elif name == "theme_cache.json":
            ok, note = check_theme_cache(path)
        elif name == "plate_rotate_cache.json":
            ok, note = check_plate_rotate_cache(path, date10)
        else:
            ok, note = generic_check(path)
        out.append(CheckItem(name=name, path=path, required=required, ok=ok, note=note))
    return out


def write_report(date10: str, mode: str, checks: list[CheckItem]) -> Path:
    date8 = date10_to_date8(date10)
    report_path = ROOT / f"cache-upload-check-{date8}.md"
    required_ok = all(x.ok for x in checks if x.required)
    lines = [
        f"# Cache 上传检查报告",
        "",
        f"- 日期：`{date10}`",
        f"- 模式：`{mode}`",
        f"- 结论：`{'可上传' if required_ok else '不可上传'}`",
        "",
        "## 检查结果",
        "",
    ]
    for x in checks:
        flag = "✅" if x.ok else ("❌" if x.required else "⚠️")
        req = "必需" if x.required else "可选"
        lines.append(f"- {flag} `{x.name}`：{req}，{x.note}")
    lines += [
        "",
        "## 远端建议",
        "",
        "- 远端只做 `./qr.sh render YYYY-MM-DD` 或 `./qr.sh deploy` 时，至少上传必需文件。",
        "- 若远端也需要更完整的离线能力，可一并上传可选文件。",
        "- 若远端无法联网抓板块轮动，`plate_rotate_cache.json` 必须保留。",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def build_bundle(date10: str, mode: str, checks: list[CheckItem], include_optionals_when_ok: bool = True) -> Path:
    date8 = date10_to_date8(date10)
    bundle_path = ROOT / f"cache-upload-bundle-{date8}-{mode}.tar.gz"
    report_path = write_report(date10, mode, checks)
    with tarfile.open(bundle_path, "w:gz") as tar:
        for item in checks:
            if not item.ok:
                continue
            if not item.required and not include_optionals_when_ok:
                continue
            tar.add(item.path, arcname=f"cache/{item.path.name}")
        tar.add(report_path, arcname=report_path.name)
    return bundle_path


def main() -> int:
    ap = argparse.ArgumentParser(description="检查并打包 cache 上传包")
    ap.add_argument("--date", required=True, help="报告日期，格式 YYYY-MM-DD")
    ap.add_argument("--mode", choices=["minimal", "full"], default="minimal", help="minimal=最小上传包，full=带更多可选缓存")
    args = ap.parse_args()

    checks = run_checks(args.date, args.mode)
    report_path = write_report(args.date, args.mode, checks)
    required_ok = all(x.ok for x in checks if x.required)

    print(f"检查报告: {report_path}")
    for x in checks:
        req = "required" if x.required else "optional"
        print(f"[{'OK' if x.ok else 'NO'}] {req:<8} {x.name:<28} {x.note}")

    if not required_ok:
        print("存在必需文件缺失/不满足，未生成上传包。")
        return 2

    bundle_path = build_bundle(args.date, args.mode, checks, include_optionals_when_ok=True)
    print(f"上传包: {bundle_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
