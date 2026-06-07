from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from daily_review.contracts import IntradaySnapshot, MarketData
from daily_review.metrics.scoring import blend_sentiment_score


def intraday_slices_path(root: Path, date: str) -> Path:
    cache_dir = root / "cache"
    d8 = date.replace("-", "")
    return cache_dir / f"intraday_slices-{d8}.json"


def intraday_snapshots_path(root: Path, date: str) -> Path:
    cache_dir = root / "cache"
    d8 = date.replace("-", "")
    return cache_dir / f"intraday_snapshots-{d8}.json"


def _to_num(v, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        if isinstance(v, str):
            return float(v.replace("%", "").strip())
        return float(v)
    except Exception:
        return default


def intraday_shift_label(score: float) -> str:
    if score >= 72:
        return "走强"
    if score >= 60:
        return "修复"
    if score >= 48:
        return "分歧"
    if score >= 36:
        return "走弱"
    return "退潮"


def normalize_intraday_snapshot(row: dict) -> IntradaySnapshot:
    rec: IntradaySnapshot = dict(row or {})
    heat = _to_num(rec.get("heat"), None)
    risk = _to_num(rec.get("risk"), None)
    if heat is not None and risk is not None:
        score = int(blend_sentiment_score(heat=heat, risk=risk))
        rec["shift_score"] = score
        label = str(rec.get("shift_label") or "").strip()
        if not label or label.replace(".", "", 1).isdigit():
            rec["shift_label"] = intraday_shift_label(score)
    return rec


def load_intraday_snapshots(*, root: Path, date: str) -> list[IntradaySnapshot]:
    for path in (intraday_slices_path(root, date), intraday_snapshots_path(root, date)):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [normalize_intraday_snapshot(row) for row in data if isinstance(row, dict)]
            if isinstance(data, dict) and isinstance(data.get("snapshots"), list):
                return [normalize_intraday_snapshot(row) for row in (data.get("snapshots") or []) if isinstance(row, dict)]
        except Exception:
            continue
    return []


def write_intraday_snapshots(*, root: Path, date: str, snapshots: list[IntradaySnapshot], simulated: bool = False) -> None:
    payload = {
        "date": date,
        "count": len(snapshots),
        "snapshots": snapshots,
        "simulated": simulated,
        "interval_min": None,
        "latest": snapshots[-1] if snapshots else None,
    }
    intraday_slices_path(root, date).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_intraday_snapshot(*, root: Path, date: str, market_data: MarketData) -> None:
    meta = market_data.get("meta") or {}
    gen_at = str(meta.get("generatedAt") or "").strip()
    snap_t = str(meta.get("snapshotTime") or meta.get("asOf", {}).get("pools") or "").strip()
    ts_bj = gen_at if len(gen_at) >= 19 else (f"{date} {snap_t}" if snap_t else "")
    if not ts_bj:
        return
    t_label = ts_bj[11:19] if len(ts_bj) >= 19 else (ts_bj[11:16] if len(ts_bj) >= 16 else snap_t[:8] if snap_t else "")

    mi = (market_data.get("features") or {}).get("mood_inputs") or {}
    mood = market_data.get("mood") or {}
    mood_signals = market_data.get("moodSignals") or {}
    hm2 = market_data.get("hm2Compare") or {}
    panorama = market_data.get("panorama") or {}
    volume = market_data.get("volume") if isinstance(market_data.get("volume"), dict) else {}
    lianban_count = int(_to_num(mi.get("lianban_count"), 0))
    if not lianban_count:
        lianban_count = (
            int(_to_num(mi.get("lb_2"), 0))
            + int(_to_num(mi.get("lb_3"), 0))
            + int(_to_num(mi.get("lb_4p"), 0))
            + int(_to_num(mi.get("lb_5p"), 0))
        )

    rec: IntradaySnapshot = {
        "time": t_label,
        "ts_bj": ts_bj,
        "date": date,
        "source": "intraday_live",
        "headline": mood_signals.get("headline") or "",
        "heat": mood.get("heat"),
        "risk": mood.get("risk"),
        "fb": mi.get("fb_rate"),
        "jj": mi.get("jj_rate"),
        "zt": int(_to_num(mi.get("zt_count"), _to_num(panorama.get("limitUp"), 0))),
        "lianban": lianban_count,
        "zab": int(_to_num(mi.get("zb_count"), 0)),
        "zb": mi.get("zb_rate"),
        "dt": panorama.get("limitDown"),
        "bf": mi.get("bf_count"),
        "max_lb": mi.get("max_lb"),
        "amount": volume.get("total") or "",
        "loss": mi.get("loss"),
        "hm2": hm2.get("score"),
        "pos": mood_signals.get("pos") or [],
        "riskSignals": mood_signals.get("risk") or [],
    }
    shift_score = int(_to_num(mood.get("score"), 0))
    rec["shift_score"] = shift_score
    rec["shift_label"] = intraday_shift_label(shift_score)

    snapshots = load_intraday_snapshots(root=root, date=date)
    snapshots = [row for row in snapshots if str(row.get("ts_bj") or "") != ts_bj]
    snapshots.append(rec)
    snapshots.sort(key=lambda row: str(row.get("ts_bj") or f"{date} {row.get('time') or '00:00:00'}"))
    write_intraday_snapshots(root=root, date=date, snapshots=snapshots[-96:], simulated=False)


def inject_intraday_snapshots(*, root: Path, date: str, market_data: MarketData) -> None:
    market_data.pop("intradaySnapshots", None)
    snapshots = load_intraday_snapshots(root=root, date=date)
    snapshots = [row for row in snapshots if isinstance(row, dict) and str(row.get("source") or "") != "simulated_close"]
    if not snapshots:
        return
    market_data["intradaySnapshots"] = {
        "date": snapshots[0].get("date") or date,
        "count": len(snapshots),
        "snapshots": snapshots,
        "simulated": False,
        "interval_min": None,
        "latest": snapshots[-1] if snapshots else None,
    }


def append_watch_runtime_slice(
    *,
    root: Path,
    market_path: Path,
    fallback_market_data: MarketData,
    fallback_mood_inputs: dict,
    log_fn: Callable[[str], None] | None = None,
) -> None:
    import datetime as _dt
    from daily_review.watch_runtime import _purge_previous_day_slices, append_intraday_slice

    rebuilt_data = json.loads(market_path.read_text(encoding="utf-8")) if market_path.exists() else fallback_market_data
    rebuilt_mi = (rebuilt_data.get("features") or {}).get("mood_inputs") or fallback_mood_inputs
    rebuilt_pan = rebuilt_data.get("panorama") if isinstance(rebuilt_data.get("panorama"), dict) else {}
    now_bj_date = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    _purge_previous_day_slices(root=root, keep_date10=now_bj_date)
    now_bj = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    lianban_count = int(rebuilt_mi.get("lianban_count", 0) or 0)
    if not lianban_count:
        lianban_count = (
            int(rebuilt_mi.get("lb_2", 0) or 0)
            + int(rebuilt_mi.get("lb_3", 0) or 0)
            + int(rebuilt_mi.get("lb_4p", 0) or 0)
            + int(rebuilt_mi.get("lb_5p", 0) or 0)
        )
    max_lb = int(rebuilt_mi.get("max_lb", 0) or 0)
    vol_total = rebuilt_data.get("volume", {}).get("total", "") or ""
    concepts_src = rebuilt_data.get("plateRankTop10") or rebuilt_data.get("conceptFundFlowTop") or []
    watch_snap = {
        "source": fallback_market_data.get("meta", {}).get("source", {}).get("indices", "fetch"),
        "ts_bj": now_bj,
        "date": now_bj_date,
        "market": {
            "zt": int(rebuilt_mi.get("zt_count", rebuilt_pan.get("limitUp", 0)) or 0),
            "dt": int(rebuilt_mi.get("dt_count", rebuilt_pan.get("limitDown", 0)) or 0),
            "zab": int(rebuilt_mi.get("zb_count", 0) or 0),
            "zab_rate": float(rebuilt_mi.get("zb_rate", 0) or 0.0),
            "lianban": lianban_count,
            "max_lianban": max_lb,
            "amount": str(vol_total),
        },
        "concepts": [
            {"name": item.get("name"), "lead": item.get("lead"), "chg_pct": item.get("chg_pct")}
            for item in concepts_src[:5]
            if isinstance(item, dict) and item.get("name")
        ],
        "alerts": [],
    }
    append_intraday_slice(root=root, snapshot=watch_snap)
    if log_fn:
        log_fn("盯盘快照已追加")
