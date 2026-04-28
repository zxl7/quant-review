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
from pathlib import Path
from typing import Any, Dict, List, Literal, Tuple


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


Level = Literal["OK", "WARN", "FAIL"]


def _is_blank(x: Any) -> bool:
    if x is None:
        return True
    if isinstance(x, str) and not x.strip():
        return True
    return False


def _in_range(x: float, lo: float, hi: float) -> bool:
    return lo <= x <= hi


def audit_v3_market_data(market_data: Dict[str, Any], *, strict: bool = True) -> Dict[str, Any]:
    v3 = market_data.get("v3") if isinstance(market_data.get("v3"), dict) else {}

    missing = [k for k in V3_KEYS if k not in v3]
    errors = []
    for k in V3_KEYS:
        obj = v3.get(k)
        if isinstance(obj, dict) and obj.get("error"):
            errors.append((k, str(obj.get("error"))))

    checks: List[Dict[str, Any]] = []

    def add_check(name: str, ok: bool, value: Any = "", *, level: Level | None = None, hint: str = "") -> None:
        if level is None:
            level = "OK" if ok else "FAIL"
        checks.append({"name": name, "level": level, "ok": bool(ok), "value": value, "hint": hint})

    # 关键范围
    score = _to_float(_get(v3, "sentiment.score"), -1)
    add_check("sentiment.score 0~10", _in_range(score, 0, 10), score)

    # confidence 0~100（多个模块）
    for key in ["sentiment", "dujie", "dragon", "mainstream", "rightside", "positionV3", "rebound", "fullPosition", "reflexivity", "collapseChain"]:
        c = _to_float(_get(v3, f"{key}.confidence"), None)
        if c is not None:
            # strict 模式：confidence=0 视为告警（通常意味着降级/兜底/无数据）
            if strict and float(c) == 0:
                add_check(f"{key}.confidence > 0", False, c, level="WARN", hint="confidence=0 通常表示模块未能给出有效判断")
            else:
                add_check(f"{key}.confidence 0~100", _in_range(float(c), 0, 100), c)

    # 仓位 0~1
    cap = _pct01(_get(v3, "positionV3.capital_pct_adjusted"))
    add_check("positionV3.capital_pct_adjusted 0~1", _in_range(cap, 0, 1.0), round(cap, 4))

    # 右侧 allowed 布尔
    allowed = _get(v3, "rightside.allowed")
    if allowed is not None:
        add_check("rightside.allowed is bool", isinstance(allowed, bool), allowed)

    # ========= strict：结构/关键字段质量 =========
    if strict:
        # 统一：v3 11模块必须齐全
        add_check("v3 keys 完整", len(missing) == 0, ", ".join(missing) if missing else "OK")
        add_check("v3 模块无 error", len(errors) == 0, f"{len(errors)}", level="FAIL" if errors else "OK", hint="任一模块输出 error 即视为失败")

        # 1) sentiment 关键字段
        add_check("sentiment.phase 非空", not _is_blank(_get(v3, "sentiment.phase")), _get(v3, "sentiment.phase"))
        dim = _get(v3, "sentiment.dim_scores")
        add_check("sentiment.dim_scores 为 dict", isinstance(dim, dict), type(dim).__name__)
        if isinstance(dim, dict):
            add_check("sentiment.dim_scores 维度>=6", len(dim) >= 6, len(dim))
            # 每一维 0~10
            for k, vv in list(dim.items())[:10]:
                x = _to_float(vv, -1)
                add_check(f"dim_scores.{k} 0~10", _in_range(x, 0, 10), x, level="FAIL" if not _in_range(x, 0, 10) else "OK")

        # 2) collapseChain
        add_check("collapseChain.level 非空", not _is_blank(_get(v3, "collapseChain.level")), _get(v3, "collapseChain.level"))
        cc_score = _to_float(_get(v3, "collapseChain.score"), -1)
        add_check("collapseChain.score >= 0", cc_score >= 0, cc_score)

        # 3) rightside
        rs_score = _to_float(_get(v3, "rightside.score"), -1)
        add_check("rightside.score 0~5", _in_range(rs_score, 0, 5), rs_score)
        sigs = _get(v3, "rightside.signals")
        add_check("rightside.signals 为 dict", isinstance(sigs, dict), type(sigs).__name__)
        if isinstance(sigs, dict):
            add_check("rightside.signals 数量>=5", len(sigs) >= 5, len(sigs), level="WARN" if len(sigs) < 5 else "OK")

        # 4) positionV3
        win_rate = _to_float(_get(v3, "positionV3.win_rate"), -1)
        add_check("positionV3.win_rate 0~100", _in_range(win_rate, 0, 100), win_rate)
        tier = _get(v3, "positionV3.tier")
        add_check("positionV3.tier 非空", not _is_blank(tier), tier)
        t1p = _get(v3, "positionV3.t1_penalty")
        add_check("positionV3.t1_penalty 为 dict", isinstance(t1p, dict), type(t1p).__name__, level="WARN" if not isinstance(t1p, dict) else "OK")

        # 5) rebound
        rb = _get(v3, "rebound.phase")
        if isinstance(rb, dict):
            add_check("rebound.phase.label 非空", not _is_blank(rb.get("label")), rb.get("label"))
        else:
            add_check("rebound.phase 为 dict", False, type(rb).__name__)
        rb_detail = _get(v3, "rebound.detail.signals")
        if rb_detail is not None:
            add_check("rebound.detail.signals 为 list", isinstance(rb_detail, list), type(rb_detail).__name__, level="WARN" if not isinstance(rb_detail, list) else "OK")

        # 6) fullPosition
        pc = _to_float(_get(v3, "fullPosition.passed_count"), -1)
        add_check("fullPosition.passed_count 0~3", _in_range(pc, 0, 3), pc)
        mpos = _pct01(_get(v3, "fullPosition.max_recommended_position"))
        add_check("fullPosition.max_recommended_position 0~1", _in_range(mpos, 0, 1.0), round(mpos, 4))

        # 7) mainstream
        ml_exists = _get(v3, "mainstream.mainline.exists")
        add_check("mainstream.mainline.exists 为 bool", isinstance(ml_exists, bool), ml_exists)
        top_sector = _get(v3, "mainstream.mainline.top_sector")
        # exists True 时必须给 top_sector；exists False 时为空/未知允许但告警
        if isinstance(ml_exists, bool) and ml_exists:
            add_check("mainline.top_sector 非空(主线存在)", not _is_blank(top_sector), top_sector)
        else:
            if _is_blank(top_sector) or str(top_sector).strip() in {"未知板块", "未知", "-"}:
                add_check("mainline.top_sector(主线未识别)", True, top_sector, level="WARN", hint="主线未识别在某些交易日合理，但会降低 v3 指导力度")
            else:
                add_check("mainline.top_sector(存在但不强制)", True, top_sector)

        # 8) tradingNature
        tn = _get(v3, "tradingNature.nature")
        add_check("tradingNature.nature 为 dict", isinstance(tn, dict), type(tn).__name__)
        if isinstance(tn, dict):
            add_check("tradingNature.nature.label 非空", not _is_blank(tn.get("label")), tn.get("label"))
            add_check("tradingNature.nature.max_position 非空", not _is_blank(tn.get("max_position")), tn.get("max_position"))
            add_check("tradingNature.nature.stop_loss 非空", not _is_blank(tn.get("stop_loss")), tn.get("stop_loss"), level="WARN" if _is_blank(tn.get("stop_loss")) else "OK")

        # 9) reflexivity
        cyc = _get(v3, "reflexivity.cycle")
        add_check("reflexivity.cycle 为 dict", isinstance(cyc, dict), type(cyc).__name__)
        if isinstance(cyc, dict):
            add_check("reflexivity.cycle.cycle_position 非空", not _is_blank(cyc.get("cycle_position")), cyc.get("cycle_position"))
            add_check("reflexivity.cycle.risk_level 非空", not _is_blank(cyc.get("risk_level")), cyc.get("risk_level"))
        psy = _get(v3, "reflexivity.psychology")
        add_check("reflexivity.psychology 为 dict", isinstance(psy, dict), type(psy).__name__, level="WARN" if not isinstance(psy, dict) else "OK")

        # 10) dujie / dragon（条件型：只有在存在“可分析对象”时才强制）
        mi = _get(market_data, "features.mood_inputs") or {}
        max_lb = int(_to_float(mi.get("max_lb"), 0)) if isinstance(mi, dict) else 0

        dj_stocks = _get(v3, "dujie.stocks")
        if max_lb >= 3:
            add_check("dujie.stocks 为 list(>=3板时)", isinstance(dj_stocks, list), type(dj_stocks).__name__)
        else:
            if dj_stocks is None:
                add_check("dujie.stocks(无高标日可缺省)", True, "-", level="OK")
            elif isinstance(dj_stocks, list):
                add_check("dujie.stocks(无高标日允许为空)", True, len(dj_stocks), level="OK")
            else:
                add_check("dujie.stocks 类型", False, type(dj_stocks).__name__, level="WARN")

        dr_rank = _get(v3, "dragon.rankings")
        if max_lb >= 2:
            add_check("dragon.rankings 为 list(>=2板时)", isinstance(dr_rank, list), type(dr_rank).__name__)
        else:
            add_check("dragon.rankings(低高度日可为空)", True, "-" if dr_rank is None else (len(dr_rank) if isinstance(dr_rank, list) else type(dr_rank).__name__), level="OK")

    return {
        "missing_keys": missing,
        "error_items": errors,
        "checks": checks,
    }


