#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BJ_TZ = timezone(timedelta(hours=8))

from daily_review.realtime_watch import build_live_snapshot
from daily_review.data.biying import resolve_trade_date
from daily_review.http import HttpClient
from daily_review.config import load_config_from_env
from daily_review.metrics.scoring import blend_sentiment_score


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


def _date8_to_10(date8: str) -> str:
    """纯函数：YYYYMMDD -> YYYY-MM-DD。"""
    d8 = str(date8 or "").strip()
    if len(d8) == 8 and d8.isdigit():
        return f"{d8[:4]}-{d8[4:6]}-{d8[6:8]}"
    return d8


def _purge_previous_day_published(*, root: Path, keep_date10: str) -> None:
    """清理前一天的已发布文件（latest_intraday*.json），确保每天重建。"""
    html_dir = root / "html"
    keep_date8 = _date10_to_8(keep_date10)
    # 清理 latest_intraday.json（单日快照）
    lip = html_dir / "latest_intraday.json"
    if lip.exists():
        try:
            data = json.loads(lip.read_text(encoding="utf-8"))
            d = str(data.get("date") or "")
            if d != keep_date10 and _date10_to_8(d) != keep_date8:
                lip.unlink()
        except Exception:
            pass
    # 清理 latest_intraday_slices.json（盘中切片）
    lsp = html_dir / "latest_intraday_slices.json"
    if lsp.exists():
        try:
            data = json.loads(lsp.read_text(encoding="utf-8"))
            d = str(data.get("date") or "")
            if d != keep_date10 and _date10_to_8(d) != keep_date8:
                lsp.unlink()
        except Exception:
            pass


def _purge_previous_day_slices(*, root: Path, keep_date10: str) -> None:
    """执行前清理前一日及更早的盘中切片缓存，仅保留当日文件。"""
    cache_dir = root / "cache"
    keep_date8 = _date10_to_8(keep_date10)
    for p in cache_dir.glob("intraday_slices-*.json"):
        stem = p.stem  # intraday_slices-YYYYMMDD
        d8 = stem.replace("intraday_slices-", "", 1)
        if d8 != keep_date8:
            try:
                p.unlink()
            except Exception:
                continue


# 盘中快照粒度（分钟）
INTRADAY_INTERVAL_MIN = 10
# 单日最多保留的盘中节点（10 分钟粒度下可覆盖约 2 个交易日）
INTRADAY_SLICE_MAX = 48


def _read_slices_rows(path: Path) -> list[dict[str, Any]]:
    raw = _read_json(path, default=None)
    if raw is None:
        return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        sn = raw.get("snapshots")
        if isinstance(sn, list):
            return [x for x in sn if isinstance(x, dict)]
    return []


def _row_ts_bj(row: dict[str, Any], fallback_date10: str) -> str:
    t = str(row.get("ts_bj") or "").strip()
    if t:
        return t
    d = str(row.get("date") or fallback_date10 or "").strip()
    tm = str(row.get("time") or "").strip()
    if len(tm) == 5 and tm[2] == ":":
        return f"{d} {tm}:00"
    if len(tm) >= 8 and tm[2] == ":" and tm[5] == ":":
        return f"{d} {tm}"
    return f"{d} 00:00:00"


def _display_time_from_ts_bj(ts_bj: str) -> str:
    s = str(ts_bj or "").strip()
    if len(s) >= 19:
        return s[11:19]
    if len(s) >= 16:
        return s[11:16]
    return s or "—"


def _normalize_slice_row(row: dict[str, Any], date10: str) -> dict[str, Any]:
    """补齐旧数据缺失的 ts_bj / time，避免排序与去重异常。"""
    r = dict(row)
    if not str(r.get("ts_bj") or "").strip():
        r["ts_bj"] = _row_ts_bj(r, date10)
    r["time"] = _display_time_from_ts_bj(str(r.get("ts_bj") or ""))
    if not r.get("date"):
        r["date"] = date10
    return r


def _prev_row_for_ts(rows: list[dict[str, Any]], curr_ts_bj: str, date10: str) -> dict[str, Any] | None:
    prev: dict[str, Any] | None = None
    for r in sorted(rows, key=lambda x: _row_ts_bj(x, date10)):
        t = _row_ts_bj(r, date10)
        if t < curr_ts_bj:
            prev = r
        elif t >= curr_ts_bj:
            break
    return prev


