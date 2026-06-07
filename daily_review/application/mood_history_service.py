from __future__ import annotations

import json
import math
import os
from pathlib import Path

from daily_review.contracts import MarketData


def inject_mood_history_and_delta(*, root: Path, date: str, market_data: MarketData) -> None:
    """
    离线增强（UI/图表需要）：
    1) features.mood_inputs.hist_* / trend_*：用于 sparkline 与情绪K线
    2) prev / delta：用于“vs昨日”对比箭头与 Δ badge
    """

    cache_dir = root / "cache"
    date8 = date.replace("-", "")
    if len(date8) != 8:
        return

    items: list[tuple[str, Path]] = []
    for fp in cache_dir.glob("market_data-*.json"):
        stem = fp.stem
        if not stem.startswith("market_data-"):
            continue
        d8 = stem.replace("market_data-", "")
        if len(d8) != 8 or not d8.isdigit():
            continue
        if d8 <= date8:
            items.append((d8, fp))
    items.sort(key=lambda row: row[0])
    if not items:
        return

    feats = market_data.setdefault("features", {})
    mood_inputs = feats.setdefault("mood_inputs", {})
    hist_days = mood_inputs.get("hist_days")

    try:
        market_panorama = market_data.get("marketPanorama") or {}
        kpis = market_panorama.get("kpis") or {}
        mood_inputs.setdefault("lianban_count", int(kpis.get("link_board", 0) or 0))
    except Exception:
        pass

    try:
        raw = market_data.get("raw") or {}
        quotes = raw.get("quotes") or {}
        quote_items = quotes.get("items") or {}
        if isinstance(quote_items, dict):
            up_count = 0
            down_count = 0
            for item in quote_items.values():
                if not isinstance(item, dict):
                    continue
                pc = item.get("pc")
                try:
                    pc = float(pc)
                except Exception:
                    continue
                if pc > 0:
                    up_count += 1
                elif pc < 0:
                    down_count += 1
            mood_inputs.setdefault("up_count", up_count)
            mood_inputs.setdefault("down_count", down_count)
    except Exception:
        pass

    need_hist = not (isinstance(hist_days, list) and len(hist_days) >= 2)
    if need_hist:
        try:
            hist_n = int(os.getenv("MOOD_HIST_DAYS", "7") or "7")
        except Exception:
            hist_n = 5
        hist_n = max(3, min(hist_n, 10))
        slice_items = items[-hist_n:]

        def _to_num(v, d=0.0):
            try:
                if v is None:
                    return d
                if isinstance(v, str):
                    v = v.replace("%", "").strip()
                return float(v)
            except Exception:
                return d

        def _pick_first_num(*values, default=0.0) -> float:
            for value in values:
                if value is None:
                    continue
                parsed = _to_num(value, float("nan"))
                if math.isfinite(parsed):
                    return parsed
            return default

        rows = []
        for d8, fp in slice_items:
            try:
                snap = json.loads(fp.read_text(encoding="utf-8"))
                snap_features = snap.get("features") or {}
                snap_mood_inputs = snap_features.get("mood_inputs") or {}
                max_lb = int(snap_mood_inputs.get("max_lb", 0) or 0)
                if not max_lb:
                    badges = []
                    for item in snap.get("ladder") or []:
                        try:
                            badges.append(int(str(item.get("badge", "")).replace("板", "").replace("板+", "")[:2] or 0))
                        except Exception:
                            pass
                    max_lb = max(badges) if badges else 0

                def _breadth_from_snap(snap_dict: dict) -> tuple[int, int]:
                    raw = snap_dict.get("raw") or {}
                    quotes = raw.get("quotes") or {}
                    quote_items = quotes.get("items") or {}
                    if not isinstance(quote_items, dict):
                        return 0, 0
                    up = 0
                    down = 0
                    for item in quote_items.values():
                        if not isinstance(item, dict):
                            continue
                        pc = item.get("pc")
                        try:
                            pc = float(pc)
                        except Exception:
                            continue
                        if pc > 0:
                            up += 1
                        elif pc < 0:
                            down += 1
                    return up, down

                up_cnt, down_cnt = _breadth_from_snap(snap)
                market_panorama = snap.get("marketPanorama") or {}
                kpis = market_panorama.get("kpis") or {}
                panorama = snap.get("panorama") or {}
                action_sheet = snap.get("actionSheet") or {}
                action_numbers = action_sheet.get("keyNumbers") if isinstance(action_sheet, dict) else {}
                delta = snap.get("delta") or {}
                three_quadrants = snap.get("threeQuadrants") or {}
                tq_axes = three_quadrants.get("axes") if isinstance(three_quadrants, dict) else {}
                tq_support = tq_axes.get("support") if isinstance(tq_axes, dict) else {}
                tq_support_components = tq_support.get("components") if isinstance(tq_support, dict) else {}
                divergence = snap.get("divergenceEngine") or {}
                support_quality = divergence.get("supportQuality") if isinstance(divergence, dict) else {}
                promotion_rate = support_quality.get("promotionRate") if isinstance(support_quality, dict) else {}

                lianban = int(_to_num(kpis.get("link_board", 0), 0))
                if not lianban:
                    lianban = int(
                        _to_num(snap_mood_inputs.get("lb_2", 0), 0)
                        + _to_num(snap_mood_inputs.get("lb_3", 0), 0)
                        + _to_num(snap_mood_inputs.get("lb_4p", 0), 0)
                        + _to_num(snap_mood_inputs.get("lb_5p", 0), 0)
                    )

                fb_rate = _pick_first_num(
                    snap_mood_inputs.get("fb_rate"),
                    action_numbers.get("fb") if isinstance(action_numbers, dict) else None,
                    delta.get("fb_rate"),
                    panorama.get("ratio"),
                )
                jj_rate = _pick_first_num(
                    snap_mood_inputs.get("jj_rate_adj"),
                    snap_mood_inputs.get("jj_rate"),
                    action_numbers.get("jj") if isinstance(action_numbers, dict) else None,
                    delta.get("jj_rate"),
                    tq_support_components.get("jj_rate") if isinstance(tq_support_components, dict) else None,
                    (
                        _to_num(promotion_rate.get("overallJjRate"), float("nan")) * 100.0
                        if isinstance(promotion_rate, dict)
                        else None
                    ),
                )
                zb_rate = _pick_first_num(
                    snap_mood_inputs.get("zb_rate"),
                    kpis.get("zb_rate"),
                    (100.0 - fb_rate) if fb_rate else None,
                )

                rows.append(
                    {
                        "date": f"{d8[0:4]}-{d8[4:6]}-{d8[6:8]}",
                        "max_lb": max_lb,
                        "fb_rate": fb_rate,
                        "jj_rate": jj_rate,
                        "broken_lb_rate": _to_num(
                            snap_mood_inputs.get("broken_lb_rate_adj", snap_mood_inputs.get("broken_lb_rate", 0)),
                            0,
                        ),
                        "zb_rate": zb_rate,
                        "zt_early_ratio": _to_num(snap_mood_inputs.get("zt_early_ratio", 0), 0),
                        "loss": _to_num(
                            snap_mood_inputs.get(
                                "loss",
                                _to_num(snap_mood_inputs.get("bf_count", 0), 0)
                                + _to_num(snap_mood_inputs.get("dt_count", 0), 0),
                            ),
                            0,
                        ),
                        "zt": int(_to_num(panorama.get("limitUp", 0), 0)),
                        "dt": int(_to_num(panorama.get("limitDown", 0), 0)),
                        "lianban": lianban,
                        "up": up_cnt,
                        "down": down_cnt,
                    }
                )
            except Exception:
                continue

        if len(rows) >= 2:
            first = rows[0]
            last = rows[-1]
            mood_inputs["hist_days"] = [row["date"] for row in rows]
            mood_inputs["hist_max_lb"] = [row["max_lb"] for row in rows]
            mood_inputs["hist_fb_rate"] = [round(row["fb_rate"], 1) for row in rows]
            mood_inputs["hist_jj_rate"] = [round(row["jj_rate"], 1) for row in rows]
            mood_inputs["hist_broken_lb_rate"] = [round(row["broken_lb_rate"], 1) for row in rows]
            mood_inputs["hist_zb_rate"] = [round(row["zb_rate"], 1) for row in rows]
            mood_inputs["hist_zt_early_ratio"] = [round(row["zt_early_ratio"], 1) for row in rows]
            mood_inputs["hist_loss"] = [round(row["loss"], 1) for row in rows]
            mood_inputs["hist_zt"] = [int(row.get("zt", 0)) for row in rows]
            mood_inputs["hist_dt"] = [int(row.get("dt", 0)) for row in rows]
            mood_inputs["hist_lianban"] = [int(row.get("lianban", 0)) for row in rows]
            mood_inputs["hist_up"] = [int(row.get("up", 0)) for row in rows]
            mood_inputs["hist_down"] = [int(row.get("down", 0)) for row in rows]
            mood_inputs["hist_zt_dt_spread"] = [int(row.get("zt", 0)) - int(row.get("dt", 0)) for row in rows]
            mood_inputs["trend_max_lb"] = round(float(last["max_lb"]) - float(first["max_lb"]), 2)
            mood_inputs["trend_fb_rate"] = round(float(last["fb_rate"]) - float(first["fb_rate"]), 2)
            mood_inputs["trend_jj_rate"] = round(float(last["jj_rate"]) - float(first["jj_rate"]), 2)
            mood_inputs["trend_broken_lb_rate"] = round(float(last["broken_lb_rate"]) - float(first["broken_lb_rate"]), 2)
            mood_inputs["trend_zb_rate"] = round(float(last["zb_rate"]) - float(first["zb_rate"]), 2)
            mood_inputs["trend_zt_early_ratio"] = round(float(last["zt_early_ratio"]) - float(first["zt_early_ratio"]), 2)
            mood_inputs["trend_loss"] = round(float(last["loss"]) - float(first["loss"]), 2)
            mood_inputs["trend_zt"] = int(last.get("zt", 0)) - int(first.get("zt", 0))
            mood_inputs["trend_dt"] = int(last.get("dt", 0)) - int(first.get("dt", 0))
            mood_inputs["trend_lianban"] = int(last.get("lianban", 0)) - int(first.get("lianban", 0))
            mood_inputs["trend_up"] = int(last.get("up", 0)) - int(first.get("up", 0))
            mood_inputs["trend_down"] = int(last.get("down", 0)) - int(first.get("down", 0))

    if len(items) < 2:
        return

    prev_fp = items[-2][1]
    try:
        prev_data = json.loads(prev_fp.read_text(encoding="utf-8"))
    except Exception:
        return

    market_data["prev"] = {
        "date": prev_data.get("date", ""),
        "panorama": prev_data.get("panorama") or {},
        "mood": prev_data.get("mood") or {},
        "moodStage": prev_data.get("moodStage") or {},
        "volume": prev_data.get("volume") or {},
        "features": (prev_data.get("features") or {}),
    }

    def _num(v, d=0.0):
        try:
            if v is None:
                return d
            if isinstance(v, str):
                v = v.replace("%", "").replace("亿", "").strip()
            return float(v)
        except Exception:
            return d

    cur_pan = market_data.get("panorama") or {}
    prev_pan = (prev_data.get("panorama") or {}) if isinstance(prev_data, dict) else {}
    cur_feats = market_data.get("features") or {}
    cur_mood_inputs = cur_feats.get("mood_inputs") or {}
    prev_feats = (prev_data.get("features") or {}) if isinstance(prev_data, dict) else {}
    prev_mood_inputs = (prev_feats.get("mood_inputs") or {}) if isinstance(prev_feats, dict) else {}

    market_data["delta"] = {
        "zt": int(_num(cur_pan.get("limitUp"), 0) - _num(prev_pan.get("limitUp"), 0)),
        "zb": int(_num(cur_pan.get("broken"), 0) - _num(prev_pan.get("broken"), 0)),
        "dt": int(_num(cur_pan.get("limitDown"), 0) - _num(prev_pan.get("limitDown"), 0)),
        "fb_rate": round(_num(cur_mood_inputs.get("fb_rate"), 0) - _num(prev_mood_inputs.get("fb_rate"), 0), 2),
        "jj_rate": round(
            _num(cur_mood_inputs.get("jj_rate_adj", cur_mood_inputs.get("jj_rate")), 0)
            - _num(prev_mood_inputs.get("jj_rate_adj", prev_mood_inputs.get("jj_rate")), 0),
            2,
        ),
        "zb_rate": round(_num(cur_mood_inputs.get("zb_rate"), 0) - _num(prev_mood_inputs.get("zb_rate"), 0), 2),
        "max_lb": round(_num(cur_mood_inputs.get("max_lb"), 0) - _num(prev_mood_inputs.get("max_lb"), 0), 2),
        "bf_count": round(_num(cur_mood_inputs.get("bf_count"), 0) - _num(prev_mood_inputs.get("bf_count"), 0), 2),
        "lianban": int(_num(cur_mood_inputs.get("lianban_count"), 0) - _num(prev_mood_inputs.get("lianban_count"), 0)),
        "up": int(_num(cur_mood_inputs.get("up_count"), 0) - _num(prev_mood_inputs.get("up_count"), 0)),
        "down": int(_num(cur_mood_inputs.get("down_count"), 0) - _num(prev_mood_inputs.get("down_count"), 0)),
        "heat": round(_num((market_data.get("mood") or {}).get("heat"), 0) - _num((prev_data.get("mood") or {}).get("heat"), 0), 2),
        "risk": round(_num((market_data.get("mood") or {}).get("risk"), 0) - _num((prev_data.get("mood") or {}).get("risk"), 0), 2),
    }