def render_report(date: str, market_path: Path, *, strict: bool = True) -> str:
    md = json.loads(market_path.read_text(encoding="utf-8"))
    r = audit_v3_market_data(md, strict=strict)
    ok_checks = sum(1 for x in r["checks"] if x["level"] == "OK")
    warn_checks = sum(1 for x in r["checks"] if x["level"] == "WARN")
    fail_checks = sum(1 for x in r["checks"] if x["level"] == "FAIL")
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
    lines.append(f"- 检查结果：OK {ok_checks} / WARN {warn_checks} / FAIL {fail_checks}（共 {total_checks}）")
    lines.append("")
    lines.append("## 检查明细")
    for x in r["checks"]:
        mark = x["level"]
        hint = f"｜{x['hint']}" if x.get("hint") else ""
        lines.append(f"- [{mark}] {x['name']} = {x.get('value','')}{hint}")
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
    ap.add_argument("--loose", action="store_true", help="宽松模式：仅检查结构/范围，不做关键字段质量的严格校验")
    args = ap.parse_args()

    root = Path(".")
    cache_dir = root / args.cache_dir
    market_path = cache_dir / f"market_data-{args.date.replace('-','')}.json"
    if not market_path.exists():
        raise SystemExit(f"找不到 {market_path}")

    report = render_report(args.date, market_path, strict=(not args.loose))
    out_path = cache_dir / f"v3_quality-{args.date.replace('-','')}.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"✅ 已生成：{out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
