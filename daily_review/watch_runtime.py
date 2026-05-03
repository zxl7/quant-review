#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from daily_review.realtime_watch import build_live_snapshot


def _workspace_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _to_num(v: Any, d: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return d
        if isinstance(v, str):
            return float(v.replace("%", "").strip())
        return float(v)
    except Exception:
        return d


def _date10_to_8(date10: str) -> str:
    return str(date10 or "").replace("-", "")


def _intraday_slices_path(root: Path, date10: str) -> Path:
    return root / "cache" / f"intraday_slices-{_date10_to_8(date10)}.json"


def _normalize_slot_label(ts_bj: str) -> str:
    slots = ["09:35", "10:05", "10:35", "11:05", "13:05", "13:35", "14:05", "14:35"]
    raw = str(ts_bj or "")[11:16] if len(str(ts_bj or "")) >= 16 else str(ts_bj or "")
    try:
        hh, mm = raw.split(":")
        cur = int(hh) * 60 + int(mm)
    except Exception:
        return raw or slots[-1]
    slot_minutes = []
    for s in slots:
        sh, sm = s.split(":")
        slot_minutes.append((int(sh) * 60 + int(sm), s))
    eligible = [label for minute, label in slot_minutes if minute <= cur]
    if eligible:
        return eligible[-1]
    return slots[0]


def _calc_shift_score(rec: dict[str, Any]) -> int:
    fb = _to_num(rec.get("fb"), 0)
    jj = _to_num(rec.get("jj"), 0)
    zb = _to_num(rec.get("zb"), 0)
    dt = _to_num(rec.get("dt"), 0)
    max_lb = _to_num(rec.get("max_lb"), 0)
    lianban = _to_num(rec.get("lianban"), 0)
    score = (
        fb * 0.28
        + jj * 0.24
        + max(0.0, 100.0 - zb) * 0.18
        + max(0.0, 100.0 - dt * 7.0) * 0.12
        + min(max_lb * 14.0, 100.0) * 0.10
        + min(lianban * 5.0, 100.0) * 0.08
    )
    return int(round(max(0.0, min(100.0, score))))


def _shift_label(score: int) -> str:
    if score >= 72:
        return "走强"
    if score >= 60:
        return "修复"
    if score >= 48:
        return "分歧"
    if score >= 36:
        return "走弱"
    return "退潮"


def _shift_note(curr: dict[str, Any], prev: dict[str, Any] | None) -> str:
    if not prev:
        return "盘中实时切片已接入，可逐点观察情绪变化。"
    diff = int(curr.get("shift_score", 0) or 0) - int(prev.get("shift_score", 0) or 0)
    if diff >= 5:
        return "承接增强、分歧收敛，情绪明显回暖。"
    if diff >= 2:
        return "情绪边际修复，但仍需确认持续性。"
    if diff <= -5:
        return "炸板/跌停抬升，情绪明显走弱。"
    if diff <= -2:
        return "情绪略有回落，注意午后分歧。"
    return "情绪整体平稳，维持当前节奏。"


def _build_slice(snapshot: dict[str, Any], prev: dict[str, Any] | None = None) -> dict[str, Any]:
    market = snapshot.get("market") or {}
    ts_bj = str(snapshot.get("ts_bj") or "")
    zt = int(round(_to_num(market.get("zt"), 0)))
    zab = int(round(_to_num(market.get("zab"), 0)))
    dt = int(round(_to_num(market.get("dt"), 0)))
    lianban = int(round(_to_num(market.get("lianban"), 0)))
    max_lb = int(round(_to_num(market.get("max_lianban"), 0)))
    zb = round(_to_num(market.get("zab_rate"), 0), 1)
    fb = round(zt / max(zt + zab, 1) * 100.0, 1)
    jj = round(lianban / max(zt, 1) * 100.0, 1)
    heat = int(round(max(0.0, min(100.0, 0.42 * fb + 0.24 * jj + min(zt, 100) * 0.16 + min(max_lb * 12.0, 100) * 0.18))))
    risk = int(round(max(0.0, min(100.0, zb * 0.55 + min(dt * 5.0, 100.0) * 0.30 + min(zab * 3.0, 100.0) * 0.15))))
    slot_time = _normalize_slot_label(ts_bj)
    rec = {
        "time": slot_time,
        "ts_bj": ts_bj,
        "date": str(snapshot.get("date") or ""),
        "source": "intraday_live",
        "provider": str(snapshot.get("source") or ""),
        "zt": zt,
        "dt": dt,
        "zab": zab,
        "zb": zb,
        "fb": fb,
        "jj": jj,
        "lianban": lianban,
        "max_lb": max_lb,
        "heat": heat,
        "risk": risk,
        "headline": "",
        "concepts": [
            {"name": c.get("name"), "lead": c.get("lead"), "chg_pct": c.get("chg_pct")}
            for c in (snapshot.get("concepts") or [])[:5]
            if isinstance(c, dict) and c.get("name")
        ],
        "alerts": snapshot.get("alerts") or [],
    }
    rec["shift_score"] = _calc_shift_score(rec)
    rec["shift_label"] = _shift_label(rec["shift_score"])
    rec["headline"] = rec["shift_label"]
    rec["note"] = _shift_note(rec, prev)
    return rec


def append_intraday_slice(*, root: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    date10 = str(snapshot.get("date") or "")
    path = _intraday_slices_path(root, date10)
    rows = _read_json(path, default=[])
    if not isinstance(rows, list):
        rows = []
    prev = rows[-1] if rows and isinstance(rows[-1], dict) else None
    rec = _build_slice(snapshot, prev)
    out: list[dict[str, Any]] = []
    replaced = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized_row = dict(row)
        normalized_row["time"] = _normalize_slot_label(str(row.get("time") or row.get("ts_bj") or ""))
        if normalized_row.get("time") == rec.get("time"):
            if not replaced:
                out.append(rec)
                replaced = True
            continue
        out.append(normalized_row)
    if not replaced:
        out.append(rec)

    dedup: dict[str, dict[str, Any]] = {}
    for row in out:
        if not isinstance(row, dict):
            continue
        key = str(row.get("time") or "")
        dedup[key] = row
    ordered_slots = ["09:35", "10:05", "10:35", "11:05", "13:05", "13:35", "14:05", "14:35"]
    out = [dedup[s] for s in ordered_slots if s in dedup][-32:]
    _write_json(path, out)
    return {
        "date": date10,
        "count": len(out),
        "interval_min": 30,
        "simulated": False,
        "snapshots": out,
        "latest": out[-1] if out else None,
        "updated_at": rec.get("ts_bj"),
    }


def publish_runtime_files(*, root: Path, latest_snapshot: dict[str, Any], slices_payload: dict[str, Any]) -> None:
    html_dir = root / "html"
    _write_json(html_dir / "latest_intraday.json", latest_snapshot)
    _write_json(html_dir / "latest_intraday_slices.json", slices_payload)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成实时盯盘切片 JSON")
    ap.add_argument("--date", default="", help="YYYYMMDD；为空取北京时间今天")
    ap.add_argument("--publish", action="store_true", help="同时输出 html/latest_intraday*.json")
    args = ap.parse_args()

    root = _workspace_root()
    snap = build_live_snapshot(args.date.strip() or None).to_dict()
    payload = append_intraday_slice(root=root, snapshot=snap)
    if args.publish:
        publish_runtime_files(root=root, latest_snapshot=snap, slices_payload=payload)
    print(f"✅ 实时切片已写入: {_intraday_slices_path(root, str(snap.get('date') or ''))}")
    if args.publish:
        print("✅ 已发布 latest_intraday.json / latest_intraday_slices.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
