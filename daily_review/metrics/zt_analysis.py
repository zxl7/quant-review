#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""明日计划：涨停个股接力/观察池算法。

只做纯计算，不请求网络。输出给 ``marketData.ztAnalysis``，前端只负责展示。
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Tuple


def _to_num(v: Any, d: float = 0.0) -> float:
    try:
        if v is None:
            return float(d)
        if isinstance(v, str):
            v = v.replace("%", "").replace("板", "").strip()
        n = float(v)
        return n if math.isfinite(n) else float(d)
    except Exception:
        return float(d)


def _round(v: float) -> int:
    return int(math.floor(float(v) + 0.5))


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(v)))


def _norm(x: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 50.0
    return _clamp(((x - lo) / (hi - lo)) * 100.0)


def _inv_norm(x: float, lo: float, hi: float) -> float:
    return 100.0 - _norm(x, lo, hi)


def _norm_code6(v: Any) -> str:
    digits = re.sub(r"\D", "", str(v or ""))
    return digits[-6:] if len(digits) >= 6 else digits


def _theme_keys_for_code(code: Any) -> List[str]:
    c6 = _norm_code6(code)
    no_zero = c6.lstrip("0")
    return list(dict.fromkeys([x for x in (c6, no_zero) if x]))


def _code_theme_list(code_themes: Dict[str, Any], code: Any) -> List[str]:
    for k in _theme_keys_for_code(code):
        v = code_themes.get(k)
        if isinstance(v, list):
            return [str(x) for x in v if str(x or "").strip()]
    return []


def _extract_kw(s: Any) -> set[str]:
    text = str(s or "")
    out: set[str] = set()
    for i in range(max(0, len(text) - 1)):
        if re.search(r"[\s()（）]", text[i]):
            continue
        out.add(text[i : i + 2])
    return out


def _fuzzy_match(a: Any, b: Any) -> bool:
    left, right = str(a or ""), str(b or "")
    if not left or not right:
        return False
    if left == right or left in right or right in left:
        return True
    ak, bk = _extract_kw(left), _extract_kw(right)
    return sum(1 for k in ak if k in bk) >= 2


def _tag(text: str, cls: str = "") -> Dict[str, str]:
    return {"text": text, "cls": cls}


def _tag_cls_rank(cls: Any) -> int:
    text = str(cls or "")
    if "ladder-chip-strong" in text or "red-text" in text:
        return 3
    if "ladder-chip-warn" in text or "orange-text" in text:
        return 2
    if "ladder-chip-cool" in text or "blue-text" in text:
        return 1
    return 0


def _dedupe_tags(tags: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen: Dict[str, int] = {}
    out: List[Dict[str, str]] = []
    for tag in tags:
        if not isinstance(tag, dict):
            continue
        text = str(tag.get("text") or "").strip()
        if not text:
            continue
        item = {"text": text, "cls": str(tag.get("cls") or "")}
        if text not in seen:
            seen[text] = len(out)
            out.append(item)
            continue
        idx = seen[text]
        if _tag_cls_rank(item.get("cls")) > _tag_cls_rank(out[idx].get("cls")):
            out[idx] = item
    return out


def _next_step_rank(text: str) -> int:
    m = re.fullmatch(r"(\d+)进(\d+)", text)
    if not m:
        return 99
    return -int(m.group(1))


def _board_rank(text: str) -> int:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)板", text)
    if not m:
        return 99
    return -int(float(m.group(1)))


def _tag_order_key(tag: Dict[str, str], idx: int) -> Tuple[int, int, int]:
    text = str(tag.get("text") or "").strip()
    if re.fullmatch(r"\d+(?:\.\d+)?板", text):
        return (1, _board_rank(text), idx)
    if re.fullmatch(r"\d+进\d+", text):
        return (0, _next_step_rank(text), idx)
    if text in {"主线", "极强主线", "强主线", "中等主线"}:
        return (2, {"主线": 0, "极强主线": 1, "强主线": 2, "中等主线": 3}.get(text, 9), idx)
    if text in {"前龙头", "核心梯队", "有梯队"}:
        return (3, {"前龙头": 0, "核心梯队": 1, "有梯队": 2}.get(text, 9), idx)
    if text.startswith("带动"):
        return (3, 3, idx)
    if text.startswith("跟风"):
        return (3, 4, idx)
    if text in {"断板风险高", "高度压制", "晋级生态弱", "题材转弱", "分歧烂板", "反复回封", "一字板", "缩量封板", "无梯队", "题材待确认"}:
        return (4, 0, idx)
    if re.fullmatch(r"\d+(?:\.\d+)?次开板", text):
        return (4, 1, idx)
    if text in {"封单充足", "加速确认", "温和放量", "高换手承接", "常规封板", "未开"}:
        return (5, {"封单充足": 0, "加速确认": 1, "温和放量": 2, "高换手承接": 3, "常规封板": 4, "未开": 5}.get(text, 9), idx)
    if text.startswith("首封"):
        return (5, 6, idx)
    if text in {"晋级生态强", "高度修复", "题材持续", "突破新高", "量价共振", "放量+板块", "题材发散", "属性标签", "无跟风"}:
        return (6, 0, idx)
    if re.fullmatch(r"封单(?:-|\d+(?:\.\d+)?)亿", text):
        return (7, 0, idx)
    if re.fullmatch(r"\d+(?:\.\d+)?%换手", text):
        return (7, 1, idx)
    if text.startswith("成交额"):
        return (7, 2, idx)
    if text.startswith("市值"):
        return (7, 3, idx)
    return (90, 0, idx)


def _tag_tone_class(tag: Dict[str, str]) -> str:
    text = str(tag.get("text") or "").strip()
    if re.fullmatch(r"\d+进\d+", text):
        m = re.fullmatch(r"(\d+)进(\d+)", text)
        if not m:
            return "ladder-chip-cool blue-text"
        step_from = int(m.group(1))
        if step_from >= 4:
            return "ladder-chip-warn orange-text"
        return "ladder-chip-strong red-text" if step_from >= 2 else "ladder-chip-cool blue-text"
    if re.fullmatch(r"\d+(?:\.\d+)?板", text):
        board = _to_num(text, 0)
        return "ladder-chip-warn orange-text" if board >= 5 else "ladder-chip-cool blue-text"
    if text in {"主线", "极强主线", "强主线", "前龙头", "核心梯队", "带动", "封单充足", "加速确认", "晋级生态强", "高度修复", "突破新高"} or text.startswith("带动"):
        return "ladder-chip-strong red-text"
    if text in {"断板风险高", "高度压制", "晋级生态弱", "题材转弱", "高换手承接", "分歧烂板", "反复回封", "一字板", "缩量封板", "无梯队", "题材待确认"} or text.startswith("跟风"):
        return "ladder-chip-warn orange-text"
    if re.fullmatch(r"\d+(?:\.\d+)?次开板", text):
        return "ladder-chip-warn orange-text"
    return "ladder-chip-cool blue-text"


def _compact_tags(tags: List[Dict[str, str]]) -> List[Dict[str, str]]:
    mainline_priority = {"极强主线": 4, "强主线": 3, "主线": 2, "中等主线": 1}
    strongest_mainline = ""
    has_specific_tier = False
    for tag in tags:
        text = str(tag.get("text") or "").strip()
        if mainline_priority.get(text, 0) > mainline_priority.get(strongest_mainline, 0):
            strongest_mainline = text
        if text in {"前龙头", "核心梯队"} or text.startswith("带动") or text.startswith("跟风"):
            has_specific_tier = True
    out: List[Dict[str, str]] = []
    mainline_added = False
    for tag in tags:
        text = str(tag.get("text") or "").strip()
        if text in mainline_priority:
            if text == strongest_mainline and not mainline_added:
                out.append(tag)
                mainline_added = True
            continue
        if text == "有梯队" and has_specific_tier:
            continue
        if text == "题材持续" and strongest_mainline in {"极强主线", "强主线"}:
            continue
        out.append(tag)
    return out


def _normalize_tags(tags: List[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped = _compact_tags(_dedupe_tags(tags))
    styled = [{**tag, "cls": _tag_tone_class(tag)} for tag in deduped]
    return [tag for _, tag in sorted(enumerate(styled), key=lambda item: _tag_order_key(item[1], item[0]))]


def _tag_tone(tag: Dict[str, str]) -> str:
    cls = str(tag.get("cls") or "")
    if "red-text" in cls:
        return "red"
    if "orange-text" in cls:
        return "orange"
    return "blue"


def _tag_rows(tags: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    rows = [
        {"tone": "red", "tags": []},
        {"tone": "orange", "tags": []},
        {"tone": "blue", "tags": []},
    ]
    row_by_tone = {str(row["tone"]): row for row in rows}
    for tag in tags:
        row_by_tone[_tag_tone(tag)]["tags"].append(tag)
    return rows


def _fmt_hhmm(fbt: Any) -> str:
    s = str(fbt or "").strip()
    if not s:
        return ""
    if ":" in s:
        return s[:5]
    if len(s) >= 4:
        return f"{s[:2]}:{s[2:4]}"
    return s


def _minutes(hhmm: Any) -> int:
    s = str(hhmm or "")
    if ":" not in s:
        return 0
    try:
        hh, mm = [int(float(x)) for x in s.split(":", 1)]
        return hh * 60 + mm
    except Exception:
        return 0


BROAD_THEME_PATTERNS = [
    re.compile(x, re.I)
    for x in (
        "低价",
        "破净",
        "基金重仓",
        "养老金",
        "融资融券",
        "沪股通",
        "深股通",
        "QFII",
        "小盘|中盘|大盘",
        "年度强势",
        "增持|回购",
        "参股",
        "退市警示",
    )
]


def _is_broad_theme(name: Any) -> bool:
    text = str(name or "")
    return any(p.search(text) for p in BROAD_THEME_PATTERNS)


def _pct(x: float) -> str:
    return f"{'+' if x >= 0 else ''}{int(x)}%"


def _gap_label(lo: float, hi: float) -> str:
    if hi <= 0:
        return "低开"
    if lo >= 0:
        return "高开"
    return "平开"


def _yi(v: Any) -> float:
    return _to_num(v, 0.0) / 1e8


def _safe_min_max(values: Iterable[float], default: Tuple[float, float] = (0.0, 0.0)) -> Tuple[float, float]:
    arr = [float(x) for x in values if math.isfinite(float(x))]
    return (min(arr), max(arr)) if arr else default


def _num_list(values: Any) -> List[float]:
    if not isinstance(values, list):
        return []
    out: List[float] = []
    for x in values:
        n = _to_num(x, math.nan)
        if math.isfinite(n):
            out.append(n)
    return out


def _avg(values: Iterable[float], default: float = 0.0) -> float:
    arr = [float(x) for x in values if math.isfinite(float(x))]
    return sum(arr) / len(arr) if arr else float(default)


def _recent_delta(values: List[float], window: int = 3) -> float:
    if len(values) < 2:
        return 0.0
    seg = values[-window:] if len(values) >= window else values
    return seg[-1] - seg[0] if len(seg) >= 2 else 0.0


def build_zt_analysis(*, market_data: Dict[str, Any]) -> Dict[str, Any]:
    """生成明日计划里的涨停接力/观察池。

    输出结构保持与前端现有渲染兼容：
    ``{"meta": {...}, "relay": [...], "watch": [...]}``
    """

    zt = market_data.get("ztgc") if isinstance(market_data.get("ztgc"), list) else []
    if not zt:
        return {"meta": {"tierThemeCount": 0, "tierThemeTop": "", "source": "python"}, "relay": [], "watch": []}

    features = market_data.get("features") if isinstance(market_data.get("features"), dict) else {}
    mi = features.get("mood_inputs") if isinstance(features.get("mood_inputs"), dict) else {}
    prev = market_data.get("prev") if isinstance(market_data.get("prev"), dict) else {}
    prev_features = prev.get("features") if isinstance(prev.get("features"), dict) else {}
    prev_mi = prev_features.get("mood_inputs") if isinstance(prev_features.get("mood_inputs"), dict) else {}
    mood_stage = market_data.get("moodStage") if isinstance(market_data.get("moodStage"), dict) else {}
    stage_type = str(mood_stage.get("type") or "warn")
    code_themes = market_data.get("zt_code_themes") if isinstance(market_data.get("zt_code_themes"), dict) else {}
    theme_panels = market_data.get("themePanels") if isinstance(market_data.get("themePanels"), dict) else {}
    theme_trend = market_data.get("themeTrend") if isinstance(market_data.get("themeTrend"), dict) else {}
    height_trend = market_data.get("heightTrend") if isinstance(market_data.get("heightTrend"), dict) else {}
    main_theme = ""
    if isinstance(theme_panels.get("ztTop"), list) and theme_panels["ztTop"]:
        first = theme_panels["ztTop"][0]
        if isinstance(first, dict):
            main_theme = str(first.get("name") or "")
    leader_max_b = _to_num(mi.get("max_lb"), 0.0)
    prev_max_b = _to_num(prev_mi.get("max_lb"), 0.0)
    rate_2to3 = _to_num(mi.get("rate_2to3"), 0.0)
    rate_3to4 = _to_num(mi.get("rate_3to4"), 0.0)
    jj_rate = _to_num(mi.get("jj_rate_adj", mi.get("jj_rate")), 0.0)
    broken_lb_rate = _to_num(mi.get("broken_lb_rate_adj", mi.get("broken_lb_rate")), 0.0)
    trend_jj_rate = _to_num(mi.get("trend_jj_rate"), jj_rate - _to_num(prev_mi.get("jj_rate_adj", prev_mi.get("jj_rate")), jj_rate))
    trend_broken_lb_rate = _to_num(mi.get("trend_broken_lb_rate"), broken_lb_rate - _to_num(prev_mi.get("broken_lb_rate_adj", prev_mi.get("broken_lb_rate")), broken_lb_rate))
    trend_max_lb = _to_num(mi.get("trend_max_lb"), leader_max_b - prev_max_b if prev_max_b else 0.0)
    hist_max_lb = _num_list(mi.get("hist_max_lb"))
    hist_jj_rate = _num_list(mi.get("hist_jj_rate"))
    hist_broken_lb_rate = _num_list(mi.get("hist_broken_lb_rate"))
    hist_lianban = _num_list(mi.get("hist_lianban"))
    height_main = _num_list(height_trend.get("main"))
    height_sub = _num_list(height_trend.get("sub"))
    if height_main:
        hist_max_lb = height_main
    height_avg = _avg(hist_max_lb[-5:], leader_max_b or 0.0)
    height_delta = _recent_delta(hist_max_lb, 3) if hist_max_lb else trend_max_lb
    sub_height_delta = _recent_delta(height_sub, 3) if height_sub else 0.0
    jj_recent_avg = _avg(hist_jj_rate[-5:], jj_rate)
    broken_recent_avg = _avg(hist_broken_lb_rate[-5:], broken_lb_rate)
    lianban_delta = _recent_delta(hist_lianban, 3) if hist_lianban else 0.0
    promo_ecology = _clamp(jj_rate * 1.55 + rate_2to3 * 0.36 + rate_3to4 * 0.28 + trend_jj_rate * 0.62 + lianban_delta * 1.1 - max(0.0, broken_lb_rate - 58.0) * 0.52)
    break_risk_base = _clamp(broken_lb_rate * 0.9 + max(0.0, trend_broken_lb_rate) * 1.25 + max(0.0, 30.0 - jj_rate) * 0.42)
    height_repair = trend_max_lb > 0 or height_delta > 0.5 or (leader_max_b >= height_avg and trend_jj_rate > 0)
    height_pressure = (trend_max_lb < 0 and leader_max_b <= height_avg) or (height_delta < -0.5 and trend_broken_lb_rate > 0) or (leader_max_b <= 4 and broken_lb_rate >= 70)
    height_context_score = _clamp(50 + trend_max_lb * 11 + height_delta * 8 + sub_height_delta * 4 + (jj_rate - jj_recent_avg) * 0.45 - (broken_lb_rate - broken_recent_avg) * 0.36)

    strength_rows = theme_panels.get("strengthRows") if isinstance(theme_panels.get("strengthRows"), list) else []
    theme_strength = {str(r.get("name")): r for r in strength_rows if isinstance(r, dict) and str(r.get("name") or "")}
    strength_names = list(theme_strength.keys())
    trend_rows = theme_trend.get("series") if isinstance(theme_trend.get("series"), list) else []
    trend_series: Dict[str, List[float]] = {
        str(r.get("name")): _num_list(r.get("values"))
        for r in trend_rows
        if isinstance(r, dict) and str(r.get("name") or "") and _num_list(r.get("values"))
    }
    trend_names = list(trend_series.keys())

    def match_strength(theme_name: Any) -> Dict[str, Any] | None:
        t = str(theme_name or "")
        if t in theme_strength:
            return theme_strength[t]
        for sn in strength_names:
            if _fuzzy_match(t, sn):
                return theme_strength.get(sn)
        return None

    def matched_strength_name_of(theme_name: Any) -> str:
        t = str(theme_name or "")
        if not t:
            return ""
        if t in theme_strength:
            return t
        for sn in strength_names:
            if _fuzzy_match(t, sn):
                return sn
        return ""

    def canonical_theme_name(name: Any) -> str:
        return matched_strength_name_of(name) or str(name or "")

    def matched_trend_name_of(theme_name: Any) -> str:
        t = str(theme_name or "")
        if not t:
            return ""
        if t in trend_series:
            return t
        for sn in trend_names:
            if _fuzzy_match(t, sn):
                return sn
        return ""

    def theme_persistence(theme_name: Any, sr: Dict[str, Any] | None = None) -> Dict[str, Any]:
        name = canonical_theme_name(theme_name)
        trend_name = matched_trend_name_of(name)
        values = trend_series.get(trend_name, []) if trend_name else []
        src = "panel"
        delta = 0.0
        if values:
            now = values[-1]
            prev_avg = _avg(values[-4:-1], values[-2] if len(values) >= 2 else now)
            delta = now - prev_avg
            score = _clamp(48 + delta * 2.0 + _recent_delta(values, 3) * 1.25 + now * 0.32)
            src = "trend"
        else:
            row = sr if isinstance(sr, dict) and sr else match_strength(name) or {}
            net = _to_num(row.get("net"), 0.0)
            risk = _to_num(row.get("risk"), 0.0)
            zt_cnt = _to_num(row.get("zt"), 0.0)
            zb_cnt = _to_num(row.get("zb"), 0.0)
            dt_cnt = _to_num(row.get("dt"), 0.0)
            delta = net - risk
            score = _clamp(42 + net * 2.15 + min(zt_cnt, 24.0) * 0.65 - risk * 1.8 - zb_cnt * 0.85 - dt_cnt * 3.0)
        if _is_broad_theme(name):
            score = _clamp(score - 18.0)
        state = "up" if score >= 66 and delta >= 0 else "fade" if score <= 42 or delta <= -4 else "flat"
        return {"score": score, "delta": delta, "state": state, "source": src}

    def theme_pick_score(entry: Dict[str, Any]) -> float:
        name = canonical_theme_name(entry.get("name") or entry.get("themeName"))
        sr = entry.get("sr") if isinstance(entry.get("sr"), dict) else {}
        net = _to_num(entry.get("net", sr.get("net")), 0.0)
        risk = _to_num(entry.get("risk", sr.get("risk")), 0.0)
        zt_cnt = _to_num(entry.get("zt", sr.get("zt")), 0.0)
        persist = theme_persistence(name, sr)
        return net - risk * 0.35 + min(zt_cnt, 12.0) * 0.2 + (_to_num(persist.get("score"), 50.0) - 50.0) * 0.08 - (8.0 if _is_broad_theme(name) else 0.0)

    def split_theme_entries(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        ordered = sorted(list(items or []), key=lambda x: (theme_pick_score(x), _to_num(x.get("net"), 0.0)), reverse=True)
        tradeable = [r for r in ordered if not _is_broad_theme(r.get("name"))]
        broad = [r for r in ordered if _is_broad_theme(r.get("name"))]
        return {"tradeable": tradeable, "broad": broad, "ordered": [*tradeable, *broad] if tradeable else ordered}

    tier_themes_raw = sorted(
        [r for r in strength_rows if isinstance(r, dict) and _to_num(r.get("zt"), 0.0) >= 3],
        key=lambda r: _to_num(r.get("zt"), 0.0),
        reverse=True,
    )
    tier_themes = split_theme_entries(tier_themes_raw)["tradeable"]
    tier_theme_top = " / ".join(f"{r.get('name')}{int(_to_num(r.get('zt'), 0))}只" for r in tier_themes[:3])
    tier_theme_set = {str(r.get("name")) for r in tier_themes}

    theme_reverse: Dict[str, List[Dict[str, Any]]] = {}

    def add_reverse(key: str, entry: Dict[str, Any]) -> None:
        arr = theme_reverse.setdefault(key, [])
        if not any(x.get("themeName") == entry.get("themeName") for x in arr):
            arr.append(entry)

    plate_rows = market_data.get("plateRotateTop") if isinstance(market_data.get("plateRotateTop"), list) else []
    for pr in plate_rows:
        if not isinstance(pr, dict):
            continue
        pr_name = str(pr.get("name") or "")
        if not pr_name:
            continue
        entry = {"themeName": pr_name, "sr": theme_strength.get(pr_name)}
        leaders = pr.get("leaders") if isinstance(pr.get("leaders"), list) else []
        for ld in leaders:
            if not isinstance(ld, dict):
                continue
            ld_code = _norm_code6(ld.get("code"))
            ld_name = str(ld.get("name") or "")
            if ld_code:
                for ck in _theme_keys_for_code(ld_code):
                    add_reverse("c_" + ck, entry)
            if ld_name:
                add_reverse("n_" + ld_name, entry)

    for key in ("ztTop", "zbTop", "dtTop"):
        items = theme_panels.get(key) if isinstance(theme_panels.get(key), list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            t_name = str(item.get("name") or "")
            ex_str = str(item.get("examples") or "")
            if not t_name or not ex_str:
                continue
            for n in [x for x in re.split(r"[·\.\s,，、]+", ex_str) if x]:
                add_reverse("n_" + n, {"themeName": t_name, "sr": theme_strength.get(t_name)})

    def lookup_theme_by_plate(code: Any, name: Any) -> List[Dict[str, Any]]:
        seen: set[str] = set()
        results: List[Dict[str, Any]] = []

        def push(arr: List[Dict[str, Any]]) -> None:
            for e in arr:
                tn = str(e.get("themeName") or "")
                if tn and tn not in seen:
                    seen.add(tn)
                    results.append(e)

        for ck in _theme_keys_for_code(code):
            push(theme_reverse.get("c_" + ck, []))
        if name:
            push(theme_reverse.get("n_" + str(name), []))
        for t in _code_theme_list(code_themes, code):
            sr = match_strength(t)
            canon = canonical_theme_name(t)
            if sr and canon and canon not in seen:
                seen.add(canon)
                results.append({"themeName": canon, "sr": sr})
        return results

    def get_theme_entries(code: Any, name: Any) -> List[Dict[str, Any]]:
        seen: set[str] = set()
        out: List[Dict[str, Any]] = []
        for e in lookup_theme_by_plate(code, name):
            sr = e.get("sr") if isinstance(e.get("sr"), dict) else {}
            canon = canonical_theme_name(e.get("themeName"))
            row = {
                "name": canon or str(e.get("themeName") or ""),
                "net": _to_num(sr.get("net"), 0.0),
                "risk": _to_num(sr.get("risk"), 0.0),
                "zt": _to_num(sr.get("zt"), 0.0),
                "zb": _to_num(sr.get("zb"), 0.0),
                "dt": _to_num(sr.get("dt"), 0.0),
            }
            if row["name"] and row["name"] not in seen:
                seen.add(row["name"])
                out.append(row)
        return sorted(out, key=lambda x: (theme_pick_score(x), _to_num(x.get("net"), 0.0)), reverse=True)

    theme_lb_names: Dict[str, List[str]] = {}
    for s in zt:
        if not isinstance(s, dict):
            continue
        code = str(s.get("dm") or s.get("code") or "")
        name = str(s.get("mc") or s.get("name") or "")
        lbc = _to_num(s.get("lbc"), 1.0)
        if not name or lbc < 2:
            continue
        c_ths = [canonical_theme_name(t) for t in _code_theme_list(code_themes, code)]
        p_ths = [e["name"] for e in get_theme_entries(code, name)]
        for tn in list(dict.fromkeys([x for x in [*c_ths, *p_ths] if x])):
            arr = theme_lb_names.setdefault(tn, [])
            if name not in arr:
                arr.append(name)

    theme_leader: Dict[str, Dict[str, Any]] = {}
    for s in zt:
        if not isinstance(s, dict):
            continue
        code = str(s.get("dm") or s.get("code") or "")
        name = str(s.get("mc") or s.get("name") or "")
        lbc = _to_num(s.get("lbc"), 1.0)
        if not name or not code or lbc < 2:
            continue
        fund_yi = _yi(s.get("zj"))
        t = _minutes(_fmt_hhmm(s.get("fbt")))
        c_ths = [canonical_theme_name(tn) for tn in _code_theme_list(code_themes, code)]
        p_ths = [e["name"] for e in get_theme_entries(code, name)]
        for tn in list(dict.fromkeys([x for x in [*c_ths, *p_ths] if x])):
            cur = theme_leader.get(tn)
            if not cur:
                theme_leader[tn] = {"name": name, "lbc": lbc, "fundYi": fund_yi, "t": t}
                continue
            better = (
                lbc > _to_num(cur.get("lbc"), 0)
                or (lbc == _to_num(cur.get("lbc"), 0) and fund_yi > _to_num(cur.get("fundYi"), 0))
                or (
                    lbc == _to_num(cur.get("lbc"), 0)
                    and fund_yi == _to_num(cur.get("fundYi"), 0)
                    and t > 0
                    and (_to_num(cur.get("t"), 0) <= 0 or t < _to_num(cur.get("t"), 0))
                )
            )
            if better:
                theme_leader[tn] = {"name": name, "lbc": lbc, "fundYi": fund_yi, "t": t}

    hy_cnt: Dict[str, int] = {}
    for s in zt:
        if isinstance(s, dict):
            hy = str(s.get("hy") or "其他")
            hy_cnt[hy] = hy_cnt.get(hy, 0) + 1
    max_hy = max(hy_cnt.values()) if hy_cnt else 0

    fund_lo, fund_hi = _safe_min_max((_yi(s.get("zj")) for s in zt if isinstance(s, dict) and _yi(s.get("zj")) > 0), (0.0, 0.0))
    open_lo, open_hi = _safe_min_max((_to_num(s.get("zbc"), 0.0) for s in zt if isinstance(s, dict)), (0.0, 0.0))
    time_lo, time_hi = _safe_min_max(
        (_minutes(_fmt_hhmm(s.get("fbt"))) for s in zt if isinstance(s, dict) and _minutes(_fmt_hhmm(s.get("fbt"))) > 0),
        (0.0, 0.0),
    )

    volume = market_data.get("volume") if isinstance(market_data.get("volume"), dict) else {}
    fear = market_data.get("fear") if isinstance(market_data.get("fear"), dict) else {}
    vol_chg = _to_num(volume.get("change"), 0.0)
    zb_rate = _to_num(mi.get("zb_rate"), _to_num(fear.get("broken"), 0.0))
    env_boost = _clamp(50 + vol_chg * 2 - (zb_rate - 20) * 0.6)
    max_lbc = max((_to_num(s.get("lbc"), 1.0) for s in zt if isinstance(s, dict)), default=1.0)

    ladder = market_data.get("ladder") if isinstance(market_data.get("ladder"), list) else []
    ladder_map: Dict[str, Dict[str, Any]] = {}
    for r in ladder:
        if not isinstance(r, dict):
            continue
        for k in (r.get("code"), r.get("dm"), r.get("name")):
            if k:
                ladder_map[str(k)] = r

    scored: List[Dict[str, Any]] = []
    for s in zt:
        if not isinstance(s, dict):
            continue
        name = str(s.get("mc") or s.get("name") or "")
        code = str(s.get("dm") or s.get("code") or "")
        lbc = _to_num(s.get("lbc"), 1.0)
        hy = str(s.get("hy") or "其他")
        fund_yi = _yi(s.get("zj"))
        open_cnt = _to_num(s.get("zbc"), 0.0)
        t = _minutes(_fmt_hhmm(s.get("fbt")))

        fund_score = _norm(fund_yi, fund_lo, fund_hi)
        open_score = _inv_norm(open_cnt, open_lo, open_hi)
        time_score = _inv_norm(t, time_lo, time_hi) if t else 50.0
        hy_score = _clamp((hy_cnt.get(hy, 0) / max_hy) * 100.0) if max_hy else 0.0

        cje_yi_raw = _yi(s.get("cje"))
        hs_raw = _to_num(s.get("hs"), 0.0)
        fbt_raw = str(s.get("fbt") or "")
        is_yizi = hs_raw < 2 and cje_yi_raw < 3 and open_cnt == 0 and (fbt_raw.startswith("0925") or fbt_raw.startswith("09:25"))
        is_shrink_seal = (not is_yizi) and hs_raw < 3 and cje_yi_raw < 5 and open_cnt == 0
        yizi_penalty = 22.0 if is_yizi else 12.0 if is_shrink_seal else 0.0

        ladder_row = ladder_map.get(code) or ladder_map.get(name) or {}
        quality_label = str(ladder_row.get("qualityLabel") or "")
        quality_note = str(ladder_row.get("note") or "")
        quality_score = (
            _to_num(ladder_row.get("qualityScore"), 0.0)
            if ladder_row.get("qualityScore") is not None
            else _clamp(fund_score * 0.3 + open_score * 0.42 + time_score * 0.28)
        )

        plate_themes = get_theme_entries(code, name)
        if plate_themes:
            all_theme_matches = plate_themes
        else:
            all_theme_matches = []
            for theme in _code_theme_list(code_themes, code):
                row = match_strength(theme)
                if not row:
                    continue
                item = {
                    "name": canonical_theme_name(theme),
                    "net": _to_num(row.get("net"), 0.0),
                    "risk": _to_num(row.get("risk"), 0.0),
                    "zt": _to_num(row.get("zt"), 0.0),
                }
                if item["name"] and not any(x.get("name") == item["name"] for x in all_theme_matches):
                    all_theme_matches.append(item)
            all_theme_matches = sorted(all_theme_matches, key=lambda x: (theme_pick_score(x), _to_num(x.get("net"), 0.0)), reverse=True)

        theme_groups = split_theme_entries(all_theme_matches)
        top_themes = theme_groups["ordered"][:2]
        action_theme = theme_groups["tradeable"][0] if theme_groups["tradeable"] else None
        has_trade_theme = bool(action_theme)
        is_broad_only = (not has_trade_theme) and any(_is_broad_theme(t.get("name")) for t in top_themes)
        pred_theme = str((action_theme or (top_themes[0] if top_themes else {})).get("name") or "")
        theme_net = _to_num(action_theme.get("net"), 0.0) if action_theme else 0.0
        theme_risk = _to_num(action_theme.get("risk"), 0.0) if action_theme else 0.0
        theme_score = _clamp(theme_net * 8.0) if action_theme else 0.0
        theme_persist = theme_persistence(pred_theme, action_theme if isinstance(action_theme, dict) else None) if pred_theme else {"score": 0.0, "delta": 0.0, "state": "none"}
        theme_persist_score = _to_num(theme_persist.get("score"), 0.0)
        theme_is_continuing = bool(has_trade_theme and theme_persist_score >= 64 and str(theme_persist.get("state")) != "fade")
        theme_is_fading = bool(has_trade_theme and (theme_persist_score <= 42 or str(theme_persist.get("state")) == "fade"))

        has_tier = bool(has_trade_theme and pred_theme and (pred_theme in tier_theme_set or any(_fuzzy_match(pred_theme, tn) for tn in tier_theme_set)))
        matched_strength_name = matched_strength_name_of(pred_theme)
        lb_list = theme_lb_names.get(pred_theme) or (theme_lb_names.get(matched_strength_name) if matched_strength_name else []) or []
        leader_name = ""
        if has_trade_theme and pred_theme:
            leader = theme_leader.get(pred_theme) or (theme_leader.get(matched_strength_name) if matched_strength_name else None)
            leader_name = str((leader or {}).get("name") or "")
        is_theme_leader = bool(leader_name and leader_name == name)
        followers = [n for n in lb_list if n != leader_name][:2]
        follow_leader = leader_name if (not is_theme_leader and leader_name) else ""
        has_follow = bool(has_trade_theme and ((is_theme_leader and followers) or follow_leader))

        is_main = bool(has_trade_theme and main_theme and not _is_broad_theme(main_theme) and any(t.get("name") == main_theme or _fuzzy_match(t.get("name"), main_theme) for t in top_themes))
        main_bonus = 10.0 if is_main else 0.0
        leader_bonus = 12.0 if leader_max_b and lbc == leader_max_b else 6.0 if leader_max_b and lbc == leader_max_b - 1 else 0.0
        leader_identity_bonus = (7.0 if is_theme_leader else 0.0) + (5.0 if leader_bonus >= 10 else 2.0 if leader_bonus > 0 else 0.0)
        follower_penalty = 4.0 if follow_leader else 0.0
        board_score = _clamp(20 + (lbc - 1) * 22)
        high_penalty = 6.0 if stage_type == "good" and lbc >= 7 else 4.0 if stage_type == "good" and lbc >= 6 else 2.0 if stage_type == "good" and lbc >= 5 else 0.0
        multi_penalty = 18.0 if open_cnt >= 3 else 8.0 if open_cnt == 2 else 0.0
        theme_penalty = _clamp(theme_risk * 2.0, 0.0, 12.0) if has_trade_theme else 0.0
        theme_clarity_penalty = 0.0 if has_trade_theme else 12.0 if is_broad_only else 8.0

        base = fund_score * 0.34 + open_score * 0.24 + time_score * 0.16 + (theme_score if has_trade_theme else hy_score) * 0.14 + board_score * 0.12

        if lbc <= 1:
            next_step = "1进2"
            step_rate = jj_rate
            step_context_score = _clamp(38 + jj_rate * 0.92 + trend_jj_rate * 0.36 - max(0.0, broken_lb_rate - 72.0) * 0.22)
        elif lbc == 2:
            next_step = "2进3"
            step_rate = rate_2to3
            step_context_score = _clamp(30 + rate_2to3 * 1.45 + trend_jj_rate * 0.42 - max(0.0, broken_lb_rate - 70.0) * 0.28)
        elif lbc == 3:
            next_step = "3进4"
            step_rate = rate_3to4
            step_context_score = _clamp(34 + rate_3to4 * 0.72 + height_context_score * 0.28 + trend_jj_rate * 0.3 - max(0.0, broken_lb_rate - 65.0) * 0.44 - (10 if height_pressure else 0) + (6 if height_repair else 0))
        else:
            next_step = f"{int(lbc)}进{int(lbc + 1)}" if float(lbc).is_integer() else "高位晋级"
            step_rate = min(rate_3to4 or jj_rate, jj_rate or rate_3to4) if (rate_3to4 or jj_rate) else 0.0
            step_context_score = _clamp(30 + height_context_score * 0.48 + step_rate * 0.36 + (12 if height_repair else 0) - (18 if height_pressure else 0) - max(0.0, broken_lb_rate - 65.0) * 0.34)

        step_context_bonus = (step_context_score - 50.0) * 0.26
        ecology_bonus = (promo_ecology - 50.0) * 0.16
        theme_persist_bonus = ((theme_persist_score - 50.0) * 0.18) if has_trade_theme else 0.0
        individual_break_risk = _clamp(
            break_risk_base
            + (18.0 if open_cnt >= 8 else 8.0 if open_cnt >= 3 else 0.0)
            + (12.0 if is_yizi else 7.0 if is_shrink_seal else 0.0)
            + (10.0 if lbc >= 4 and height_pressure else 0.0)
            + (8.0 if theme_is_fading else 0.0)
            - (10.0 if theme_is_continuing else 0.0)
            - max(0.0, step_context_score - 55.0) * 0.16
        )
        break_risk_penalty = max(0.0, individual_break_risk - 58.0) * 0.21

        cje_yi = _yi(s.get("cje"))
        zsz_yi = _yi(s.get("zsz"))
        hs_pct = _to_num(s.get("hs"), 0.0)
        cap_score = _clamp(100 - max(0.0, zsz_yi - 150) * 0.55) if zsz_yi else 55.0
        cap_bonus = (cap_score - 55.0) * 0.1

        cje_relaxed = lbc >= 3 and open_cnt == 0 and zsz_yi < 100 and bool(top_themes) and theme_net >= 8
        cje_threshold = 5.0 if cje_relaxed else 10.0
        if cje_yi > 0:
            if cje_yi <= cje_threshold:
                cje_target_score = _clamp(36.0 * (cje_yi / cje_threshold), 0.0, 36.0)
            else:
                cje_target_score = _clamp(92.0 + min(cje_yi - 10, 25) * 0.46 - max(0.0, cje_yi - 40) * 0.55, 76.0, 100.0)
        else:
            cje_target_score = 0.0
        cje_bonus = (cje_target_score / 100.0) * 18.0
        capacity_bonus = 4.0 if 10.0 <= cje_yi <= 40.0 else 2.0 if 5.0 <= cje_yi < 10.0 else 0.0

        seal_vol_cap = 20.0 if open_cnt == 0 and lbc >= 2 else 12.0
        vol_tier_score = _clamp(100.0 - abs(hs_pct - 8.0) * 6.5) if hs_pct else 55.0
        vol_bonus = (vol_tier_score / 100.0) * 18.0
        is_moderate_volume = bool(hs_pct >= 3 and hs_pct <= seal_vol_cap)
        mild_vol_extra = (14.0 if cje_yi > cje_threshold else 8.0) if is_moderate_volume else 0.0

        is_new_high = lbc >= max_lbc and max_lbc >= 3
        new_high_bonus = 12.0 if is_new_high and max_lbc >= 6 else 8.0 if is_new_high and max_lbc >= 4 else 5.0 if is_new_high else 0.0
        has_spread = len(theme_groups["tradeable"]) >= 2
        theme_action_bonus = (6.0 if has_tier else 0.0) + (7.0 if is_theme_leader and has_follow else 4.0 if has_follow else 0.0) + (4.0 if has_spread else 0.0)
        theme_net_bonus = 16.0 if has_trade_theme and theme_net >= 12 else 10.0 if has_trade_theme and theme_net >= 8 else 5.0 if has_trade_theme and theme_net >= 5 else 0.0
        warm_vol_theme_combo = 16.0 if is_moderate_volume and has_trade_theme and theme_net >= 8 else 8.0 if is_moderate_volume and has_trade_theme and theme_net >= 5 else 0.0

        raw_score = _clamp(
            base * 0.44
            + quality_score * 0.22
            + env_boost * 0.10
            + main_bonus
            + leader_bonus
            + leader_identity_bonus
            + theme_action_bonus
            + cap_bonus
            + cje_bonus
            + capacity_bonus
            + vol_bonus
            + mild_vol_extra
            + new_high_bonus
            + theme_net_bonus
            + warm_vol_theme_combo
            + step_context_bonus
            + ecology_bonus
            + theme_persist_bonus
            - high_penalty
            - multi_penalty
            - theme_penalty
            - theme_clarity_penalty
            - yizi_penalty
            - follower_penalty
            - break_risk_penalty
        )

        tags: List[Dict[str, str]] = []
        if quality_label:
            tags.append(_tag(quality_label, "ladder-chip-strong red-text" if quality_score >= 88 else "ladder-chip-warn orange-text" if quality_score >= 72 else "ladder-chip-cool blue-text"))
        if is_main:
            tags.append(_tag("主线", "ladder-chip-strong red-text"))
        if leader_bonus >= 10:
            tags.append(_tag("前龙头", "ladder-chip-strong red-text"))
        elif leader_bonus > 0:
            tags.append(_tag("核心梯队", "ladder-chip-warn orange-text"))
        tags.append(_tag("有梯队" if has_tier else "无梯队" if has_trade_theme else "属性标签" if is_broad_only else "题材待确认", "ladder-chip-warn orange-text" if has_tier else "ladder-chip-cool blue-text"))
        if has_trade_theme:
            tags.append(_tag(f"带动{'、'.join(followers) or '—'}" if is_theme_leader and has_follow else f"跟风{follow_leader}" if has_follow else "无跟风", "ladder-chip-cool blue-text"))
        tags.append(_tag(next_step, "ladder-chip-strong red-text" if step_context_score >= 70 else "ladder-chip-warn orange-text" if step_context_score >= 52 else "ladder-chip-cool blue-text"))
        if promo_ecology >= 62:
            tags.append(_tag("晋级生态强", "ladder-chip-strong red-text"))
        elif promo_ecology <= 42:
            tags.append(_tag("晋级生态弱", "ladder-chip-warn orange-text"))
        if height_repair:
            tags.append(_tag("高度修复", "ladder-chip-strong red-text"))
        elif height_pressure:
            tags.append(_tag("高度压制", "ladder-chip-warn orange-text"))
        if theme_is_continuing:
            tags.append(_tag("题材持续", "ladder-chip-strong red-text"))
        elif theme_is_fading:
            tags.append(_tag("题材转弱", "ladder-chip-warn orange-text"))
        if individual_break_risk >= 68:
            tags.append(_tag("断板风险高", "ladder-chip-warn orange-text"))
        tags.extend(
            [
                _tag(f"{int(lbc)}板", "ladder-chip-strong red-text" if lbc >= 6 else "ladder-chip-warn orange-text" if lbc >= 4 else "ladder-chip-cool blue-text"),
                _tag(f"封单{fund_yi:.2f}亿" if fund_yi else "封单-亿", "ladder-chip-strong red-text" if fund_yi >= 3 else "ladder-chip-warn orange-text" if fund_yi >= 1 else "ladder-chip-cool blue-text"),
                _tag(f"{int(open_cnt)}次开板", "ladder-chip-warn orange-text" if open_cnt >= 3 else "ladder-chip-cool blue-text") if open_cnt else _tag("未开", "ladder-chip-cool blue-text"),
            ]
        )
        if _fmt_hhmm(s.get("fbt")):
            tags.append(_tag(f"首封{_fmt_hhmm(s.get('fbt'))}", "ladder-chip-strong red-text" if time_score >= 70 else "ladder-chip-cool blue-text"))
        if zsz_yi:
            tags.append(_tag(f"市值{zsz_yi:.0f}亿", "ladder-chip-warn orange-text" if zsz_yi <= 150 else "ladder-chip-cool blue-text"))
        if cje_yi:
            tags.append(_tag(f"成交额{cje_yi:.2f}亿", "ladder-chip-strong red-text" if cje_yi > 10 else "ladder-chip-warn orange-text" if cje_yi >= 3 else "ladder-chip-cool blue-text"))
        if hs_pct:
            tags.append(_tag(f"{hs_pct:.1f}%换手", "ladder-chip-warn orange-text" if is_moderate_volume else "ladder-chip-cool blue-text"))
        if is_moderate_volume:
            tags.append(_tag("温和放量", "ladder-chip-strong red-text"))
        if is_new_high:
            tags.append(_tag("突破新高", "ladder-chip-strong red-text"))
        if has_trade_theme and theme_net >= 12:
            tags.append(_tag("极强主线", "ladder-chip-strong red-text"))
        elif has_trade_theme and theme_net >= 8:
            tags.append(_tag("强主线", "ladder-chip-strong red-text"))
        elif has_trade_theme and theme_net >= 5:
            tags.append(_tag("中等主线", "ladder-chip-warn orange-text"))
        if warm_vol_theme_combo >= 16:
            tags.append(_tag("量价共振", "ladder-chip-strong red-text"))
        elif warm_vol_theme_combo >= 8:
            tags.append(_tag("放量+板块", "ladder-chip-warn orange-text"))
        if is_yizi:
            tags.append(_tag("一字板", "ladder-chip-cool blue-text"))
        if is_shrink_seal:
            tags.append(_tag("缩量封板", "ladder-chip-cool blue-text"))
        if has_spread:
            tags.append(_tag("题材发散", "ladder-chip-cool blue-text"))
        if top_themes:
            for trow in top_themes:
                tname = str(trow.get("name") or "")
                tags.append(_tag(tname, "ladder-chip-cool blue-text" if _is_broad_theme(tname) else "ladder-chip-warn orange-text" if _to_num(trow.get("net"), 0) >= 12 else ""))
        else:
            tags.append(_tag(f"{hy}×{hy_cnt.get(hy, 1)}", "ladder-chip-warn orange-text" if hy_score >= 60 else ""))

        reason_bits: List[str] = []
        if quality_label:
            reason_bits.append(f"封板质量：{quality_label}")
        if fund_yi >= fund_lo + (fund_hi - fund_lo) * 0.6:
            reason_bits.append("封单偏强")
        if open_cnt <= 1:
            reason_bits.append("开板少/封板稳")
        if time_score >= 70:
            reason_bits.append("早封")
        if top_themes:
            reason_bits.append(f"{'板块归属' if has_trade_theme else '属性标签'}：" + "、".join(str(x.get("name") or "") for x in top_themes))
        elif hy_score >= 60:
            reason_bits.append("行业内涨停集中")
        if is_main:
            reason_bits.append("主线加成")
        if leader_bonus >= 10:
            reason_bits.append("龙头梯队")
        if has_tier and has_follow:
            reason_bits.append("梯队带动" if is_theme_leader else "梯队+跟风")
        if promo_ecology >= 62:
            reason_bits.append(f"晋级生态强({int(jj_rate)}%/{int(broken_lb_rate)}%)")
        elif promo_ecology <= 42:
            reason_bits.append(f"晋级生态弱({int(jj_rate)}%/{int(broken_lb_rate)}%)")
        if height_repair:
            reason_bits.append("高度修复")
        elif height_pressure:
            reason_bits.append("高度压制")
        if theme_is_continuing:
            reason_bits.append("题材持续")
        elif theme_is_fading:
            reason_bits.append("题材转弱")
        if individual_break_risk >= 68:
            reason_bits.append("断板风险高")
        if lbc >= 2:
            reason_bits.append("梯队内有辨识度")
        if zsz_yi and zsz_yi <= 150:
            reason_bits.append("小市值")
        if cje_yi and cje_yi > 10:
            reason_bits.append("成交额>10亿")
        if is_moderate_volume:
            reason_bits.append("温和放量")
        if is_new_high:
            reason_bits.append(f"突破新高({int(max_lbc)}板)")
        if is_yizi:
            reason_bits.append("一字板(参与难度大)")
        elif is_shrink_seal:
            reason_bits.append("缩量封板(参与难度大)")
        if has_tier and has_follow and (has_spread or theme_net >= 10):
            reason_bits.append("题材联动")
        if has_trade_theme and theme_net >= 12:
            reason_bits.append("极强主线(板块净强≥12)")
        elif has_trade_theme and theme_net >= 8:
            reason_bits.append("强主线(板块净强≥8)")
        if warm_vol_theme_combo >= 16:
            reason_bits.append("量价共振(温和放量+强板块)")
        elif warm_vol_theme_combo >= 8:
            reason_bits.append("放量+板块共振")
        if open_cnt >= 8:
            reason_bits.append("强分歧(多开板)")
        elif open_cnt >= 3:
            reason_bits.append("分歧偏大")
        if stage_type == "good" and lbc >= 5:
            reason_bits.append("高位谨慎")

        gap_range = {"lo": 3, "hi": 6} if raw_score >= 82 else {"lo": 1, "hi": 4} if raw_score >= 70 else {"lo": 0, "hi": 2} if raw_score >= 58 else {"lo": -1, "hi": 1} if raw_score >= 45 else {"lo": -3, "hi": 0}
        if step_context_score >= 72 and not height_pressure:
            gap_range = {"lo": gap_range["lo"] + 1, "hi": gap_range["hi"] + 1}
        elif individual_break_risk >= 70 or height_pressure:
            gap_range = {"lo": gap_range["lo"] - 1, "hi": gap_range["hi"] - 1}
        if lbc >= 4 and not height_repair:
            gap_range = {"lo": min(gap_range["lo"], 1), "hi": min(gap_range["hi"], 4)}
        auc_ratio = 0.08 if raw_score >= 82 else 0.06 if raw_score >= 70 else 0.045 if raw_score >= 58 else 0.03
        if step_context_score < 45 or individual_break_risk >= 70:
            auc_ratio += 0.015
        elif step_context_score >= 70 and theme_is_continuing:
            auc_ratio = max(0.035, auc_ratio - 0.01)
        auc_need = max(0.15, cje_yi * auc_ratio) if cje_yi else 0.0
        fund_ref = fund_yi if fund_yi > 0 else 0.0

        if open_cnt >= 8:
            lo, hi = min(gap_range["lo"], 0), min(gap_range["hi"], 2)
            need = fund_ref * 0.5 if fund_ref else 0.0
            observe_point = (
                f'<div class="exp-row"><span class="exp-pill pill-pre">预期</span>{_gap_label(lo, hi)}（{_pct(lo)}~{_pct(hi)}）</div>'
                f'<div class="exp-row"><span class="exp-pill pill-hi">超预期</span>回封 + 封单回补≥{need:.2f}亿（≈今{fund_ref:.2f}亿×50%） + 竞价成交额≥{auc_need:.2f}亿（≈今{cje_yi:.2f}亿×{_round(auc_ratio * 100)}%）</div>'
                '<div class="exp-row"><span class="exp-pill pill-lo">低预期</span>不回封 或 多开板继续放大</div>'
            )
        elif open_cnt >= 3:
            lo, hi = min(gap_range["lo"], 0), gap_range["hi"]
            need = fund_ref * 0.35 if fund_ref else 0.0
            observe_point = (
                f'<div class="exp-row"><span class="exp-pill pill-pre">预期</span>{_gap_label(lo, hi)}（{_pct(lo)}~{_pct(hi)}）</div>'
                f'<div class="exp-row"><span class="exp-pill pill-hi">超预期</span>高开≥{_pct(hi)} + 回封后封单≥{need:.2f}亿（≈今{fund_ref:.2f}亿×35%） + 竞价成交额≥{auc_need:.2f}亿</div>'
                f'<div class="exp-row"><span class="exp-pill pill-lo">低预期</span>低开≤{_pct(gap_range["lo"])} 或 开板继续放大</div>'
            )
        else:
            lo, hi = gap_range["lo"], gap_range["hi"]
            observe_point = (
                f'<div class="exp-row"><span class="exp-pill pill-pre">预期</span>{_gap_label(lo, hi)}（{_pct(lo)}~{_pct(hi)}）</div>'
                f'<div class="exp-row"><span class="exp-pill pill-hi">超预期</span>高开≥{_pct(hi)} + 竞价成交额≥{auc_need:.2f}亿（≈今{cje_yi:.2f}亿×{_round(auc_ratio * 100)}%） + 开板≤1</div>'
                f'<div class="exp-row"><span class="exp-pill pill-lo">低预期</span>低于{_pct(lo)} 或 竞价量能<{auc_need * 0.7:.2f}亿</div>'
            )

        head = " · ".join(reason_bits) if reason_bits else "综合条件一般"
        normalized_tags = _normalize_tags(tags)
        scored.append(
            {
                "name": name,
                "code": code,
                "lbc": int(lbc) if float(lbc).is_integer() else lbc,
                "hy": hy,
                "fundYi": fund_yi,
                "open": int(open_cnt) if float(open_cnt).is_integer() else open_cnt,
                "predTheme": pred_theme,
                "hasTier": has_tier,
                "hasTradeTheme": has_trade_theme,
                "isBroadOnly": is_broad_only,
                "cjeYi": cje_yi,
                "qualityLabel": quality_label,
                "qualityScore": quality_score,
                "nextStep": next_step,
                "stepRate": step_rate,
                "stepContextScore": _round(step_context_score),
                "promoEcology": _round(promo_ecology),
                "heightContextScore": _round(height_context_score),
                "breakRisk": _round(individual_break_risk),
                "themePersistScore": _round(theme_persist_score),
                "isYizi": is_yizi,
                "isShrinkSeal": is_shrink_seal,
                "_leaderBonus": leader_bonus,
                "_isThemeLeader": is_theme_leader,
                "_isNewHigh": is_new_high,
                "_themeNet": theme_net,
                "_isMain": is_main,
                "_raw": _round(raw_score),
                "score": _round(raw_score),
                "tags": normalized_tags,
                "tagRows": _tag_rows(normalized_tags),
                "reason": f'<span class="reason-bits">{head}</span><div class="exp-wrap">{observe_point}</div>',
            }
        )

    ranked = sorted(scored, key=lambda r: (_to_num(r.get("_raw"), 0), _to_num(r.get("qualityScore"), 0), _to_num(r.get("fundYi"), 0), _to_num(r.get("lbc"), 0)), reverse=True)
    n = len(ranked) or 1
    for idx, r in enumerate(ranked):
        r["score"] = int(_clamp(_round(((n - idx) / n) * 100.0), 1, 100))

    def relay_sort(r: Dict[str, Any]) -> Tuple[float, float, float, float, float]:
        return (
            _to_num(r.get("_raw"), 0),
            _to_num(r.get("stepContextScore"), 0),
            -_to_num(r.get("breakRisk"), 0),
            _to_num(r.get("qualityScore"), 0),
            _to_num(r.get("fundYi"), 0),
        )

    relay_core = sorted(
        [
            r
            for r in scored
            if r.get("hasTradeTheme")
            and not r.get("isYizi")
            and not r.get("isShrinkSeal")
            and 2 <= _to_num(r.get("lbc"), 0) <= 5
            and _to_num(r.get("open"), 0) < 8
            and _to_num(r.get("breakRisk"), 0) < 76
            and _to_num(r.get("stepContextScore"), 0) >= 38
        ],
        key=relay_sort,
        reverse=True,
    )
    relay_one_to_two = sorted(
        [
            r
            for r in scored
            if r.get("hasTradeTheme")
            and not r.get("isYizi")
            and not r.get("isShrinkSeal")
            and _to_num(r.get("lbc"), 0) == 1
            and _to_num(r.get("open"), 0) < 3
            and _to_num(r.get("_raw"), 0) >= 72
            and _to_num(r.get("stepContextScore"), 0) >= 55
            and _to_num(r.get("breakRisk"), 0) < 68
        ],
        key=relay_sort,
        reverse=True,
    )[:3]
    relay = sorted([*relay_core, *relay_one_to_two], key=relay_sort, reverse=True)[:8]
    relay_n = len(relay) or 1
    for idx, r in enumerate(relay):
        r["score"] = int(_clamp(_round(((relay_n - idx) / relay_n) * 100.0), 1, 100))
    relay_names = {str(x.get("name") or "") for x in relay}

    cap_arr = sorted([_to_num(r.get("cjeYi"), 0) for r in scored if _to_num(r.get("cjeYi"), 0) > 0])
    cap_p80 = cap_arr[int(len(cap_arr) * 0.8)] if cap_arr else 0.0

    cap_threshold = max(20.0, cap_p80)

    def watch_bucket(r: Dict[str, Any]) -> int:
        cje_yi = _to_num(r.get("cjeYi"), 0.0)
        open_cnt = _to_num(r.get("open"), 0.0)
        lbc = _to_num(r.get("lbc"), 0.0)
        break_risk = _to_num(r.get("breakRisk"), 0.0)
        leader_bonus = _to_num(r.get("_leaderBonus"), 0.0)
        if lbc >= max(4.0, max_lbc) or leader_bonus >= 10 or r.get("_isThemeLeader") or r.get("_isNewHigh"):
            return 0
        if lbc >= 3:
            return 1
        if cje_yi >= cap_threshold and r.get("hasTradeTheme") and open_cnt < 3 and break_risk < 70:
            return 2
        if cje_yi >= cap_threshold or open_cnt >= 3 or break_risk >= 68:
            return 3
        if _to_num(r.get("stepContextScore"), 0.0) < 42 or not r.get("hasTradeTheme"):
            return 4
        return 5

    def watch_group(r: Dict[str, Any]) -> str:
        return {
            0: "高标/题材核心",
            1: "高位分歧",
            2: "容量核心",
            3: "风险观察",
            4: "补充观察",
        }.get(watch_bucket(r), "补充观察")

    def watch_rank(r: Dict[str, Any]) -> float:
        cje_yi = _to_num(r.get("cjeYi"), 0.0)
        open_cnt = _to_num(r.get("open"), 0.0)
        lbc = _to_num(r.get("lbc"), 0.0)
        bucket = watch_bucket(r)
        capacity = min(cje_yi, 90.0) * 0.92 + (18.0 if cje_yi >= cap_threshold else 0.0)
        divergence = min(open_cnt, 12.0) * 5.0 + max(0.0, _to_num(r.get("breakRisk"), 0.0) - 60.0) * 0.95
        height = lbc * 18.0 + _to_num(r.get("_leaderBonus"), 0.0) * 1.7 + (12.0 if r.get("_isThemeLeader") else 0.0) + (8.0 if r.get("_isNewHigh") else 0.0)
        theme_gap = 0.0 if r.get("hasTradeTheme") else 22.0 if r.get("isBroadOnly") else 16.0
        theme_core = _to_num(r.get("_themeNet"), 0.0) * 1.8 + _to_num(r.get("stepContextScore"), 0.0) * 0.22
        weak_step = max(0.0, 48.0 - _to_num(r.get("stepContextScore"), 0.0)) * 0.45
        core = _to_num(r.get("_raw"), 0.0) * 0.35 + _to_num(r.get("qualityScore"), 0.0) * 0.15
        bucket_base = {0: 240.0, 1: 200.0, 2: 165.0, 3: 130.0, 4: 95.0}.get(bucket, 70.0)
        if bucket == 0:
            return bucket_base + height + theme_core * 0.55 + capacity * 0.22 + core * 0.22 - divergence * 0.15
        if bucket == 1:
            return bucket_base + height * 0.65 + divergence * 0.78 + capacity * 0.42 + theme_core * 0.25
        if bucket == 2:
            return bucket_base + capacity + theme_core * 0.72 + core * 0.22 - divergence * 0.22
        if bucket == 3:
            return bucket_base + capacity * 0.78 + divergence * 0.82 + theme_core * 0.22 + theme_gap * 0.25
        return bucket_base + core * 0.45 + capacity * 0.45 + height * 0.35 + theme_gap + weak_step

    watch_pool = [
        r
        for r in scored
        if str(r.get("name") or "") not in relay_names
        and (
            watch_bucket(r) <= 1
            or (_to_num(r.get("cjeYi"), 0) and _to_num(r.get("cjeYi"), 0) >= cap_threshold)
            or _to_num(r.get("lbc"), 0) >= 5
            or _to_num(r.get("open"), 0) >= 3
            or _to_num(r.get("breakRisk"), 0) >= 68
            or _to_num(r.get("stepContextScore"), 0) < 42
            or not r.get("hasTradeTheme")
        )
    ]
    def watch_sort_key(r: Dict[str, Any]) -> Tuple[float, float, float, float, float, float]:
        return (
            -float(watch_bucket(r)),
            watch_rank(r),
            _to_num(r.get("lbc"), 0),
            _to_num(r.get("cjeYi"), 0),
            _to_num(r.get("_raw"), 0),
            _to_num(r.get("qualityScore"), 0),
        )

    watch_pool = sorted(watch_pool, key=watch_sort_key, reverse=True)
    watch = watch_pool[:10]
    if not watch:
        watch = sorted([r for r in scored if str(r.get("name") or "") not in relay_names], key=watch_sort_key, reverse=True)[:10]

    ladder_must = []
    for x in ladder:
        if isinstance(x, dict) and _to_num(x.get("badge"), 0) >= 4:
            nm = str(x.get("name") or "").replace("👑", "").strip()
            if nm:
                ladder_must.append(nm)
    must_set = set(ladder_must)
    must_objs = sorted(
        [x for x in scored if str(x.get("name") or "") in must_set and str(x.get("name") or "") not in relay_names],
        key=watch_sort_key,
        reverse=True,
    )
    merged: List[Dict[str, Any]] = []
    seen_names: set[str] = set()
    for x in [*must_objs, *watch]:
        nm = str(x.get("name") or "")
        if nm and nm not in seen_names:
            merged.append(x)
            seen_names.add(nm)
    watch = sorted(merged, key=watch_sort_key, reverse=True)[:8]
    watch_n = len(watch) or 1
    for idx, r in enumerate(watch):
        rank_score = int(_clamp(_round(((watch_n - idx) / watch_n) * 100.0), 1, 100))
        r["watchRank"] = rank_score
        r["watchGroup"] = watch_group(r)
        r["score"] = rank_score

    def strip(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for x in rows:
            y = dict(x)
            for k in ("_raw", "hasTradeTheme", "isBroadOnly", "isYizi", "isShrinkSeal", "_leaderBonus", "_isThemeLeader", "_isNewHigh", "_themeNet", "_isMain"):
                y.pop(k, None)
            out.append(y)
        return out

    return {
        "meta": {
            "tierThemeCount": len(tier_themes),
            "tierThemeTop": tier_theme_top,
            "source": "python",
            "model": "zt_analysis_factor_v2",
            "promoEcology": _round(promo_ecology),
            "heightContext": "repair" if height_repair else "pressure" if height_pressure else "neutral",
            "breakRiskBase": _round(break_risk_base),
        },
        "relay": strip(relay[:8]),
        "watch": strip(watch[:8]),
    }
