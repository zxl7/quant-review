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
import subprocess
import sys
from pathlib import Path

from daily_review.modules.registry import apply_modules, available_modules
from daily_review.render.render_html import render_html_template


def _workspace_root() -> Path:
    # /workspace/daily_review/cli.py -> /workspace
    return Path(__file__).resolve().parent.parent


def run_full(date: str | None) -> int:
    """
    全量更新：仍然调用现有 gen_report_v4.py（保持行为不变）
    """
    script = _workspace_root() / "gen_report_v4.py"
    cmd = [sys.executable, str(script)]
    if date:
        cmd.append(date)
    return subprocess.call(cmd)


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
    market_data = apply_modules(market_data, modules)

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
    ap.add_argument("--only", nargs="+", help=f"部分更新：指定模块名，可选：{', '.join(available_modules())}")
    args = ap.parse_args(argv)

    if args.only:
        if not args.date:
            raise SystemExit("--only 模式必须指定 --date")
        return run_partial(args.date, args.only)

    return run_full(args.date)


if __name__ == "__main__":
    raise SystemExit(main())
