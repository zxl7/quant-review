#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
v3 数据质量检查工具

用途：
1) 校验 v3 11 个模块是否都有输出且无 error
2) 校验关键字段取值范围（score/confidence/仓位等）
3) 输出一份 Markdown 报告到 cache/

运行示例：
PYTHONPATH=. python3 -m daily_review.v3_quality --date 2026-04-28
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple


V3_KEYS = [
    "collapseChain",
    "sentiment",
    "dujie",
    "dragon",
    "mainstream",
    "tradingNature",
    "rightside",
    "positionV3",
    "rebound",
    "fullPosition",
    "reflexivity",
]


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        if isinstance(v, str) and v.endswith("%"):
            v = v[:-1]
        return float(v)
    except Exception:
        return default


def _pct01(v: Any) -> float:
    # 允许 0~1 或 0~100
    x = _to_float(v, 0.0)
    return x / 100.0 if x > 1.01 else x


def _get(d: Dict[str, Any], path: str) -> Any:
    cur: Any = d
    for p in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def audit_v3_market_data(market_data: Dict[str, Any]) -> Dict[str, Any]:
    v3 = market_data.get("v3") if isinstance(market_data.get("v3"), dict) else {}

    missing = [k for k in V3_KEYS if k not in v3]
    errors = []
    for k in V3_KEYS:
        obj = v3.get(k)
        if isinstance(obj, dict) and obj.get("error"):
            errors.append((k, str(obj.get("error"))))

    checks: List[Tuple[str, bool, str]] = []

    # 关键范围
    score = _to_float(_get(v3, "sentiment.score"), -1)
    checks.append(("sentiment.score 0~10", 0 <= score <= 10, f"{score}"))

    # confidence 0~100（多个模块）
    for key in ["sentiment", "dujie", "dragon", "mainstream", "rightside", "positionV3", "rebound", "fullPosition", "reflexivity", "collapseChain"]:
        c = _to_float(_get(v3, f"{key}.confidence"), None)
        if c is not None and c != 0:
            checks.append((f"{key}.confidence 0~100", 0 <= c <= 100, f"{c}"))

    # 仓位 0~1
    cap = _pct01(_get(v3, "positionV3.capital_pct_adjusted"))
    checks.append(("positionV3.capital_pct_adjusted 0~1", 0 <= cap <= 1.0, f"{cap:.2f}"))

    # 右侧 allowed 布尔
    allowed = _get(v3, "rightside.allowed")
    if allowed is None:
        allowed = _get(v3, "rightside.allowed")  # keep
    if allowed is not None:
        checks.append(("rightside.allowed is bool", isinstance(allowed, bool), str(allowed)))

    return {
        "missing_keys": missing,
        "error_items": errors,
        "checks": [{"name": n, "ok": ok, "value": v} for n, ok, v in checks],
    }


def render_report(date: str, market_path: Path) -> str:
    md = json.loads(market_path.read_text(encoding="utf-8"))
    r = audit_v3_market_data(md)
    ok_checks = sum(1 for x in r["checks"] if x["ok"])
    total_checks = len(r["checks"])

    lines = []
    lines.append(f"# v3 数据质量报告（{date}）")
    lines.append("")
    lines.append(f"- v3 keys 缺失：{len(r['missing_keys'])}")
    if r["missing_keys"]:
        lines.append("  - " + ", ".join(r["missing_keys"]))
    lines.append(f"- v3 模块 error：{len(r['error_items'])}")
    for k, e in r["error_items"]:
        lines.append(f"  - {k}: {e}")
    lines.append(f"- 范围/类型检查通过：{ok_checks}/{total_checks}")
    lines.append("")
    lines.append("## 检查明细")
    for x in r["checks"]:
        lines.append(f"- [{'OK' if x['ok'] else 'FAIL'}] {x['name']} = {x['value']}")
    lines.append("")

    # 关键摘要（便于人工快速看）
    v3 = md.get("v3") if isinstance(md.get("v3"), dict) else {}
    lines.append("## 快速摘要")
    lines.append(f"- 情绪：{_get(v3,'sentiment.score')}｜{_get(v3,'sentiment.phase')}｜风险：{_get(v3,'sentiment.risk_level')}")
    lines.append(f"- 主线：{_get(v3,'mainstream.mainline.top_sector')}｜exists={_get(v3,'mainstream.mainline.exists')}")
    lines.append(f"- 右侧：allowed={_get(v3,'rightside.allowed')}｜score={_get(v3,'rightside.score')}")
    lines.append(f"- 仓位：{_get(v3,'positionV3.capital_pct_adjusted')}")
    lines.append(f"- 反弹：{_get(v3,'rebound.phase.label') or _get(v3,'rebound.phase')}")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--cache-dir", default="cache", help="cache 目录（默认 cache）")
    args = ap.parse_args()

    root = Path(".")
    cache_dir = root / args.cache_dir
    market_path = cache_dir / f"market_data-{args.date.replace('-','')}.json"
    if not market_path.exists():
        raise SystemExit(f"找不到 {market_path}")

    report = render_report(args.date, market_path)
    out_path = cache_dir / f"v3_quality-{args.date.replace('-','')}.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"✅ 已生成：{out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

