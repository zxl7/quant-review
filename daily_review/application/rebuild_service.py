from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from daily_review.cache_io import read_json
from daily_review.contracts import MarketData
from daily_review.features.build_features import build_mood_inputs, default_chart_palette
from daily_review.pipeline.context import Context


@dataclass
class RebuildContextBundle:
    ctx: Context
    market_data: MarketData
    market_path: Path


def load_market_data(*, root: Path, date: str, source_market_path: Path | None = None) -> tuple[MarketData, Path]:
    cache_dir = root / "cache"
    date_compact = date.replace("-", "")
    market_path = source_market_path if source_market_path and source_market_path.exists() else cache_dir / f"market_data-{date_compact}.json"
    if not market_path.exists():
        raise FileNotFoundError(f"找不到缓存 marketData：{market_path}（请先跑一次 ./qr.sh fetch {date}）")
    market_data = json.loads(market_path.read_text(encoding="utf-8"))
    return market_data, market_path


def load_pools_for_date(root: Path, date: str) -> dict:
    cache_path = root / "cache" / "pools_cache.json"
    if not cache_path.exists():
        return {"ztgc": [], "dtgc": [], "zbgc": []}
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    pools = data.get("pools") or {}
    return {
        "ztgc": ((pools.get("ztgc") or {}).get(date)) or [],
        "dtgc": ((pools.get("dtgc") or {}).get(date)) or [],
        "zbgc": ((pools.get("zbgc") or {}).get(date)) or [],
        "qsgc": ((pools.get("qsgc") or {}).get(date)) or [],
        "all_dates": sorted(set((pools.get("ztgc") or {}).keys()) | set((pools.get("dtgc") or {}).keys()) | set((pools.get("zbgc") or {}).keys())),
    }


def prev_trade_date(all_dates: list[str], date: str) -> str | None:
    ds = sorted([day for day in (all_dates or []) if isinstance(day, str)])
    if date in ds:
        idx = ds.index(date)
        return ds[idx - 1] if idx > 0 else None
    past = [day for day in ds if day < date]
    return past[-1] if past else None


def load_ztgc_by_day_window(*, root: Path, date: str, n: int = 7) -> dict[str, list[dict]]:
    try:
        cache_path = root / "cache" / "pools_cache.json"
        if not cache_path.exists():
            return {}
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        pools = data.get("pools") or {}
        zt_by_day = pools.get("ztgc") or {}
        if not isinstance(zt_by_day, dict):
            return {}
        days = sorted([day for day in zt_by_day.keys() if isinstance(day, str) and day <= date])
        days = days[-max(1, int(n or 7)) :]
        out: dict[str, list[dict]] = {}
        for day in days:
            rows = zt_by_day.get(day) or []
            out[day] = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        return out
    except Exception:
        return {}


def load_theme_cache(root: Path) -> dict[str, list[str]]:
    path = root / "cache" / "theme_cache.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (data.get("codes") or {}) if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_index_klines_cache(root: Path) -> dict:
    path = root / "cache" / "index_kline_cache.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_height_trend_cache(root: Path) -> dict:
    path = root / "cache" / "height_trend_cache.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_theme_trend_cache(root: Path) -> dict:
    path = root / "cache" / "theme_trend_cache.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_catalyst_cache(root: Path, date: str) -> dict:
    date8 = str(date or "").replace("-", "")
    cache_dir = root / "cache_online"
    return {
        "abnormal": read_json(cache_dir / f"xuangubao_abnormal-{date8}.json", default={}),
        "surge_plates": read_json(cache_dir / f"xuangubao_surge_plates-{date8}.json", default={}),
        "tomorrow_themes": read_json(cache_dir / f"eastmoney_tomorrow_themes-{date8}.json", default={}),
    }


def inject_offline_raw_context(*, ctx: Context, root: Path, date: str) -> None:
    pools_today = load_pools_for_date(root, date)
    yest = prev_trade_date(pools_today.get("all_dates") or [], date)
    pools_yest = load_pools_for_date(root, yest) if yest else {"ztgc": [], "dtgc": [], "zbgc": []}
    ctx.raw.setdefault("pools", {})
    ctx.raw["pools"].update(
        {
            "ztgc": pools_today.get("ztgc") or [],
            "dtgc": pools_today.get("dtgc") or [],
            "zbgc": pools_today.get("zbgc") or [],
            "qsgc": pools_today.get("qsgc") or [],
            "yest_ztgc": pools_yest.get("ztgc") or [],
            "yest_dtgc": pools_yest.get("dtgc") or [],
            "yest_zbgc": pools_yest.get("zbgc") or [],
            "yest_date": yest or "",
        }
    )
    ctx.raw["pools"]["ztgc_by_day"] = load_ztgc_by_day_window(root=root, date=date, n=7)
    ctx.raw.setdefault("themes", {})
    ctx.raw["themes"]["code2themes"] = load_theme_cache(root)
    ctx.raw["index_klines"] = load_index_klines_cache(root)
    ctx.raw["height_trend_cache"] = load_height_trend_cache(root)
    ctx.raw["theme_trend_cache"] = load_theme_trend_cache(root)
    ctx.raw["catalyst_cache"] = load_catalyst_cache(root, date)


def rebuild_features(ctx: Context) -> None:
    try:
        pools_for_feat = ctx.raw.get("pools") or {}
        quotes_items = (((ctx.raw.get("quotes") or {}) if isinstance(ctx.raw, dict) else {}).get("items") or {})
        mood_inputs = build_mood_inputs(pools=pools_for_feat, quotes=quotes_items)
        feats = ctx.market_data.get("features") if isinstance(ctx.market_data.get("features"), dict) else {}
        if not isinstance(feats, dict):
            feats = {}
        feats["mood_inputs"] = mood_inputs
        feats.setdefault("chart_palette", default_chart_palette())
        ctx.market_data["features"] = feats
        ctx.features = feats
    except Exception:
        return


def build_rebuild_context(*, root: Path, date: str, source_market_path: Path | None = None) -> RebuildContextBundle:
    market_data, market_path = load_market_data(root=root, date=date, source_market_path=source_market_path)
    ctx = Context.from_market_data(market_data)
    inject_offline_raw_context(ctx=ctx, root=root, date=date)
    rebuild_features(ctx)
    return RebuildContextBundle(ctx=ctx, market_data=ctx.market_data, market_path=market_path)
