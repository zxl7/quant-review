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
    if "ladder-chip-cool" in text or "muted-text" in text or "blue-text" in text:
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
    if text in {"市场总龙头", "前龙头", "核心梯队", "有梯队"}:
        return (3, {"市场总龙头": 0, "前龙头": 1, "核心梯队": 2, "有梯队": 3}.get(text, 9), idx)
    if text.startswith("突破") and text.endswith("板压制"):
        return (3, 2, idx)
    if text.startswith("带动") and len(text) <= 8:
        return (3, 3, idx)
    if text.startswith("带动"):
        return (3, 4, idx)
    if text.startswith("跟风"):
        return (3, 5, idx)
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
            return "ladder-chip-cool muted-text"
        step_from = int(m.group(1))
        if step_from >= 4:
            return "ladder-chip-warn orange-text"
        return "ladder-chip-strong red-text" if step_from >= 2 else "ladder-chip-cool muted-text"
    if re.fullmatch(r"\d+(?:\.\d+)?板", text):
        board = _to_num(text, 0)
        return "ladder-chip-warn orange-text" if board >= 5 else "ladder-chip-cool muted-text"
    if text in {"主线", "极强主线", "强主线", "前龙头", "核心梯队", "带动", "封单充足", "加速确认", "晋级生态强", "高度修复", "突破新高"} or text.startswith("带动"):
        return "ladder-chip-strong red-text"
    if text in {"中等主线", "断板风险高", "高度压制", "晋级生态弱", "题材转弱", "高换手承接", "分歧烂板", "反复回封", "一字板", "缩量封板", "无梯队", "题材待确认"} or text.startswith("跟风"):
        return "ladder-chip-warn orange-text"
    if re.fullmatch(r"\d+(?:\.\d+)?次开板", text):
        return "ladder-chip-warn orange-text"
    return "ladder-chip-cool muted-text"


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
    return "muted"


