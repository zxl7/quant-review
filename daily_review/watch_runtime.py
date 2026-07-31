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


def _market_data_cache_path(root: Path, date10: str) -> Path:
    return root / "cache" / f"market_data-{_date10_to_8(date10)}.json"


def _intraday_slices_path(root: Path, date10: str) -> Path:
    return root / "cache" / f"intraday_slices-{_date10_to_8(date10)}.json"


def _intraday_runtime_paths(root: Path) -> tuple[Path, Path]:
    return (
        root / "web" / "public" / "intraday_runtime.json",
        root / "web" / "dist" / "intraday_runtime.json",
    )


def _date8_to_10(date8: str) -> str:
    """纯函数：YYYYMMDD -> YYYY-MM-DD。"""
    d8 = str(date8 or "").strip()
    if len(d8) == 8 and d8.isdigit():
        return f"{d8[:4]}-{d8[4:6]}-{d8[6:8]}"
    return d8


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


# 单日最多保留的盘中节点；Actions 实际触发时间可能偏离 cron，不承诺固定分钟粒度。
INTRADAY_SLICE_MAX = 96


def _is_trading_session(ts_bj: str) -> bool:
    """只让连续盘中交易时段进入轨迹，收盘重建不应制造新的盘中节点。"""
    text = str(ts_bj or "").strip()
    time_text = text[11:16] if len(text) >= 16 else text[:5]
    return ("09:30" <= time_text <= "11:30") or ("13:00" <= time_text <= "15:00")


def _is_market_snapshot_credible(snapshot: dict[str, Any], prev: dict[str, Any] | None) -> bool:
    """过滤接口空池和单池异常响应，避免它们被误画成盘中情绪急变。"""
    market = snapshot.get("market") if isinstance(snapshot.get("market"), dict) else {}
    health = snapshot.get("health") if isinstance(snapshot.get("health"), dict) else {}
    pool_status = health.get("pool_status") if isinstance(health.get("pool_status"), dict) else {}
    valid_status = {"valid", "valid_empty"}
    core_known = not pool_status or str(pool_status.get("ztgc") or "") in valid_status
    zt = int(round(_to_num(market.get("zt"), 0)))
    dt = int(round(_to_num(market.get("dt"), 0)))
    zab = int(round(_to_num(market.get("zab"), 0)))
    lianban = int(round(_to_num(market.get("lianban"), 0)))
    max_lb = int(round(_to_num(market.get("max_lianban"), 0)))

    if min(zt, dt, zab, lianban, max_lb) < 0:
        return False
    # 涨停池为空时，连板和高度也不应同时归零后被当作市场真实状态。
    if core_known and zt == 0 and lianban == 0 and max_lb == 0:
        return False
    if not prev:
        return True

    prev_zt = int(round(_to_num(prev.get("zt"), 0)))
    prev_dt = int(round(_to_num(prev.get("dt"), 0)))
    # 盘中十分钟内涨停保持活跃而跌停突然从低位跳到三位数，是单池异常而非情绪反转。
    if prev_zt >= 10 and zt >= 10 and prev_dt <= 50 and dt >= 100:
        return False
    return True


def _snapshot_rejection_reason(snapshot: dict[str, Any], prev: dict[str, Any] | None) -> str:
    """给运行时健康状态提供可审计的拒绝原因。"""
    health = snapshot.get("health") if isinstance(snapshot.get("health"), dict) else {}
    source_status = str(health.get("status") or "")
    pool_status = health.get("pool_status") if isinstance(health.get("pool_status"), dict) else {}
    ts_bj = str(snapshot.get("ts_bj") or "")
    if not _is_trading_session(ts_bj):
        return "outside_trading_session"
    valid_status = {"valid", "valid_empty"}
    valid_pool_count = sum(1 for status in pool_status.values() if str(status or "") in valid_status)
    market = snapshot.get("market") if isinstance(snapshot.get("market"), dict) else {}
    all_core_fields_unknown = all(market.get(key) is None for key in ("zt", "dt", "zab", "lianban", "max_lianban"))
    # 任一池成功就保留降级节点；三池全失败时，仅在已有当日可信节点后追加“数据暂缺”槽位。
    # 这样既保持十分钟时间轴连续，也不会在首个有效节点前用空数据覆盖昨日成品。
    if health and source_status not in {"valid", ""}:
        if source_status == "partial" and valid_pool_count > 0:
            pass
        elif prev is not None and pool_status and all_core_fields_unknown and source_status in {"partial", "failed", "fallback", "unavailable"}:
            return ""
        else:
            return f"source_{source_status}"
    if not _is_market_snapshot_credible(snapshot, prev):
        return "market_snapshot_not_credible"
    return ""


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


def _row_as_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts_bj": row.get("ts_bj"),
        "health": {
            "status": row.get("data_quality") or "",
            "pool_status": row.get("pool_status") or {},
        },
        "market": {
            "zt": row.get("zt"), "dt": row.get("dt"), "zab": row.get("zab"),
            "lianban": row.get("lianban"), "max_lianban": row.get("max_lb"),
        },
    }


