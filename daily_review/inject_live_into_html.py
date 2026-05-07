#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把“实时盯盘 live 数据”直接注入到已渲染的 HTML 里（避免前端 fetch）。

用法：
  python -m daily_review.inject_live_into_html --html path/to/index.html
  python -m daily_review.inject_live_into_html --html a.html --html b.html --date 20260429

实现：
- 从 HTML 中定位：const __INJECTED_MARKET_DATA__ = {...};
- 解析 JSON，写入 md["live"]，并设置 md["meta"]["live_embedded"]=true
- 保留原有的其它字段（EOD/其它模块不变），只更新实时模块所需 live
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

from daily_review.realtime_watch import build_live_snapshot


BJ_TZ = timezone(timedelta(hours=8))


def _now_bj() -> datetime:
    return datetime.now(BJ_TZ)


_RE = re.compile(
    r"(const\s+__INJECTED_MARKET_DATA__\s*=\s*)(\{.*\})(\s*;?)"
)


def _inject_one(html_path: Path, date8: str | None) -> None:
    text = html_path.read_text(encoding="utf-8")
    m = _RE.search(text)
    if not m:
        raise RuntimeError(f"找不到 __INJECTED_MARKET_DATA__ 注入点：{html_path}")

    payload = m.group(2)

    md: Dict[str, Any] = json.loads(payload)

    # live 快照（AkShare 主用 + 必盈兜底，口径与 realtime_watch.py 保持一致）
    live = build_live_snapshot(date8).to_dict()
    md["live"] = live

    meta = md.get("meta") if isinstance(md.get("meta"), dict) else {}
    meta = dict(meta)
    meta["live_embedded"] = True
    meta.setdefault("rendered_at_bj", _now_bj().strftime("%Y-%m-%d %H:%M:%S"))
    md["meta"] = meta

    new_payload = json.dumps(md, ensure_ascii=False, separators=(",", ":"))
    new_text = text[: m.start(2)] + new_payload + text[m.end(2) :]
    html_path.write_text(new_text, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", action="append", required=True, help="要注入的 HTML 文件路径，可重复传入多个")
    ap.add_argument("--date", default="", help="YYYYMMDD；为空则取北京时间今天")
    args = ap.parse_args()

    date8 = args.date.strip() or _now_bj().strftime("%Y%m%d")
    for p in args.html:
        _inject_one(Path(p), date8)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