def _calc_shift_score(rec: dict[str, Any]) -> int:
    heat = _to_num(rec.get("heat"), 0)
    risk = _to_num(rec.get("risk"), 0)
    return int(blend_sentiment_score(heat=heat, risk=risk))


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
    rec = {
        "time": _display_time_from_ts_bj(ts_bj),
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
        "bf": 0,  # 盘中难以精确获取大面，设为0占位
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
    rows = [_normalize_slice_row(r, date10) for r in _read_slices_rows(path)]
    ts_bj = str(snapshot.get("ts_bj") or "").strip()
    if not ts_bj:
        ts_bj = datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")
    snap2 = dict(snapshot)
    snap2["ts_bj"] = ts_bj
    prev = _prev_row_for_ts(rows, ts_bj, date10)
    rec = _build_slice(snap2, prev)
    merged: list[dict[str, Any]] = []
    seen_ts = rec.get("ts_bj") or ts_bj
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _row_ts_bj(row, date10) == seen_ts:
            continue
        # 过滤掉非当天的旧数据（ts_bj 前 10 位是日期 YYYY-MM-DD）
        row_ts = _row_ts_bj(row, date10)
        if row_ts[:10] != date10:
            continue
        merged.append(row)
    merged.append(rec)
    merged.sort(key=lambda x: _row_ts_bj(x, date10))
    if len(merged) > INTRADAY_SLICE_MAX:
        merged = merged[-INTRADAY_SLICE_MAX:]
    latest_ts = str(rec.get("ts_bj") or "")
    envelope: dict[str, Any] = {
        "schema": "intraday_snapshot_v1",
        "render_mode": "snapshot_stream",
        "date": date10,
        "count": len(merged),
        "interval_min": INTRADAY_INTERVAL_MIN,
        "simulated": False,
        "snapshots": merged,
        "latest": merged[-1] if merged else None,
        "updated_at": latest_ts,
        "snapshot_sig": f"{date10}|{latest_ts}|{len(merged)}",
    }
    _write_json(path, envelope)
    return envelope


def publish_runtime_files(*, root: Path, latest_snapshot: dict[str, Any], slices_payload: dict[str, Any]) -> None:
    html_dir = root / "html"
    _write_json(html_dir / "latest_intraday.json", latest_snapshot)
    _write_json(html_dir / "latest_intraday_slices.json", slices_payload)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成实时盯盘切片 JSON")
    ap.add_argument("--date", default="", help="YYYYMMDD；为空取北京时间今天")
    ap.add_argument("--publish", action="store_true", help="同时输出 html/latest_intraday*.json")
    ap.add_argument("--offline", action="store_true", help="离线模式：允许使用本地缓存（用于测试）")
    args = ap.parse_args()

    root = _workspace_root()
    date8 = args.date.strip() or datetime.now(BJ_TZ).strftime("%Y%m%d")
    date10 = _date8_to_10(date8)
    intraday = not args.offline

    # 自动回退到最近交易日（非交易日时生效）
    cfg = load_config_from_env()
    client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=30)
    resolved_date10, date_note = resolve_trade_date(client, date10)
    if date_note:
        print(f"ℹ️ {date_note}")
    date10 = resolved_date10
    date8 = _date10_to_8(date10)

    # 先清前一日缓存和已发布文件，确保每天重建
    _purge_previous_day_slices(root=root, keep_date10=date10)
    _purge_previous_day_published(root=root, keep_date10=date10)

    snap = build_live_snapshot(date8, intraday=intraday).to_dict()
    payload = append_intraday_slice(root=root, snapshot=snap)
    if args.publish:
        publish_runtime_files(root=root, latest_snapshot=snap, slices_payload=payload)
    print(f"✅ 实时切片已写入: {_intraday_slices_path(root, str(snap.get('date') or ''))}")
    if args.publish:
        print("✅ 已发布 latest_intraday.json / latest_intraday_slices.json")
    if args.offline:
        print("⚠️  离线模式：数据可能非实时")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
