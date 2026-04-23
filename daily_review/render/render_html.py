#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模板渲染器（A方案的第一步）

职责：
1) 读取 HTML 模板文件（report_template.html）
2) 注入 marketData JSON（替换模板中的 /*__MARKET_DATA_JSON__*/ null）
3) 替换 __REPORT_DATE__ / __DATE_NOTE__ 等占位符

说明：
- 该脚本只负责“渲染”，不负责任何数据抓取与指标计算。
- 这样可以保证原始 HTML/CSS/JS 结构不变，只替换数据，从而 1:1 保持视觉效果。
"""

from __future__ import annotations

import json
import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict


def render_html_template(
    *,
    template_path: Path,
    output_path: Path,
    market_data: Dict[str, Any],
    report_date: str,
    date_note: str = "",
) -> None:
    tpl = template_path.read_text(encoding="utf-8")

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
        - 优先基于 strengthRows 的“净强-风险”来选主线（更稳，减少“涨停数虚胖”）
        - examples 优先从当日涨停池里抽样，确保举例与主线一致（避免不精准）
        """
        tp = market_data.get("themePanels") or {}
        rows = (tp.get("strengthRows") or [])[:10]
        best = None
        best_score = -1e9
        for r in rows:
            net = to_num(r.get("net"), 0)
            risk = to_num(r.get("risk"), 0)
            # 经验权重：净强优先，风险惩罚；避免“高净强但风险爆表”的误判
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

    # 高位断板（断板最高板）——用于同步到“明日指南”
    top_duanban_name = str(mi.get("top_duanban_name") or "")
    top_duanban_lb = int(to_num(mi.get("top_duanban_lb"), 0) or 0)
    top_duanban_is_high = int(to_num(mi.get("top_duanban_is_high"), 0) or 0) == 1
    second_lb = int(to_num(mi.get("second_lb"), 0) or 0)

    mood_stage = (market_data.get("moodStage") or {})
    stage = mood_stage.get("title") or "-"
    stage_type = mood_stage.get("type") or "warn"
    cycle = str(mood_stage.get("cycle") or "")
    cycle_cn = str(mood_stage.get("detail") or "")
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
    zt_cnt = int(to_num((market_data.get("panorama") or {}).get("limitUp"), to_num(mi.get("zt_count"), 0)))
    vol_chg = to_num(((market_data.get("volume") or {}).get("change")), 0)  # %

    # 阈值容忍度：随阶段动态变化（避免写死绝对阈值）
    if stage_type == "good":
        tol = {"fb": 8, "jj": 10, "zb": 10, "loss": 3}
        stage_cls = "ladder-chip-strong red-text"
    elif stage_type == "fire":
        tol = {"fb": 6, "jj": 8, "zb": 8, "loss": 2}
        stage_cls = "ladder-chip-cool blue-text"
    else:
        tol = {"fb": 5, "jj": 8, "zb": 8, "loss": 2}
        stage_cls = "ladder-chip-warn orange-text"

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

    # 盘面基调（给行动指南一个“像复盘”的总起）
    if stage_type == "good":
        regime = "强势偏高潮"
        verdict_type = "good"
    elif stage_type == "fire":
        regime = "弱势偏退潮"
        verdict_type = "fire"
    else:
        regime = "震荡分歧"
        verdict_type = "warn"

    stance = "均衡"
    if heat >= 70 and risk <= 40 and fb >= 70:
        stance = "进攻"
    elif risk >= 60 or loss >= 10 or fb <= 55:
        stance = "防守"
    # 若 moodStage 已给出“周期建议立场”，优先用它（更贴近你的短线框架）
    if stance_from_stage:
        stance = stance_from_stage

    # 模式选择（4态）：接力 / 套利 / 低位试错 / 休息
    # 你的要求：默认偏“进攻”，只有出现明确的风险/失效信号才降级
    dzb = to_num(delta.get("zb_rate"), 0) if delta else 0
    dloss = to_num(delta.get("loss"), 0) if delta else 0
    risk_trend_up = (dzb >= 1.0) or (dloss >= 2)
    strong_divergence = (zbc_ge3_ratio >= 18) or (avg_zbc >= 1.8)

    mode = "接力"  # 默认进攻（旧逻辑）
    # 1) 先判“必须休息”的情形
    if stage_type == "fire" or stance == "防守" or overlap_score >= 75 or risk >= 70 or loss >= 15:
        mode = "休息"
    # 2) 再判“套利态”：强分歧或风险趋势上行，但还没到必须休息
    elif strong_divergence or risk_trend_up or theme_risk >= 6:
        mode = "套利"
    # 3) 最后判“低位试错”：主线净强不足/承接不足时，别硬接高位
    elif theme_net < 9 or fb < 55 or jj < 25:
        mode = "低位试错"

    # 周期模板模式（新逻辑）：让“阶段→策略”更直观
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

    meta_title = f"🧩 盘面基调：{tag_stage}｜主线：{theme.get('name','主线')}｜模式：{mode_show}｜建议：{stance}"
    meta_detail = (
        f"涨停{zt_cnt}，封板{fb:.1f}%（早封{early:.1f}%），晋级{jj:.1f}%；"
        f"炸板{zb:.1f}%、扩散{int(loss)}；量能{vol_chg:+.2f}%；"
        f"多开板≥3占比{zbc_ge3_ratio:.1f}%（均开板{avg_zbc:.2f}）。"
    )

    # === 纯数据驱动文案（避免固定话术堆料）===
    def bar(*parts: str) -> str:
        return "｜".join([p for p in parts if p])

    main_name = str(theme.get("name") or "主线")
    main_examples = str(theme.get("examples") or "—")
    main_str = f"{main_name}（样本：{main_examples}）"
    leader_name = str(leader.get("names") or "龙头")
    leader_b = leader.get("maxB") or "-"

    # 观察清单：你明确不需要（容易产生“滞后/空泛”观感），保持为空
    observe: list[Dict[str, Any]] = []

    # 开盘2条：纯数据 + 阈值（不写“建议/观察/优先”这类空话）
    confirm = [
        {
            "dot": "dot-safe",
            "title": f"开盘① 定主线：{main_name}",
            "desc": bar(
                f"净强{theme_net:.1f} · 风险{theme_risk:.1f}",
                f"拥挤(重叠){overlap_score:.1f}%",
                f"保留底线：净强≥{max(theme_net-1.0,0):.1f}",
            ),
            "tags": [
                tag(f"样本{main_examples}", "ladder-chip-cool blue-text"),
            ],
        },
        {
            "dot": "dot-safe",
            "title": "开盘② 定节奏：承接 vs 分歧",
            "desc": bar(
                f"承接：封板{fb:.1f}% / 晋级{jj:.1f}% / 早封{early:.1f}%",
                f"分歧：炸板{zb:.1f}% / ≥3开板{zbc_ge3_ratio:.1f}% / 均开板{avg_zbc:.2f}",
            ),
            "tags": [
                *(x for x in [dtag("fb_rate", "pp"), dtag("jj_rate", "pp"), dtag("zb_rate", "pp"), dtag("loss")] if x),
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

    # 若出现“高位断板”，把它作为明日盯盘重点：观察断板龙头的反馈是否压制次高板/梯队
    if top_duanban_is_high and top_duanban_name and top_duanban_lb >= 6:
        retreat[1]["title"] = "盯盘红灯② 高位断板反馈"
        retreat[1]["desc"] = bar(
            f"断板最高：{top_duanban_name}({top_duanban_lb}板)",
            f"次高板：{second_lb}板（易受反馈影响）" if second_lb else "次高板：—",
            "看点：反抽无力/继续走弱 → 次高板更难晋级；强修复回封 → 梯队回暖",
        )
        retreat[1]["tags"] = [tag("先看反馈", "ladder-chip-warn orange-text")]

    return {
        "meta": {"title": meta_title, "detail": meta_detail, "type": verdict_type},
        "confirm": confirm,
        "retreat": retreat,
    }


def build_summary3(*, market_data: Dict[str, Any]) -> Dict[str, Any]:
    """全站三句话（复盘口径统一）：今天是什么盘 / 主线与龙头 / 明天模式与触发条件"""
    ag = (market_data.get("actionGuideV2") or {})
    meta = (ag.get("meta") or {})

    # 1) 今天是什么盘（取 meta.detail 的数字版 + stage）
    stage = (market_data.get("moodStage") or {}).get("title") or "-"
    line1 = f"今日：{stage}，{meta.get('detail','').strip()}"

    # 2) 主线与龙头
    theme = ((market_data.get("actionGuideV2") or {}).get("meta") or {}).get("title", "")
    # meta.title 内含“主线：xx”，这里再提取一次更直白
    main = (market_data.get("themePanels") or {}).get("ztTop") or []
    main_name = ""
    if "主线：" in str(meta.get("title", "")):
        try:
            main_name = str(meta.get("title")).split("主线：", 1)[1].split("｜", 1)[0].strip()
        except Exception:
            main_name = ""
    if not main_name:
        main_name = (main[0].get("name") if main else "主线")
    leader = "龙头"
    ladder = market_data.get("ladder") or []
    if ladder:
        maxb = max(int(float(r.get("badge", 0) or 0)) for r in ladder)
        tops = [r for r in ladder if int(float(r.get("badge", 0) or 0)) == maxb]
        leader = "、".join([str(r.get("name") or "") for r in tops[:2] if str(r.get("name") or "")]) or leader
        leader = f"{leader}（{maxb}板）"
    line2 = f"主线：{main_name}；空间锚：{leader}。"

    # 3) 明天怎么做（模式 + 关键触发）
    mode = ""
    if "模式：" in str(meta.get("title", "")):
        try:
            mode = str(meta.get("title")).split("模式：", 1)[1].split("｜", 1)[0].strip()
        except Exception:
            mode = ""
    if not mode:
        mode = "低位试错"

    # 从 confirm/retreat 抽一句最关键的阈值（尽量短）
    cf = (ag.get("confirm") or [])
    rt = (ag.get("retreat") or [])
    cf_hint = ""
    rt_hint = ""
    if cf:
        cf_hint = str((cf[1].get("desc") if len(cf) > 1 else cf[0].get("desc")) or "").strip()
        cf_hint = cf_hint.split("；", 1)[0]
    if rt:
        rt_hint = str(rt[0].get("desc") or "").strip().split("，", 1)[0]
    line3 = f"明日：{mode}。确认：{cf_hint or '承接确认'}；撤退：{rt_hint or '风险放大就降级'}。"

    return {"lines": [line1, line2, line3]}

def build_learning_notes(*, market_data: Dict[str, Any], cache_dir: Path) -> Dict[str, Any]:
    """
    学习短线的注意事项 + 1~2 句语录（偏复盘语气）。
    - 不引用外部 PDF 原文，避免版权风险；内容为归纳提炼。
    - 可随盘面阶段动态切换语气（更贴合每日复盘）。
    """
    date = str(market_data.get("date") or "").strip() or "unknown-date"
    mood_stage = (market_data.get("moodStage") or {})
    stage_type = (mood_stage.get("type") or "warn").strip()
    cycle = str(mood_stage.get("cycle") or "").strip()
    mi = ((market_data.get("features") or {}).get("mood_inputs") or {})
    risk_spike = int(mi.get("risk_spike", 0) or 0)
    tier_integrity_low = int(mi.get("tier_integrity_low", 0) or 0)

    def _norm_line(s: str) -> str:
        s = s.strip()
        # 去掉常见编号/标题前缀
        s = re.sub(r"^\s*[（(]?\s*\d+\s*[）)]\s*", "", s)
        s = re.sub(r"^\s*\d+\s*[\.、]\s*", "", s)
        s = re.sub(r"^\s*[一二三四五六七八九十]+\s*[、.．]\s*", "", s)
        s = s.replace("—", "—").strip()
        return s

    def _split_sentences(text: str) -> list[str]:
        # 按中文标点粗切分
        parts = re.split(r"[。！？!?\n]+", text)
        out: list[str] = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            # 再按分号/冒号轻切
            out.extend([x.strip() for x in re.split(r"[；;]+", p) if x.strip()])
        return out

    def _load_user_pool() -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, str]]]:
        """
        从工作区的 ocr_识别结果.md 中提炼候选：
        - 返回 (tips_add, quotes_add, fire_quotes_add)
        说明：这里只做“短句提炼”，不搬运长段落；且不引用外部链接内容。
        """
        workspace_root = cache_dir.parent
        md_path = workspace_root / "ocr_识别结果.md"
        if not md_path.exists():
            return ([], [], [])

        raw = md_path.read_text(encoding="utf-8", errors="ignore")
        lines = [ln for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        sentences: list[str] = []
        for ln in lines:
            ln = _norm_line(ln)
            if not ln or ln == "图片":
                continue
            # 过滤明显标题
            if re.match(r"^(利弗莫尔|经典|整理|一、|二、|三\.|四、|五、|六\.|七\.|八\.|九\.|十\.)", ln):
                continue
            sentences.extend(_split_sentences(ln))

        # 去重 + 长度控制
        seen: set[str] = set()
        cand: list[str] = []
        for s in sentences:
            s = _norm_line(s)
            s = re.sub(r"\s+", "", s)
            if len(s) < 12 or len(s) > 44:
                continue
            if s in seen:
                continue
            seen.add(s)
            cand.append(s)

        tips_add: list[tuple[str, str]] = []
        quotes_add: list[tuple[str, str]] = []
        fire_quotes_add: list[tuple[str, str]] = []
        for s in cand:
            _id = "u" + hashlib.md5(s.encode("utf-8")).hexdigest()[:8]
            # 归类：更短的当“语录”，稍长的当“提醒”
            if len(s) <= 26:
                # 退潮/防守类句子放到 fire_quotes
                if any(k in s for k in ["止损", "亏损", "认赔", "危险", "躲开", "不摊", "不平摊", "保命"]):
                    fire_quotes_add.append((_id, s))
                else:
                    quotes_add.append((_id, s))
            else:
                tips_add.append((_id, s))

        return (tips_add, quotes_add, fire_quotes_add)

    # 展示强度 A：每天仅 1 条注意事项 + 1 句语录，并做近 7 日去重
    # 候选池尽量丰富，避免两三天就重复
    tips_general = [
        ("t001", "先活下来：单笔/单日都要有可执行的止损与撤退点，回撤不可失控。"),
        ("t002", "只做主线：分歧市做减法，优先“主线 + 辨识度 + 确认点”。"),
        ("t003", "先确认后加仓：不要用想象加仓，用回封/换手/承接数据加仓。"),
        ("t004", "轻仓试错，重仓在确定性：大赚来自少数几次，平时用小仓位换信息。"),
        ("t005", "复盘要可验证：写清入场理由、撤退条件、次日验证点，形成可复制模式。"),
        ("t006", "只做你统计过的形态：没复盘过、没验证过的，默认不做。"),
        ("t007", "一致与分歧要分开：一致吃溢价，分歧吃性价比，别混用打法。"),
        ("t008", "别拿消息当逻辑：题材只是壳，核心是强度、承接和情绪。"),
        ("t009", "仓位要跟随情绪：热度升、风险降才扩仓；反之先收缩。"),
        ("t010", "交易日只做两件事：等信号、执行纪律；不做“临盘改剧本”。"),
        # 来自你上传内容的归纳（利弗莫尔/关键点体系）
        ("t011", "价位是确认信号的核心：不等关键价位被市场确认，不轻举妄动。"),
        ("t012", "频繁交易是失败者的玩法：当市场缺乏大好机会，应缩手不动。"),
        ("t013", "集中火力做领先股：先确认谁是领头股，再集中，而不是分散。"),
        ("t014", "两股验证：用同题材两只辨识度相互印证，减少“单票误判”。"),
        ("t015", "先有盈利再加仓：没有浮盈，就不要谈格局与耐心。"),
        ("t016", "成交量是危险信号：放量不涨、趋势不延续，要优先防守。"),
        ("t017", "不靠消息下单：只看事实（强度、承接、联动、风险）。"),
    ]
    tips_good = [
        ("tg01", "高潮日更要克制：不追尾盘一致，优先分歧回封/换手确认。"),
        ("tg02", "高度打开≠随便追：盯龙头与主线扩散，别追补涨跟风。"),
        ("tg03", "高位一旦放量分歧，先减仓再谈接力。"),
        ("tg04", "重要趋势的利润多发生在最后阶段：但前提是你一直在场内、且仓位可控。"),
        ("tg05", "强市也要分批：先试错确认，再加仓扩大利润段。"),
    ]
    tips_warn = [
        ("tw01", "分歧市先做减法：宁可少做，也不乱做。"),
        ("tw02", "主线不强就不硬接：用低位换手试错换信息。"),
        ("tw03", "炸板与扩散同步走高时，宁可空仓观望。"),
        ("tw04", "最小阻力线不一致就不做：先让市场本身证实你的判断。"),
        ("tw05", "板块不联动就不强：同题材不共振，优先等待。"),
    ]
    tips_fire = [
        ("tf01", "退潮阶段先保命：不做高位接力，不做情绪硬接。"),
        ("tf02", "弱势只做模式内：小仓试错，错了就退。"),
        ("tf03", "亏钱效应不收敛前，优先休息而不是寻找机会。"),
        ("tf04", "看到危险信号就躲开：过几天再回来，省麻烦也省钱。"),
        ("tf05", "退潮期少做：休息也是交易的一部分。"),
    ]

    quotes_good = [
        ("qg01", "高潮不追一致，分歧回封才是性价比。"),
        ("qg02", "赚快钱的前提是：仓位可控、退出清晰。"),
        ("qg03", "空间来自龙头，但利润来自纪律。"),
        ("qg04", "强市也会杀人：别在最高点证明自己勇敢。"),
        ("qg05", "能赚到钱靠的不是想法，真正赚到钱的是坐在那里等待机会的出现。"),
        ("qg06", "趋势发动前的等待，胜过趋势发动后的追赶。"),
    ]
    quotes_warn = [
        ("qw01", "分歧市做减法：只做最强主线的最强辨识度。"),
        ("qw02", "看懂亏钱效应，比看懂赚钱效应更重要。"),
        ("qw03", "没有确认点的交易，都是情绪消费。"),
        ("qw04", "做对很难，少犯错更重要。"),
        ("qw05", "市场只有一个方向：不是多头也不是空头，而是做对的方向。"),
        ("qw06", "关键价位之上5%~10%才入场，往往已经错过最佳时机。"),
        ("qw07", "没有共振的强，只是单点的热。"),
    ]
    quotes_fire = [
        ("qf01", "退潮先保命：不亏钱就是赢。"),
        ("qf02", "只在模式内出手，别用情绪下单。"),
        ("qf03", "弱势里的机会，往往是强势里的陷阱。"),
        ("qf04", "等风来，不是赌风来。"),
        ("qf05", "当我看见危险信号时，我不跟它争执，我躲开。"),
        ("qf06", "绝不要平反亏损——亏损只会让判断失真。"),
        ("qf07", "先躲开危险信号，机会永远会再来。"),
    ]

    # 追加：从你维护的 ocr_识别结果.md 中提炼的“理念句子”
    user_tips_add, user_quotes_add, user_fire_quotes_add = _load_user_pool()
    if user_tips_add:
        tips_general = user_tips_add + tips_general
    if user_quotes_add:
        quotes_warn = user_quotes_add + quotes_warn
    if user_fire_quotes_add:
        quotes_fire = user_fire_quotes_add + quotes_fire

    if stage_type == "good":
        tip_pool = tips_good + tips_general
        quote_pool = quotes_good
    elif stage_type == "fire":
        tip_pool = tips_fire + tips_general
        quote_pool = quotes_fire
    else:
        tip_pool = tips_warn + tips_general
        quote_pool = quotes_warn

    history_path = cache_dir / "learning_notes_history.json"
    history = {"tip_ids": [], "quote_ids": [], "last_date": ""}
    try:
        if history_path.exists():
            history = json.loads(history_path.read_text(encoding="utf-8")) or history
    except Exception:
        history = {"tip_ids": [], "quote_ids": [], "last_date": ""}

    tip_used = set((history.get("tip_ids") or [])[:7])
    quote_used = set((history.get("quote_ids") or [])[:7])

    def pick_one(pool: list[tuple[str, str]], used: set[str], seed_key: str) -> tuple[str, str]:
        if not pool:
            return ("", "")
        seed = int(hashlib.md5(seed_key.encode("utf-8")).hexdigest(), 16)
        start = seed % len(pool)
        for i in range(len(pool)):
            _id, _txt = pool[(start + i) % len(pool)]
            if _id not in used:
                return (_id, _txt)
        return pool[start]

    tip_id, tip_txt = pick_one(tip_pool, tip_used, f"{date}:{stage_type}:tip")
    quote_id, quote_txt = pick_one(quote_pool, quote_used, f"{date}:{stage_type}:quote")

    # === 结构化卡片（阶段/触发信号）===
    # 每天输出 2~3 条：阶段卡 + 触发卡 + 1 条通用提醒
    try:
        from daily_review.rules.shortline import NOTE_CARDS
    except Exception:
        NOTE_CARDS = []

    def card_hit(card: dict) -> bool:
        when = card.get("when") or {}
        if not isinstance(when, dict):
            return False
        if "cycle" in when:
            cs = when.get("cycle") or []
            if isinstance(cs, list) and cycle and cycle not in cs:
                return False
        if "risk_spike" in when:
            vs = when.get("risk_spike") or []
            if isinstance(vs, list) and risk_spike not in vs:
                return False
        if "tier_integrity_low" in when:
            vs = when.get("tier_integrity_low") or []
            if isinstance(vs, list) and tier_integrity_low not in vs:
                return False
        return True

    picked_cards: list[str] = []
    for c in NOTE_CARDS:
        if not isinstance(c, dict):
            continue
        if card_hit(c):
            txt = str(c.get("text") or "").strip()
            if txt:
                picked_cards.append(txt)
        if len(picked_cards) >= 2:
            break

    tips: list[str] = []
    for t in picked_cards:
        if t not in tips:
            tips.append(t)
    if tip_txt and tip_txt not in tips:
        tips.append(tip_txt)
    tips = tips[:3]

    # 更新历史（同一天重复渲染不重复追加）
    try:
        if history.get("last_date") != date:
            history["tip_ids"] = [tip_id] + list(history.get("tip_ids") or [])
            history["quote_ids"] = [quote_id] + list(history.get("quote_ids") or [])
            history["tip_ids"] = (history["tip_ids"] or [])[:7]
            history["quote_ids"] = (history["quote_ids"] or [])[:7]
            history["last_date"] = date
            history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return {"tips": tips, "quotes": [quote_txt] if quote_txt else []}


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

    # 离线增强：补齐“情绪周期趋势（近5/7日）”数据
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
                mood_inputs["trend_max_lb"] = round(float(last["max_lb"]) - float(first["max_lb"]), 2)
                mood_inputs["trend_fb_rate"] = round(float(last["fb_rate"]) - float(first["fb_rate"]), 2)
                mood_inputs["trend_jj_rate"] = round(float(last["jj_rate"]) - float(first["jj_rate"]), 2)
                mood_inputs["trend_broken_lb_rate"] = round(float(last["broken_lb_rate"]) - float(first["broken_lb_rate"]), 2)
    except Exception:
        pass

    # 离线增强：把 pools_cache.json 中的当日涨停池注入到 market_data，供 HTML 做“涨停个股分析”
    # 注意：此处不做任何网络请求，只读取本地缓存文件
    try:
        pools_cache_path = market_json_path.parent / "pools_cache.json"
        if pools_cache_path.exists():
            pools_cache = json.loads(pools_cache_path.read_text(encoding="utf-8"))
            ztgc = (((pools_cache.get("pools") or {}).get("ztgc") or {}).get(args.date)) or []
            # 为避免与其他字段冲突，使用 ztgc 作为当日涨停池明细
            market_data["ztgc"] = ztgc
            # 同步注入题材映射（theme_cache.json）：为涨停个股分析提供“更细粒度题材”
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

    # 离线增强：用 Python 算法生成“明日计划”（避免前端出现“写死文案”的错觉）
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

    # 离线增强：学习短线提醒 + 语录（随情绪阶段动态切换）
    try:
        market_data.setdefault("learningNotes", build_learning_notes(market_data=market_data, cache_dir=market_json_path.parent))
    except Exception:
        market_data.setdefault("learningNotes", {"tips": [], "quotes": []})

    render_html_template(
        template_path=template_path,
        output_path=output_path,
        market_data=market_data,
        report_date=args.date,
        date_note=args.note,
    )
