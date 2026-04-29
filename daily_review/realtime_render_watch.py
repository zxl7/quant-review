#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定时渲染“盯盘页”（不依赖浏览器 fetch）

目标：
- 每次执行都生成一个全新的、可直接打开的 HTML（已内嵌 marketData.live）
- 解决 file:// 场景无法 fetch latest_intraday.json 的问题
- 数据源保持一致：优先 AkShare，必要时必盈兜底（与 realtime_watch.py 同口径）
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

from daily_review.realtime_watch import build_live_snapshot
from daily_review.render.render_html import render_html_template


BJ_TZ = timezone(timedelta(hours=8))


def _now_bj() -> datetime:
    return datetime.now(BJ_TZ)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="YYYYMMDD；为空取北京时间今天")
    ap.add_argument("--out", required=True, help="输出 HTML 文件路径")
    args = ap.parse_args()

    now = _now_bj()
    date8 = args.date.strip() or now.strftime("%Y%m%d")
    date10 = f"{date8[:4]}-{date8[4:6]}-{date8[6:8]}"
    out = Path(args.out)

    live = build_live_snapshot(date8).to_dict()

    # 只注入盯盘页用到的最小集合；其它模块保持空，避免误导
    market_data: Dict[str, Any] = {
        "date": date10,
        "meta": {
            "default_page": "watch",  # 让页面打开默认切到“实时盯盘”
        },
        "live": live,
        # 兼容字段：没有就空（前端会优雅降级）
        "moodSignals": None,
        "intradaySnapshots": None,
    }

    template_path = Path(__file__).resolve().parent.parent / "templates" / "report_template.html"
    render_html_template(
        template_path=template_path,
        output_path=out,
        market_data=market_data,
        report_date=date10,
        date_note="盯盘页（定时渲染）",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
