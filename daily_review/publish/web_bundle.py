"""
Web runtime bundle publish service.

Canonical responsibilities:
- load cache/market_data-YYYYMMDD.json
- prepare publish-safe web payloads
- sync runtime artifacts into web/dist and web/public

`inject_data.py` is kept only as a compatibility CLI/import wrapper.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Optional

from daily_review.application.mood_history_service import inject_mood_history_and_delta
from daily_review.features.sector_resolver import normalize_sector


ROOT = Path(__file__).resolve().parents[2]


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _to_int(value: object, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _format_pct_from_ratio(value: object) -> str:
    if value is None or value == "":
        return "-"
    try:
        num = float(value)
    except Exception:
        return "-"
    return f"{round(num * 100)}%"


def _format_return(value: object) -> str:
    try:
        num = float(value)
    except Exception:
        return "-"
    sign = "+" if num > 0 else ""
    text = f"{num:.2f}"
    if text.endswith(".00"):
        text = text[:-3]
    return f"{sign}{text}%"


def _median_numbers(values: list[float]) -> float:
    nums = sorted(v for v in values if isinstance(v, (int, float)))
    if not nums:
        return 0.0
    mid = len(nums) // 2
    if len(nums) % 2:
        return float(nums[mid])
    return (float(nums[mid - 1]) + float(nums[mid])) / 2.0


def _top_labels(rows: list[dict], key_fn, limit: int = 2) -> list[str]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(key_fn(row) or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return [name for name, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _build_theme_alias_map(md: dict, watchlist: Optional[dict] = None) -> dict:
    """
    汇总今日题材别名映射：canonical_name -> 出现过的原始名集合。

    归一化责任已经下沉到后端算法层（tide / core_tide / zt_analysis），
    本函数只做“收集 + 分组”：
    - 后端已带 canonical 字段的来源（tide/core_tide/zt_analysis）：
      用算法层吐出来的 canonical 作为分组 key，把同行的 raw name 一并塞进桶里。
    - 上游没带 canonical 的来源（plateRankTop10/sectors/leaders/zt_code_themes/watchlist）：
      用 raw name 自身作为分组 key，等同于“透传”。

    这样前端拿到的 alias_map 直接反映后端的判定结果，不需要在 publish 层
    再跑一遍 normalize_sector。
    """
    alias_map: dict[str, set[str]] = {}

    def push(name: object, canonical: object = None) -> None:
        raw = str(name or "").strip()
        canon = str(canonical or "").strip()
        key = canon or raw
        if not key:
            return
        bucket = alias_map.setdefault(key, set())
        bucket.add(key)
        if raw:
            bucket.add(raw)

    for row in md.get("plateRankTop10") or []:
        if isinstance(row, dict):
            push(row.get("name"))
    for row in md.get("sectors") or []:
        if isinstance(row, dict):
            push(row.get("name"))
    theme_panels = md.get("themePanels") if isinstance(md.get("themePanels"), dict) else {}
    for key in ("strengthRows", "ztTop", "zbTop", "dtTop"):
        for row in theme_panels.get(key) or []:
            if isinstance(row, dict):
                push(row.get("name"))
    for row in md.get("leaders") or []:
        if isinstance(row, dict):
            push(row.get("theme"))
    code_themes = md.get("zt_code_themes") if isinstance(md.get("zt_code_themes"), dict) else {}
    for themes in code_themes.values():
        for theme in themes or []:
            push(theme)

    for signal_key in ("tideSignal", "coreTideSignal"):
        signal = md.get(signal_key) if isinstance(md.get(signal_key), dict) else {}
        for row in signal.get("themes") or []:
            if isinstance(row, dict):
                push(row.get("name"), row.get("canonical_name"))
    zt_analysis = md.get("ztAnalysis") if isinstance(md.get("ztAnalysis"), dict) else {}
    for bucket_key in ("relay", "watch"):
        for row in zt_analysis.get(bucket_key) or []:
            if not isinstance(row, dict):
                continue
            push(row.get("predTheme"), row.get("predThemeCanonical"))
            push(row.get("plateName"), row.get("plateNameCanonical"))

    if isinstance(watchlist, dict):
        ladder = watchlist.get("ladder") if isinstance(watchlist.get("ladder"), dict) else {}
        for row in ladder.get("main_lines") or []:
            if not isinstance(row, dict):
                continue
            push(row.get("name"))
            for theme in row.get("constituents") or []:
                push(theme)
        picks = watchlist.get("picks_advisor") if isinstance(watchlist.get("picks_advisor"), dict) else {}
        for row in picks.get("main_line_picks") or []:
            if not isinstance(row, dict):
                continue
            push(row.get("main_line"))
            for theme in row.get("constituents") or []:
                push(theme)
        sector_resolution = watchlist.get("sector_resolution") if isinstance(watchlist.get("sector_resolution"), dict) else {}
        stock_to_sectors = sector_resolution.get("stock_to_sectors") if isinstance(sector_resolution.get("stock_to_sectors"), dict) else {}
        for info in stock_to_sectors.values():
            sectors = info.get("sectors") if isinstance(info, dict) else []
            for sector in sectors or []:
                if isinstance(sector, dict):
                    push(sector.get("sector"))

    return {key: sorted(values) for key, values in alias_map.items() if key and values}


def _normalize_theme_token(value: object) -> str:
    return "".join(str(value or "").strip().split()).lower()


def _build_theme_alias_lookup(md: dict) -> tuple[dict[str, str], list[tuple[str, str]]]:
    raw_map = md.get("theme_alias_map") if isinstance(md.get("theme_alias_map"), dict) else _build_theme_alias_map(md)
    lookup: dict[str, str] = {}
    for key, aliases in raw_map.items():
        canonical = str(key or "").strip()
        if not canonical:
            continue
        for name in [canonical, *(aliases if isinstance(aliases, list) else [])]:
            token = _normalize_theme_token(name)
            if token and token not in lookup:
                lookup[token] = canonical
    ordered = sorted(lookup.items(), key=lambda item: len(item[0]), reverse=True)
    return lookup, ordered


def _canonicalize_theme_name(name: object, *, lookup: dict[str, str], ordered_aliases: list[tuple[str, str]]) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    normalized = str(normalize_sector(raw) or raw).strip()
    for candidate in (raw, normalized):
        token = _normalize_theme_token(candidate)
        if token and token in lookup:
            return lookup[token]
    raw_token = _normalize_theme_token(raw)
    for alias_token, canonical in ordered_aliases:
        if alias_token and (alias_token in raw_token or raw_token in alias_token):
            return canonical
    return normalized or raw


def _load_cached_xgb_surge_plates(date8: str) -> list[dict]:
    path = ROOT / "cache_online" / f"xuangubao_surge_plates-{date8}.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    raw = payload.get("raw") if isinstance(payload, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    inner = data.get("data") if isinstance(data.get("data"), dict) else {}
    items = inner.get("items") if isinstance(inner, dict) else None
    return [row for row in (items or []) if isinstance(row, dict)]


def _load_cached_eastmoney_tomorrow_themes(date8: str) -> list[dict]:
    path = ROOT / "cache_online" / f"eastmoney_tomorrow_themes-{date8}.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    raw = payload.get("raw") if isinstance(payload, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    inner = raw.get("raw") if isinstance(raw.get("raw"), dict) else {}
    items = inner.get("data") if isinstance(inner, dict) else None
    return [row for row in (items or []) if isinstance(row, dict)]


def _prune_plan_text_fields(md: dict) -> None:
    """移除明日行动指南已下线的聚焦/底部文案字段。"""
    if not isinstance(md, dict):
        return
    md.pop("actionGuideV2", None)
    md.pop("summary3", None)


def _is_complete_stock_research_backtest(payload: object) -> bool:
    """
    判断个股回测对象是否为当前前端可直接消费的完整 schema。

    说明：
    - 早期缓存里可能带着旧版 stockResearchBacktest，对象存在但字段不全；
    - 这类旧对象若直接透传到线上，会让“当前研究池/历史回测”表现为空或不完整；
    - 因此这里只要关键字段缺失，就在 publish 阶段强制重算。
    """
    if not isinstance(payload, dict):
        return False
    if str(payload.get("schema") or "") != "stock_research_backtest_v2":
        return False
    summary = payload.get("summary")
    realtime_buy = payload.get("realtimeBuy")
    meta = payload.get("meta")
    current_pool_records = payload.get("currentPoolRecords")
    records = payload.get("records")
    if not isinstance(summary, dict) or not isinstance(realtime_buy, dict) or not isinstance(meta, dict):
        return False
    if not isinstance(current_pool_records, list) or not isinstance(records, list):
        return False
    required_summary_keys = {
        "total_samples",
        "source_samples",
        "filtered_non_backtest_samples",
        "eligible_samples",
        "realtime_candidate_count",
        "realtime_buy_count",
        "realtime_pending_count",
        "realtime_unavailable_count",
    }
    if not required_summary_keys.issubset(summary.keys()):
        return False
    if "latest_recommendation_date" not in meta:
        return False
    if "active_trade_date" not in meta:
        return False
    if "trade_date" not in realtime_buy:
        return False
    return True


def _ensure_stock_research_backtest(md: dict) -> None:
    """
    为 web 数据补齐个股回测。

    说明：
    - 优先保留 cache/market_data 已经写入的 stockResearchBacktest；
    - 若旧缓存里还没有，则在 publish 阶段现场补算，保证 web 新 tab 有数据可读；
    - 失败时静默跳过，前端会展示空态说明。
    """
    if not isinstance(md, dict):
        return
    existing = md.get("stockResearchBacktest")
    if _is_complete_stock_research_backtest(existing):
        return
    preserved = ((md.get("preservedResearch") or {}) if isinstance(md.get("preservedResearch"), dict) else {}).get("marketData")
    preserved_backtest = preserved.get("stockResearchBacktest") if isinstance(preserved, dict) else None
    if _is_complete_stock_research_backtest(preserved_backtest):
        md["stockResearchBacktest"] = preserved_backtest
        return
    try:
        from scripts.build_stock_research_backtest import build_stock_research_backtest_payload

        md["stockResearchBacktest"] = build_stock_research_backtest_payload(current_market_data=md)
    except Exception:
        return


def _resolve_data_path(date8: str, source: Optional[str] = None) -> Path:
    """解析数据源路径；优先使用显式 source，其次回退到标准收盘缓存。"""
    if source:
        data_path = Path(source)
        if not data_path.is_absolute():
            data_path = ROOT / data_path
        return data_path
    return ROOT / "cache" / f"market_data-{date8}.json"


def _resolve_eastmoney_tomorrow_path() -> Path:
    path = ROOT / "web" / "public" / "eastmoney_tomorrow.json"
    fallback = ROOT / "web" / "dist" / "eastmoney_tomorrow.json"
    if path.exists():
        return path
    return fallback


def _resolve_intraday_resonance_path(date8: str) -> Path:
    """盘中共振数据，从 cache_online 读取（由 cli intraday 模式产出）"""
    path = ROOT / "cache_online" / f"intraday_resonance-{date8}.json"
    if path.exists():
        return path
    return ROOT / "web" / "public" / "intraday_resonance.json"


def _resolve_watchlist_path(date8: str) -> Path:
    """
    watchlist_cache 由 tools/fetch_watchlist.py 产出，保存在 cache_online/。

    注意：watchlist 的"数据日期"通常是接口当天（YYYY-MM-DD），可能与涨停池
    数据日期（pools_date）不一致。这里先按 date8 找；若不存在，回退到最新一份。
    """
    direct = ROOT / "cache_online" / f"watchlist_cache-{date8}.json"
    if direct.exists():
        return direct
    files = sorted((ROOT / "cache_online").glob("watchlist_cache-*.json"))
    return files[-1] if files else direct


def _build_watchlist_stock_index(watchlist: dict) -> dict:
    """
    反向索引：code -> {primary_sector, primary_confidence, all_sectors,
                      main_line, main_line_confidence}

    前端可 O(1) 查询，避免每个 zt-item 都遍历 stock_to_sectors。
    """
    out: dict = {}
    sec = watchlist.get("sector_resolution") or {}
    sts = sec.get("stock_to_sectors") or {}
    if not isinstance(sts, dict):
        return out

    main_lines = (watchlist.get("ladder") or {}).get("main_lines") or []
    sector_to_main: dict[str, tuple[str, float]] = {}
    for ml in main_lines:
        if not isinstance(ml, dict):
            continue
        ml_name = str(ml.get("name") or "")
        ml_conf = float(ml.get("confidence") or 0.0)
        if not ml_name:
            continue
        for sector in ml.get("constituents") or []:
            if isinstance(sector, str) and sector:
                prev = sector_to_main.get(sector)
                if prev is None or ml_conf > prev[1]:
                    sector_to_main[sector] = (ml_name, ml_conf)

    for code, info in sts.items():
        if not isinstance(info, dict):
            continue
        sectors = info.get("sectors") or []
        if not isinstance(sectors, list) or not sectors:
            continue
        sorted_sectors = sorted(
            (
                (str(sector.get("sector") or ""), float(sector.get("confidence") or 0.0))
                for sector in sectors
                if isinstance(sector, dict) and sector.get("sector")
            ),
            key=lambda kv: kv[1],
            reverse=True,
        )
        if not sorted_sectors:
            continue
        primary_sector, primary_conf = sorted_sectors[0]
        best_main: tuple[str, float] | None = None
        for sec_name, _confidence in sorted_sectors:
            cand = sector_to_main.get(sec_name)
            if cand and (best_main is None or cand[1] > best_main[1]):
                best_main = cand
        out[str(code)] = {
            "primary_sector": primary_sector,
            "primary_confidence": round(primary_conf, 3),
            "all_sectors": [[name, round(conf, 3)] for name, conf in sorted_sectors[:5]],
            "main_line": best_main[0] if best_main else "",
            "main_line_confidence": round(best_main[1], 3) if best_main else 0.0,
        }
    return out


def _enhance_with_watchlist(md: dict, watchlist: dict) -> None:
    """
    用 watchlist 多源融合结果就地增强 md：
    1. 重写 zt_code_themes（watchlist 在前，原列表兜底）
    2. 让 watchlist 最强主线占据 themePanels.ztTop[0]
    3. 透传 watchlist 整包 + 反向索引

    所有改动都是 idempotent + graceful：watchlist 为空时直接返回。
    """
    if not isinstance(watchlist, dict) or not watchlist:
        return

    sec = watchlist.get("sector_resolution") or {}
    sts = sec.get("stock_to_sectors") or {}

    if isinstance(sts, dict) and sts:
        old_map = dict(md.get("zt_code_themes") or {})
        new_map: dict = {}
        for code, info in sts.items():
            sectors = info.get("sectors") if isinstance(info, dict) else None
            if not isinstance(sectors, list):
                continue
            themes = [
                str(sector.get("sector") or "").strip()
                for sector in sectors
                if isinstance(sector, dict) and sector.get("sector")
            ]
            themes = [theme for theme in themes if theme]
            origin = old_map.get(str(code)) or []
            for theme in origin:
                theme_text = str(theme or "").strip()
                if theme_text and theme_text not in themes:
                    themes.append(theme_text)
            if themes:
                new_map[str(code)] = themes
        for code, themes in old_map.items():
            if str(code) not in new_map:
                new_map[str(code)] = themes
        md["zt_code_themes"] = new_map

    main_lines = (watchlist.get("ladder") or {}).get("main_lines") or []
    if main_lines and isinstance(main_lines[0], dict):
        top_name = str(main_lines[0].get("name") or "").strip()
        if top_name and isinstance(md.get("themePanels"), dict):
            zt_top = list(md["themePanels"].get("ztTop") or [])
            existing_idx = next(
                (
                    idx
                    for idx, row in enumerate(zt_top)
                    if isinstance(row, dict) and str(row.get("name") or "") == top_name
                ),
                -1,
            )
            if existing_idx > 0:
                zt_top.insert(0, zt_top.pop(existing_idx))
            elif existing_idx < 0:
                zt_top.insert(0, {"name": top_name, "source": "watchlist"})
            md["themePanels"]["ztTop"] = zt_top

    md["watchlist"] = watchlist
    md["watchlist_stock_index"] = _build_watchlist_stock_index(watchlist)

    picks = watchlist.get("picks_advisor")
    if isinstance(picks, dict) and picks.get("main_line_picks"):
        md["picks_advisor"] = picks

    tide = watchlist.get("tide_signal")
    if isinstance(tide, dict):
        md["tideSignal"] = tide

    core_tide = watchlist.get("core_tide_signal")
    if isinstance(core_tide, dict):
        md["coreTideSignal"] = core_tide

    md["theme_alias_map"] = _build_theme_alias_map(md, watchlist)


def _ensure_mood_history(md: dict, *, date8: str) -> None:
    """
    对齐 daily_review.cli 的历史回填逻辑：
    publish service 直接从 cache/market_data-YYYYMMDD.json 生成 web 产物时，
    原始缓存未必已经带上 features.mood_inputs.hist_*。
    这里显式补一遍，避免 dist/public 里的更多维度和 moodTrend7d 仍然读到空历史。
    """
    try:
        date10 = f"{date8[0:4]}-{date8[4:6]}-{date8[6:8]}"
        inject_mood_history_and_delta(root=ROOT, date=date10, market_data=md)
    except Exception as exc:
        print(f"⚠ 情绪历史回填失败（跳过）: {exc}", file=sys.stderr)


def _load_market_data(date8: str, source: Optional[str] = None) -> tuple[dict, Path]:
    data_path = _resolve_data_path(date8, source)
    if not data_path.exists():
        raise FileNotFoundError(f"数据缓存不存在: {data_path}")
    return json.loads(data_path.read_text(encoding="utf-8")), data_path


def _rebuild_web_derivatives(md: dict, *, date8: str, warn_context: str = "") -> None:
    md.pop("raw", None)
    _prune_plan_text_fields(md)
    _ensure_stock_research_backtest(md)
    _ensure_mood_history(md, date8=date8)
    try:
        from daily_review.render.render_html import (
            build_market_overview_7d,
            build_mood_trend_7d,
            build_sentiment_explain_dims,
        )

        md["marketOverview7d"] = build_market_overview_7d(market_data=md)
        md["moodTrend7d"] = build_mood_trend_7d(market_data=md)
        md["sentimentExplainDims"] = build_sentiment_explain_dims(market_data=md)
    except Exception as exc:
        label = f"{warn_context}跳过" if warn_context else "跳过"
        print(f"⚠ 7日情绪衍生字段重算失败（{label}）: {exc}", file=sys.stderr)


def _apply_watchlist_enhancements(md: dict, *, date8: str, warn_context: str = "") -> None:
    wl_path = _resolve_watchlist_path(date8)
    if wl_path.exists():
        try:
            watchlist = json.loads(wl_path.read_text(encoding="utf-8"))
            _enhance_with_watchlist(md, watchlist)
        except Exception as exc:
            label = f"{warn_context}跳过" if warn_context else "跳过"
            print(f"⚠ watchlist 增强失败（{label}）: {exc}", file=sys.stderr)
    if "theme_alias_map" not in md:
        md["theme_alias_map"] = _build_theme_alias_map(md)


def _build_shortline_decision(md: dict) -> dict:
    mood_stage = md.get("moodStage") if isinstance(md.get("moodStage"), dict) else {}
    mood = md.get("mood") if isinstance(md.get("mood"), dict) else {}
    plan_guide = md.get("planGuide") if isinstance(md.get("planGuide"), dict) else {}
    rotation = md.get("rotation") if isinstance(md.get("rotation"), dict) else {}
    panorama = md.get("panorama") if isinstance(md.get("panorama"), dict) else {}
    theme_panels = md.get("themePanels") if isinstance(md.get("themePanels"), dict) else {}
    plate_rank = md.get("plateRankTop10") if isinstance(md.get("plateRankTop10"), list) else []
    ladder = md.get("ladder") if isinstance(md.get("ladder"), list) else []
    structure_summary = (md.get("structureV2") or {}).get("summary") if isinstance(md.get("structureV2"), dict) else []
    core_tide = md.get("coreTideSignal") if isinstance(md.get("coreTideSignal"), dict) else {}
    if not core_tide:
        core_tide = md.get("tideSignal") if isinstance(md.get("tideSignal"), dict) else {}
    market_regime = core_tide.get("marketRegime") if isinstance(core_tide.get("marketRegime"), dict) else {}
    picks_advisor = md.get("picks_advisor") if isinstance(md.get("picks_advisor"), dict) else {}
    backtest = md.get("stockResearchBacktest") if isinstance(md.get("stockResearchBacktest"), dict) else {}

    rightside_text = str(plan_guide.get("rightsideText") or mood_stage.get("stance") or "").strip()
    if any(text in rightside_text for text in ("禁止", "防守", "休息")):
        stance_tone = "danger"
        stance_label = "先防守"
    elif any(text in rightside_text for text in ("允许", "进攻", "确认")):
        stance_tone = "attack"
        stance_label = "可进攻"
    else:
        stance_tone = "watch"
        stance_label = "可试错"

    stance_lead = str(plan_guide.get("advice") or "").strip() or str(mood_stage.get("detail") or "").strip() or "先看情绪、主线和接力环境，再决定是否出手。"

    explicit_position = plan_guide.get("position")
    if explicit_position not in (None, ""):
        position_text = _format_pct_from_ratio(explicit_position)
    else:
        heat = _to_float(mood.get("heat"), 0.0)
        risk = _to_float(mood.get("risk"), 0.0)
        if risk >= heat + 10:
            position_text = "20%–35%"
        elif heat >= risk + 10:
            position_text = "50%–70%"
        else:
            position_text = "35%–50%"
    position_hint = f"{rightside_text} · {str(plan_guide.get('nature') or '优先看主线')}".strip(" ·") if rightside_text else str(rotation.get("style") or "按情绪和主线动态调整")

    top_theme = theme_panels.get("ztTop")[0] if isinstance(theme_panels.get("ztTop"), list) and theme_panels.get("ztTop") else {}
    top_plate = plate_rank[0] if plate_rank and isinstance(plate_rank[0], dict) else {}
    mainline_title = str((top_theme or {}).get("name") or "").strip() or str(top_plate.get("name") or "").strip() or str(plan_guide.get("mainline") or "暂无明确主线")
    mainline_hint_parts = []
    if top_plate.get("name"):
        mainline_hint_parts.append(f"板块强度：{top_plate.get('name')}")
    if top_plate.get("lead"):
        mainline_hint_parts.append(f"核心：{top_plate.get('lead')}")
    if rotation.get("style"):
        mainline_hint_parts.append(f"风格：{rotation.get('style')}")
    mainline_hint = " · ".join(mainline_hint_parts) or "主线未完全聚焦，优先跟辨识度最高的方向。"
    from_summary = core_tide.get("summary", {}).get("mainline_candidates") if isinstance(core_tide.get("summary"), dict) else []
    from_themes = []
    for row in core_tide.get("themes") or []:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "")
        if any(flag in status for flag in ("confirmed", "resonance", "observe", "traverse")):
            label = str(row.get("canonical_name") or row.get("name") or "").strip()
            if label:
                from_themes.append(label)
    mainline_candidates = list(dict.fromkeys([str(x).strip() for x in (from_summary or []) + from_themes if str(x).strip()]))[:5]

    ladder_top = ladder[0] if ladder and isinstance(ladder[0], dict) else {}
    ladder_title = "暂无高度核心"
    ladder_hint = "等待高度与承接进一步确认。"
    if ladder_top:
        ladder_title = f"{ladder_top.get('name') or '-'} {ladder_top.get('badge') or '-'}板"
        quality = str(ladder_top.get("qualityLabel") or "承接待确认")
        next_step = str(ladder_top.get("status") or "")
        ladder_hint = f"{quality} · {next_step or '次日看承接'}"
    ladder_action = ""
    if isinstance(structure_summary, list):
        for row in structure_summary:
            if isinstance(row, dict) and str(row.get("key") or "") == "height":
                ladder_action = str(row.get("action") or "")
                break
    ladder_action = ladder_action or str(ladder_top.get("note") or "重点看高位是否出现换手回封。")

    warnings = plan_guide.get("warnings") if isinstance(plan_guide.get("warnings"), list) else []
    reasons = market_regime.get("reasons") if isinstance(market_regime.get("reasons"), list) else []
    risk_warnings = list(dict.fromkeys([str(x).strip() for x in [*warnings, *reasons] if str(x).strip()]))[:4]

    flattened_picks: list[dict] = []
    for group in picks_advisor.get("main_line_picks") or []:
        if not isinstance(group, dict):
            continue
        main_line = str(group.get("main_line") or "").strip()
        for bucket in ("buy", "watch"):
            for row in group.get(bucket) or []:
                if isinstance(row, dict):
                    flattened_picks.append({**row, "bucket": bucket, "line": main_line})
    flattened_picks.sort(key=lambda row: (0 if row.get("bucket") == "buy" else 1, -_to_float(row.get("score"), 0.0)))

    def _candidate_tone(row: dict) -> str:
        if str(row.get("bucket") or "") == "buy":
            return "attack"
        if _to_float(row.get("risk_penalty"), 0.0) >= 5 or any(flag in str(row.get("tide_status") or "") for flag in ("avoid", "weak")):
            return "danger"
        return "watch"

    market_gate = str((picks_advisor.get("diagnostics") or {}).get("market_gate") or "").strip() or "按情绪择时"
    tide_gate = str((picks_advisor.get("diagnostics") or {}).get("core_tide_status") or "").strip() or "neutral"
    strict_gate = market_gate in {"休息优先", "防守优先"} or stance_tone == "danger"

    primary_candidates_raw = [row for row in flattened_picks if row.get("bucket") == "buy"][:3]
    watch_candidates_raw = [row for row in flattened_picks if row.get("bucket") != "buy"][:4]
    if strict_gate:
        watch_candidates_raw = (primary_candidates_raw + watch_candidates_raw)[:4]
        primary_candidates_raw = []

    def _candidate_reason_text(row: dict) -> str:
        reasons_local = [str(x).strip() for x in (row.get("reasons") or []) if str(x).strip()][:3]
        cautions_local = [str(x).strip() for x in (row.get("cautions") or []) if str(x).strip()][:2]
        parts = []
        if reasons_local:
            parts.append("看点：" + " / ".join(reasons_local))
        if cautions_local:
            parts.append("风险：" + " / ".join(cautions_local))
        return " · ".join(parts)

    def _serialize_candidate(row: dict, *, bucket_label: str) -> dict:
        return {
            "code": str(row.get("code") or "").strip(),
            "name": str(row.get("name") or row.get("code") or "-"),
            "line": str(row.get("line") or row.get("main_line") or "").strip(),
            "score": _to_int(row.get("score"), 0),
            "styleTag": str(row.get("style_tag") or "").strip(),
            "primarySector": str(row.get("primary_sector") or "").strip(),
            "reasonText": _candidate_reason_text(row),
            "tone": _candidate_tone(row),
            "bucket": bucket_label,
        }

    primary_candidates = [_serialize_candidate(row, bucket_label="优先跟踪") for row in primary_candidates_raw]
    watch_candidates = [_serialize_candidate(row, bucket_label="观察确认") for row in watch_candidates_raw]

    if primary_candidates:
        trade_summary = f"今天有 {len(primary_candidates)} 只可优先跟踪：" + " / ".join(row["name"] for row in primary_candidates)
    elif watch_candidates:
        trade_summary = f"今天没有明确买点，先观察 {len(watch_candidates)} 只低位/主线候选"
    else:
        trade_summary = "今天没有明确可执行标的，先看情绪与主线是否修复。"
    if strict_gate:
        trade_summary = f"{market_gate}：先观察，暂不把候选当成直接出手信号。"

    current_pool_records = backtest.get("currentPoolRecords") if isinstance(backtest.get("currentPoolRecords"), list) else []
    current_pool_map = {
        str(row.get("code") or "").strip(): row
        for row in current_pool_records
        if isinstance(row, dict) and str(row.get("code") or "").strip()
    }

    script_cards: list[dict] = []
    seen_codes: set[str] = set()
    for row in primary_candidates + watch_candidates:
        code = row.get("code") or ""
        matched = current_pool_map.get(code)
        expectation = matched.get("expectation") if isinstance(matched, dict) else {}
        if not isinstance(expectation, dict):
            continue
        if not any(expectation.get(key) for key in ("expected_text", "super_text", "low_text")):
            continue
        seen_codes.add(code)
        script_cards.append(
            {
                "code": code,
                "name": row.get("name") or code,
                "line": row.get("line") or "",
                "nextStep": str((matched or {}).get("next_step") or (matched or {}).get("bucket_label") or "待验证"),
                "bucket": row.get("bucket"),
                "tone": row.get("tone"),
                "superExpected": str(expectation.get("super_text") or "").strip(),
                "expected": str(expectation.get("expected_text") or "").strip(),
                "lowExpected": str(expectation.get("low_text") or "").strip(),
            }
        )
    for row in current_pool_records:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        if not code or code in seen_codes:
            continue
        expectation = row.get("expectation") if isinstance(row.get("expectation"), dict) else {}
        if not any(expectation.get(key) for key in ("expected_text", "super_text", "low_text")):
            continue
        script_cards.append(
            {
                "code": code,
                "name": str(row.get("name") or code),
                "line": str(row.get("main_line") or row.get("hy") or "").strip(),
                "nextStep": str(row.get("next_step") or row.get("bucket_label") or "待验证"),
                "bucket": "观察确认",
                "tone": "watch",
                "superExpected": str(expectation.get("super_text") or "").strip(),
                "expected": str(expectation.get("expected_text") or "").strip(),
                "lowExpected": str(expectation.get("low_text") or "").strip(),
            }
        )
        if len(script_cards) >= 4:
            break
    script_cards = script_cards[:4]

    historical_records = backtest.get("records") if isinstance(backtest.get("records"), list) else []
    next_day_metric = (backtest.get("metrics") or {}).get("next_day") if isinstance(backtest.get("metrics"), dict) else {}
    next_day_metric = next_day_metric if isinstance(next_day_metric, dict) else {}
    covered_rows = [
        row
        for row in historical_records
        if isinstance(row, dict) and str(((row.get("performance") or {}).get("next_day") or {}).get("status") or "") == "covered"
    ]
    skipped_rows = [
        row
        for row in historical_records
        if isinstance(row, dict) and str(((row.get("performance") or {}).get("next_day") or {}).get("status") or "") == "skipped"
    ]
    wins = [row for row in covered_rows if ((row.get("performance") or {}).get("next_day") or {}).get("win")]
    losses = [row for row in covered_rows if ((row.get("performance") or {}).get("next_day") or {}).get("loss")]
    gap_trap_losses = [row for row in losses if ((row.get("performance") or {}).get("open_check") or {}).get("gap_trap")]
    expected_avg = _to_float(((next_day_metric.get("by_open_status") or {}).get("expected") or {}).get("avg_return"), 0.0)
    super_avg = _to_float(((next_day_metric.get("by_open_status") or {}).get("super") or {}).get("avg_return"), 0.0)

    continue_text = "当前样本还少，先继续按低位确认和同源条件过滤。"
    if len(covered_rows) >= 5 and wins:
        parts = []
        effective_themes = _top_labels(wins, lambda row: (row.get("main_line") if isinstance(row, dict) else ""), limit=2)
        effective_styles = _top_labels(wins, lambda row: (row.get("style_tag") if isinstance(row, dict) else ""), limit=2)
        if effective_themes:
            parts.append("盈利样本更多集中在 " + " / ".join(effective_themes))
        if effective_styles:
            parts.append("形态上 " + " / ".join(effective_styles) + " 更容易留下正收益")
        if expected_avg > super_avg:
            parts.append("符合预期的开口径比硬顶超预期更稳")
        if parts:
            continue_text = "，".join(parts)

    avoid_text = "亏损样本主要说明接力仍要看竞价质量和承接。"
    if len(covered_rows) >= 5 and losses:
        danger_themes = _top_labels(losses, lambda row: (row.get("main_line") if isinstance(row, dict) else ""), limit=2)
        danger_styles = _top_labels(losses, lambda row: (row.get("style_tag") if isinstance(row, dict) else ""), limit=2)
        parts = []
        if super_avg < expected_avg:
            parts.append("超预期开得太高反而更容易吃面，别把高开当成绝对强")
        if gap_trap_losses:
            parts.append(f"当前已有 {len(gap_trap_losses)} 只出现高开陷阱，竞价强不代表收盘强")
        if danger_styles:
            parts.append("风险形态更多出现在 " + " / ".join(danger_styles))
        if danger_themes:
            parts.append("失效方向集中在 " + " / ".join(danger_themes))
        if parts:
            avoid_text = "，".join(parts)

    if len(covered_rows) < 5:
        action_items = [
            f"当前隔日回测仅覆盖 {len(covered_rows)} 个样本，先把它当观察结论，不要放大成铁律。",
            "继续保留低预期过滤和竞价确认纪律，等样本再多一些再调规则。",
            "首页提示以辅助为主，最终仍以后端推送的研究池和竞价条件为准。",
        ]
    else:
        action_items = [
            "优先做符合预期的竞价，不抢明显过热的超预期开口。" if expected_avg > super_avg else "超预期并非绝对差，但仍要叠加承接和量能确认。",
            "看到高开过猛但收盘承接弱的票，宁愿放弃也别追。" if gap_trap_losses else "把低预期直接过滤掉，保留资金给真正符合条件的票。",
            f"最近已有 {len(skipped_rows)} 只被低预期规则挡掉，这条过滤规则先别放松。" if skipped_rows else "继续保留低预期不过滤的纪律，别为了凑交易去强上。",
        ]

    backtest_correction = {
        "sampleReady": len(covered_rows) >= 5,
        "kpis": [
            {"label": "隔日覆盖", "value": f"{next_day_metric.get('covered', 0)}/{next_day_metric.get('eligible', 0)}"},
            {"label": "隔日胜率", "value": f"{next_day_metric.get('win_rate', 0)}%"},
            {"label": "隔日均值", "value": _format_return(next_day_metric.get("avg_return"))},
            {"label": "低预期跳过", "value": str(len(skipped_rows))},
        ],
        "continueText": continue_text,
        "avoidText": avoid_text,
        "actionItems": action_items,
    }

    decision_steps = [
        {"title": "先判断能不能做", "detail": f"{mood_stage.get('title') or '-'} · {stance_label}", "tab": "sentiment", "cta": "看情绪"},
        {"title": "再判断做什么方向", "detail": " / ".join(mainline_candidates) or mainline_title, "tab": "themes", "cta": "看主线"},
        {"title": "接着判断做哪类票", "detail": ladder_action, "tab": "ladder", "cta": "看梯队"},
        {
            "title": "最后看验证与纠偏",
            "detail": f"待验证池 {min(len(current_pool_records), 3)} 只，回测继续补全竞价与收益" if current_pool_records else "没有待验证池时，先看历史回测结论",
            "tab": "backtest",
            "cta": "看回测",
        },
    ]

    radar_cards = [
        {
            "label": "情绪阶段",
            "value": str(mood_stage.get("title") or "-"),
            "note": f"综合 {mood.get('score', '-')} 分 · 热 {mood.get('heat', '-')} / 险 {mood.get('risk', '-')}",
            "tone": stance_tone,
        },
        {
            "label": "建议仓位",
            "value": position_text,
            "note": position_hint,
            "tone": "attack" if stance_tone == "attack" else "watch",
        },
        {
            "label": "主线方向",
            "value": mainline_title,
            "note": mainline_hint,
            "tone": "watch",
        },
        {
            "label": "接力环境",
            "value": ladder_title,
            "note": ladder_hint,
            "tone": "danger" if any(flag in ladder_hint for flag in ("分歧", "烂板", "风险")) else "watch",
        },
    ]

    market_pulse = [
        {"label": "涨停", "value": _to_int(panorama.get("limitUp"), 0) or "-"},
        {"label": "炸板", "value": _to_int(panorama.get("broken"), 0) or "-"},
        {"label": "跌停", "value": _to_int(panorama.get("limitDown"), 0) or "-"},
        {"label": "封板率", "value": str(panorama.get("ratio") or "-")},
    ]

    current_pool_preview = [
        {
            "code": str(row.get("code") or "").strip(),
            "name": str(row.get("name") or row.get("code") or "-"),
            "line": str(row.get("main_line") or row.get("hy") or "").strip(),
            "nextStep": str(row.get("next_step") or row.get("bucket_label") or "待验证"),
        }
        for row in current_pool_records[:3]
        if isinstance(row, dict)
    ]

    indices_rows = [
        {"code": str(row.get("code") or ""), "name": str(row.get("name") or "-"), "chg": str(row.get("chg") or "-")}
        for row in (md.get("indices") or [])[:3]
        if isinstance(row, dict)
    ]
    index_foot = f"市场节奏：{market_regime.get('status') or '-'} · 风险级别 {market_regime.get('risk_level') or '-'} · 量能 {mood.get('market_components', {}).get('volume_score', '-') if isinstance(mood.get('market_components'), dict) else '-'}"

    hero_tags = [
        str(mood_stage.get("mode") or mood_stage.get("stance") or "观察确认"),
        str(plan_guide.get("nature") or "主线优先"),
        str(rotation.get("style") or "按结构应对"),
    ]

    return {
        "stanceTone": stance_tone,
        "stanceLabel": stance_label,
        "stanceLead": stance_lead,
        "heroTags": [tag for tag in hero_tags if tag],
        "marketPulse": market_pulse,
        "radarCards": radar_cards,
        "mainline": {
            "title": "今天先看哪些方向",
            "hint": mainline_hint,
            "candidates": mainline_candidates,
            "jumpTab": "themes",
            "jumpLabel": "展开主线证据",
        },
        "risk": {
            "title": "今天最容易亏在哪",
            "warnings": risk_warnings,
            "jumpTab": "sentiment",
            "jumpLabel": "回到情绪细节",
        },
        "decisionSteps": decision_steps,
        "tradePlan": {
            "title": "先买谁，再观察谁",
            "summary": trade_summary,
            "marketGate": market_gate,
            "tideGate": tide_gate,
            "strictGate": strict_gate,
            "primaryCandidates": primary_candidates,
            "watchCandidates": watch_candidates,
            "jumpTab": "plan",
            "jumpLabel": "展开全部个股研究",
        },
        "scripts": {
            "title": "次日 9:25 重点怎么判",
            "cards": script_cards,
            "jumpTab": "backtest",
            "jumpLabel": "展开回测与竞价验证",
        },
        "backtestCorrection": {
            "title": "最近样本在提醒我们什么",
            **backtest_correction,
            "jumpTab": "backtest",
            "jumpLabel": "回到回测明细",
        },
        "currentPool": {
            "title": "次日优先盯哪些票",
            "rows": current_pool_preview,
            "jumpTab": "backtest",
        },
        "indices": {
            "title": "指数和环境怎么配合",
            "rows": indices_rows,
            "foot": index_foot,
        },
    }


def _build_sentiment_decision(md: dict) -> dict:
    theme_panels = md.get("themePanels") if isinstance(md.get("themePanels"), dict) else {}
    top_zt_theme = theme_panels.get("ztTop")[0] if isinstance(theme_panels.get("ztTop"), list) and theme_panels.get("ztTop") else {}
    rotation = md.get("rotation") if isinstance(md.get("rotation"), dict) else {}
    structure_v2 = md.get("structureV2") if isinstance(md.get("structureV2"), dict) else {}
    zt_code_themes = md.get("zt_code_themes") if isinstance(md.get("zt_code_themes"), dict) else {}
    ztgc = md.get("ztgc") if isinstance(md.get("ztgc"), list) else []
    features = md.get("features") if isinstance(md.get("features"), dict) else {}
    mood_inputs = features.get("mood_inputs") if isinstance(features.get("mood_inputs"), dict) else {}

    date8 = str(md.get("date") or "").replace("-", "")
    alias_lookup, ordered_aliases = _build_theme_alias_lookup(md)

    xgb_plates = _load_cached_xgb_surge_plates(date8) if date8 else []
    em_themes = _load_cached_eastmoney_tomorrow_themes(date8) if date8 else []

    xgb_hot_set = {
        _canonicalize_theme_name(row.get("name"), lookup=alias_lookup, ordered_aliases=ordered_aliases)
        for row in xgb_plates
        if str(row.get("id") or "").strip() != "-1" and str(row.get("name") or "").strip()
    }
    xgb_hot_set.discard("")

    em_all_names = [
        _canonicalize_theme_name(row.get("themeName"), lookup=alias_lookup, ordered_aliases=ordered_aliases)
        for row in em_themes
        if str(row.get("themeName") or "").strip()
    ]
    em_all_set = {name for name in em_all_names if name}
    em_hot_names = [
        _canonicalize_theme_name(row.get("themeName"), lookup=alias_lookup, ordered_aliases=ordered_aliases)
        for row in em_themes
        if row.get("isHot") in (1, "1", True) and str(row.get("themeName") or "").strip()
    ]
    em_hot_set = {name for name in em_hot_names if name}

    top_theme_name = str((top_zt_theme or {}).get("name") or "").strip()
    top_theme_canonical = _canonicalize_theme_name(top_theme_name, lookup=alias_lookup, ordered_aliases=ordered_aliases)
    narrative_sources: list[str] = []
    if top_theme_canonical and top_theme_canonical in xgb_hot_set:
        narrative_sources.append("选股宝热点")
    if top_theme_canonical and top_theme_canonical in em_hot_set:
        narrative_sources.append("东财明日热门")
    elif top_theme_canonical and top_theme_canonical in em_all_set:
        narrative_sources.append("东财明日")
    narrative_hit = bool(narrative_sources)

    zt_total_count = _to_int(mood_inputs.get("zt_count"), 0)
    if zt_total_count <= 0:
        zt_total_count = sum(_to_int(row.get("count"), 0) for row in (theme_panels.get("ztTop") or []) if isinstance(row, dict))
    top_theme_count = _to_int((top_zt_theme or {}).get("count"), 0)
    top_zt_conc_ratio = round((top_theme_count / zt_total_count) * 1000) / 10 if top_theme_count and zt_total_count else 0.0

    style = str(rotation.get("style") or "").strip()
    high_ratio = _to_float(rotation.get("highLevelRatio"), 0.0)
    overlap_score_raw = str((((structure_v2.get("evidence") or {}) if isinstance(structure_v2.get("evidence"), dict) else {}).get("overlap") or {}).get("score") or "").replace("%", "")
    overlap = _to_float(overlap_score_raw, float("nan"))

    if not top_zt_conc_ratio:
        resonance_verdict = {"text": "-", "cls": ""}
    elif overlap == overlap and overlap >= 50:
        resonance_verdict = {"text": "主线与炸板高度重叠,主线在分歧/退潮,情绪面承压", "cls": "orange-text"}
    elif top_zt_conc_ratio >= 35 and narrative_hit:
        resonance_verdict = {"text": f"主线抱团 + {'/'.join(narrative_sources)} narrative 双重确认,情绪偏强", "cls": "red-text"}
    elif top_zt_conc_ratio >= 35 and any(flag in style for flag in ("高位", "加速", "主升")):
        resonance_verdict = {"text": "主线抱团 + 高位接力,情绪偏热,警惕兑现", "cls": "orange-text"}
    elif top_zt_conc_ratio >= 35:
        resonance_verdict = {"text": "主线抱团明显,接力链条值得追踪", "cls": "red-text"}
    elif top_zt_conc_ratio >= 20 and narrative_hit:
        resonance_verdict = {"text": f"主线初现 + {'/'.join(narrative_sources)} narrative 加持,题材有发酵潜力", "cls": "red-text"}
    elif top_zt_conc_ratio >= 20 and any(flag in style for flag in ("低位", "试错")):
        resonance_verdict = {"text": "主线初现 + 低位试错,题材有发酵潜力", "cls": "red-text"}
    elif top_zt_conc_ratio < 20 and high_ratio >= 30:
        resonance_verdict = {"text": "题材分散 + 高位拥挤,易出现高位接力风险", "cls": "orange-text"}
    elif top_zt_conc_ratio < 20 and not narrative_hit:
        resonance_verdict = {"text": "资金分散且 narrative 未共振,主线尚未形成", "cls": "green-text"}
    elif top_zt_conc_ratio < 20:
        resonance_verdict = {"text": "资金分散,主线尚未形成", "cls": "green-text"}
    else:
        resonance_verdict = {"text": "主线一般,关注后续切换", "cls": "orange-text"}

    narrative_overview = None
    if xgb_plates or em_themes:
        narrative_overview = {
            "xgbCnt": len(xgb_plates),
            "tmrHot": sum(1 for row in em_themes if row.get("isHot") in (1, "1", True)),
            "tmrAll": len(em_themes),
            "topZtName": top_theme_name,
            "hit": narrative_hit,
            "sources": narrative_sources,
        }

    narrative_coverage = None
    if zt_code_themes and xgb_hot_set:
        hit = 0
        hit_codes: list[str] = []
        for code, themes in zt_code_themes.items():
            rows = themes if isinstance(themes, list) else []
            if any(
                _canonicalize_theme_name(theme, lookup=alias_lookup, ordered_aliases=ordered_aliases) in xgb_hot_set
                for theme in rows
            ):
                hit += 1
                if len(hit_codes) < 6:
                    hit_codes.append(str(code).strip())
        total = len(zt_code_themes)
        ratio = round((hit / total) * 100) if total else 0
        if ratio >= 40:
            verdict = "narrative 驱动 — 涨停股大面积命中 narrative 主线"
            cls = "red-text"
        elif ratio >= 20:
            verdict = "部分共振 — 主线在但未全面发酵"
            cls = "orange-text"
        else:
            verdict = "narrative 脱节 — 涨停与今日叙事相关度低"
            cls = "green-text"
        code_to_name = {
            str(row.get("dm") or row.get("code") or "").strip(): str(row.get("mc") or row.get("name") or row.get("dm") or row.get("code") or "").strip()
            for row in ztgc
            if isinstance(row, dict) and str(row.get("dm") or row.get("code") or "").strip()
        }
        narrative_coverage = {
            "total": total,
            "hit": hit,
            "ratio": ratio,
            "hitCodes": hit_codes,
            "hitNames": " / ".join(code_to_name.get(code, code) for code in hit_codes),
            "verdict": verdict,
            "cls": cls,
        }

    return {
        "resonanceVerdict": resonance_verdict,
        "narrativeOverview": narrative_overview,
        "narrativeCoverage": narrative_coverage,
    }


def _build_ladder_decision(md: dict) -> dict:
    ladder_rows = [row for row in (md.get("ladder") or []) if isinstance(row, dict)]
    mood_inputs = ((md.get("features") or {}).get("mood_inputs") or {}) if isinstance(md.get("features"), dict) else {}
    zt_code_themes = md.get("zt_code_themes") if isinstance(md.get("zt_code_themes"), dict) else {}
    top_theme_name = str((((md.get("themePanels") or {}) if isinstance(md.get("themePanels"), dict) else {}).get("ztTop") or [{}])[0].get("name") or "").strip() if isinstance((((md.get("themePanels") or {}) if isinstance(md.get("themePanels"), dict) else {}).get("ztTop") or []), list) and (((md.get("themePanels") or {}) if isinstance(md.get("themePanels"), dict) else {}).get("ztTop") or []) else ""
    alias_lookup, ordered_aliases = _build_theme_alias_lookup(md)

    def themes_for(code: object) -> list[str]:
        key = str(code or "").strip()
        if not key:
            return []
        rows = zt_code_themes.get(key) if isinstance(zt_code_themes.get(key), list) else []
        out: list[str] = []
        for theme in rows[:4]:
            canonical = _canonicalize_theme_name(theme, lookup=alias_lookup, ordered_aliases=ordered_aliases)
            if canonical and canonical not in out:
                out.append(canonical)
        return out

    groups: dict[int, list[dict]] = {}
    for row in ladder_rows:
        badge = _to_int(row.get("badge"), 0)
        if badge <= 0:
            continue
        groups.setdefault(badge, []).append(row)

    grouped_ladder: list[dict] = []
    for badge in sorted(groups.keys(), reverse=True):
        rows = groups[badge]
        sector_counts: dict[str, int] = {}
        for row in rows:
            for theme in themes_for(row.get("code")):
                sector_counts[theme] = sector_counts.get(theme, 0) + 1
        top_sectors = [
            {"name": name, "count": count}
            for name, count in sorted(sector_counts.items(), key=lambda item: (-item[1], item[0]))[:2]
        ]

        def q_count(label: str) -> int:
            return sum(1 for row in rows if str(row.get("qualityLabel") or "") == label)

        accel = q_count("加速确认")
        relay = q_count("温和放量") + q_count("高换手承接")
        weak = q_count("分歧烂板") + q_count("反复回封")
        relay_sentiment = "均衡"
        relay_cls = "kpi-orange"
        if accel > len(rows) * 0.5:
            relay_sentiment = "加速"
            relay_cls = "kpi-red"
        elif relay > len(rows) * 0.4:
            relay_sentiment = "接力"
            relay_cls = "kpi-orange"
        elif weak > len(rows) * 0.3:
            relay_sentiment = "分歧"
            relay_cls = "kpi-blue"

        zbc_values = [_to_float(row.get("zbc"), 0.0) for row in rows]
        reseal_count = sum(1 for value in zbc_values if value >= 1)
        multi_open_count = sum(1 for value in zbc_values if value >= 2)
        reseal_rate = round((reseal_count / len(rows)) * 100) if rows else 0
        multi_open_rate = round((multi_open_count / len(rows)) * 100) if rows else 0
        seal_values = [_to_float(row.get("zj"), 0.0) / 1e8 for row in rows if _to_float(row.get("zj"), 0.0) > 0]
        grouped_ladder.append(
            {
                "badge": badge,
                "badgeClass": "badge-6" if badge >= 6 else "badge-5" if badge == 5 else f"badge-{badge}",
                "rows": rows,
                "count": len(rows),
                "topSectors": top_sectors,
                "relaySentiment": relay_sentiment,
                "relayCls": relay_cls,
                "resealRate": reseal_rate,
                "multiOpenRate": multi_open_rate,
                "resealCls": "kpi-red" if reseal_rate >= 55 else "kpi-orange" if reseal_rate >= 35 else "kpi-blue",
                "multiCls": "kpi-red" if multi_open_rate >= 35 else "kpi-orange" if multi_open_rate >= 18 else "kpi-blue",
                "sealMed": _median_numbers(seal_values),
                "sealMax": max(seal_values) if seal_values else 0.0,
                "resonanceScore": min(len(top_sectors) * 20 + len(rows) * 2 + badge * 5, 100),
            }
        )

    total = len(ladder_rows)
    promote = sum(1 for row in ladder_rows if str(row.get("status") or "") == "晋级")
    yest = _to_int(mood_inputs.get("yest_lb_count"), 0)
    jj_value = mood_inputs.get("jj_rate")
    zb_value = mood_inputs.get("zb_rate")
    zt = _to_int(((md.get("panorama") or {}) if isinstance(md.get("panorama"), dict) else {}).get("limitUp"), 0)
    max_lb = _to_int(mood_inputs.get("max_lb"), 0) or (grouped_ladder[0]["badge"] if grouped_ladder else 0)

    def clean_name(name: object) -> str:
        return str(name or "").lstrip("👑⭐🔥 ").strip()

    def total_q_count(label: str) -> int:
        return sum(1 for row in ladder_rows if str(row.get("qualityLabel") or "") == label)

    accel_count = total_q_count("加速确认")
    warm_count = total_q_count("温和放量")
    rotten_count = total_q_count("分歧烂板")
    reseal_count_total = total_q_count("反复回封")
    high_turn_count = total_q_count("高换手承接")
    top_rows = sorted(ladder_rows, key=lambda row: (-_to_float(row.get("badge"), 0.0), -_to_float(row.get("zj"), 0.0)))
    top_row = top_rows[0] if top_rows else {}
    second_badge = _to_int(top_rows[1].get("badge"), 0) if len(top_rows) > 1 and isinstance(top_rows[1], dict) else 0
    top_badge = _to_int(top_row.get("badge"), 0) or max_lb
    top_name = clean_name(top_row.get("name"))
    has_space_leader = bool(top_name and top_badge >= 5 and top_badge > second_badge)
    tier_span = len(grouped_ladder)

    quality_title = f"{top_name}打开{top_badge}板高度" if has_space_leader else "梯队承接"
    quality_sub = "市场空间核心，先看它对高标与同题材的带动。" if has_space_leader else f"连板覆盖 {tier_span} 个梯队，先看前排能否继续晋级。"
    if not has_space_leader and accel_count + warm_count >= max(3, (total + 1) // 2 if total else 3):
        quality_title = "确认型占优"
        quality_sub = f"加速/温和放量 {accel_count + warm_count} 只，前排承接偏稳。"
    elif not has_space_leader and rotten_count + reseal_count_total >= max(2, int((total * 0.35) + 0.999)):
        quality_title = "分歧板偏多"
        quality_sub = f"烂板/反复回封 {rotten_count + reseal_count_total} 只，次日更看去弱留强。"
    elif not has_space_leader and high_turn_count >= max(2, int((total * 0.25) + 0.999)):
        quality_title = "换手承接"
        quality_sub = f"高换手承接 {high_turn_count} 只，资金偏向换手确认。"

    return {
        "mainTheme": top_theme_name,
        "groupedLadder": grouped_ladder,
        "summary": {
            "total": total,
            "promote": promote,
            "yest": yest,
            "jj": f"{_to_float(jj_value, 0.0):.1f}%" if jj_value not in (None, "") else "-",
            "zt": zt,
            "maxLb": max_lb,
            "zbRate": f"{_to_float(zb_value, 0.0):.1f}%" if zb_value not in (None, "") else "-",
            "qualityTitle": quality_title,
            "qualitySub": quality_sub,
        },
    }


def _build_plan_decision(md: dict) -> dict:
    mood_stage = md.get("moodStage") if isinstance(md.get("moodStage"), dict) else {}
    mood = md.get("mood") if isinstance(md.get("mood"), dict) else {}
    plan_guide = md.get("planGuide") if isinstance(md.get("planGuide"), dict) else {}

    rightside_text = str(plan_guide.get("rightsideText") or "").strip()
    if rightside_text == "禁止":
        stance = "防守"
        cls = "pos-def"
        pill_cls = "def"
    elif rightside_text == "允许":
        stance = "进攻"
        cls = "pos-attack"
        pill_cls = "attack"
    else:
        stance = "均衡"
        cls = "pos-balance"
        pill_cls = "balance"

    explicit_position = plan_guide.get("position")
    if explicit_position not in (None, ""):
        position_range = _format_pct_from_ratio(explicit_position)
    else:
        heat = _to_float(mood.get("heat"), 0.0)
        risk = _to_float(mood.get("risk"), 0.0)
        stage = str(mood_stage.get("type") or "").strip()
        if stage == "fire":
            stance = "防守"
            cls = "pos-def"
            pill_cls = "def"
            position_range = "15–30%"
        elif risk >= heat + 10:
            stance = "防守"
            cls = "pos-def"
            pill_cls = "def"
            position_range = "20%–35%"
        elif heat >= risk + 10:
            stance = "进攻"
            cls = "pos-attack"
            pill_cls = "attack"
            position_range = "50%–70%"
        else:
            position_range = "35%–50%"

    guide_pills = [
        {"text": f"右侧：{rightside_text or '-'}", "primary": True},
    ]
    mainline = str(plan_guide.get("mainline") or "").strip()
    nature = str(plan_guide.get("nature") or "").strip()
    resonance = str(plan_guide.get("resonance") or "").strip()
    if mainline:
        guide_pills.append({"text": f"主线：{mainline}", "primary": False})
    if nature:
        guide_pills.append({"text": f"性质：{nature}", "primary": False})
    if resonance:
        guide_pills.append({"text": f"共振：{resonance}", "primary": False})

    warnings = plan_guide.get("warnings") if isinstance(plan_guide.get("warnings"), list) else []

    return {
        "positionAdvice": {
            "stance": stance,
            "range": position_range,
            "cls": cls,
            "pillCls": pill_cls,
        },
        "guidePills": guide_pills,
        "guideWarnings": [str(x).strip() for x in warnings if str(x).strip()],
    }


def _build_publish_payload(date8: str, source: Optional[str] = None, *, warn_context: str = "") -> str:
    md, _data_path = _load_market_data(date8, source)
    _rebuild_web_derivatives(md, date8=date8, warn_context=warn_context)
    _apply_watchlist_enhancements(md, date8=date8, warn_context=warn_context)
    md["ladderDecision"] = _build_ladder_decision(md)
    md["sentimentDecision"] = _build_sentiment_decision(md)
    md["planDecision"] = _build_plan_decision(md)
    md["shortlineDecision"] = _build_shortline_decision(md)
    preserved_market = ((md.get("preservedResearch") or {}) if isinstance(md.get("preservedResearch"), dict) else {}).get("marketData")
    if isinstance(preserved_market, dict):
        preserved_market["ladderDecision"] = _build_ladder_decision(preserved_market)
        preserved_market["sentimentDecision"] = _build_sentiment_decision(preserved_market)
        preserved_market["planDecision"] = _build_plan_decision(preserved_market)
        preserved_market["shortlineDecision"] = _build_shortline_decision(preserved_market)
    return json.dumps(md, ensure_ascii=False)


def _read_optional_payload(*, path: Path, fallback: Optional[Path] = None, default: str) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    if fallback is not None and fallback.exists():
        return fallback.read_text(encoding="utf-8")
    return default


def _latest_cache_date8() -> Optional[str]:
    files = sorted((ROOT / "cache").glob("market_data-*.json"))
    for path in reversed(files):
        name = path.name.replace("market_data-", "").replace(".json", "")
        if len(name) == 8 and name.isdigit():
            return name
    return None


def build_web_data(date8: str, source: Optional[str] = None) -> Path:
    """生成 web/dist 旁路数据文件并返回 dist 目录。"""
    payload = _build_publish_payload(date8, source)

    tp_payload = _read_optional_payload(
        path=ROOT / "web" / "public" / "tomorrow_picks.json",
        fallback=ROOT / "web" / "dist" / "tomorrow_picks.json",
        default="{}",
    )
    em_payload = _read_optional_payload(path=_resolve_eastmoney_tomorrow_path(), default="{}")
    resonance_payload = _read_optional_payload(path=_resolve_intraday_resonance_path(date8), default="[]")

    dist_dir = ROOT / "web" / "dist"
    if not (dist_dir / "index.html").exists():
        raise FileNotFoundError(f"Vite 构建产物不存在: {dist_dir / 'index.html'}\n请先执行: cd web && npm run build")

    (dist_dir / "market_data.json").write_text(payload, encoding="utf-8")
    (dist_dir / "market_data.js").write_text(f"window.__MARKET_DATA__={payload};", encoding="utf-8")
    if tp_payload != "{}":
        (dist_dir / "tomorrow_picks.json").write_text(tp_payload, encoding="utf-8")
    if em_payload != "{}":
        (dist_dir / "eastmoney_tomorrow.json").write_text(em_payload, encoding="utf-8")
    if resonance_payload != "[]":
        (dist_dir / "intraday_resonance.json").write_text(resonance_payload, encoding="utf-8")

    return dist_dir


def inject(date8: str, source: Optional[str] = None) -> Path:
    """兼容旧调用名：只生成 web 运行时数据。"""
    return build_web_data(date8, source)


def refresh_dev_data(date8: str, source: Optional[str] = None) -> None:
    """刷新 web/public 数据文件（供 Vite dev 和 dist 直开使用）"""
    payload = _build_publish_payload(date8, source, warn_context="dev ")

    dev_file = ROOT / "web" / "public" / "market_data.json"
    dev_script = ROOT / "web" / "public" / "market_data.js"
    dev_file.parent.mkdir(parents=True, exist_ok=True)
    dev_file.write_text(payload, encoding="utf-8")
    dev_script.write_text(f"window.__MARKET_DATA__={payload};", encoding="utf-8")

    res_file = _resolve_intraday_resonance_path(date8)
    if res_file.exists():
        target_res_file = ROOT / "web" / "public" / "intraday_resonance.json"
        if res_file.resolve() != target_res_file.resolve():
            shutil.copy2(res_file, target_res_file)
            print("  盘中共振 dev 数据已同步")
    print(f"  dev 数据已刷新: {dev_file}")
    print(f"  dev 脚本已刷新: {dev_script}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="将 market_data 写入 web/public 与 web/dist 数据文件")
    ap.add_argument("date8", nargs="?", help="交易日，格式 YYYYMMDD；不传则自动取最新缓存")
    ap.add_argument("--dev-only", action="store_true", help="仅刷新 web/public 下的数据文件")
    ap.add_argument("--source", help="显式指定数据源 JSON 路径，可用于 intraday 缓存")
    args = ap.parse_args(argv)

    if args.dev_only:
        date8 = args.date8 or _latest_cache_date8()
        if not date8:
            print("错误: cache/ 中没有 market_data-*.json", file=sys.stderr)
            return 1
        refresh_dev_data(date8, args.source)
        return 0

    date8 = args.date8 or _latest_cache_date8()
    if not date8:
        print("错误: cache/ 中没有 market_data-*.json", file=sys.stderr)
        return 1

    out = inject(date8, args.source)
    print(f"✅ web 数据已生成: {out}")
    source_path = _resolve_data_path(date8, args.source)
    source_text = source_path.relative_to(ROOT) if source_path.is_relative_to(ROOT) else source_path
    print(f"   数据来源: {source_text}")
    print("   Web 入口: web/dist/index.html")

    refresh_dev_data(date8, args.source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
