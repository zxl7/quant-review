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
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

from daily_review.application.mood_history_service import inject_mood_history_and_delta
from daily_review.features.sector_resolver import CHAIN_MAP, normalize_sector


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


def _plan_chip(text: str, cls: str) -> dict[str, str]:
    return {"text": str(text or "").strip(), "cls": str(cls or "").strip()}


def _build_plan_stock_tags(stock: dict, plate_name: str = "") -> list[dict[str, str]]:
    tags: list[dict[str, str]] = []
    if str(stock.get("source") or "") == "xgb":
        tags.append(_plan_chip("实时", "stp-chip stp-chip-hot"))
    limit_up_days = _to_int(stock.get("limitUpDays"), _to_int(stock.get("lbc"), 0))
    lbc = _to_int(stock.get("lbc"), 0)
    if limit_up_days >= 2 or lbc >= 2:
        tags.append(_plan_chip(f"{max(limit_up_days, lbc)}板", "stp-chip stp-chip-red"))
    else:
        tags.append(_plan_chip("首板", "stp-chip stp-chip-amber"))
    change_pct = _to_float(stock.get("changePct"), 0.0)
    if change_pct >= 8:
        tags.append(_plan_chip(f"涨幅+{change_pct:.1f}%", "stp-chip stp-chip-red"))
    elif change_pct >= 3:
        tags.append(_plan_chip(f"涨幅+{change_pct:.1f}%", "stp-chip stp-chip-amber"))
    seal_fund = _to_float(stock.get("zjYi"), 0.0)
    turnover_yi = _to_float(stock.get("cjeYi"), 0.0)
    if seal_fund >= 1.5:
        tags.append(_plan_chip(f"封{seal_fund:.1f}亿", "stp-chip stp-chip-blue"))
    elif turnover_yi >= 20:
        tags.append(_plan_chip(f"{turnover_yi:.0f}亿", "stp-chip stp-chip-blue"))
    if plate_name:
        tags.append(_plan_chip(plate_name, "stp-chip stp-chip-slate"))
    return tags[:4]


def _calculate_plan_stock_score(stock: dict, plate_strength: float = 0.0, *, is_realtime_plate: bool = False) -> int:
    score = 24.0
    score += min(_to_int(stock.get("lbc"), 0) * 15, 45)
    score += min(_to_float(stock.get("zjYi"), 0.0) * 6, 16)
    score += min(_to_float(stock.get("cjeYi"), 0.0) * 0.5, 12)
    score += min(_to_float(stock.get("changePct"), 0.0) * 1.4, 12)
    score += min(plate_strength / 5, 10)
    if is_realtime_plate:
        score += 6
    if str(stock.get("source") or "") == "xgb":
        score += 8
    if _to_int(stock.get("limitUpDays"), 0) >= 2:
        score += 6
    zbc = _to_int(stock.get("zbc"), 0)
    if zbc >= 3:
        score -= 8
    elif zbc >= 1:
        score -= 3
    return max(0, min(100, round(score)))


def _calculate_plan_resonance_score(sources: list[str], stocks: list[dict], plate_strength: float = 0.0) -> int:
    score = len(sources) * 15
    score += min(len(stocks) * 5, 30)
    max_lbc = _to_int((stocks[0] or {}).get("lbc") if stocks else 0, 0)
    score += max_lbc * 8
    if plate_strength:
        score += min(plate_strength / 4, 30)
    if any("热门" in str(source or "") for source in sources):
        score += 10
    return min(round(score), 100)


def _calculate_plan_theme_score(sources: list[str], stocks: list[dict], plate_strength: float = 0.0, resonance_score: float = 0.0, zt_evidence: Optional[dict] = None) -> int:
    score = 22.0
    score += min(resonance_score * 0.42, 42)
    score += min(plate_strength / 4, 16)
    score += min(len(stocks) * 4, 16)
    score += min(_to_int((stocks[0] or {}).get("lbc") if stocks else 0, 0) * 6, 18)
    if any("选股宝" in str(source or "") for source in sources):
        score += 6
    if any("热门" in str(source or "") for source in sources):
        score += 5
    if isinstance(zt_evidence, dict):
        score += min(_to_int(zt_evidence.get("relayCount"), 0) * 6, 16)
        score += min(_to_int(zt_evidence.get("watchCount"), 0) * 2, 6)
        score += min(_to_float(zt_evidence.get("maxRelayFactorScore"), 0.0) * 0.08, 8)
        score += min(_to_float(zt_evidence.get("maxEnvironmentScore"), 0.0) * 0.05, 5)
        risk_control = _to_float(zt_evidence.get("maxRiskControlScore"), 0.0)
        score += max(0.0, risk_control - 55) * 0.12
        score -= max(0.0, 45 - risk_control) * 0.2
        break_risk_raw = zt_evidence.get("minBreakRisk")
        if break_risk_raw not in (None, ""):
            score -= max(0.0, _to_float(break_risk_raw, 0.0) - 68) * 0.18
    if not stocks:
        # 纯题材叙事只能作为“跟踪”，不能和已经形成涨停梯队的板块同分竞争。
        evidence_support = _to_int((zt_evidence or {}).get("relayCount"), 0) + _to_int((zt_evidence or {}).get("watchCount"), 0)
        score -= 18.0
        score = min(score, 58.0 if evidence_support > 0 else 48.0)
    elif len(stocks) == 1 and _to_int((stocks[0] or {}).get("lbc"), 0) <= 1:
        # 单个首板/首涨更多是试错信号，先别把势能抬太高。
        score -= 6.0
    return max(0, min(100, round(score)))