def _sanitize_slice_rows(rows: list[dict[str, Any]], date10: str) -> list[dict[str, Any]]:
    """发布前再次清洗旧切片，避免历史污染在后续运行中永久保留。"""
    valid: list[dict[str, Any]] = []
    for raw in sorted(rows, key=lambda x: _row_ts_bj(x, date10)):
        row = _normalize_slice_row(raw, date10)
        if _row_ts_bj(row, date10)[:10] != date10:
            continue
        if _snapshot_rejection_reason(_row_as_snapshot(row), valid[-1] if valid else None):
            continue
        valid.append(row)
    return valid


def _pick_runtime_indices(*, root: Path, date10: str, snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    required = ("上证指数", "深证成指", "创业板指")

    def extract(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        rows = payload.get("indices") if isinstance(payload.get("indices"), list) else []
        as_of = str(((payload.get("meta") or {}) if isinstance(payload.get("meta"), dict) else {}).get("asOf", {}).get("indices") or "").strip()
        picked: list[dict[str, Any]] = []
        by_name: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            if name:
                by_name[name] = dict(row)
        for name in required:
            row = by_name.get(name)
            if row:
                picked.append(row)
        return picked, as_of

    direct = {"indices": snapshot.get("indices"), "meta": {"asOf": (snapshot.get("asOf") or {})}}
    rows, as_of = extract(direct)
    if len(rows) == 3 and as_of and as_of != "收盘":
        return rows, as_of

    # 指数接口短暂失败时，保留同日最后一份实时指数；绝不回退到收盘缓存伪装盘中数据。
    previous = _read_json(_intraday_runtime_paths(root)[0], {})
    if str(previous.get("date") or "") == date10:
        rows, as_of = extract(previous)
        if len(rows) == 3 and as_of and as_of != "收盘":
            return rows, as_of
    return [], ""


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
    if curr.get("data_quality") == "unavailable":
        return "本槽位三池请求均未成功，已记录数据暂缺；等待下一节点自动恢复。"
    if curr.get("shift_score") is None:
        return "本槽位仅部分三池成功；节点已保留，缺失指标不参与判断。"
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
    source_health = snapshot.get("health") if isinstance(snapshot.get("health"), dict) else {}
    pool_status = source_health.get("pool_status") if isinstance(source_health.get("pool_status"), dict) else {}
    pool_errors = source_health.get("pool_errors") if isinstance(source_health.get("pool_errors"), dict) else {}
    valid_status = {"valid", "valid_empty"}
    zt_known = not pool_status or str(pool_status.get("ztgc") or "") in valid_status
    dt_known = not pool_status or str(pool_status.get("dtgc") or "") in valid_status
    zab_known = not pool_status or str(pool_status.get("zbgc") or "") in valid_status
    known_pool_count = sum(1 for status in pool_status.values() if str(status or "") in valid_status)
    data_quality = "valid" if str(source_health.get("status") or "") in {"", "valid"} else ("partial" if known_pool_count else "unavailable")
    ts_bj = str(snapshot.get("ts_bj") or "")
    zt = int(round(_to_num(market.get("zt"), 0))) if zt_known and market.get("zt") is not None else None
    zab = int(round(_to_num(market.get("zab"), 0))) if zab_known else None
    dt = int(round(_to_num(market.get("dt"), 0))) if dt_known else None
    lianban = int(round(_to_num(market.get("lianban"), 0))) if zt_known and market.get("lianban") is not None else None
    max_lb = int(round(_to_num(market.get("max_lianban"), 0))) if zt_known and market.get("max_lianban") is not None else None
    zb = round(_to_num(market.get("zab_rate"), 0), 1) if market.get("zab_rate") is not None else None
    fb = round(zt / max(zt + zab, 1) * 100.0, 1) if zt is not None and zab is not None else None
    jj = round(lianban / max(zt, 1) * 100.0, 1) if zt is not None and lianban is not None else None
    heat = int(round(max(0.0, min(100.0, 0.42 * fb + 0.24 * jj + min(zt, 100) * 0.16 + min(max_lb * 12.0, 100) * 0.18)))) if fb is not None and jj is not None and max_lb is not None else None
    risk = int(round(max(0.0, min(100.0, zb * 0.55 + min(dt * 5.0, 100.0) * 0.30 + min(zab * 3.0, 100.0) * 0.15)))) if zb is not None and dt is not None and zab is not None else None
    rec = {
        "time": _display_time_from_ts_bj(ts_bj),
        "ts_bj": ts_bj,
        "date": str(snapshot.get("date") or ""),
        "source": "intraday_live",
        "provider": str(snapshot.get("source") or ""),
        "data_quality": data_quality,
        "pool_status": pool_status,
        "pool_errors": pool_errors,
        "zt": zt,
        "dt": dt,
        "zab": zab,
        "zb": zb,
        "fb": fb,
        "jj": jj,
        "lianban": lianban,
        "max_lb": max_lb,
        "amount": str(market.get("amount") or ""),
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
    rec["shift_score"] = _calc_shift_score(rec) if heat is not None and risk is not None else None
    rec["shift_label"] = _shift_label(rec["shift_score"]) if rec["shift_score"] is not None else ("数据暂缺" if data_quality == "unavailable" else "数据部分可用")
    rec["headline"] = rec["shift_label"]
    rec["note"] = _shift_note(rec, prev)
    return rec


def append_intraday_slice(*, root: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    date10 = str(snapshot.get("date") or "")
    path = _intraday_slices_path(root, date10)
    rows = _sanitize_slice_rows(_read_slices_rows(path), date10)
    ts_bj = str(snapshot.get("ts_bj") or "").strip()
    if not ts_bj:
        ts_bj = datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")
    snap2 = dict(snapshot)
    snap2["ts_bj"] = ts_bj
    prev = _prev_row_for_ts(rows, ts_bj, date10)
    rejection_reason = _snapshot_rejection_reason(snap2, prev)
    should_append = not rejection_reason
    rec = _build_slice(snap2, prev) if should_append else None
    merged: list[dict[str, Any]] = []
    seen_ts = rec.get("ts_bj") if rec else ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        if seen_ts and _row_ts_bj(row, date10) == seen_ts:
            continue
        merged.append(row)
    if rec:
        merged.append(rec)
    merged.sort(key=lambda x: _row_ts_bj(x, date10))
    if len(merged) > INTRADAY_SLICE_MAX:
        merged = merged[-INTRADAY_SLICE_MAX:]
    latest = merged[-1] if merged else None
    latest_ts = str((latest or {}).get("ts_bj") or "")
    accepted_quality = str((rec or {}).get("data_quality") or "")
    envelope: dict[str, Any] = {
        "schema": "intraday_snapshot_v1",
        "render_mode": "snapshot_stream",
        "date": date10,
        "count": len(merged),
        "interval_min": None,
        "simulated": False,
        "snapshots": merged,
        "latest": latest,
        "updated_at": latest_ts,
        "snapshot_sig": f"{date10}|{latest_ts}|{len(merged)}",
        "health": {
            "status": ("degraded" if accepted_quality in {"partial", "unavailable"} else "valid") if rec else "stale",
            "last_valid_at": latest_ts,
            "rejected_reason": rejection_reason,
            "source": (snap2.get("health") if isinstance(snap2.get("health"), dict) else {}),
        },
    }
    _write_json(path, envelope)
    return envelope


def write_intraday_runtime(*, root: Path, snapshot: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    date10 = str(snapshot.get("date") or "")
    latest = envelope.get("latest") if isinstance(envelope, dict) and isinstance(envelope.get("latest"), dict) else None
    indices_rows, indices_as_of = _pick_runtime_indices(root=root, date10=date10, snapshot=snapshot)
    # live 与 latest 使用同一个已验收节点，拒绝原始响应穿透到顶部实时数值。
    latest_market = latest or {}
    health = dict(envelope.get("health") or {}) if isinstance(envelope, dict) and isinstance(envelope.get("health"), dict) else {}
    health["indices_status"] = "valid" if indices_rows else "unavailable"
    payload = {
        "schema": "intraday_runtime_v1",
        "date": date10,
        "updated_at": str((latest or {}).get("ts_bj") or ""),
        "source": str(snapshot.get("source") or "intraday_live"),
        "latest": (envelope.get("latest") if isinstance(envelope, dict) else None),
        "snapshots": (envelope.get("snapshots") if isinstance(envelope, dict) else []),
        "indices": indices_rows,
        "asOf": {
            "indices": indices_as_of,
        },
        "health": health,
        "live": {
            "market": {
                "zt": latest_market.get("zt"), "dt": latest_market.get("dt"), "zab": latest_market.get("zab"),
                "zab_rate": latest_market.get("zb"), "lianban": latest_market.get("lianban"),
                "max_lianban": latest_market.get("max_lb"), "amount": latest_market.get("amount"),
            },
            "alerts": latest_market.get("alerts") or [],
            "concepts": latest_market.get("concepts") or [],
        },
    }
    public_path, dist_path = _intraday_runtime_paths(root)
    _write_json(public_path, payload)
    if dist_path.parent.exists():
        _write_json(dist_path, payload)
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="生成实时盯盘切片 JSON")
    ap.add_argument("--date", default="", help="YYYYMMDD；为空取北京时间今天")
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

    # 先清前一日缓存，确保每天重建
    _purge_previous_day_slices(root=root, keep_date10=date10)

    snap = build_live_snapshot(date8, intraday=intraday).to_dict()
    envelope = append_intraday_slice(root=root, snapshot=snap)
    write_intraday_runtime(root=root, snapshot=snap, envelope=envelope)
    print(f"✅ 实时切片已写入: {_intraday_slices_path(root, str(snap.get('date') or ''))}")
    print(f"✅ 盘中运行时已写入: {_intraday_runtime_paths(root)[0]}")
    if args.offline:
        print("⚠️  离线模式：数据可能非实时")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