def _tag_rows(tags: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    rows = [
        {"tone": "red", "tags": []},
        {"tone": "orange", "tags": []},
        {"tone": "muted", "tags": []},
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


def _factor_band(score: float) -> Dict[str, str]:
    if score >= 80:
        return {"label": "强候选", "tone": "strong", "action": "只等竞价确认"}
    if score >= 70:
        return {"label": "重点候选", "tone": "good", "action": "优先看确认点"}
    if score >= 60:
        return {"label": "条件触发", "tone": "watch", "action": "需要超预期"}
    return {"label": "只观察", "tone": "cool", "action": "不主动接力"}


def _market_gate(score: float, *, promo_ecology: float, break_risk_base: float, height_pressure: bool) -> Dict[str, Any]:
    if score >= 82 and promo_ecology >= 52 and break_risk_base < 72:
        label, action, adjust = "进攻窗口", "可做主线核心", 2.0
    elif score >= 70:
        label, action, adjust = "接力可做", "优先核心确认", 0.0
    elif score >= 58:
        label, action, adjust = "只做核心", "降低出手频次", -4.0
    elif score >= 45:
        label, action, adjust = "防守观察", "只看回封确认", -8.0
    else:
        label, action, adjust = "休息优先", "不主动接力", -14.0
    if height_pressure:
        adjust -= 2.0
        if label in {"进攻窗口", "接力可做"}:
            action = f"{action}，高位降档"
    return {"score": _round(score), "label": label, "action": action, "adjust": adjust}


def _factor_label(score: float) -> str:
    if score >= 82:
        return "强"
    if score >= 70:
        return "偏强"
    if score >= 58:
        return "中性"
    return "偏弱"


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
    action_advisor = market_data.get("actionAdvisor") if isinstance(market_data.get("actionAdvisor"), dict) else {}
    stage_type = str(mood_stage.get("type") or "warn")
    cycle_code = str(mood_stage.get("cycle") or "")
    day_state = str(mood_stage.get("dayState") or "")
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
    prior_height_window = hist_max_lb[:-1] if len(hist_max_lb) >= 2 else []
    recent_height_cap = max(prior_height_window[-5:] or [prev_max_b or 0.0])
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

    strength_ranked = sorted(
        [r for r in strength_rows if isinstance(r, dict) and str(r.get("name") or "")],
        key=lambda r: theme_pick_score(r),
        reverse=True,
    )

    def theme_rank_score(theme_name: Any) -> float:
        name = canonical_theme_name(theme_name)
        if not name:
            return 42.0
        for idx, row in enumerate(strength_ranked):
            rname = str(row.get("name") or "")
            if rname == name or _fuzzy_match(rname, name):
                return _clamp(92.0 - idx * 4.5, 35.0, 92.0)
        return 42.0

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

    plate_strengths = [_to_num(r.get("strength"), 0.0) for r in plate_rows if isinstance(r, dict)]
    plate_lo, plate_hi = _safe_min_max((x for x in plate_strengths if x > 0), (0.0, 0.0))
    top_theme_rows = [r for r in strength_ranked if isinstance(r, dict) and not _is_broad_theme(r.get("name"))][:5]
    top_theme_net_avg = _avg((_to_num(r.get("net"), 0.0) for r in top_theme_rows), 0.0)
    top_theme_risk_avg = _avg((_to_num(r.get("risk"), 0.0) for r in top_theme_rows), 0.0)
    top_theme_zt_avg = _avg((_to_num(r.get("zt"), 0.0) for r in top_theme_rows), 0.0)
    top_plate_rows = [r for r in plate_rows if isinstance(r, dict)][:5]
    plate_rank_avg = _avg((_clamp(100.0 - max(0.0, _to_num(r.get("rank"), 12.0) - 1.0) * 7.0, 28.0, 100.0) for r in top_plate_rows), 45.0)
    plate_strength_avg = _avg((_to_num(r.get("strength"), 0.0) for r in top_plate_rows), 0.0)
    plate_strength_score = _norm(plate_strength_avg, plate_lo, plate_hi) if plate_hi > plate_lo else 55.0
    theme_env_score = _clamp(
        26.0
        + top_theme_net_avg * 2.9
        + min(top_theme_zt_avg, 24.0) * 0.72
        + len(tier_themes) * 2.4
        + (8.0 if main_theme and not _is_broad_theme(main_theme) else 0.0)
        + (plate_rank_avg - 50.0) * 0.14
        + (plate_strength_score - 50.0) * 0.12
        - top_theme_risk_avg * 1.95
    )

    def matched_plate_row(theme_name: Any, code: Any = "", name: Any = "") -> Dict[str, Any] | None:
        target = str(theme_name or "")
        for row in plate_rows:
            if not isinstance(row, dict):
                continue
            rname = str(row.get("name") or "")
            if target and (rname == target or _fuzzy_match(rname, target)):
                return row
            leaders = row.get("leaders") if isinstance(row.get("leaders"), list) else []
            for leader in leaders:
                if not isinstance(leader, dict):
                    continue
                lcode = _norm_code6(leader.get("code"))
                lname = str(leader.get("name") or "")
                if (code and lcode and lcode == _norm_code6(code)) or (name and lname == str(name)):
                    return row
        return None

    def plate_rotation_context(theme_name: Any, code: Any = "", name: Any = "") -> Dict[str, Any]:
        row = matched_plate_row(theme_name, code, name)
        if not row:
            return {"score": 50.0, "rank": 0, "name": "", "lead": "", "strength": 0.0}
        rank = _to_num(row.get("rank"), 12.0)
        strength = _to_num(row.get("strength"), 0.0)
        rank_score = _clamp(100.0 - max(0.0, rank - 1.0) * 7.0, 28.0, 100.0)
        strength_score = _norm(strength, plate_lo, plate_hi) if plate_hi > plate_lo else 55.0
        return {
            "score": _clamp(rank_score * 0.58 + strength_score * 0.42),
            "rank": int(rank) if rank else 0,
            "name": str(row.get("name") or ""),
            "lead": str(row.get("lead") or ""),
            "strength": strength,
        }

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
    mood = market_data.get("mood") if isinstance(market_data.get("mood"), dict) else {}
    panorama = market_data.get("panorama") if isinstance(market_data.get("panorama"), dict) else {}
    vol_chg = _to_num(volume.get("change"), 0.0)
    zb_rate = _to_num(mi.get("zb_rate"), _to_num(fear.get("broken"), 0.0))
    fb_rate = _to_num(mi.get("fb_rate"), _to_num(panorama.get("ratio"), 50.0))
    mood_score = _to_num(mood.get("score"), 50.0)
    mood_heat = _to_num(mood.get("heat"), mood_score)
    mood_risk = _to_num(mood.get("risk"), 50.0)
    limit_up_count = _to_num(mi.get("zt_count"), _to_num(panorama.get("limitUp"), len(zt)))
    dt_count = _to_num(mi.get("dt_count"), _to_num(panorama.get("limitDown"), 0.0))
    env_liquidity_score = _clamp(50 + vol_chg * 2 - (zb_rate - 20) * 0.6)
    market_sentiment_score = _clamp(
        32.0
        + mood_score * 0.18
        + mood_heat * 0.12
        + fb_rate * 0.12
        + jj_rate * 0.26
        + rate_2to3 * 0.10
        + rate_3to4 * 0.08
        + height_context_score * 0.10
        + min(limit_up_count, 120.0) * 0.08
        - mood_risk * 0.12
        - max(0.0, broken_lb_rate - 62.0) * 0.30
        - max(0.0, zb_rate - 18.0) * 0.20
        - max(0.0, dt_count - 3.0) * 1.40
        + trend_jj_rate * 0.18
        - max(0.0, trend_broken_lb_rate) * 0.24
        + max(0.0, -trend_broken_lb_rate) * 0.08
    )
    posture = str(action_advisor.get("posture") or "")
    position_text = str(action_advisor.get("position") or "")
    posture_bonus = (
        10.0 if posture == "进攻"
        else 6.0 if posture in {"积极试探", "试探进攻"}
        else 2.0 if posture in {"谨慎进攻", "谨慎试错"}
        else -4.0 if posture in {"控仓试错", "防守"}
        else -10.0 if posture == "空仓等待"
        else 0.0
    )
    position_bonus = (
        8.0 if position_text in {"5-7成", "3-5成"}
        else 3.0 if position_text in {"2-4成", "2-3成"}
        else -4.0 if position_text in {"1-2成", "1-3成或空仓"}
        else -10.0 if position_text == "空仓"
        else 0.0
    )
    day_state_penalty = 5.0 if day_state == "分歧" else 9.0 if "退潮" in day_state else 0.0
    cycle_bonus = 7.0 if cycle_code == "FERMENT" else 4.0 if cycle_code == "START" else -8.0 if cycle_code == "ICE" else 0.0
    env_score = _clamp(
        market_sentiment_score * 0.46
        + theme_env_score * 0.18
        + env_liquidity_score * 0.12
        + promo_ecology * 0.12
        + height_context_score * 0.07
        + (100.0 - break_risk_base) * 0.05
        + posture_bonus
        + position_bonus
        + cycle_bonus
        - day_state_penalty
    )
    market_gate = _market_gate(env_score, promo_ecology=promo_ecology, break_risk_base=break_risk_base, height_pressure=height_pressure)
    env_score = _clamp(env_score + _to_num(market_gate.get("adjust"), 0.0) * 0.8)
    market_gate = _market_gate(env_score, promo_ecology=promo_ecology, break_risk_base=break_risk_base, height_pressure=height_pressure)
    env_boost = _clamp(env_liquidity_score * 0.22 + market_sentiment_score * 0.34 + theme_env_score * 0.18 + env_score * 0.26)
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
        theme_zt = _to_num(action_theme.get("zt"), 0.0) if action_theme else 0.0
        theme_zb = _to_num(action_theme.get("zb"), 0.0) if action_theme else 0.0
        theme_dt = _to_num(action_theme.get("dt"), 0.0) if action_theme else 0.0
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

        opportunity_signal = _clamp(
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
        opportunity_score = _clamp(50.0 + (opportunity_signal - 50.0) * 0.62)
        sector_rank_context_score = theme_rank_score(pred_theme) if pred_theme else 42.0
        plate_ctx = plate_rotation_context(pred_theme, code, name)
        plate_score = _to_num(plate_ctx.get("score"), 50.0)
        plate_rank = _to_num(plate_ctx.get("rank"), 99.0)
        plate_name = str(plate_ctx.get("name") or "")
        plate_lead = str(plate_ctx.get("lead") or "")
        is_plate_leader = bool(plate_lead and plate_lead == name)
        plate_is_strong = bool(1 <= plate_rank <= 5 and plate_score >= 62)
        is_market_top = bool(leader_max_b and lbc == leader_max_b)
        height_breakout_leader = bool(
            is_market_top
            and is_new_high
            and lbc >= 6
            and lbc > max(recent_height_cap, prev_max_b)
            and not height_pressure
            and not is_yizi
            and not is_shrink_seal
            and open_cnt <= 2
            and (has_follow or is_theme_leader or is_plate_leader)
            and (theme_net >= 8 or plate_is_strong)
        )
        height_breakout_bonus = 0.0
        if height_breakout_leader:
            height_breakout_bonus = (
                7.0
                + min(6.0, max(0.0, lbc - max(recent_height_cap, 0.0)) * 3.0)
                + (3.0 if is_plate_leader else 0.0)
                + (2.5 if has_follow else 0.0)
                + (2.0 if theme_net >= 12 or plate_score >= 70 else 0.0)
            )
        sector_trend_score = _clamp(
            theme_persist_score * 0.34
            + sector_rank_context_score * 0.24
            + plate_score * 0.22
            + min(theme_net, 20.0) * 0.55
            + (5.0 if has_tier else 0.0)
            + (4.0 if is_theme_leader else 0.0)
            + (2.0 if has_follow else 0.0)
            - (8.0 if theme_is_fading else 0.0)
            - (6.0 if is_broad_only else 0.0)
        )
        if has_trade_theme:
            sector_panel_score = _clamp(
                28.0
                + theme_net * 1.65
                + min(theme_zt, 24.0) * 0.55
                + (theme_persist_score - 50.0) * 0.16
                + (6.0 if has_tier else 0.0)
                + (5.0 if is_main else 0.0)
                + (3.0 if has_spread else 0.0)
                - theme_risk * 1.80
                - theme_zb * 0.70
                - theme_dt * 3.00
                - (8.0 if theme_is_fading else 0.0)
            )
            sector_sentiment_score = _clamp(sector_panel_score * 0.64 + sector_trend_score * 0.36)
        elif is_broad_only:
            sector_panel_score = _clamp(34.0 + hy_score * 0.20 - 10.0)
            sector_sentiment_score = _clamp(sector_panel_score * 0.76 + sector_trend_score * 0.24)
        else:
            sector_panel_score = _clamp(30.0 + hy_score * 0.32)
            sector_sentiment_score = _clamp(sector_panel_score * 0.84 + sector_trend_score * 0.16)

        leader_signal_score = 78.0 if is_theme_leader else 70.0 if leader_bonus >= 10 else 62.0 if leader_bonus > 0 else 46.0 if follow_leader else 54.0
        stock_strength_score = _clamp(
            quality_score * 0.24
            + fund_score * 0.16
            + open_score * 0.13
            + time_score * 0.09
            + board_score * 0.09
            + step_context_score * 0.18
            + leader_signal_score * 0.11
            + (6.0 if is_new_high else 0.0)
            - multi_penalty * 0.32
            - yizi_penalty * 0.45
            - follower_penalty * 0.55
        )
        leader_factor_score = _clamp(
            leader_signal_score * 0.34
            + board_score * 0.18
            + quality_score * 0.14
            + step_context_score * 0.12
            + (86.0 if is_main else 62.0 if has_trade_theme else 38.0) * 0.08
            + (82.0 if is_new_high else 46.0) * 0.08
            + (76.0 if has_follow else 44.0) * 0.06
            - follower_penalty * 1.05
            - high_penalty * 0.95
            - yizi_penalty * 0.28
        )
        liquidity_band_score = 86.0 if 10.0 <= cje_yi <= 40.0 else 72.0 if 5.0 <= cje_yi < 10.0 else 66.0 if 40.0 < cje_yi <= 90.0 else 48.0 if cje_yi > 0 else 34.0
        capacity_score = _clamp(cje_target_score * 0.44 + vol_tier_score * 0.24 + cap_score * 0.17 + liquidity_band_score * 0.15)
        relay_factor_score = _clamp(
            step_context_score * 0.38
            + quality_score * 0.18
            + open_score * 0.12
            + fund_score * 0.10
            + promo_ecology * 0.10
            + opportunity_score * 0.07
            + max(0.0, 100.0 - individual_break_risk) * 0.05
        )
        risk_pressure = _clamp(
            individual_break_risk * 0.52
            + break_risk_base * 0.18
            + theme_clarity_penalty * 1.15
            + theme_penalty * 1.35
            + high_penalty * 1.45
            + yizi_penalty * 1.05
            + follower_penalty * 1.15
            + max(0.0, open_cnt - 1.0) * 2.60
            - max(0.0, step_context_score - 62.0) * 0.18
        )
        risk_control_score = _clamp(100.0 - risk_pressure)
        identity_edge = (
            (3.5 if is_theme_leader else 0.0)
            + (1.5 if leader_bonus > 0 else 0.0)
            + (1.2 if is_new_high else 0.0)
            + max(0.0, capacity_score - 72.0) * 0.05
            + max(0.0, leader_factor_score - 66.0) * 0.04
            - (1.8 if follow_leader else 0.0)
            - max(0.0, risk_pressure - 58.0) * 0.04
        )
        raw_score = _clamp(
            env_score * 0.16
            + sector_sentiment_score * 0.22
            + leader_factor_score * 0.21
            + relay_factor_score * 0.17
            + capacity_score * 0.14
            + risk_control_score * 0.08
            + opportunity_score * 0.02
            + identity_edge
            + height_breakout_bonus
            + _to_num(market_gate.get("adjust"), 0.0)
        )
        score_band = _factor_band(_round(raw_score))
        factor_breakdown = {
            "environment": _round(env_score),
            "market": _round(market_sentiment_score),
            "themeEnv": _round(theme_env_score),
            "marketGate": _round(_to_num(market_gate.get("adjust"), 0.0)),
            "sector": _round(sector_sentiment_score),
            "leader": _round(leader_factor_score),
            "relay": _round(relay_factor_score),
            "capacity": _round(capacity_score),
            "risk": _round(risk_control_score),
            "opportunity": _round(opportunity_score),
            "edge": _round(identity_edge),
            "heightBreakout": _round(height_breakout_bonus),
        }
        factor_hint = (
            f"环境{factor_breakdown['environment']}({market_gate.get('label')}) / "
            f"板块{factor_breakdown['sector']} / 龙头{factor_breakdown['leader']} / "
            f"接力{factor_breakdown['relay']} / 容量{factor_breakdown['capacity']} / "
            f"风险{factor_breakdown['risk']} / {score_band['label']}"
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
        if height_breakout_leader:
            tags.append(_tag("市场总龙头", "ladder-chip-strong red-text"))
            tags.append(_tag(f"突破{int(recent_height_cap)}板压制", "ladder-chip-strong red-text"))
            if plate_name:
                tags.append(_tag(f"带动{plate_name}", "ladder-chip-strong red-text"))
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

        core_bits: List[str] = []
        support_bits: List[str] = []
        risk_bits: List[str] = []

        def _push_reason(bucket: List[str], text: str) -> None:
            text = str(text or "").strip()
            if text and text not in core_bits and text not in support_bits and text not in risk_bits:
                bucket.append(text)

        theme_label = str(pred_theme or plate_name or hy or "").strip()
        follower_text = "、".join(followers[:2])
        if height_breakout_leader:
            _push_reason(core_bits, f"市场总龙头：突破近5日{int(recent_height_cap)}板压制")
            if plate_name:
                _push_reason(core_bits, f"带动{plate_name}板块")
        elif is_plate_leader and plate_name and plate_is_strong:
            _push_reason(core_bits, f"{plate_name}板块龙头")
        elif is_theme_leader and has_follow and theme_label:
            _push_reason(core_bits, f"{theme_label}龙头带动")
        elif leader_bonus >= 10:
            _push_reason(core_bits, "前排龙头梯队")
        elif leader_bonus > 0:
            _push_reason(core_bits, "核心梯队")

        if has_tier and has_follow:
            _push_reason(core_bits, f"梯队带动{follower_text}" if is_theme_leader and follower_text else "梯队带动" if is_theme_leader else "梯队跟随")
        elif has_tier:
            _push_reason(core_bits, "梯队完整")
        elif top_themes:
            _push_reason(core_bits, f"{'板块归属' if has_trade_theme else '属性标签'}：" + "、".join(str(x.get("name") or "") for x in top_themes[:2]))
        elif hy_score >= 60:
            _push_reason(core_bits, "行业内涨停集中")

        if has_trade_theme and theme_net >= 12:
            _push_reason(core_bits, "极强主线")
        elif has_trade_theme and theme_net >= 8:
            _push_reason(core_bits, "强主线")
        elif is_main:
            _push_reason(core_bits, "主线加成")
        if is_new_high and not height_breakout_leader:
            _push_reason(core_bits, f"突破新高({int(max_lbc)}板)")
        if theme_is_continuing:
            _push_reason(core_bits, "题材持续")
        if has_tier and has_follow and (has_spread or theme_net >= 10):
            _push_reason(core_bits, "题材联动")
        if height_repair:
            _push_reason(core_bits, "高度修复")

        if quality_label in {"封单充足", "加速确认"}:
            _push_reason(support_bits, quality_label)
        elif quality_label == "温和放量" or is_moderate_volume:
            _push_reason(support_bits, "温和放量")
        elif quality_label == "高换手承接":
            _push_reason(support_bits, "换手承接")
        elif quality_label in {"分歧烂板", "反复回封"}:
            _push_reason(support_bits, quality_label)
        if fund_yi >= fund_lo + (fund_hi - fund_lo) * 0.6:
            _push_reason(support_bits, "封单偏强")
        if open_cnt <= 1 and not is_yizi:
            _push_reason(support_bits, "封板稳")
        if time_score >= 70:
            _push_reason(support_bits, "早封")
        if cje_yi and cje_yi > 10:
            _push_reason(support_bits, "容量够")
        if zsz_yi and zsz_yi <= 150 and not core_bits:
            _push_reason(support_bits, "小市值")
        if warm_vol_theme_combo >= 16:
            _push_reason(support_bits, "量价共振")
        elif warm_vol_theme_combo >= 8:
            _push_reason(support_bits, "放量+板块")
        if promo_ecology >= 62:
            _push_reason(support_bits, f"晋级生态强({int(jj_rate)}%/{int(broken_lb_rate)}%)")

        if height_pressure:
            _push_reason(risk_bits, "高度压制")
        if theme_is_fading:
            _push_reason(risk_bits, "题材转弱")
        if individual_break_risk >= 68:
            _push_reason(risk_bits, "断板风险高")
        if promo_ecology <= 42:
            _push_reason(risk_bits, f"晋级生态弱({int(jj_rate)}%/{int(broken_lb_rate)}%)")
        if is_yizi:
            _push_reason(risk_bits, "一字板(参与难度大)")
        elif is_shrink_seal:
            _push_reason(risk_bits, "缩量封板(参与难度大)")
        if open_cnt >= 8:
            _push_reason(risk_bits, "强分歧(多开板)")
        elif open_cnt >= 3:
            _push_reason(risk_bits, "分歧偏大")
        if stage_type == "good" and lbc >= 5:
            _push_reason(risk_bits, "高位谨慎")

        reason_bits = [*core_bits[:4], *support_bits[:3], *risk_bits[:2]]

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
                "environmentScore": _round(env_score),
                "leaderFactorScore": _round(leader_factor_score),
                "relayFactorScore": _round(relay_factor_score),
                "capacityFactorScore": _round(capacity_score),
                "riskControlScore": _round(risk_control_score),
                "breakRisk": _round(individual_break_risk),
                "themePersistScore": _round(theme_persist_score),
                "isYizi": is_yizi,
                "isShrinkSeal": is_shrink_seal,
                "_leaderBonus": leader_bonus,
                "_isThemeLeader": is_theme_leader,
                "_isNewHigh": is_new_high,
                "_heightBreakoutLeader": height_breakout_leader,
                "_themeNet": theme_net,
                "_isMain": is_main,
                "_raw": _round(raw_score),
                "score": _round(raw_score),
                "factorScore": _round(raw_score),
                "factorBreakdown": factor_breakdown,
                "factorHint": factor_hint,
                "scoreBand": score_band["label"],
                "scoreBandTone": score_band["tone"],
                "scoreAction": score_band["action"],
                "marketGate": {
                    "score": market_gate.get("score"),
                    "label": market_gate.get("label"),
                    "action": market_gate.get("action"),
                },
                "sectorTrendScore": _round(sector_trend_score),
                "sectorRankScore": _round(sector_rank_context_score),
                "plateRank": plate_ctx.get("rank"),
                "plateName": plate_ctx.get("name"),
                "factorLabels": {
                    "environment": _factor_label(env_score),
                    "sector": _factor_label(sector_sentiment_score),
                    "leader": _factor_label(leader_factor_score),
                    "relay": _factor_label(relay_factor_score),
                    "capacity": _factor_label(capacity_score),
                    "risk": _factor_label(risk_control_score),
                },
                "tags": normalized_tags,
                "tagRows": _tag_rows(normalized_tags),
                "reason": f'<span class="reason-bits">{head}</span><div class="exp-wrap">{observe_point}</div>',
            }
        )

    ranked = sorted(scored, key=lambda r: (_to_num(r.get("_raw"), 0), _to_num(r.get("qualityScore"), 0), _to_num(r.get("fundYi"), 0), _to_num(r.get("lbc"), 0)), reverse=True)
    for idx, r in enumerate(ranked):
        r["factorRank"] = idx + 1

    def relay_sort(r: Dict[str, Any]) -> Tuple[float, float, float, float, float, float, float]:
        return (
            1.0 if r.get("_heightBreakoutLeader") else 0.0,
            _to_num(r.get("_raw"), 0),
            _to_num(r.get("leaderFactorScore"), 0),
            _to_num(r.get("relayFactorScore"), 0),
            _to_num(r.get("environmentScore"), 0),
            _to_num(r.get("capacityFactorScore"), 0),
            -_to_num(r.get("breakRisk"), 0),
        )

    def relay_height_breakout_ok(r: Dict[str, Any]) -> bool:
        return bool(
            r.get("_heightBreakoutLeader")
            and _to_num(r.get("lbc"), 0) >= 6
            and _to_num(r.get("_raw"), 0) >= 72
            and _to_num(r.get("leaderFactorScore"), 0) >= 76
            and _to_num(r.get("relayFactorScore"), 0) >= 70
            and _to_num(r.get("breakRisk"), 0) < 68
            and _to_num(r.get("stepContextScore"), 0) >= 70
            and _to_num(r.get("open"), 0) <= 2
        )

    def relay_core_ok(r: Dict[str, Any]) -> bool:
        return bool(
            r.get("hasTradeTheme")
            and not r.get("isYizi")
            and not r.get("isShrinkSeal")
            and 2 <= _to_num(r.get("lbc"), 0) <= 5
            and _to_num(r.get("_raw"), 0) >= 60
            and _to_num(r.get("open"), 0) < 8
            and _to_num(r.get("breakRisk"), 0) < 76
            and _to_num(r.get("stepContextScore"), 0) >= 38
        )

    def relay_one_to_two_ok(r: Dict[str, Any]) -> bool:
        return bool(
            r.get("hasTradeTheme")
            and not r.get("isYizi")
            and not r.get("isShrinkSeal")
            and _to_num(r.get("lbc"), 0) == 1
            and _to_num(r.get("open"), 0) < 3
            and _to_num(r.get("_raw"), 0) >= 72
            and _to_num(r.get("stepContextScore"), 0) >= 55
            and _to_num(r.get("breakRisk"), 0) < 68
        )

    def relay_relaxed_ok(r: Dict[str, Any]) -> bool:
        return bool(
            r.get("hasTradeTheme")
            and not r.get("isYizi")
            and not r.get("isShrinkSeal")
            and 2 <= _to_num(r.get("lbc"), 0) <= 4
            and _to_num(r.get("open"), 0) < 8
            and _to_num(r.get("stepContextScore"), 0) >= 50
            and _to_num(r.get("breakRisk"), 0) < 90
            and _to_num(r.get("leaderFactorScore"), 0) >= 58
            and _to_num((r.get("factorBreakdown") or {}).get("sector"), 0) >= 70
            and _to_num(r.get("capacityFactorScore"), 0) >= 55
        )

    def relay_broad_ok(r: Dict[str, Any]) -> bool:
        # 线上字段不完整时，避免接力池直接空白；但仍排除明显不可参与/高风险品种。
        return bool(
            not r.get("isYizi")
            and not r.get("isShrinkSeal")
            and 1 <= _to_num(r.get("lbc"), 0) <= 5
            and _to_num(r.get("open"), 0) < 12
            and _to_num(r.get("breakRisk"), 0) < 94
            and _to_num(r.get("_raw"), 0) >= 58
        )

    relay_diagnostics = {
        "scored": len(scored),
        "themeRows": sum(1 for r in scored if r.get("hasTradeTheme")),
        "heightBreakoutEligible": sum(1 for r in scored if relay_height_breakout_ok(r)),
        "coreEligible": sum(1 for r in scored if relay_core_ok(r)),
        "oneToTwoEligible": sum(1 for r in scored if relay_one_to_two_ok(r)),
        "relaxedEligible": sum(1 for r in scored if relay_relaxed_ok(r)),
        "broadEligible": sum(1 for r in scored if relay_broad_ok(r)),
        "riskBlocked": sum(1 for r in scored if _to_num(r.get("breakRisk"), 0) >= 76),
        "openBlocked": sum(1 for r in scored if _to_num(r.get("open"), 0) >= 8),
        "stepWeak": sum(1 for r in scored if _to_num(r.get("stepContextScore"), 0) < 38),
        "yiziBlocked": sum(1 for r in scored if r.get("isYizi")),
        "shrinkBlocked": sum(1 for r in scored if r.get("isShrinkSeal")),
    }

    relay_breakout = sorted(
        [r for r in scored if relay_height_breakout_ok(r)],
        key=relay_sort,
        reverse=True,
    )
    relay_core = sorted(
        [r for r in scored if relay_core_ok(r)],
        key=relay_sort,
        reverse=True,
    )
    relay_one_to_two = sorted(
        [r for r in scored if relay_one_to_two_ok(r)],
        key=relay_sort,
        reverse=True,
    )[:3]
    relay_pool: List[Dict[str, Any]] = []
    relay_seen: set[str] = set()
    for item in [*relay_breakout, *relay_core, *relay_one_to_two]:
        nm = str(item.get("name") or "")
        if nm in relay_seen:
            continue
        relay_seen.add(nm)
        relay_pool.append(item)
    relay = sorted(relay_pool, key=relay_sort, reverse=True)[:8]
    relay_selection_mode = "strict" if relay else "relaxed"
    if not relay:
        relay = sorted(
            [r for r in scored if relay_relaxed_ok(r)],
            key=relay_sort,
            reverse=True,
        )[:3]
    if not relay:
        relay_selection_mode = "broad"
        relay = sorted([r for r in scored if relay_broad_ok(r)], key=relay_sort, reverse=True)[:3]
    if not relay:
        relay_selection_mode = "none"
    for idx, r in enumerate(relay):
        r["relayRank"] = idx + 1
        r["relaySelectionMode"] = relay_selection_mode
        r["scoreLabel"] = "推荐因子"
        if r.get("_heightBreakoutLeader"):
            r["scoreSubLabel"] = f"市场总龙头 · {r.get('scoreBand')}"
        elif relay_selection_mode == "broad":
            r["scoreSubLabel"] = "兜底候选 · 仅超预期"
        else:
            gate_label = str(((r.get("marketGate") or {}).get("label") or "")).strip()
            r["scoreSubLabel"] = f"{gate_label} · {r.get('scoreBand')}" if gate_label and r.get("scoreBand") else str(r.get("scoreBand") or gate_label)
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
        capacity = _to_num(r.get("capacityFactorScore"), 0.0) * 0.88 + min(cje_yi, 90.0) * 0.24 + (18.0 if cje_yi >= cap_threshold else 0.0)
        divergence = min(open_cnt, 12.0) * 5.0 + max(0.0, _to_num(r.get("breakRisk"), 0.0) - 60.0) * 0.95
        height = lbc * 18.0 + _to_num(r.get("_leaderBonus"), 0.0) * 1.7 + _to_num(r.get("leaderFactorScore"), 0.0) * 0.48 + (12.0 if r.get("_isThemeLeader") else 0.0) + (8.0 if r.get("_isNewHigh") else 0.0)
        theme_gap = 0.0 if r.get("hasTradeTheme") else 22.0 if r.get("isBroadOnly") else 16.0
        theme_core = _to_num(r.get("_themeNet"), 0.0) * 1.8 + _to_num(r.get("sectorTrendScore"), 0.0) * 0.18 + _to_num(r.get("environmentScore"), 0.0) * 0.14
        weak_step = max(0.0, 48.0 - _to_num(r.get("stepContextScore"), 0.0)) * 0.45
        core = _to_num(r.get("_raw"), 0.0) * 0.26 + _to_num(r.get("leaderFactorScore"), 0.0) * 0.18 + _to_num(r.get("relayFactorScore"), 0.0) * 0.14 + _to_num(r.get("qualityScore"), 0.0) * 0.10
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
    for idx, r in enumerate(watch):
        r["watchRank"] = idx + 1
        r["watchGroup"] = watch_group(r)
        r["scoreLabel"] = "观察因子"
        gate_label = str(((r.get("marketGate") or {}).get("label") or "")).strip()
        r["scoreSubLabel"] = " · ".join([x for x in (r["watchGroup"], r.get("scoreBand") or gate_label) if x])

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
            "model": "zt_analysis_factor_v5",
            "relaySelectionMode": relay_selection_mode,
            "relayDiagnostics": relay_diagnostics,
            "marketGate": market_gate,
            "environment": {
                "score": _round(env_score),
                "label": market_gate.get("label"),
                "action": market_gate.get("action"),
                "components": {
                    "market": _round(market_sentiment_score),
                    "themeEnv": _round(theme_env_score),
                    "liquidity": _round(env_liquidity_score),
                    "ecology": _round(promo_ecology),
                    "height": _round(height_context_score),
                    "riskSafe": _round(100.0 - break_risk_base),
                },
            },
            "factorModel": {
                "order": ["environment", "sector", "leader", "relay", "capacity", "risk"],
                "weights": {
                    "environment": 0.16,
                    "sector": 0.22,
                    "leader": 0.21,
                    "relay": 0.17,
                    "capacity": 0.14,
                    "risk": 0.08,
                    "opportunity": 0.02,
                },
            },
            "promoEcology": _round(promo_ecology),
            "heightContext": "repair" if height_repair else "pressure" if height_pressure else "neutral",
            "breakRiskBase": _round(break_risk_base),
        },
        "relay": strip(relay[:8]),
        "watch": strip(watch[:8]),
    }