def _build_plan_theme_tags(theme: str, stocks: list[dict], sources: list[str], plate_strength: float = 0.0, resonance_score: float = 0.0, zt_evidence: Optional[dict] = None) -> list[dict[str, str]]:
    tags: list[dict[str, str]] = []
    if any("选股宝" in str(source or "") for source in sources):
        tags.append(_plan_chip("实时热点", "stp-chip stp-chip-hot"))
    if any("热门" in str(source or "") for source in sources):
        tags.append(_plan_chip("明日热门", "stp-chip stp-chip-red"))
    top_lbc = _to_int((stocks[0] or {}).get("lbc") if stocks else 0, 0)
    if top_lbc >= 3:
        tags.append(_plan_chip(f"{top_lbc}板龙头", "stp-chip stp-chip-red"))
    elif top_lbc == 2:
        tags.append(_plan_chip("2板承接", "stp-chip stp-chip-amber"))
    if plate_strength >= 70:
        tags.append(_plan_chip("板块强", "stp-chip stp-chip-blue"))
    elif plate_strength >= 45:
        tags.append(_plan_chip("板块活跃", "stp-chip stp-chip-blue"))
    if isinstance(zt_evidence, dict):
        relay_count = _to_int(zt_evidence.get("relayCount"), 0)
        watch_count = _to_int(zt_evidence.get("watchCount"), 0)
        if relay_count:
            tags.append(_plan_chip(f"接力池{relay_count}", "stp-chip stp-chip-red"))
        elif watch_count:
            tags.append(_plan_chip(f"观察池{watch_count}", "stp-chip stp-chip-blue"))
        if _to_float(zt_evidence.get("maxRiskControlScore"), 0.0) < 40 or _to_float(zt_evidence.get("minBreakRisk"), 0.0) >= 70:
            tags.append(_plan_chip("风险偏大", "stp-chip stp-chip-amber"))
    if resonance_score >= 85:
        tags.append(_plan_chip("强共振", "stp-chip stp-chip-red"))
    elif resonance_score >= 70:
        tags.append(_plan_chip("有共振", "stp-chip stp-chip-slate"))
    if len(stocks) >= 4:
        tags.append(_plan_chip(f"{len(stocks)}股联动", "stp-chip stp-chip-slate"))
    return tags[:4]


def _build_plan_evidence_summary(zt_evidence: Optional[dict]) -> str:
    if not isinstance(zt_evidence, dict):
        return ""
    bits: list[str] = []
    relay_count = _to_int(zt_evidence.get("relayCount"), 0)
    watch_count = _to_int(zt_evidence.get("watchCount"), 0)
    if relay_count:
        bits.append(f"接力池{relay_count}")
    if watch_count:
        bits.append(f"观察池{watch_count}")
    sector_trend = _to_float(zt_evidence.get("maxSectorTrendScore"), 0.0)
    if sector_trend > 0:
        bits.append(f"板块势{round(sector_trend)}")
    risk_control = _to_float(zt_evidence.get("maxRiskControlScore"), 0.0)
    if risk_control > 0:
        bits.append(f"风控稳{round(risk_control)}" if risk_control >= 60 else f"风控弱{round(risk_control)}")
    stock_names = [str(name or "").strip() for name in (zt_evidence.get("stockNames") or []) if str(name or "").strip()]
    if stock_names:
        bits.append(f"命中{' / '.join(stock_names[:2])}")
    return " · ".join(bits)


def _plan_tide_display_group(name: object) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    if re.search(r"半导体|芯片|chiplet|igbt|光刻|封装|存储|soc|oled|mled|pcb", text, re.IGNORECASE):
        return "半导体链"
    if re.search(r"电力|风电|风能|核电|特高压|电网|虚拟电厂|水电|绿电|绿色电力", text):
        return "电力链"
    if re.search(r"机器人|减速器|机器视觉|丝杠|伺服", text):
        return "机器人链"
    if re.search(r"光伏|储能|锂电|电池|新能源", text):
        return "新能源链"
    if re.search(r"算力|服务器|数据中心|液冷|cpo|光模块|ai应用|aigc|人工智能", text, re.IGNORECASE):
        return "AI算力链"
    return text


def _plan_is_tide_risk_theme(row: dict) -> bool:
    if str(row.get("tide_phase") or "") == "ebbing":
        return True
    status = str(row.get("status") or "")
    return str(row.get("tide_zone") or "") == "ebbing" or str(row.get("action") or "") in ("avoid", "no_new_position") or status in {
        "avoid_weak",
        "weak",
        "afterglow_risk",
        "shrinking_rebound",
        "rebound_warning",
        "volume_rebound",
    }


def _plan_is_tide_rising_theme(row: dict) -> bool:
    if str(row.get("tide_phase") or "") == "rising":
        return True
    status = str(row.get("status") or "")
    return str(row.get("tide_zone") or "") == "rising" or str(row.get("action") or "") == "confirm" or status in {
        "core_mainline",
        "resonance_traverse",
        "confirmed_mainline",
        "traverse_candidate",
    }


def _plan_is_tide_neutral_theme(row: dict) -> bool:
    if str(row.get("tide_phase") or "") == "neutral":
        return True
    return not _plan_is_tide_rising_theme(row) and not _plan_is_tide_risk_theme(row)


def _plan_tide_theme_score(row: dict) -> float:
    return _to_float(row.get("core_score"), _to_float(row.get("tide_score"), 0.0))


def _plan_tide_ebb_sort_score(row: dict) -> float:
    ebb = row.get("ebb_score")
    if ebb not in (None, ""):
        return _to_float(ebb, 0.0)
    tide = _to_float(row.get("tide_score"), 50.0)
    core = _to_float(row.get("core_score"), 50.0)
    strength = _to_float(row.get("strength_score"), 50.0)
    return max(0.0, min(100.0, (100 - tide) * 0.45 + (100 - strength) * 0.25 + (100 - core) * 0.2))


def _pick_plan_tide_group_phase(bucket: dict[str, object]) -> tuple[str, dict] | None:
    rising = bucket.get("rising") if isinstance(bucket.get("rising"), dict) else None
    neutral = bucket.get("neutral") if isinstance(bucket.get("neutral"), dict) else None
    ebbing = bucket.get("ebbing") if isinstance(bucket.get("ebbing"), dict) else None

    if rising:
        return "rising", rising
    if neutral and ebbing:
        neutral_score = _plan_tide_theme_score(neutral)
        ebb_score = _plan_tide_ebb_sort_score(ebbing)
        # 同一大链条里只要还有中性承接，就不要被单个弱分支轻易打成整体退潮。
        if neutral_score >= 60.0 or neutral_score + 8.0 >= ebb_score:
            return "neutral", neutral
        return "ebbing", ebbing
    if neutral:
        return "neutral", neutral
    if ebbing:
        return "ebbing", ebbing
    return None


