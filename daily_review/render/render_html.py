#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模板渲染器（A方案的第一步）

职责：
1) 读取 HTML 模板文件（report_template.html）
2) 注入 marketData JSON（替换模板中的 /*__MARKET_DATA_JSON__*/ null）
3) 替换 __REPORT_DATE__ / __DATE_NOTE__ 等占位符

说明：
- 该脚本只负责「渲染」，不负责任何数据抓取与指标计算。
- 这样可以保证原始 HTML/CSS/JS 结构不变，只替换数据，从而 1:1 保持视觉效果。
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import os
import re
from pathlib import Path
from typing import Any, Dict


BJ_TZ = timezone(timedelta(hours=8))


def _now_bj_iso() -> str:
    """
    纯函数：返回北京时间的 ISO 字符串（YYYY-MM-DD HH:MM:SS）。

    用途：
    - 前端展示“数据更新时间”，让读者知道这份报告是何时渲染/更新的。
    """
    return datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _with_render_meta(market_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    纯函数：为 market_data 注入渲染元信息，不改变原对象。
    """
    md = dict(market_data or {})
    meta = md.get("meta") if isinstance(md.get("meta"), dict) else {}
    meta = dict(meta)
    meta.setdefault("rendered_at_bj", str(meta.get("generatedAt") or _now_bj_iso()))
    md["meta"] = meta
    return md


def _to_num(v: Any, d: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return d
        if isinstance(v, str):
            s = v.replace("%", "").replace("亿", "").strip()
            return float(s) if s else d
        n = float(v)
        return n if n == n else d
    except Exception:
        return d


def _clamp100(x: float) -> float:
    return max(0.0, min(100.0, float(x)))


def _delta_badge_html(v: Any, unit: str = "") -> str:
    if v is None or v == "":
        return ""
    try:
        n = float(v)
    except Exception:
        return ""
    if abs(n) < 1e-12:
        return ""
    sign = "+" if n > 0 else ""
    text = f"{sign}{n:.1f}{unit}" if unit == "pp" else f"{sign}{int(n) if float(n).is_integer() else n}{unit}"
    cls = "up" if n > 0 else "down"
    return f'<span class="delta-badge {cls}">Δ{text}</span>'


def _mood_index_series(mi: Dict[str, Any]) -> list[float]:
    days = mi.get("hist_days") if isinstance(mi.get("hist_days"), list) else []
    max_lb = [_to_num(v, 0) for v in (mi.get("hist_max_lb") if isinstance(mi.get("hist_max_lb"), list) else [])]
    fb = [_to_num(v, 0) for v in (mi.get("hist_fb_rate") if isinstance(mi.get("hist_fb_rate"), list) else [])]
    jj = [_to_num(v, 0) for v in (mi.get("hist_jj_rate") if isinstance(mi.get("hist_jj_rate"), list) else [])]
    n = min(len(days), len(max_lb), len(fb), len(jj))
    if n < 2:
        return []
    out: list[float] = []
    for i in range(n):
        h = _clamp100(max(0.0, min(10.0, max_lb[i])) / 10.0 * 100.0)
        out.append(round(max(0.0, min(100.0, 0.45 * fb[i] + 0.35 * jj[i] + 0.20 * h)), 2))
    return out


def build_heatmap(market_data: Dict[str, Any]) -> Dict[str, Any]:
    existing = market_data.get("heatmap")
    if isinstance(existing, dict) and isinstance(existing.get("cells"), list) and existing.get("cells"):
        return existing

    md = market_data or {}
    mi = ((md.get("features") or {}).get("mood_inputs") or {}) if isinstance(md.get("features"), dict) else {}
    pan = md.get("panorama") or {}
    fear = md.get("fear") or {}
    mood = md.get("mood") or {}

    fb = _to_num(mi.get("fb_rate"), _to_num(pan.get("ratio"), 0))
    jj = _to_num(mi.get("jj_rate_adj"), _to_num(mi.get("jj_rate"), 0))
    zb = _to_num(mi.get("zb_rate"), 0)
    dt = _to_num(pan.get("limitDown"), 0)
    bf = _to_num(mi.get("bf_count"), _to_num(fear.get("bigFace"), 0))
    ladder = md.get("ladder") if isinstance(md.get("ladder"), list) else []
    max_lb = _to_num(mi.get("max_lb"), _to_num((ladder[0] or {}).get("badge") if ladder else 0, 0))

    def cell(key: str, title: str, value: str, tag: str, note: str, level: int, sig_cls: str, sig_icon: str, sig_text: str, pulse: bool = False) -> Dict[str, Any]:
        return {
            "key": key,
            "title": title,
            "value": value,
            "tag": tag,
            "note": note,
            "level": level,
            "signalClass": sig_cls,
            "signalIcon": sig_icon,
            "signalText": sig_text,
            "pulse": pulse,
        }

    def signal_pos(x: float, hi: float, mid: float) -> tuple[str, str, str]:
        if x >= hi:
            return ("good", "🔥", "强")
        if x >= mid:
            return ("warn", "⚠", "一般")
        return ("bad", "🧊", "弱")

    def signal_neg(x: float, lo: float, mid: float, good_text: str = "低", warn_text: str = "中", bad_text: str = "高") -> tuple[str, str, str]:
        if x <= lo:
            return ("good", "🔥", good_text)
        if x <= mid:
            return ("warn", "⚠", warn_text)
        return ("bad", "🧊", bad_text)

    fb_sig = signal_pos(fb, 70, 55)
    jj_sig = signal_pos(jj, 30, 20)
    zb_sig = signal_neg(zb, 30, 45, "可控", "偏高", "高")
    dt_sig = signal_neg(dt, 5, 12)
    bf_sig = signal_neg(bf, 15, 30)
    h_sig = signal_pos(max_lb, 6, 4)

    t_fb = _to_num(mi.get("trend_fb_rate"), 0)
    t_jj = _to_num(mi.get("trend_jj_rate"), 0)
    t_hb = _to_num(mi.get("trend_max_lb"), 0)
    s = (1 if t_fb > 0 else 0) + (1 if t_jj > 0 else 0) + (1 if t_hb > 0 else 0) - (1 if t_fb < 0 else 0) - (1 if t_jj < 0 else 0) - (1 if t_hb < 0 else 0)
    trend = {"icon": "↑↑", "text": "升温"} if s >= 2 else ({"icon": "↓↓", "text": "降温"} if s <= -2 else {"icon": "→→", "text": "稳定"})
    score = int(round(_to_num(mood.get("score"), round(fb * 0.4 + jj * 0.35 + (100 - zb) * 0.15 + (100 - dt) * 0.10))))
    summary = f"封板{fb:.1f} / 晋级{jj:.1f} / 炸板{zb:.1f}；跌停{int(round(dt))}家"
    return {
        "score": score,
        "summary": summary,
        "trend": trend,
        "cells": [
            cell("fb_rate", "封板率", f"{fb:.1f}%", "关键", "封板质量决定次日承接空间", 5 if fb >= 75 else 4 if fb >= 60 else 3 if fb >= 45 else 2, *fb_sig, True),
            cell("jj_rate", "晋级率", f"{jj:.1f}%", "关键", "连板生存与高度延续的核心指标", 5 if jj >= 35 else 4 if jj >= 25 else 3 if jj >= 18 else 2, *jj_sig, True),
            cell("zb_rate", "炸板率", f"{zb:.1f}%", "分歧", "分歧强度（高→承接变差/回封难）", 4 if zb <= 25 else 3 if zb <= 40 else 2, *zb_sig),
            cell("dt", "跌停数", f"{int(round(dt))}家", "风险", "极端负反馈密度（低→可博弈修复）", 4 if dt <= 3 else 3 if dt <= 10 else 2, *dt_sig),
            cell("bf_count", "大面扩散", f"{int(round(bf))}只", "亏钱", "亏钱效应与情绪退潮信号", 4 if bf <= 10 else 3 if bf <= 25 else 2, *bf_sig),
            cell("max_lb", "高度", f"{int(round(max_lb))}板", "空间", "空间高度（配合断板/大面判断风险）", 5 if max_lb >= 7 else 4 if max_lb >= 5 else 3 if max_lb >= 3 else 2, *h_sig),
        ],
    }


def build_mood_tri_cards(market_data: Dict[str, Any]) -> list[Dict[str, Any]]:
    md = market_data or {}
    mi = ((md.get("features") or {}).get("mood_inputs") or {}) if isinstance(md.get("features"), dict) else {}
    pan = md.get("panorama") or {}
    mood = md.get("mood") or {}
    fear = md.get("fear") or {}
    delta = md.get("delta") or {}

    fb = _to_num(mi.get("fb_rate"), _to_num(pan.get("ratio"), 0))
    jj = _to_num(mi.get("jj_rate_adj"), _to_num(mi.get("jj_rate"), 0))
    risk = _to_num(mood.get("risk"), 0)
    heat = _to_num(mood.get("heat"), 0)
    score = mood.get("score")
    earn_value = f"{score} 分" if score not in (None, "") else f"{(0.55 * fb + 0.45 * jj):.0f} 分"
    risk_series = mi.get("hist_zt_dt_spread") if isinstance(mi.get("hist_zt_dt_spread"), list) else []
    cash_series = ((md.get("volume") or {}).get("values") or []) if isinstance((md.get("volume") or {}).get("values"), list) else []
    return [
        {
            "key": "earn",
            "cls": "earn",
            "title": "赚：承接强度",
            "value": earn_value,
            "valueClass": "red-text" if heat >= 70 else ("orange-text" if heat >= 50 else "blue-text"),
            "sub": "承接=封板质量 × 晋级延续 × 高度（更关注“结论”，原始率见引擎与K线）",
            "badges": "".join([x for x in [_delta_badge_html(delta.get("fb_rate"), "pp"), _delta_badge_html(delta.get("jj_rate"), "pp")] if x]),
            "spark": _mood_index_series(mi),
            "sparkStroke": "rgba(239,68,68,0.82)",
        },
        {
            "key": "risk",
            "cls": "risk",
            "title": "险：亏钱扩散",
            "value": str(int(round(risk))),
            "valueClass": "red-text" if risk >= 70 else ("orange-text" if risk >= 50 else "blue-text"),
            "sub": f"跌停 {pan.get('limitDown', '-')} · 大面 {fear.get('bigFace', '-')} · 风险越高越谨慎",
            "badges": "".join([x for x in [_delta_badge_html(delta.get('dt')), _delta_badge_html(delta.get('bf_count'))] if x]),
            "spark": risk_series,
            "sparkStroke": "rgba(16,185,129,0.82)",
        },
        {
            "key": "cash",
            "cls": "cash",
            "title": "资：量能回流",
            "value": f"{((md.get('volume') or {}).get('change') or '-')}",
            "valueClass": "red-text" if str(((md.get('volume') or {}).get('change') or '')).startswith('+') else ("green-text" if str(((md.get('volume') or {}).get('change') or '')).startswith('-') else ""),
            "sub": f"两市 {((md.get('volume') or {}).get('total') or '-')} · 增量 {((md.get('volume') or {}).get('increase') or '-')}",
            "badges": "",
            "spark": cash_series,
            "sparkStroke": "rgba(96,165,250,0.86)",
        },
    ]


def build_sentiment_explain_dims(market_data: Dict[str, Any]) -> list[Dict[str, Any]]:
    """
    情绪页解释维度（后端统一口径）：
    - 只输出客观维度与趋势
    - 前端不再做分位/趋势/文案推导
    """

    md = market_data or {}
    mi = ((md.get("features") or {}).get("mood_inputs") or {}) if isinstance(md.get("features"), dict) else {}
    pan = md.get("panorama") or {}
    prev = md.get("prev") or {}
    prev_pan = prev.get("panorama") or {}
    delta = md.get("delta") or {}
    mp = md.get("marketPanorama") or {}
    kpis = (mp.get("kpis") or {}) if isinstance(mp, dict) else {}

    def last_n(arr: Any, n: int = 7) -> list[float]:
        if not isinstance(arr, list):
            return []
        out: list[float] = []
        for x in arr[-n:]:
            n0 = _to_num(x, float("nan"))
            if n0 == n0:
                out.append(n0)
        return out

    def q(arr: list[float], p: float) -> float | None:
        if not arr:
            return None
        rows = sorted(arr)
        idx = max(0, min(len(rows) - 1, round((len(rows) - 1) * p)))
        return rows[idx]

    def level_by_hist(v: float, hist: list[float], *, reverse: bool = False, fallback_a: float = 0.0, fallback_b: float = 0.0) -> tuple[str, str]:
        a = q(hist, 0.33)
        b = q(hist, 0.66)
        aa = fallback_a if a is None else a
        bb = fallback_b if b is None else b
        if reverse:
            if v >= bb:
                return ("高位", "high")
            if v >= aa:
                return ("中位", "mid")
            return ("低位", "low")
        if v >= bb:
            return ("高位", "high")
        if v >= aa:
            return ("中位", "mid")
        return ("低位", "low")

    def fmt_trend(arr: list[float], *, unit: str = "") -> str:
        if not arr:
            return ""
        parts: list[str] = []
        for x in arr:
            if unit == "%":
                parts.append(f"{x:.1f}%")
            else:
                parts.append(str(int(round(x))) if float(x).is_integer() else f"{x:.1f}")
        return "-".join(parts)

    def delta_meta(v: float, prev_v: float, key: str, *, unit: str = "") -> tuple[str, str, Any]:
        d = _to_num(delta.get(key), v - prev_v)
        if abs(d) < 1e-9:
            return ("", "flat", "")
        abs_text = f"{abs(d):.1f}{unit}" if unit in {"%", "pp"} else (f"{abs(d):.1f}" if not float(abs(d)).is_integer() else f"{int(round(abs(d)))}")
        sign = "+" if d > 0 else "-"
        return (f"{'上升' if d > 0 else '下降'} {sign}{abs_text}", "up" if d > 0 else "down", d)

    zt = _to_num(pan.get("limitUp"), _to_num(mi.get("zt_count"), 0))
    zt_prev = _to_num(prev_pan.get("limitUp"), _to_num((((prev.get("features") or {}) if isinstance(prev.get("features"), dict) else {}).get("mood_inputs") or {}).get("zt_count"), 0))
    zt_hist = last_n(mi.get("hist_zt"))

    lb = _to_num(mi.get("lianban_count"), _to_num(kpis.get("link_board"), 0))
    lb_prev = _to_num((((prev.get("features") or {}) if isinstance(prev.get("features"), dict) else {}).get("mood_inputs") or {}).get("lianban_count"), lb)
    lb_hist = last_n(mi.get("hist_lianban"))

    max_lb = _to_num(mi.get("max_lb"), _to_num(kpis.get("max_lianban"), 0))
    max_lb_prev = _to_num((((prev.get("features") or {}) if isinstance(prev.get("features"), dict) else {}).get("mood_inputs") or {}).get("max_lb"), max_lb)
    max_lb_hist = last_n(mi.get("hist_max_lb"))

    dt = _to_num(pan.get("limitDown"), _to_num(mi.get("dt_count"), 0))
    dt_prev = _to_num(prev_pan.get("limitDown"), _to_num((((prev.get("features") or {}) if isinstance(prev.get("features"), dict) else {}).get("mood_inputs") or {}).get("dt_count"), dt))
    dt_hist = last_n(mi.get("hist_dt"))

    fb = _to_num(mi.get("fb_rate"), _to_num(pan.get("ratio"), 0))
    fb_prev = _to_num((((prev.get("features") or {}) if isinstance(prev.get("features"), dict) else {}).get("mood_inputs") or {}).get("fb_rate"), fb)
    fb_hist = last_n(mi.get("hist_fb_rate"))

    jj = _to_num(mi.get("jj_rate_adj", mi.get("jj_rate")), 0)
    jj_prev = _to_num((((prev.get("features") or {}) if isinstance(prev.get("features"), dict) else {}).get("mood_inputs") or {}).get("jj_rate_adj", (((prev.get("features") or {}) if isinstance(prev.get("features"), dict) else {}).get("mood_inputs") or {}).get("jj_rate")), jj)
    jj_hist = last_n(mi.get("hist_jj_rate"))

    specs = [
        ("max_lb", "空间高度", max_lb, max_lb_prev, max_lb_hist, False, 3.0, 5.0, "板", 10.0),
        ("zt", "涨停家数", zt, zt_prev, zt_hist, False, 50.0, 90.0, "", 120.0),
        ("dt", "跌停家数", dt, dt_prev, dt_hist, True, 3.0, 10.0, "", 30.0),
        ("jj_rate", "晋级率", jj, jj_prev, jj_hist, False, 18.0, 30.0, "%", 100.0),
        ("fb_rate", "封板率", fb, fb_prev, fb_hist, False, 55.0, 75.0, "%", 100.0),
        ("lianban", "连板家数", lb, lb_prev, lb_hist, False, 10.0, 20.0, "", 40.0),
    ]

    rows: list[Dict[str, Any]] = []
    for key, title, value, prev_v, hist, reverse, fallback_a, fallback_b, unit, cap in specs:
        level, level_cls = level_by_hist(value, hist, reverse=reverse, fallback_a=fallback_a, fallback_b=fallback_b)
        chg_unit = "pp" if unit == "%" else unit
        chg_str, chg_cls, _ = delta_meta(value, prev_v, key, unit=chg_unit)
        if unit == "%":
            value_text = f"{value:.1f}%"
        elif unit == "板":
            value_text = f"{int(round(value))}板"
        else:
            value_text = str(int(round(value))) if float(value).is_integer() else f"{value:.1f}"
        rows.append(
            {
                "key": key,
                "title": title,
                "value": value_text,
                "level": level,
                "levelCls": level_cls,
                "chgStr": chg_str,
                "chgCls": chg_cls,
                "bar": _clamp100((value / max(1.0, cap)) * 100.0),
                "kind": "risk" if reverse else "heat",
                "vs": f"近7日：{fmt_trend(hist, unit=unit)}" if hist else "",
                "trendHtml": "",
            }
        )
    return rows


def build_plate_rank_top10(market_data: Dict[str, Any]) -> list[Dict[str, Any]]:
    md = market_data or {}
    plate_rows = list(md.get("plateRotateTop") or [])
    if plate_rows:
        plate_rows.sort(key=lambda x: _to_num((x or {}).get("strength"), -1e9), reverse=True)
        max_strength = max([_to_num((x or {}).get("strength"), 0) for x in plate_rows] + [0])
        out = []
        for r in plate_rows[:10]:
            if not isinstance(r, dict):
                continue
            strength = _to_num(r.get("strength"), 0)
            item = dict(r)
            item["displayValue"] = str(int(round(strength))) if strength > 0 else "-"
            item["displayClass"] = "red-text"
            item["barPct"] = (strength / max_strength * 100) if max_strength > 0 else 0
            item["sourceNote"] = "" if (r.get("lead") or r.get("volume") is not None) else "｜当日板块强度"
            out.append(item)
        return out

    rows = list(md.get("conceptFundFlowTop") or [])
    rows.sort(key=lambda x: (_to_num((x or {}).get("chg_pct"), -1e9), _to_num((x or {}).get("net"), -1e9)), reverse=True)
    out = []
    for r in rows[:10]:
        if not isinstance(r, dict):
            continue
        chg = r.get("chg_pct")
        item = dict(r)
        item["displayValue"] = "-" if chg is None else f"{_to_num(chg, 0):+,.1f}%".replace(",", "")
        item["displayClass"] = "red-text" if _to_num(chg, 0) > 0 else ("green-text" if _to_num(chg, 0) < 0 else "")
        item["barPct"] = _to_num(chg, 0) * 10
        out.append(item)
    return out


def render_html_template(
    *,
    template_path: Path,
    output_path: Path,
    market_data: Dict[str, Any],
    report_date: str,
    date_note: str = "",
) -> None:
    tpl = template_path.read_text(encoding="utf-8")

    # 清理历史示例数据大注释块：仅用于开发回溯，保留在模板里会显著放大最终 HTML。
    tpl = re.sub(
        r"\n\s*// 核心数据对象\s*\n\s*/\*[\s\S]*?\n\s*// 默认值：模板单独打开时不展示任何“写死行情”",
        "\n      // 默认值：模板单独打开时不展示任何“写死行情”",
        tpl,
        count=1,
    )

    market_data = _with_render_meta(market_data)
    market_data_js = json.dumps(market_data, ensure_ascii=False)

    # 1) 注入 marketData
    tpl = tpl.replace("/*__MARKET_DATA_JSON__*/ null", market_data_js)

    # 2) 注入日期类占位符
    tpl = tpl.replace("__REPORT_DATE__", report_date)
    tpl = tpl.replace("__DATE_NOTE__", date_note or "")
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", report_date)
    report_date_cn = f"{m.group(1)}年{m.group(2)}月{m.group(3)}日" if m else report_date
    tpl = tpl.replace("__REPORT_DATE_CN__", report_date_cn)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(tpl, encoding="utf-8")


def build_action_guide_v2(market_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    明日计划（行动指南）算法：只基于已有 market_data 推导，不做任何外部请求。
    输出结构与前端 actionGuideV2 保持一致：{observe:[], do:[], avoid:[]}
    """

    def to_num(v: Any, d: float = 0.0) -> float:
        try:
            if v is None:
                return d
            if isinstance(v, str):
                v = v.replace("%", "").strip()
            n = float(v)
            return n
        except Exception:
            return d

    def tag(text: str, cls: str = "") -> Dict[str, str]:
        return {"text": text, "cls": cls}

    def pick_theme() -> Dict[str, Any]:
        """
        主线识别（复盘版）：
        - 优先基于 strengthRows 的「净强-风险」来选主线（更稳，减少「涨停数虚胖」）
        - examples 优先从当日涨停池里抽样，确保举例与主线一致（避免不精准）
        """
        tp = market_data.get("themePanels") or {}
        rows = (tp.get("strengthRows") or [])[:10]
        best = None
        best_score = -1e9
        for r in rows:
            net = to_num(r.get("net"), 0)
            risk = to_num(r.get("risk"), 0)
            # 经验权重：净强优先，风险惩罚；避免「高净强但风险爆表」的误判
            score = net - risk * 0.6
            if score > best_score:
                best_score = score
                best = r

        # 兜底：无 strengthRows 时回退到涨停Top
        if not best:
            t = ((tp.get("ztTop") or [])[:1] or [None])[0]
            if not t:
                return {"name": "主线", "count": 0, "examples": ""}
            return t

        name = str(best.get("name") or "主线")
        count = int(to_num(best.get("zt"), 0))

        # 从涨停池抽样 examples（依赖渲染器注入 ztgc + zt_code_themes）
        ztgc = market_data.get("ztgc") or []
        code2themes = market_data.get("zt_code_themes") or {}
        picks: list[tuple[float, str]] = []
        for s in ztgc:
            code = str(s.get("dm") or s.get("code") or "")
            mc = str(s.get("mc") or "")
            if not code or not mc:
                continue
            ths = code2themes.get(code) or []
            if name not in ths:
                continue
            lbc = to_num(s.get("lbc"), 1)
            zj = to_num(s.get("zj"), 0)
            zbc = to_num(s.get("zbc"), 0)
            score = lbc * 100 + zj / 1e8 * 10 - zbc * 2
            picks.append((score, mc))
        picks.sort(reverse=True)
        examples = "·".join([mc for _, mc in picks[:3]]) if picks else str(((tp.get("ztTop") or [{}])[0] or {}).get("examples") or "")
        return {"name": name, "count": count, "examples": examples}

    def pick_leader(*, prefer_theme: str) -> Dict[str, Any]:
        """
        龙头识别（复盘版）：
        - 先取最高板组
        - 同板高度下：优先主线题材命中，其次封单更大、开板更少
        """
        rows = market_data.get("ladder") or []
        max_b = 0
        for r in rows:
            max_b = max(max_b, int(to_num(r.get("badge"), 0)))
        top = [r for r in rows if int(to_num(r.get("badge"), 0)) == max_b]
        if not top:
            return {"maxB": max_b, "names": "龙头", "count": 0}

        code2themes = market_data.get("zt_code_themes") or {}

        def rank_key(r: Dict[str, Any]) -> float:
            code = str(r.get("code") or r.get("dm") or "")
            ths = code2themes.get(code) or []
            is_main = 1 if (prefer_theme and prefer_theme in ths) else 0
            zj = to_num(r.get("zj"), 0)
            zbc = to_num(r.get("zbc"), 0)
            # 主线命中优先；封单大更好；开板多惩罚
            return is_main * 1e6 + (zj / 1e8) * 1000 - zbc * 10

        top_sorted = sorted(top, key=rank_key, reverse=True)
        names = [str(r.get("name") or "") for r in top_sorted]
        names = [n for n in names if n]
        return {"maxB": max_b, "names": "、".join(names[:3]) if names else "龙头", "count": len(top_sorted)}

    def pick_theme_strength(name: str) -> Dict[str, Any]:
        rows = ((market_data.get("themePanels") or {}).get("strengthRows") or [])
        for r in rows:
            if str(r.get("name")) == str(name):
                return r
        return {}

    mi = ((market_data.get("features") or {}).get("mood_inputs") or {})
    delta = market_data.get("delta") or {}

    # 高位断板（断板最高板）——用于同步到「明日指南」
    top_duanban_name = str(mi.get("top_duanban_name") or "")
    top_duanban_lb = int(to_num(mi.get("top_duanban_lb"), 0) or 0)
    top_duanban_is_high = int(to_num(mi.get("top_duanban_is_high"), 0) or 0) == 1
    second_lb = int(to_num(mi.get("second_lb"), 0) or 0)

    mood_stage = (market_data.get("moodStage") or {})
    stage = mood_stage.get("title") or "-"
    stage_type = mood_stage.get("type") or "warn"
    stance_from_stage = str(mood_stage.get("stance") or "")
    mode_from_stage = str(mood_stage.get("mode") or "")
    theme = pick_theme()
    leader = pick_leader(prefer_theme=str(theme.get("name") or ""))
    theme_row = pick_theme_strength(str(theme.get("name") or ""))
    theme_net = to_num(theme_row.get("net"), 0)
    theme_risk = to_num(theme_row.get("risk"), 0)
    overlap = ((market_data.get("themePanels") or {}).get("overlap") or {})
    overlap_score = to_num(overlap.get("score"), 0)

    fb = to_num(mi.get("fb_rate"), to_num((market_data.get("panorama") or {}).get("ratio"), 0))
    jj = to_num(mi.get("jj_rate"), 0)
    zb = to_num(mi.get("zb_rate"), to_num((market_data.get("fear") or {}).get("broken"), 0))
    early = to_num(mi.get("zt_early_ratio"), 0)
    avg_zbc = to_num(mi.get("avg_zt_zbc"), 0)
    zbc_ge3_ratio = to_num(mi.get("zt_zbc_ge3_ratio"), 0)
    loss = to_num(mi.get("bf_count"), 0) + to_num(mi.get("dt_count"), 0)
    heat = to_num((market_data.get("mood") or {}).get("heat"), 0)
    risk = to_num((market_data.get("mood") or {}).get("risk"), 0)
    vol_chg = to_num(((market_data.get("volume") or {}).get("change")), 0)  # %

    def dtag(key: str, unit: str = "") -> Dict[str, str] | None:
        v = delta.get(key)
        if v is None:
            return None
        n = to_num(v, None)  # type: ignore[arg-type]
        if n is None:
            return None
        cls = "ladder-chip-strong red-text" if n > 0 else ("ladder-chip-cool blue-text" if n < 0 else "")
        sign = "+" if n > 0 else ""
        # pp（百分点）保留 1 位小数
        if unit == "pp":
            text = f"Δ{sign}{n:.1f}{unit}"
        else:
            text = f"Δ{sign}{int(n) if float(n).is_integer() else n}{unit}"
        return tag(text, cls)

    def delta_text(key: str, unit: str = "", digits: int = 0) -> str:
        """返回更语义化的增量文本，如：+2 / -3 / +1.2pp；缺失则返回空字符串"""
        v = delta.get(key)
        if v is None:
            return ""
        n = to_num(v, None)  # type: ignore[arg-type]
        if n is None:
            return ""
        sign = "+" if n > 0 else ""
        if unit == "pp":
            return f"{sign}{n:.1f}{unit}"
        if digits > 0:
            return f"{sign}{n:.{digits}f}{unit}"
        return f"{sign}{int(n) if float(n).is_integer() else n}{unit}"

    # 盘面基调（给行动指南一个「像复盘」的总起）
    if stage_type == "good":
        verdict_type = "good"
    elif stage_type == "fire":
        verdict_type = "fire"
    else:
        verdict_type = "warn"

    stance = "均衡"
    if heat >= 70 and risk <= 40 and fb >= 70:
        stance = "进攻"
    elif risk >= 60 or loss >= 10 or fb <= 55:
        stance = "防守"
    # 若 moodStage 已给出「周期建议立场」，优先用它（更贴近你的短线框架）
    if stance_from_stage:
        stance = stance_from_stage

    # 模式选择（4态）：接力 / 套利 / 低位试错 / 休息
    # 你的要求：默认偏「进攻」，只有出现明确的风险/失效信号才降级
    dzb = to_num(delta.get("zb_rate"), 0) if delta else 0
    dloss = to_num(delta.get("loss"), 0) if delta else 0
    risk_trend_up = (dzb >= 1.0) or (dloss >= 2)
    strong_divergence = (zbc_ge3_ratio >= 18) or (avg_zbc >= 1.8)

    mode = "接力"  # 默认进攻（旧逻辑）
    # 1) 先判「必须休息」的情形
    if stage_type == "fire" or stance == "防守" or overlap_score >= 75 or risk >= 70 or loss >= 15:
        mode = "休息"
    # 2) 再判「套利态」：强分歧或风险趋势上行，但还没到必须休息
    elif strong_divergence or risk_trend_up or theme_risk >= 6:
        mode = "套利"
    # 3) 最后判「低位试错」：主线净强不足/承接不足时，别硬接高位
    elif theme_net < 9 or fb < 55 or jj < 25:
        mode = "低位试错"

    # 周期模板模式（新逻辑）：让「阶段→策略」更直观
    def _short_mode(m: str) -> str:
        if not m:
            return ""
        if "休息" in m:
            return "休息"
        if "低位" in m:
            return "低位试错"
        if "兑现" in m:
            return "兑现"
        if "接力" in m:
            return "接力"
        return m

    mode_tpl = _short_mode(mode_from_stage)
    mode_show = mode_tpl or mode
    tag_stage = f"{stage}" if stage else "-"

    # === 纯数据驱动文案（避免固定话术堆料）===
    def bar(*parts: str) -> str:
        return "｜".join([p for p in parts if p])

    meta_title = f"🧩 盘面基调：{tag_stage}｜主线：{theme.get('name','主线')}｜模式：{mode_show}｜仓位：{stance}"

    # 盘面摘要：更语义化（减少“数字流水账”）
    # - 只表达方向与结论：回暖/收敛/扩散/缩量 等
    def _dir(x: float, *, up: str, down: str, flat: str = "持平", th: float = 0.8) -> str:
        if x >= th:
            return up
        if x <= -th:
            return down
        return flat

    dfb = to_num(delta.get("fb_rate"), 0) if delta else 0
    djj = to_num(delta.get("jj_rate"), 0) if delta else 0
    dzb2 = to_num(delta.get("zb_rate"), 0) if delta else 0
    dloss2 = to_num(delta.get("loss"), 0) if delta else 0

    carry_dir = "走强" if (dfb > 0.8 or djj > 0.8) else ("走弱" if (dfb < -0.8 or djj < -0.8) else "未确认")
    diverge_dir = _dir(dzb2, up="扩大", down="收敛", flat="未放大", th=0.8)
    loss_dir = "扩散" if (loss >= 12 or dloss2 >= 2) else ("收敛" if (loss <= 7 or dloss2 <= -2) else "中性")
    vol_dir = _dir(vol_chg, up="放量", down="缩量", flat="平量", th=1.0)

    # 一句话解读：承接/分歧/风险趋势（保持你的短线语言）
    take = []
    if fb >= 70 and jj >= 30:
        take.append("承接回暖")
    elif fb < 60 or jj < 25:
        take.append("承接偏弱")
    if zb >= 35 or zbc_ge3_ratio >= 18:
        take.append("分歧偏大")
    if loss >= 12 or risk >= 60:
        take.append("风险偏高")
    if not take:
        take.append("震荡中性")

    # 语义化摘要（不再堆“封/晋/早/炸/开/均开/扩散/量能/Δxx”这些数字流）
    summary_line = bar(
        f"承接{carry_dir}",
        f"分歧{diverge_dir}",
        f"亏钱{loss_dir}",
        f"量能{vol_dir}",
    )
    # 动作建议：更像复盘而不是数据播报
    action_hint = (
        "动作：优先主线核心/回封确认，避免追高一致；"
        "若扩散继续走高则降级为低位试错/休息。"
    )
    meta_detail = bar(summary_line, "解读：" + "、".join(take) + "。", action_hint)

    def desc_short(s: str, *, limit: int = 60) -> str:
        """
        行动指南压缩版描述：用于「单行展示」，避免占用过多高度。
        - 保留数字与关键字段
        - 去掉重复标签/括号注释
        """
        x = str(s or "").strip()
        if not x:
            return x
        # 去掉括号内补充说明（例如：拥挤(重叠) / 休息阈值）
        x = re.sub(r"（[^）]*）", "", x)
        x = x.replace("承接：", "").replace("分歧：", "")
        x = x.replace("拥挤(重叠)", "拥挤").replace("拥挤", "拥挤")
        x = x.replace("保留底线：", "").replace("保留底线", "")
        x = x.replace("封板", "封").replace("晋级", "晋").replace("早封", "早")
        x = x.replace("炸板", "炸").replace("均开板", "均开").replace("≥3开板", "≥3开")
        x = re.sub(r"\s+", " ", x).strip()
        if len(x) > limit:
            x = x[: limit - 1] + "…"
        return x

    main_name = str(theme.get("name") or "主线")
    main_examples = str(theme.get("examples") or "—")
    leader_name = str(leader.get("names") or "龙头")
    leader_b = leader.get("maxB") or "-"

    # 观察清单：你明确不需要（容易产生「滞后/空泛」观感），保持为空
    # 开盘2条：纯数据 + 阈值（不写「建议/观察/优先」这类空话）
    confirm = [
        {
            "dot": "dot-safe",
            "title": f"开盘① 定主线：{main_name}",
            "desc": bar(
                f"看点：主线是否继续承接（净强{theme_net:.1f}/风险{theme_risk:.1f}）",
                f"拥挤{overlap_score:.1f}%",
                f"动作：围绕主线辨识度做（非主线少碰）",
            ),
            "tags": [
                tag(f"样本{main_examples}", "ladder-chip-cool blue-text"),
            ],
        },
        {
            "dot": "dot-safe",
            "title": "开盘② 定节奏：承接 vs 分歧",
            "desc": bar(
                f"承接：封{fb:.1f}/晋{jj:.1f}/早{early:.1f}",
                f"分歧：炸{zb:.1f}/≥3开{zbc_ge3_ratio:.1f}/均开{avg_zbc:.2f}",
                "动作：承接强→接力/换手；分歧大→只做回封与低位确认",
            ),
            "tags": [
                *(x for x in [dtag("fb_rate", "pp"), dtag("jj_rate", "pp"), dtag("zb_rate", "pp")] if x),
            ],
        },
    ]

    # 盘中2条失效：同样纯数据/阈值表达
    retreat = [
        {
            "dot": "dot-risk",
            "title": "盯盘红灯① 亏钱线抬头",
            "desc": bar(
                f"亏钱扩散{int(loss)}（休息阈值≥15）",
                f"炸板{zb:.1f}%",
                (f"扩散Δ{delta_text('loss')}" if delta_text("loss") else ""),
            ),
            "tags": [
                tag(f"风险{int(risk)}", "ladder-chip-strong red-text" if risk >= 60 else "ladder-chip-cool blue-text"),
            ],
        },
        {
            "dot": "dot-risk",
            "title": "盯盘红灯② 主线断轴",
            "desc": bar(
                f"龙头{leader_name}({leader_b}板)",
                f"主线{main_name}（净强{theme_net:.1f}/风险{theme_risk:.1f}）",
                f"拥挤(重叠){overlap_score:.1f}%",
            ),
            "tags": [
                tag(f"≥3开板{zbc_ge3_ratio:.1f}%", "ladder-chip-warn orange-text" if zbc_ge3_ratio >= 18 else "ladder-chip-cool blue-text"),
            ],
        },
    ]

    # 若出现「高位断板」，把它作为明日盯盘重点：观察断板龙头的反馈是否压制次高板/梯队
    if top_duanban_is_high and top_duanban_name and top_duanban_lb >= 6:
        retreat[1]["title"] = "盯盘红灯② 高位断板反馈"
        retreat[1]["desc"] = bar(
            f"断板最高：{top_duanban_name}({top_duanban_lb}板)",
            f"次高板：{second_lb}板（易受反馈影响）" if second_lb else "次高板：—",
            "看点：反抽无力/继续走弱 → 次高板更难晋级；强修复回封 → 梯队回暖",
        )
        retreat[1]["tags"] = [tag("先看反馈", "ladder-chip-warn orange-text")]

    # 给前端一个「单行展示」的压缩字段（保留完整 desc 供 hover/展开）
    for it in (confirm + retreat):
        try:
            it["descShort"] = desc_short(str(it.get("desc") or ""))
        except Exception:
            it["descShort"] = str(it.get("desc") or "")

    return {
        "meta": {"title": meta_title, "detail": meta_detail, "type": verdict_type},
        "confirm": confirm,
        "retreat": retreat,
    }


def build_summary3(*, market_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    全站两句话（复盘口径统一）：
    1) 今日情绪温度摘要（完全基于“情绪温度/特征数据”，不拼主观策略文案）
    2) 主线与空间锚（题材/最高板）
    """

    def _num(x, d=0.0) -> float:
        try:
            if x is None:
                return float(d)
            if isinstance(x, str):
                x = x.replace("%", "").replace("板", "").strip()
            return float(x)
        except Exception:
            return float(d)

    stage = (market_data.get("moodStage") or {}).get("title") or "-"
    feats = market_data.get("features") or {}
    mi = (feats.get("mood_inputs") or {}) if isinstance(feats, dict) else {}
    pano = market_data.get("panorama") or {}
    mp = market_data.get("marketPanorama") or {}
    kpis = (mp.get("kpis") or {}) if isinstance(mp, dict) else {}

    # 口径：优先 mood_inputs（离线统一口径），其次 panorama/kpis 兜底
    zt = int(_num(mi.get("zt_count"), _num(pano.get("limitUp"), 0)))
    dt = int(_num(mi.get("dt_count"), _num(pano.get("limitDown"), 0)))
    fb = _num(mi.get("fb_rate"), 0.0)
    jj = _num(mi.get("jj_rate_adj", mi.get("jj_rate")), 0.0)
    max_lb = int(_num(mi.get("max_lb"), _num(mi.get("max_lianban"), _num(kpis.get("max_lianban"), 0))))

    # 历史窗口（用于趋势与分位评级）
    W = 7

    def _tail(arr: Any) -> list[float]:
        if not isinstance(arr, list):
            return []
        out: list[float] = []
        for x in arr[-W:]:
            try:
                out.append(float(str(x).replace("%", "").replace("板", "").strip()))
            except Exception:
                continue
        return out

    def _q(arr: list[float], p: float) -> float | None:
        a = [x for x in arr if isinstance(x, (int, float))]
        a = sorted(a)
        if not a:
            return None
        idx = int(round((len(a) - 1) * p))
        idx = max(0, min(len(a) - 1, idx))
        return a[idx]

    def _lvl_by_hist(v: float, hist: list[float], *, fallback_a: float, fallback_b: float, reverse: bool = False) -> str:
        q33 = _q(hist, 0.33)
        q66 = _q(hist, 0.66)
        a = q33 if q33 is not None else fallback_a
        b = q66 if q66 is not None else fallback_b
        if reverse:
            # 值越大越差（风险）
            if v >= b:
                return "偏高"
            if v >= a:
                return "中位"
            return "偏低"
        # 值越大越好（热度/承接）
        if v >= b:
            return "偏强"
        if v >= a:
            return "中位"
        return "偏弱"

    def _trend_word(hist: list[float], *, reverse: bool = False) -> str:
        """
        reverse=False：值越大越强（涨停/封板率/晋级率/连板/高度）→ 走强/走弱
        reverse=True ：值越大越差（跌停等亏钱指标）→ 扩散/收敛
        """
        if len(hist) < 2:
            return "无趋势"
        d = hist[-1] - hist[0]
        if abs(d) < 1e-6:
            return "走平"
        if reverse:
            return "扩散" if d > 0 else "收敛"
        return "走强" if d > 0 else "走弱"

    # 近7日趋势（用于摘要与动作建议）
    zt_hist = _tail(mi.get("hist_zt"))
    dt_hist = _tail(mi.get("hist_dt"))
    fb_hist = _tail(mi.get("hist_fb_rate"))
    jj_hist = _tail(mi.get("hist_jj_rate"))
    maxlb_hist = _tail(mi.get("hist_max_lb"))

    zt_lvl = _lvl_by_hist(float(zt), zt_hist, fallback_a=50, fallback_b=90, reverse=False)
    dt_lvl = _lvl_by_hist(float(dt), dt_hist, fallback_a=3, fallback_b=6, reverse=True)
    fb_lvl = _lvl_by_hist(float(fb), fb_hist, fallback_a=70, fallback_b=80, reverse=False)
    jj_lvl = _lvl_by_hist(float(jj), jj_hist, fallback_a=20, fallback_b=35, reverse=False)
    maxlb_lvl = _lvl_by_hist(float(max_lb), maxlb_hist, fallback_a=3, fallback_b=5, reverse=False)
    # 简单“温度/风险”合成逻辑（算法输出：仅依赖数据分位与趋势）
    heat_up = (zt_lvl in ("偏强", "中位")) and (fb_lvl in ("偏强", "中位"))
    risk_up = (dt_lvl == "偏高") or (jj_lvl == "偏弱")

    if heat_up and not risk_up:
        tone = "情绪回暖，承接占优"
    elif heat_up and risk_up:
        tone = "情绪修复中，风险未完全收敛"
    else:
        tone = "情绪偏谨慎，先看承接修复"

    # 操作指南（只用客观触发）
    if dt_lvl == "偏高":
        action = "动作：先降速降仓，优先低位试错/等待回封确认，避免高位一致。"
    elif jj_lvl == "偏弱":
        action = "动作：承接未强，主线只做最强辨识度的分歧回封，少做接力。"
    elif fb_lvl == "偏强" and zt_lvl == "偏强":
        action = "动作：承接偏强，可聚焦主线核心的回封/换手确认，避免追高一致。"
    else:
        action = "动作：以主线核心为主，等待确认信号后再加速。"

    # 输出“总结”而不是“报数”：基于维度趋势/分位 → 归纳情绪温度 & 注意事项 & 操作指南
    heat_tr = _trend_word(zt_hist)  # 走强/走弱/走平
    risk_tr = _trend_word(dt_hist, reverse=True)  # 扩散/收敛/走平
    carry_tr = _trend_word(fb_hist)  # 走强/走弱/走平
    relay_tr = _trend_word(jj_hist)  # 走强/走弱/走平
    space_tr = _trend_word(maxlb_hist)  # 走强/走弱/走平

    # 结构化归因（仍然只依赖算法数据）
    notes: list[str] = []
    # 赚钱效应/情绪热度
    if heat_tr == "走强" and zt_lvl in ("偏强", "中位"):
        notes.append("赚钱效应回暖")
    elif heat_tr == "走弱" or zt_lvl == "偏弱":
        notes.append("赚钱效应偏弱")
    else:
        notes.append("赚钱效应中性")

    # 亏钱效应（风险）
    if risk_tr == "扩散" or dt_lvl == "偏高":
        notes.append("亏钱效应仍在扩散")
    elif risk_tr == "收敛" and dt_lvl in ("偏低", "中位"):
        notes.append("亏钱效应收敛")
    else:
        notes.append("风险处于可控区间")

    # 承接/接力延续性（封板率 + 晋级率）
    if fb_lvl == "偏强" and carry_tr in ("走强", "走平") and jj_lvl != "偏弱":
        notes.append("承接偏强，接力可尝试")
    elif jj_lvl == "偏弱" or relay_tr == "走弱":
        notes.append("接力延续性不足")
    else:
        notes.append("承接中性，择强参与")

    # 空间（高度/连板结构）
    if maxlb_lvl == "偏强" and space_tr in ("走强", "走平"):
        notes.append("空间维持")
    elif space_tr == "走弱":
        notes.append("空间走弱，谨慎高位")

    line1 = f"今日：{stage}，{tone}。{ '；'.join(notes) }。{action}"

    # 主线与龙头（保持客观输出：题材 + 最高板）
    main = (market_data.get("themePanels") or {}).get("ztTop") or []
    main_name = (main[0].get("name") if main else "") or "主线"
    leader = "龙头"
    ladder = market_data.get("ladder") or []
    if ladder:
        maxb = max(int(_num(r.get("badge", 0), 0)) for r in ladder)
        tops = [r for r in ladder if int(_num(r.get("badge", 0), 0)) == maxb]
        def _clean_name(s: str) -> str:
            s = (s or "").strip()
            # 避免重复冠冕符号：上游可能已带 👑
            s = s.replace("👑", "").strip()
            return s

        names = [_clean_name(str(r.get("name") or "")) for r in tops[:2]]
        names = [n for n in names if n]
        if names:
            leader = "、".join(names)
        leader = f"👑 {leader}（{maxb}板）"
    line2 = f"主线：{main_name}；空间锚：{leader}。"

    return {"lines": [line1, line2]}


def build_market_overview_7d(*, market_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    市场全景 · 7日对比
    - 合并量能 / 全景核心KPI
    - 提供近7日极值与当前相对位置，供前端统一展示
    """

    def _num(x, d=0.0) -> float:
        try:
            if x is None:
                return float(d)
            if isinstance(x, str):
                x = x.replace("%", "").replace("板", "").replace("亿", "").strip()
            return float(x)
        except Exception:
            return float(d)

    def _tail(arr: Any, n: int = 7) -> list[float]:
        if not isinstance(arr, list):
            return []
        out: list[float] = []
        for x in arr[-n:]:
            try:
                out.append(float(str(x).replace("%", "").replace("板", "").replace("亿", "").strip()))
            except Exception:
                continue
        return out

    def _fmt_num(v: float, kind: str) -> str:
        if kind == "pct":
            return f"{v:.1f}%"
        if kind == "board":
            return f"{int(round(v))}板"
        if kind == "yi":
            return f"{v:.2f}亿"
        return f"{int(round(v))}"

    def _series_meta(*, key: str, label: str, values: list[float], dates: list[str], kind: str) -> dict[str, Any]:
        if not values:
            return {"key": key, "label": label, "current": "-", "max": "-", "min": "-", "note": "无数据"}
        curr = float(values[-1])
        max_v = max(values)
        min_v = min(values)
        max_idx = max(range(len(values)), key=lambda i: values[i])
        min_idx = min(range(len(values)), key=lambda i: values[i])
        rank = sorted(values, reverse=True).index(curr) + 1 if values.count(curr) == 1 else None
        note = []
        if curr == max_v:
            note.append("当前就是7日最高")
        elif curr == min_v:
            note.append("当前就是7日最低")
        else:
            note.append(f"7日最高 {_fmt_num(max_v, kind)}")
        note.append(f"高点日 {dates[max_idx] if max_idx < len(dates) else '-'}")
        if rank is not None:
            note.append(f"排序第{rank}/{len(values)}")
        return {
            "key": key,
            "label": label,
            "current": _fmt_num(curr, kind),
            "max": _fmt_num(max_v, kind),
            "min": _fmt_num(min_v, kind),
            "maxDate": dates[max_idx] if max_idx < len(dates) else "-",
            "minDate": dates[min_idx] if min_idx < len(dates) else "-",
            "note": "｜".join(note),
            "currentValue": curr,
            "maxValue": max_v,
            "minValue": min_v,
            "kind": kind,
        }

    feats = market_data.get("features") or {}
    mi = (feats.get("mood_inputs") or {}) if isinstance(feats, dict) else {}
    volume = market_data.get("volume") or {}
    volume_dates = list(volume.get("dates") or []) if isinstance(volume, dict) else []
    volume_values = [float(x) for x in (volume.get("values") or [])] if isinstance(volume, dict) and isinstance(volume.get("values"), list) else []

    hist_days = list(mi.get("hist_days") or []) if isinstance(mi.get("hist_days"), list) else []
    dates7 = [(d[5:] if len(str(d)) >= 10 else str(d)) for d in hist_days[-7:]]
    if not dates7:
        dates7 = volume_dates[-7:]

    zt_hist = _tail(mi.get("hist_zt"), 7)
    dt_hist = _tail(mi.get("hist_dt"), 7)
    fb_hist = _tail(mi.get("hist_fb_rate"), 7)
    maxlb_hist = _tail(mi.get("hist_max_lb"), 7)
    lb_hist = _tail(mi.get("hist_lianban"), 7)
    broken_hist = _tail(mi.get("hist_broken_lb_rate"), 7)
    zb_hist = [round(max(0.0, 100.0 - x), 1) for x in fb_hist] if fb_hist else []

    # 日期长度对齐
    n = max(len(zt_hist), len(dt_hist), len(zb_hist), len(maxlb_hist), len(volume_values), len(lb_hist), len(broken_hist))
    if len(dates7) < n:
        if volume_dates and len(volume_dates) >= n:
            dates7 = volume_dates[-n:]
        else:
            dates7 = dates7 + ["-"] * (n - len(dates7))
    elif len(dates7) > n and n > 0:
        dates7 = dates7[-n:]

    series = []
    series.append(_series_meta(key="volume", label="两市成交", values=volume_values[-7:], dates=volume_dates[-7:] if volume_dates else dates7, kind="yi"))
    series.append(_series_meta(key="zt", label="涨停家数", values=zt_hist, dates=dates7, kind="count"))
    series.append(_series_meta(key="zb_rate", label="炸板率", values=zb_hist, dates=dates7, kind="pct"))
    series.append(_series_meta(key="dt", label="跌停家数", values=dt_hist, dates=dates7, kind="count"))
    series.append(_series_meta(key="max_lb", label="最高高度", values=maxlb_hist, dates=dates7, kind="board"))
    series.append(_series_meta(key="link_board", label="连板家数", values=lb_hist, dates=dates7, kind="count"))
    series.append(_series_meta(key="broken_lb_rate", label="断板率", values=broken_hist, dates=dates7, kind="pct"))
    series = [s for s in series if s.get("current") != "-"]

    def _find(key: str) -> dict[str, Any]:
        for s in series:
            if s.get("key") == key:
                return s
        return {}

    zt_meta = _find("zt")
    zb_meta = _find("zb_rate")
    high_meta = _find("max_lb")
    vol_meta = _find("volume")

    highlights: list[str] = []
    if zt_meta:
        highlights.append(f"7日最高涨停家数 {zt_meta.get('max')}（{zt_meta.get('maxDate', '-')}）")
    if zb_meta:
        highlights.append(f"7日最高炸板率 {zb_meta.get('max')}（{zb_meta.get('maxDate', '-')}）")
    if high_meta:
        highlights.append(f"7日最高高度 {high_meta.get('max')}（{high_meta.get('maxDate', '-')}）")
    if vol_meta:
        highlights.append(f"7日最高成交额 {vol_meta.get('max')}（{vol_meta.get('maxDate', '-')}）")

    return {
        "window": 7,
        "dates": dates7,
        "series": series,
        "highlights": highlights[:4],
    }