def _build_plan_tide_zone_panel(signal: dict) -> dict[str, list[dict]]:
    grouped: dict[str, dict[str, object]] = {}
    for row in signal.get("themes") or []:
        if not isinstance(row, dict):
            continue
        group = _plan_tide_display_group(row.get("name"))
        if not group:
            continue
        bucket = grouped.setdefault(group, {"children": set(), "rising": None, "neutral": None, "ebbing": None})
        children = bucket["children"]
        if isinstance(children, set):
            raw_name = str(row.get("name") or "").strip()
            if raw_name:
                children.add(raw_name)
        if _plan_is_tide_rising_theme(row):
            prev = bucket.get("rising")
            if not isinstance(prev, dict) or _plan_tide_theme_score(row) > _plan_tide_theme_score(prev):
                bucket["rising"] = row
        elif _plan_is_tide_risk_theme(row):
            prev = bucket.get("ebbing")
            if not isinstance(prev, dict) or _plan_tide_ebb_sort_score(row) > _plan_tide_ebb_sort_score(prev):
                bucket["ebbing"] = row
        elif _plan_is_tide_neutral_theme(row):
            prev = bucket.get("neutral")
            if not isinstance(prev, dict) or _plan_tide_theme_score(row) > _plan_tide_theme_score(prev):
                bucket["neutral"] = row

    rising: list[dict] = []
    neutral: list[dict] = []
    ebbing: list[dict] = []
    for group, bucket in grouped.items():
        children = sorted(name for name in (bucket.get("children") or set()) if name and name != group)[:4]
        picked = _pick_plan_tide_group_phase(bucket)
        if not picked:
            continue
        phase, row = picked
        payload = {**row, "name": group, "children": children}
        if phase == "rising":
            rising.append(payload)
        elif phase == "neutral":
            neutral.append(payload)
        else:
            ebbing.append(payload)

    rising.sort(key=_plan_tide_theme_score, reverse=True)
    neutral.sort(key=_plan_tide_theme_score, reverse=True)
    ebbing.sort(key=_plan_tide_ebb_sort_score, reverse=True)
    return {
        "rising": rising[:6],
        "neutral": neutral[:6],
        "ebbing": ebbing[:8],
    }


def _build_plan_tide_risk_panel(md: dict) -> Optional[dict]:
    watchlist = md.get("watchlist") if isinstance(md.get("watchlist"), dict) else {}
    signal = watchlist.get("core_tide_signal") if isinstance(watchlist.get("core_tide_signal"), dict) else {}
    if not signal:
        signal = md.get("coreTideSignal") if isinstance(md.get("coreTideSignal"), dict) else {}
    if not signal:
        signal = watchlist.get("tide_signal") if isinstance(watchlist.get("tide_signal"), dict) else {}
    if not signal:
        signal = md.get("tideSignal") if isinstance(md.get("tideSignal"), dict) else {}
    if not signal:
        return None

    market = signal.get("market") if isinstance(signal.get("market"), dict) else {}
    market_regime = signal.get("marketRegime") if isinstance(signal.get("marketRegime"), dict) else {}
    market_status = str(market_regime.get("status") or ("ebb" if market.get("is_ebb_day") else "")).strip()
    loss_score_raw = market_regime.get("loss_score")
    if loss_score_raw in (None, ""):
        loss_score_raw = ((market.get("loss_effect") or {}) if isinstance(market.get("loss_effect"), dict) else {}).get("score")
    loss_score = _to_float(loss_score_raw, float("nan"))
    triggers = [str(item).strip() for item in (market.get("triggers") or []) if str(item).strip()]
    reasons = [str(item).strip() for item in (market_regime.get("reasons") or []) if str(item).strip()]
    if not reasons:
        reasons = [
            str(item).strip()
            for item in ((((market.get("loss_effect") or {}) if isinstance(market.get("loss_effect"), dict) else {}).get("reasons")) or [])
            if str(item).strip()
        ]
    zones = _build_plan_tide_zone_panel(signal)
    has_risk = market_status in {"ebb", "ice"} or loss_score == loss_score or any(zones[key] for key in ("rising", "neutral", "ebbing"))
    if not has_risk:
        return None
    return {
        "status": "冰点退潮" if market_status == "ice" else "市场退潮" if market_status == "ebb" else "潮汐分层",
        "lossScore": round(loss_score) if loss_score == loss_score else None,
        "triggers": triggers,
        "reasons": reasons,
        "zones": zones,
    }


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

    merge_map, diagnostics = _build_data_driven_theme_merges(md, alias_map)
    if merge_map:
        alias_map = _apply_theme_merge_map(alias_map, merge_map)
    md["theme_merge_meta"] = {
        "mergeMap": dict(sorted(merge_map.items())),
        "diagnostics": diagnostics,
    }
    return {key: sorted(values) for key, values in alias_map.items() if key and values}


_THEME_PAREN_RE = re.compile(r"[（(][^）)]*[）)]")
_THEME_SUFFIX_RE = re.compile(r"(概念|题材|板块|行业)$")


def _theme_merge_base_name(value: object) -> str:
    text = str(value or "").strip().replace(" ", "")
    if not text:
        return ""
    text = _THEME_PAREN_RE.sub("", text)
    text = _THEME_SUFFIX_RE.sub("", text)
    return text.strip()


def _theme_chain_name(name: object) -> str:
    canonical = str(normalize_sector(str(name or "").strip()) or "").strip()
    if not canonical:
        return ""
    for chain, members in CHAIN_MAP.items():
        if canonical == chain or canonical in members:
            return chain
    return canonical


def _theme_name_penalty(name: object) -> tuple[int, int]:
    text = str(name or "").strip()
    base = _theme_merge_base_name(text)
    has_paren = 1 if ("（" in text or "(" in text) else 0
    extra_len = max(0, len(text) - len(base))
    return has_paren, extra_len