def build_action_advisor(*, market_data: Dict[str, Any]) -> Dict[str, Any]:
    # 逻辑已抽离到独立模块，便于集中维护
    from daily_review.metrics.action_advisor import build_action_advisor as _impl

    return _impl(market_data=market_data)

def build_learning_notes(*, market_data: Dict[str, Any], cache_dir: Path) -> Dict[str, Any]:
    from daily_review.learning.notes_loader import build_learning_notes as _impl

    return _impl(market_data=market_data, cache_dir=cache_dir)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True, help="HTML 模板路径")
    ap.add_argument("--market-data-json", required=True, help="marketData 的 JSON 文件路径")
    ap.add_argument("--out", required=True, help="输出 HTML 路径")
    ap.add_argument("--date", required=True, help="报告日期 YYYY-MM-DD")
    ap.add_argument("--note", default="", help="日期备注（非交易日回退提示等）")
    args = ap.parse_args()

    template_path = Path(args.template)
    market_json_path = Path(args.market_data_json)
    output_path = Path(args.out)

    market_data = json.loads(market_json_path.read_text(encoding="utf-8"))

    # 离线增强：补齐「情绪周期趋势（近5/7日）」数据
    # 说明：
    # - 新版 gen_report_v4 会写入 features.mood_inputs.hist_* 与 trend_*
    # - 但如果你只离线 render（且缓存来自旧版本），这里会自动用本地 cache/market_data-*.json 补齐
    try:
        features = market_data.setdefault("features", {})
        mood_inputs = features.setdefault("mood_inputs", {})

        hist_days = mood_inputs.get("hist_days")
        if not (isinstance(hist_days, list) and len(hist_days) >= 2):
            # 历史窗口：默认 5 天，可用环境变量覆盖（和 gen_report_v4 对齐）
            try:
                hist_n = int(os.getenv("MOOD_HIST_DAYS", "5") or "5")
            except Exception:
                hist_n = 5
            hist_n = max(3, min(hist_n, 10))

            cache_dir = market_json_path.parent
            items = []
            for fp in cache_dir.glob("market_data-*.json"):
                m = re.search(r"market_data-(\d{8})$", fp.stem)
                if not m:
                    continue
                d8 = m.group(1)
                d10 = f"{d8[0:4]}-{d8[4:6]}-{d8[6:8]}"
                if d10 <= args.date:
                    items.append((d10, fp))
            items.sort(key=lambda x: x[0])
            items = items[-hist_n:]

            rows = []
            for d10, fp in items:
                try:
                    snap = json.loads(fp.read_text(encoding="utf-8"))
                    fin = snap.get("features") or {}
                    mi = fin.get("mood_inputs") or {}
                    si = fin.get("style_inputs") or {}
                    rows.append(
                        {
                            "date": str(snap.get("date") or d10),
                            "max_lb": int(si.get("max_lb", 0) or 0),
                            "fb_rate": float(mi.get("fb_rate", 0) or 0),
                            "jj_rate": float(mi.get("jj_rate_adj", mi.get("jj_rate", 0)) or 0),
                            "broken_lb_rate": float(mi.get("broken_lb_rate_adj", mi.get("broken_lb_rate", 0)) or 0),
                            "zb_rate": float(mi.get("zb_rate", 0) or 0),
                            "zt_early_ratio": float(mi.get("zt_early_ratio", 0) or 0),
                            "loss": float(mi.get("loss", (float(mi.get("bf_count", 0) or 0) + float(mi.get("dt_count", 0) or 0))) or 0),
                        }
                    )
                except Exception:
                    continue

            if len(rows) >= 2:
                first, last = rows[0], rows[-1]
                mood_inputs["hist_days"] = [r["date"] for r in rows]
                mood_inputs["hist_max_lb"] = [r["max_lb"] for r in rows]
                mood_inputs["hist_fb_rate"] = [round(r["fb_rate"], 1) for r in rows]
                mood_inputs["hist_jj_rate"] = [round(r["jj_rate"], 1) for r in rows]
                mood_inputs["hist_broken_lb_rate"] = [round(r["broken_lb_rate"], 1) for r in rows]
                mood_inputs["hist_zb_rate"] = [round(r["zb_rate"], 1) for r in rows]
                mood_inputs["hist_zt_early_ratio"] = [round(r["zt_early_ratio"], 1) for r in rows]
                mood_inputs["hist_loss"] = [round(r["loss"], 1) for r in rows]
                mood_inputs["trend_max_lb"] = round(float(last["max_lb"]) - float(first["max_lb"]), 2)
                mood_inputs["trend_fb_rate"] = round(float(last["fb_rate"]) - float(first["fb_rate"]), 2)
                mood_inputs["trend_jj_rate"] = round(float(last["jj_rate"]) - float(first["jj_rate"]), 2)
                mood_inputs["trend_broken_lb_rate"] = round(float(last["broken_lb_rate"]) - float(first["broken_lb_rate"]), 2)
                mood_inputs["trend_zb_rate"] = round(float(last["zb_rate"]) - float(first["zb_rate"]), 2)
                mood_inputs["trend_zt_early_ratio"] = round(float(last["zt_early_ratio"]) - float(first["zt_early_ratio"]), 2)
                mood_inputs["trend_loss"] = round(float(last["loss"]) - float(first["loss"]), 2)
    except Exception:
        pass

    # 离线增强：把 pools_cache.json 中的当日涨停池注入到 market_data，供 HTML 做「涨停个股分析」
    # 注意：此处不做任何网络请求，只读取本地缓存文件
    try:
        pools_cache_path = market_json_path.parent / "pools_cache.json"
        if pools_cache_path.exists():
            pools_cache = json.loads(pools_cache_path.read_text(encoding="utf-8"))
            ztgc = (((pools_cache.get("pools") or {}).get("ztgc") or {}).get(args.date)) or []
            # 为避免与其他字段冲突，使用 ztgc 作为当日涨停池明细
            market_data["ztgc"] = ztgc
            # 同步注入题材映射（theme_cache.json）：为涨停个股分析提供「更细粒度题材」
            theme_cache_path = market_json_path.parent / "theme_cache.json"
            if theme_cache_path.exists():
                theme_cache = json.loads(theme_cache_path.read_text(encoding="utf-8"))
                code2themes = theme_cache.get("codes") or {}
                # 只注入当日涨停池涉及的代码，避免把整个题材库塞进 HTML
                zt_code_themes = {}
                for s in ztgc:
                    code = str(s.get("dm") or s.get("code") or "")
                    if code and code in code2themes:
                        zt_code_themes[code] = code2themes.get(code) or []
                market_data["zt_code_themes"] = zt_code_themes
    except Exception:
        # 缓存缺失或格式异常时忽略，不影响主页面渲染
        pass

    # 离线增强：用 Python 算法生成「明日计划」（避免前端出现「写死文案」的错觉）
    try:
        market_data.setdefault("actionGuideV2", build_action_guide_v2(market_data))
    except Exception:
        market_data.setdefault("actionGuideV2", {"observe": [], "do": [], "avoid": []})

    # 离线增强：龙头识别（如果 marketData 中还没有 leaders，则补齐）
    try:
        if not market_data.get("leaders"):
            from daily_review.modules.leader import rebuild_leaders

            market_data.update(rebuild_leaders(market_data))
    except Exception:
        market_data.setdefault("leaders", [])

    # 离线增强：全站三句话（口径统一）
    try:
        market_data.setdefault("summary3", build_summary3(market_data=market_data))
    except Exception:
        market_data.setdefault("summary3", {"lines": []})

    # 离线增强：市场全景 · 7日对比（量能 / 涨停 / 炸板 / 高度统一看）
    try:
        market_data.setdefault("marketOverview7d", build_market_overview_7d(market_data=market_data))
    except Exception:
        market_data.setdefault("marketOverview7d", {"window": 7, "dates": [], "series": [], "highlights": []})

    # 前四个 tab：统一下沉到后端，前端尽量只展示
    try:
        market_data.setdefault("heatmap", build_heatmap(market_data))
    except Exception:
        market_data.setdefault("heatmap", {"score": "-", "summary": "", "trend": {"icon": "→→", "text": "稳定"}, "cells": []})

    try:
        if not market_data.get("hm2Compare"):
            from daily_review.metrics.mood_signals import build_hm2_compare

            market_data["hm2Compare"] = build_hm2_compare(market_data)
    except Exception:
        market_data.setdefault("hm2Compare", {"score": 0, "hint": "", "pointerLeft": "0%", "cells": []})

    try:
        if not market_data.get("sectorHeatmap"):
            from daily_review.metrics.sector_heatmap import build_sector_heatmap

            market_data["sectorHeatmap"] = build_sector_heatmap(market_data)
    except Exception:
        market_data.setdefault("sectorHeatmap", {"globalScore": 0, "rows": [], "alpha": "", "hint": ""})

    try:
        market_data.setdefault("moodTriCards", build_mood_tri_cards(market_data))
    except Exception:
        market_data.setdefault("moodTriCards", [])

    try:
        market_data.setdefault("sentimentExplainDims", build_sentiment_explain_dims(market_data))
    except Exception:
        market_data.setdefault("sentimentExplainDims", [])

    try:
        market_data.setdefault("plateRankTop10", build_plate_rank_top10(market_data))
    except Exception:
        market_data.setdefault("plateRankTop10", [])

    # 离线增强：学习短线提醒 + 语录（随情绪阶段动态切换）
    try:
        ln = market_data.get("learningNotes") or {}
        if not ln.get("tips"):
            market_data["learningNotes"] = build_learning_notes(market_data=market_data, cache_dir=market_json_path.parent)
    except Exception:
        market_data.setdefault("learningNotes", {"tips": [], "quotes": []})

    render_html_template(
        template_path=template_path,
        output_path=output_path,
        market_data=market_data,
        report_date=args.date,
        date_note=args.note,
    )