def _jaccard_ratio(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    inter = left & right
    union = left | right
    return len(inter) / len(union) if union else 0.0


def _apply_theme_merge_map(alias_map: dict[str, set[str]], merge_map: dict[str, str]) -> dict[str, set[str]]:
    merged = {str(key): set(values) for key, values in alias_map.items() if str(key or "").strip()}
    for raw_alias, raw_canonical in merge_map.items():
        alias = str(raw_alias or "").strip()
        canonical = str(raw_canonical or "").strip()
        if not alias or not canonical or alias == canonical:
            continue
        bucket = merged.setdefault(canonical, set())
        bucket.add(canonical)
        bucket.add(alias)
        source_bucket = merged.pop(alias, set())
        bucket.update(source_bucket)
    return merged


def _build_data_driven_theme_merges(
    md: dict,
    raw_alias_map: Optional[dict[str, set[str] | list[str]]] = None,
) -> tuple[dict[str, str], list[dict[str, object]]]:
    """
    用数据自己归并题材，而不是依赖人工维护映射表。

    只使用高置信度信号：
    - 名称主干一致（去掉括号/概念/题材等噪音后）
    - 成分股交集较高
    - 一方龙头出现在另一方成分股里

    人工 alias 仅作为非常弱的先验，不单独触发合并。
    """

    evidence: dict[str, dict[str, object]] = {}

    def ensure(name: object) -> dict[str, object] | None:
        raw = str(name or "").strip()
        if not raw:
            return None
        row = evidence.get(raw)
        if row is None:
            row = {
                "codes": set(),
                "leader_codes": set(),
                "support_score": 0.0,
                "display_rank": 999,
                "base_name": _theme_merge_base_name(raw),
                "normalize_hint": str(normalize_sector(raw) or "").strip(),
                "chain_name": _theme_chain_name(raw),
                "sources": set(),
            }
            evidence[raw] = row
        return row

    def bump(name: object, *, score: float = 0.0, source: str = "", display_rank: Optional[int] = None) -> None:
        row = ensure(name)
        if not isinstance(row, dict):
            return
        row["support_score"] = float(row.get("support_score") or 0.0) + score
        if source:
            sources = row.get("sources")
            if isinstance(sources, set):
                sources.add(source)
        if display_rank is not None:
            row["display_rank"] = min(int(row.get("display_rank") or 999), int(display_rank))

    def add_code(name: object, code: object, *, leader: bool = False) -> None:
        row = ensure(name)
        if not isinstance(row, dict):
            return
        code_text = str(code or "").strip()
        if not code_text:
            return
        codes = row.get("codes")
        if isinstance(codes, set):
            codes.add(code_text)
        if leader:
            leader_codes = row.get("leader_codes")
            if isinstance(leader_codes, set):
                leader_codes.add(code_text)

    if isinstance(raw_alias_map, dict):
        for key, values in raw_alias_map.items():
            bump(key, score=0.6, source="alias_key")
            if isinstance(values, (list, set, tuple)):
                for value in values:
                    bump(value, score=0.3, source="alias_value")

    for idx, row in enumerate(md.get("plateRankTop10") or []):
        if not isinstance(row, dict):
            continue
        theme_name = row.get("name")
        bump(theme_name, score=3.0, source="plate_rank", display_rank=_to_int(row.get("rank"), idx + 1) or (idx + 1))
        for leader in row.get("leaders") or []:
            if not isinstance(leader, dict):
                continue
            add_code(theme_name, leader.get("code"), leader=True)
        add_code(theme_name, row.get("leadCode"), leader=True)

    for idx, row in enumerate((((md.get("themePanels") or {}) if isinstance(md.get("themePanels"), dict) else {}).get("strengthRows") or [])):
        if not isinstance(row, dict):
            continue
        bump(row.get("name"), score=2.4, source="strength_panel", display_rank=idx + 1)

    for row in md.get("leaders") or []:
        if not isinstance(row, dict):
            continue
        theme_name = row.get("theme")
        bump(theme_name, score=1.8, source="leaders")
        add_code(theme_name, row.get("code"), leader=True)

    ztgc_rows = [row for row in (md.get("ztgc") or []) if isinstance(row, dict)]
    zt_code_themes = md.get("zt_code_themes") if isinstance(md.get("zt_code_themes"), dict) else {}
    for row in ztgc_rows:
        code = str(row.get("dm") or row.get("code") or "").strip()
        if not code:
            continue
        raw_themes = zt_code_themes.get(code) if isinstance(zt_code_themes.get(code), list) else None
        if not raw_themes:
            hy = str(row.get("hy") or "").strip()
            raw_themes = [hy] if hy else []
        for raw_theme in raw_themes or []:
            bump(raw_theme, score=0.35, source="ztgc_theme")
            add_code(raw_theme, code)

    for signal_key in ("tideSignal", "coreTideSignal"):
        signal = md.get(signal_key) if isinstance(md.get(signal_key), dict) else {}
        for row in signal.get("themes") or []:
            if not isinstance(row, dict):
                continue
            bump(row.get("name"), score=1.0, source=signal_key)
            bump(row.get("canonical_name"), score=0.2, source=f"{signal_key}_canonical")

    names = sorted(name for name in evidence.keys() if name)
    if len(names) < 2:
        return {}, []

    parent = {name: name for name in names}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(left: str, right: str) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left == root_right:
            return
        parent[root_right] = root_left

    merged_edges: list[dict[str, object]] = []
    for idx, left in enumerate(names):
        left_row = evidence[left]
        left_codes = left_row.get("codes") if isinstance(left_row.get("codes"), set) else set()
        left_leaders = left_row.get("leader_codes") if isinstance(left_row.get("leader_codes"), set) else set()
        left_base = str(left_row.get("base_name") or "")
        left_hint = str(left_row.get("normalize_hint") or "")
        for right in names[idx + 1 :]:
            right_row = evidence[right]
            right_codes = right_row.get("codes") if isinstance(right_row.get("codes"), set) else set()
            right_leaders = right_row.get("leader_codes") if isinstance(right_row.get("leader_codes"), set) else set()
            right_base = str(right_row.get("base_name") or "")
            right_hint = str(right_row.get("normalize_hint") or "")
            left_chain = str(left_row.get("chain_name") or "")
            right_chain = str(right_row.get("chain_name") or "")

            same_base = bool(left_base and left_base == right_base)
            contains_base = bool(
                not same_base
                and left_base
                and right_base
                and min(len(left_base), len(right_base)) >= 3
                and (left_base in right_base or right_base in left_base)
            )
            same_chain = bool(left_chain and right_chain and left_chain == right_chain and left != right)
            overlap = _jaccard_ratio(left_codes, right_codes)
            leader_cross = bool((left_leaders & (right_codes | right_leaders)) or (right_leaders & (left_codes | left_leaders)))
            same_hint = bool(left_hint and right_hint and left_hint == right_hint and left != right)
            name_affine = same_base or contains_base or same_hint or same_chain

            score = 0.0
            reasons: list[str] = []
            if same_base:
                score += 0.95
                reasons.append("base_match")
            elif contains_base:
                score += 0.35
                reasons.append("base_contains")
            if same_chain:
                score += 0.4
                reasons.append("same_chain")
            if overlap >= 0.5:
                score += 1.0
                reasons.append("stock_overlap_high")
            elif overlap >= 0.34:
                score += 0.8
                reasons.append("stock_overlap_mid")
            elif overlap >= 0.2:
                score += 0.55
                reasons.append("stock_overlap_low")
            if leader_cross:
                score += 0.45
                reasons.append("leader_cross")
            if same_hint:
                score += 0.18
                reasons.append("normalize_hint")

            should_merge = False
            # 不允许只因为“单只股票重合”就合并，必须至少存在名字/链条亲缘。
            if same_base and (leader_cross or overlap >= 0.2):
                should_merge = True
            elif same_chain and overlap >= 0.34:
                should_merge = True
            elif name_affine and score >= 1.25 and (leader_cross or overlap >= 0.2):
                should_merge = True

            if not should_merge:
                continue
            union(left, right)
            merged_edges.append(
                {
                    "left": left,
                    "right": right,
                    "score": round(score, 3),
                    "reasons": reasons,
                    "sharedCodes": sorted((left_codes & right_codes) | (left_leaders & right_codes) | (right_leaders & left_codes))[:6],
                }
            )

    clusters: dict[str, list[str]] = {}
    for name in names:
        clusters.setdefault(find(name), []).append(name)

    merge_map: dict[str, str] = {}
    diagnostics: list[dict[str, object]] = []
    for members in clusters.values():
        if len(members) <= 1:
            continue
        ranked = sorted(
            members,
            key=lambda name: (
                _theme_name_penalty(name)[0],
                _theme_name_penalty(name)[1],
                _to_int(evidence[name].get("display_rank"), 999),
                -_to_float(evidence[name].get("support_score"), 0.0),
                -len(evidence[name].get("codes") if isinstance(evidence[name].get("codes"), set) else set()),
                len(name),
                name,
            ),
        )
        canonical = ranked[0]
        for member in members:
            merge_map[member] = canonical
        related_edges = [
            edge
            for edge in merged_edges
            if str(edge.get("left") or "") in members and str(edge.get("right") or "") in members
        ]
        diagnostics.append(
            {
                "canonical": canonical,
                "members": sorted(members),
                "confidence": round(
                    min(
                        1.0,
                        (
                            max((_to_float(edge.get("score"), 0.0) for edge in related_edges), default=0.0) / 2.5
                            + min(0.15, max(0, len(members) - 1) * 0.05)
                        ),
                    ),
                    3,
                ),
                "reasons": sorted(
                    {
                        str(reason)
                        for edge in related_edges
                        for reason in (edge.get("reasons") or [])
                        if str(reason).strip()
                    }
                ),
                "sharedCodes": sorted(
                    {
                        str(code)
                        for edge in related_edges
                        for code in (edge.get("sharedCodes") or [])
                        if str(code).strip()
                    }
                )[:8],
                "evidence": related_edges[:6],
            }
        )

    return merge_map, diagnostics


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


def _theme_merge_info_by_canonical(md: dict) -> dict[str, dict[str, object]]:
    meta = md.get("theme_merge_meta") if isinstance(md.get("theme_merge_meta"), dict) else {}
    rows = meta.get("diagnostics") if isinstance(meta.get("diagnostics"), list) else []
    out: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        canonical = str(row.get("canonical") or "").strip()
        if canonical:
            out[canonical] = row
    return out


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
        return str(name or "").lstrip("🐲⭐🔥 ").strip()

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


def _build_plan_theme_resolver(md: dict) -> dict:
    alias_lookup, ordered_aliases = _build_theme_alias_lookup(md)
    merge_info_map = _theme_merge_info_by_canonical(md)
    contexts: dict[str, dict] = {}

    def ensure_context(name: object) -> dict | None:
        canonical = _canonicalize_theme_name(name, lookup=alias_lookup, ordered_aliases=ordered_aliases)
        if not canonical:
            return None
        ctx = contexts.get(canonical)
        if ctx is None:
            ctx = {
                "canonicalTheme": canonical,
                "aliases": set([canonical]),
                "matchedLocalThemes": set(),
                "stocks": [],
                "_stockCodes": set(),
                "plateStrength": None,
                "plateLead": "",
                "leader": None,
                "advisor": None,
                "tide": None,
                "ztEvidence": None,
                "mergeInfo": merge_info_map.get(canonical),
                "fallbackThemeCount": 0,
                "fallbackPanel": None,
            }
            contexts[canonical] = ctx
        return ctx

    def merge_contexts(primary: dict, incoming: dict) -> None:
        if not isinstance(primary, dict) or not isinstance(incoming, dict) or primary is incoming:
            return
        for field in ("aliases", "matchedLocalThemes", "_stockCodes"):
            left = primary.get(field)
            right = incoming.get(field)
            if isinstance(left, set) and isinstance(right, set):
                left.update(right)
        if isinstance(primary.get("stocks"), list) and isinstance(incoming.get("stocks"), list):
            existing = {str(row.get("code") or "") for row in primary["stocks"] if isinstance(row, dict)}
            for row in incoming["stocks"]:
                if not isinstance(row, dict):
                    continue
                code = str(row.get("code") or "")
                if code and code in existing:
                    continue
                primary["stocks"].append(row)
                if code:
                    existing.add(code)
        if (primary.get("plateStrength") in (None, "", 0)) and incoming.get("plateStrength") not in (None, "", 0):
            primary["plateStrength"] = incoming.get("plateStrength")
        if not primary.get("plateLead") and incoming.get("plateLead"):
            primary["plateLead"] = incoming.get("plateLead")
        for field in ("leader", "advisor", "tide", "ztEvidence", "mergeInfo", "fallbackPanel"):
            prev = primary.get(field)
            nxt = incoming.get(field)
            prev_score = _to_float((prev or {}).get("score") if isinstance(prev, dict) else (prev or {}).get("core_score") if isinstance(prev, dict) else 0.0, 0.0)
            nxt_score = _to_float((nxt or {}).get("score") if isinstance(nxt, dict) else (nxt or {}).get("core_score") if isinstance(nxt, dict) else 0.0, 0.0)
            if prev is None or (nxt is not None and nxt_score >= prev_score):
                primary[field] = nxt
        if isinstance(primary.get("tideByAlias"), dict) and isinstance(incoming.get("tideByAlias"), dict):
            primary["tideByAlias"].update(incoming["tideByAlias"])
        primary["fallbackThemeCount"] = _to_int(primary.get("fallbackThemeCount"), 0) + _to_int(incoming.get("fallbackThemeCount"), 0)

    def add_alias(ctx: dict | None, *names: object) -> None:
        if not isinstance(ctx, dict):
            return
        for name in names:
            raw = str(name or "").strip()
            if not raw:
                continue
            ctx["aliases"].add(raw)
            normalized = str(normalize_sector(raw) or raw).strip()
            if normalized:
                ctx["aliases"].add(normalized)

    ztgc_rows = [row for row in (md.get("ztgc") or []) if isinstance(row, dict)]
    zt_code_themes = md.get("zt_code_themes") if isinstance(md.get("zt_code_themes"), dict) else {}
    for row in ztgc_rows:
        code = str(row.get("dm") or row.get("code") or "").strip()
        if not code:
            continue
        seen_contexts_for_code: set[str] = set()
        raw_themes = zt_code_themes.get(code) if isinstance(zt_code_themes.get(code), list) else None
        if not raw_themes:
            hy = str(row.get("hy") or "").strip()
            raw_themes = [hy] if hy else []
        stock_payload = {
            "code": code,
            "name": str(row.get("mc") or row.get("name") or code),
            "lbc": _to_int(row.get("lbc"), 0),
            "cjeYi": round(_to_float(row.get("cje"), 0.0) / 1e8, 3),
            "zjYi": round(_to_float(row.get("zj"), 0.0) / 1e8, 3),
            "zbc": _to_int(row.get("zbc"), 0),
        }
        for raw_theme in raw_themes or []:
            ctx = ensure_context(raw_theme)
            if not ctx:
                continue
            add_alias(ctx, raw_theme)
            raw_theme_name = str(raw_theme).strip()
            ctx["matchedLocalThemes"].add(raw_theme_name)
            canonical = str(ctx.get("canonicalTheme") or "").strip()
            if canonical and canonical not in seen_contexts_for_code:
                seen_contexts_for_code.add(canonical)
                ctx["fallbackThemeCount"] = _to_int(ctx.get("fallbackThemeCount"), 0) + 1
            if code not in ctx["_stockCodes"]:
                ctx["_stockCodes"].add(code)
                ctx["stocks"].append(stock_payload)

    theme_panels = md.get("themePanels") if isinstance(md.get("themePanels"), dict) else {}
    for idx, row in enumerate(theme_panels.get("strengthRows") or []):
        if not isinstance(row, dict):
            continue
        ctx = ensure_context(row.get("name"))
        if not ctx:
            continue
        add_alias(ctx, row.get("name"))
        prev_panel = ctx.get("fallbackPanel")
        next_panel = {
            "zt": _to_int(row.get("zt"), 0),
            "zb": _to_int(row.get("zb"), 0),
            "dt": _to_int(row.get("dt"), 0),
            "net": _to_float(row.get("net"), 0.0),
            "risk": _to_float(row.get("risk"), 0.0),
            "order": idx,
        }
        if not isinstance(prev_panel, dict) or _to_int(prev_panel.get("order"), idx) > idx:
            ctx["fallbackPanel"] = next_panel

    for row in (md.get("plateRankTop10") or []):
        if not isinstance(row, dict):
            continue
        ctx = ensure_context(row.get("name"))
        if not ctx:
            continue
        add_alias(ctx, row.get("name"))
        ctx["plateStrength"] = _to_float(row.get("strength"), 0.0)
        ctx["plateLead"] = str(row.get("lead") or "").strip()
        lead_name = str(row.get("lead") or "").strip()
        lead_code = str(row.get("leadCode") or "").strip()
        if lead_name and lead_code:
            prev = ctx.get("leader")
            lead_score = max(_to_float(row.get("strength"), 0.0), 60.0)
            if not isinstance(prev, dict) or lead_score > _to_float(prev.get("score"), 0.0):
                ctx["leader"] = {
                    "name": lead_name,
                    "code": lead_code,
                    "score": lead_score,
                }
        for leader_row in row.get("leaders") or []:
            if not isinstance(leader_row, dict):
                continue
            leader_name = str(leader_row.get("name") or "").strip()
            leader_code = str(leader_row.get("code") or "").strip()
            if not leader_name or not leader_code:
                continue
            prev = ctx.get("leader")
            leader_score = max(_to_float(row.get("strength"), 0.0), 58.0)
            if not isinstance(prev, dict) or leader_score > _to_float(prev.get("score"), 0.0):
                ctx["leader"] = {
                    "name": leader_name,
                    "code": leader_code,
                    "score": leader_score,
                }

    for row in (md.get("plateRotateTop") or []):
        if not isinstance(row, dict):
            continue
        ctx = ensure_context(row.get("name"))
        if not ctx:
            continue
        add_alias(ctx, row.get("name"))
        if not ctx.get("plateLead"):
            ctx["plateLead"] = str(row.get("lead") or "").strip()
        if ctx.get("plateStrength") in (None, "", 0):
            ctx["plateStrength"] = _to_float(row.get("strength"), 0.0)
        lead_name = str(row.get("lead") or "").strip()
        lead_code = str(row.get("leadCode") or "").strip()
        if lead_name and lead_code:
            prev = ctx.get("leader")
            lead_score = max(_to_float(row.get("strength"), 0.0), 60.0)
            if not isinstance(prev, dict) or lead_score > _to_float(prev.get("score"), 0.0):
                ctx["leader"] = {
                    "name": lead_name,
                    "code": lead_code,
                    "score": lead_score,
                }

    for row in (md.get("leaders") or []):
        if not isinstance(row, dict):
            continue
        ctx = ensure_context(row.get("theme"))
        if not ctx:
            continue
        add_alias(ctx, row.get("theme"))
        leader_score = _to_float(row.get("score"), 0.0)
        prev = ctx.get("leader")
        if not isinstance(prev, dict) or leader_score > _to_float(prev.get("score"), 0.0):
            ctx["leader"] = {
                "name": str(row.get("name") or "").replace("🐲", "").strip(),
                "code": str(row.get("code") or "").strip(),
                "score": leader_score,
            }
        canonical_theme = str(ctx.get("canonicalTheme") or "").strip()
        raw_theme = str(row.get("theme") or "").strip()
        if canonical_theme and raw_theme and canonical_theme != raw_theme:
            canonical_ctx = ensure_context(canonical_theme)
            if canonical_ctx:
                add_alias(canonical_ctx, raw_theme, canonical_theme)
                canonical_prev = canonical_ctx.get("leader")
                if not isinstance(canonical_prev, dict) or leader_score > _to_float(canonical_prev.get("score"), 0.0):
                    canonical_ctx["leader"] = {
                        "name": str(row.get("name") or "").replace("🐲", "").strip(),
                        "code": str(row.get("code") or "").strip(),
                        "score": leader_score,
                    }

    watchlist = md.get("watchlist") if isinstance(md.get("watchlist"), dict) else {}
    picks_advisor = md.get("picks_advisor") if isinstance(md.get("picks_advisor"), dict) else {}
    if not picks_advisor:
        picks_advisor = watchlist.get("picks_advisor") if isinstance(watchlist.get("picks_advisor"), dict) else {}
    for row in picks_advisor.get("main_line_picks") or []:
        if not isinstance(row, dict):
            continue
        target_names = [row.get("main_line"), *(row.get("constituents") or [])]
        for raw_name in target_names:
            ctx = ensure_context(raw_name)
            if not ctx:
                continue
            add_alias(ctx, raw_name, row.get("main_line"), *(row.get("constituents") or []))
            prev = ctx.get("advisor")
            prev_conf = _to_float((prev or {}).get("confidence") if isinstance(prev, dict) else 0.0, 0.0)
            next_conf = _to_float(row.get("confidence"), 0.0)
            if not isinstance(prev, dict) or next_conf >= prev_conf:
                ctx["advisor"] = row

    tide_signal = watchlist.get("core_tide_signal") if isinstance(watchlist.get("core_tide_signal"), dict) else {}
    if not tide_signal:
        tide_signal = md.get("coreTideSignal") if isinstance(md.get("coreTideSignal"), dict) else {}
    if not tide_signal:
        tide_signal = watchlist.get("tide_signal") if isinstance(watchlist.get("tide_signal"), dict) else {}
    if not tide_signal:
        tide_signal = md.get("tideSignal") if isinstance(md.get("tideSignal"), dict) else {}
    for row in tide_signal.get("themes") or []:
        if not isinstance(row, dict):
            continue
        ctx = ensure_context(row.get("canonical_name") or row.get("name"))
        if not ctx:
            continue
        add_alias(ctx, row.get("name"), row.get("canonical_name"))
        tide_by_alias = ctx.get("tideByAlias")
        if not isinstance(tide_by_alias, dict):
            tide_by_alias = {}
            ctx["tideByAlias"] = tide_by_alias
        for alias_name in [row.get("name"), row.get("canonical_name")]:
            alias_text = str(alias_name or "").strip()
            if alias_text:
                tide_by_alias[alias_text] = row
        prev = ctx.get("tide")
        prev_score = _to_float((prev or {}).get("core_score") if isinstance(prev, dict) else 0.0, 0.0)
        next_score = _to_float(row.get("core_score"), 0.0)
        if not isinstance(prev, dict) or next_score >= prev_score:
            ctx["tide"] = row

    zt_analysis = md.get("ztAnalysis") if isinstance(md.get("ztAnalysis"), dict) else {}
    evidence_rows = [
        *[{**row, "__placement": "relay"} for row in (zt_analysis.get("relay") or []) if isinstance(row, dict)],
        *[{**row, "__placement": "watch"} for row in (zt_analysis.get("watch") or []) if isinstance(row, dict)],
    ]
    for row in evidence_rows:
        for raw_name in [row.get("predTheme"), row.get("plateName")]:
            ctx = ensure_context(raw_name)
            if not ctx:
                continue
            add_alias(ctx, raw_name)
            evidence = ctx.get("ztEvidence")
            if not isinstance(evidence, dict):
                evidence = {
                    "relayCount": 0,
                    "watchCount": 0,
                    "maxRelayFactorScore": 0.0,
                    "maxRiskControlScore": 0.0,
                    "maxEnvironmentScore": 0.0,
                    "maxSectorTrendScore": 0.0,
                    "minBreakRisk": None,
                    "watchGroups": [],
                    "stockNames": [],
                }
                ctx["ztEvidence"] = evidence
            if row.get("__placement") == "relay":
                evidence["relayCount"] += 1
            if row.get("__placement") == "watch":
                evidence["watchCount"] += 1
            evidence["maxRelayFactorScore"] = max(_to_float(evidence.get("maxRelayFactorScore"), 0.0), _to_float(row.get("relayFactorScore"), 0.0))
            evidence["maxRiskControlScore"] = max(_to_float(evidence.get("maxRiskControlScore"), 0.0), _to_float(row.get("riskControlScore"), 0.0))
            evidence["maxEnvironmentScore"] = max(_to_float(evidence.get("maxEnvironmentScore"), 0.0), _to_float(row.get("environmentScore"), 0.0))
            evidence["maxSectorTrendScore"] = max(_to_float(evidence.get("maxSectorTrendScore"), 0.0), _to_float(row.get("sectorTrendScore"), 0.0))
            break_risk = row.get("breakRisk")
            if break_risk not in (None, ""):
                risk_val = _to_float(break_risk, 0.0)
                evidence["minBreakRisk"] = risk_val if evidence.get("minBreakRisk") is None else min(_to_float(evidence.get("minBreakRisk"), risk_val), risk_val)
            watch_group = str(row.get("watchGroup") or "").strip()
            if watch_group and watch_group not in evidence["watchGroups"]:
                evidence["watchGroups"].append(watch_group)
            stock_name = str(row.get("name") or "").strip()
            if stock_name and stock_name not in evidence["stockNames"]:
                evidence["stockNames"].append(stock_name)

    canonical_groups: dict[str, list[str]] = {}
    for key in list(contexts.keys()):
        normalized_canonical = str(normalize_sector(key) or key).strip()
        canonical_groups.setdefault(normalized_canonical, []).append(key)
    for normalized_canonical, keys in canonical_groups.items():
        if len(keys) <= 1:
            continue
        primary_key = normalized_canonical if normalized_canonical in contexts else keys[0]
        primary_ctx = contexts.get(primary_key)
        if not isinstance(primary_ctx, dict):
            continue
        for key in keys:
            if key == primary_key:
                continue
            incoming_ctx = contexts.get(key)
            if not isinstance(incoming_ctx, dict):
                continue
            merge_contexts(primary_ctx, incoming_ctx)
            contexts.pop(key, None)

    alias_to_theme: dict[str, str] = {}
    serialized_contexts: dict[str, dict] = {}
    for canonical, ctx in contexts.items():
        stocks = sorted(
            list(ctx["stocks"]),
            key=lambda row: (-_to_float(row.get("lbc"), 0.0), -_to_float(row.get("zjYi"), 0.0), -_to_float(row.get("cjeYi"), 0.0)),
        )
        matched_local_themes = sorted(name for name in ctx["matchedLocalThemes"] if name)
        aliases = sorted(name for name in ctx["aliases"] if name)
        fallback_panel = None
        panel = ctx.get("fallbackPanel")
        leader = ctx.get("leader")
        plate_strength = _to_float(ctx.get("plateStrength"), 0.0)
        local_sources: list[str] = []
        if _to_int(ctx.get("fallbackThemeCount"), 0) > 0:
            local_sources.append("本地涨停归集")
        if isinstance(panel, dict):
            local_sources.append("本地板块推测")
        if isinstance(ctx.get("advisor"), dict):
            local_sources.append("推荐线")
        scored_stocks = []
        for stock in stocks:
            stock_with_meta = dict(stock)
            stock_with_meta["score"] = _calculate_plan_stock_score(stock_with_meta, plate_strength, is_realtime_plate=False)
            stock_with_meta["tags"] = _build_plan_stock_tags(stock_with_meta, canonical)
            scored_stocks.append(stock_with_meta)
        scored_stocks.sort(
            key=lambda row: (
                -_to_float(row.get("score"), 0.0),
                -_to_float(row.get("lbc"), 0.0),
                -_to_float(row.get("changePct"), 0.0),
                -_to_float(row.get("zjYi"), 0.0),
                -_to_float(row.get("cjeYi"), 0.0),
            )
        )
        if isinstance(panel, dict):
            zt = _to_int(panel.get("zt"), 0)
            zb = _to_int(panel.get("zb"), 0)
            dt = _to_int(panel.get("dt"), 0)
            net = _to_float(panel.get("net"), 0.0)
            risk = _to_float(panel.get("risk"), 0.0)
            strength_score = max(0, min(100, round(50 + zt * 5 - zb * 4 - dt * 6 + net * 4 - risk * 3)))
            desc_bits = [
                f"{zt}涨停",
                f"{zb}炸板" if zb > 0 else "",
                f"{dt}跌停" if dt > 0 else "",
                f"净强{net:.1f}",
                f"风险{risk:.1f}",
                f"龙头{leader.get('name')}" if isinstance(leader, dict) and str(leader.get("name") or "").strip() else "",
            ]
            is_risky = risk >= 4.5 or zb >= 3 or dt >= 3
            fallback_panel = {
                "zt": zt,
                "zb": zb,
                "dt": dt,
                "net": round(net, 2),
                "risk": round(risk, 2),
                "order": _to_int(panel.get("order"), 0),
                "strengthScore": strength_score,
                "desc": " · ".join(bit for bit in desc_bits if bit),
                "tagText": "高分歧" if is_risky else "本地推测",
                "tagCls": "stp-chip stp-chip-amber" if is_risky else "stp-chip stp-chip-slate",
            }
        zt_evidence = ctx.get("ztEvidence") if isinstance(ctx.get("ztEvidence"), dict) else None
        base_resonance_score = _calculate_plan_resonance_score(local_sources, scored_stocks, plate_strength)
        base_theme_score = _calculate_plan_theme_score(local_sources, scored_stocks, plate_strength, base_resonance_score, zt_evidence)
        base_theme_tags = _build_plan_theme_tags(canonical, scored_stocks, local_sources, plate_strength, base_resonance_score, zt_evidence)
        evidence_summary = _build_plan_evidence_summary(zt_evidence)
        for alias in aliases:
            token = _normalize_theme_token(alias)
            if token and token not in alias_to_theme:
                alias_to_theme[token] = canonical
        serialized_contexts[canonical] = {
            "canonicalTheme": canonical,
            "aliases": aliases,
            "matchedLocalThemes": matched_local_themes,
            "stocks": scored_stocks,
            "plateStrength": ctx.get("plateStrength"),
            "plateLead": ctx.get("plateLead") or "",
            "leader": ctx.get("leader"),
            "advisor": ctx.get("advisor"),
            "tide": ctx.get("tide"),
            "tideByAlias": ctx.get("tideByAlias") if isinstance(ctx.get("tideByAlias"), dict) else {},
            "ztEvidence": zt_evidence,
            "mergeInfo": ctx.get("mergeInfo"),
            "fallbackThemeCount": _to_int(ctx.get("fallbackThemeCount"), 0),
            "fallbackPanel": fallback_panel,
            "baseSources": local_sources,
            "baseResonanceScore": base_resonance_score,
            "baseThemeScore": base_theme_score,
            "baseThemeTags": base_theme_tags,
            "evidenceSummary": evidence_summary,
        }

    fallback_themes = [
        {
            "theme": canonical,
            "themeCount": _to_int(context.get("fallbackThemeCount"), 0),
            "panelStrengthScore": _to_int((((context.get("fallbackPanel") or {}) if isinstance(context.get("fallbackPanel"), dict) else {}).get("strengthScore")), 0),
        }
        for canonical, context in serialized_contexts.items()
        if _to_int(context.get("fallbackThemeCount"), 0) > 0 or isinstance(context.get("fallbackPanel"), dict)
    ]
    fallback_themes.sort(
        key=lambda item: (
            -_to_int(item.get("themeCount"), 0),
            -_to_int(item.get("panelStrengthScore"), 0),
            -_to_float(((serialized_contexts.get(str(item.get("theme") or "")) or {}).get("plateStrength")), 0.0),
            -len((((serialized_contexts.get(str(item.get("theme") or "")) or {}).get("stocks")) or [])),
            str(item.get("theme") or ""),
        )
    )

    return {
        "aliasToTheme": alias_to_theme,
        "contexts": serialized_contexts,
        "themeMergeMeta": md.get("theme_merge_meta") if isinstance(md.get("theme_merge_meta"), dict) else {},
        "fallbackThemes": fallback_themes[:8],
        "tideRiskPanel": _build_plan_tide_risk_panel(md),
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
    md["planThemeResolver"] = _build_plan_theme_resolver(md)
    md["ladderDecision"] = _build_ladder_decision(md)
    md["sentimentDecision"] = _build_sentiment_decision(md)
    md["planDecision"] = _build_plan_decision(md)
    md["shortlineDecision"] = _build_shortline_decision(md)
    preserved_market = ((md.get("preservedResearch") or {}) if isinstance(md.get("preservedResearch"), dict) else {}).get("marketData")
    if isinstance(preserved_market, dict):
        preserved_market["planThemeResolver"] = _build_plan_theme_resolver(preserved_market)
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
