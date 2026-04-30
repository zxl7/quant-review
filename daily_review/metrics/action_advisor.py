#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
六维情绪 → 操作建议（Action Advisor）

目标：
- 用“原系统字段/原算法输出”的六个维度趋势变化，生成可执行的短线操作推演与仓位建议
- 输出结构化字段，供前端自由渲染（而不是硬编码固定文案）

说明：
- 纯计算：不做任何网络请求
- 输入：market_data（daily_review 全链路的 marketData 字典）
"""

from __future__ import annotations

from typing import Any, Dict


def build_action_advisor(*, market_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    操作建议引擎（Action Advisor）

    输出为结构化数据：
    - posture / position / action_line
    - summary / posture_line / action_guide
    - tags（围绕六维趋势的摘要标签）

    约束：
    - 字段与数据均来自“现有系统”：moodStage / mood / features.mood_inputs
    - 只做纯计算，不做外部请求
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

    def _tail(arr: Any, n: int = 7) -> list[float]:
        if not isinstance(arr, list):
            return []
        out: list[float] = []
        for x in arr[-n:]:
            try:
                out.append(float(str(x).replace("%", "").replace("板", "").strip()))
            except Exception:
                continue
        return out

    def _trend_dir_pct(seq: list[float]) -> tuple[str, float]:
        # 用“昨日对比”定义趋势（更贴近短线）
        if len(seq) < 2:
            return ("flat", 0.0)
        y0, y1 = float(seq[-2]), float(seq[-1])
        d = y1 - y0
        if abs(d) < 1e-9:
            return ("flat", 0.0)
        denom = max(abs(y0), 1.0)
        pct = d / denom * 100.0
        return ("up" if d > 0 else "down", pct)

    def _count_consecutive_up(seq: list[float]) -> int:
        if len(seq) < 2:
            return 0
        c = 0
        for i in range(len(seq) - 1, 0, -1):
            try:
                if float(seq[i]) > float(seq[i - 1]):
                    c += 1
                else:
                    break
            except Exception:
                break
        return c

    # === 输入 ===
    mood_stage = market_data.get("moodStage") or {}
    stage_title = str(mood_stage.get("title") or "").strip() or "-"
    cycle_code = str(mood_stage.get("cycle") or "").strip()  # ICE / START / FERMENT / CLIMAX
    day_state = str(mood_stage.get("dayState") or "").strip()  # 分歧/一致等（若有）

    # cycle_key：用于基底建议（4 大类），保持与你 PRD 的口径一致（中文）
    cycle_key = ""
    if cycle_code == "ICE":
        cycle_key = "冰点"
    elif cycle_code == "CLIMAX":
        cycle_key = "亢奋"
    elif cycle_code in ("START", "FERMENT"):
        cycle_key = "修复"
    if not cycle_key:
        # 兜底：从 title 推断
        if "亢奋" in stage_title or "加速" in stage_title:
            cycle_key = "亢奋"
        elif "修复" in stage_title:
            cycle_key = "修复"
        elif "冰点" in stage_title or "退潮" in stage_title:
            cycle_key = "冰点"
        else:
            cycle_key = "分歧"

    mood = market_data.get("mood") or {}
    heat = _num(mood.get("heat"), 0.0)
    risk = _num(mood.get("risk"), 0.0)
    score = _num(mood.get("score"), 0.0)

    feats = market_data.get("features") or {}
    mi = (feats.get("mood_inputs") or {}) if isinstance(feats, dict) else {}

    # === 六维：涨停/跌停/封板率/晋级率/高度/连板 ===
    zt_seq = _tail(mi.get("hist_zt"))
    dt_seq = _tail(mi.get("hist_dt"))
    fb_seq = _tail(mi.get("hist_fb_rate"))
    jj_seq = _tail(mi.get("hist_jj_rate"))
    maxlb_seq = _tail(mi.get("hist_max_lb"))
    lb_seq = _tail(mi.get("hist_lianban"))

    zt_dir, zt_pct = _trend_dir_pct(zt_seq)
    dt_dir, dt_pct = _trend_dir_pct(dt_seq)
    fb_dir, fb_pct = _trend_dir_pct(fb_seq)
    jj_dir, jj_pct = _trend_dir_pct(jj_seq)
    maxlb_dir, maxlb_pct = _trend_dir_pct(maxlb_seq)
    lb_dir, lb_pct = _trend_dir_pct(lb_seq)

    # 高度突破：创新高且>=4板
    height_breakout = False
    if len(maxlb_seq) >= 2:
        prev_max = max(maxlb_seq[:-1]) if maxlb_seq[:-1] else maxlb_seq[-1]
        height_breakout = (maxlb_seq[-1] > prev_max and maxlb_seq[-1] >= 4)

    seal_streak = _count_consecutive_up(fb_seq)

    # === 非六维但“动作闭环”兜底用（不进 summary/tags 主输出）===
    loss = float(_num(mi.get("loss"), 0.0))  # 亏钱扩散强度（上游口径）
    broken_rate = float(_num(mi.get("broken_lb_rate_adj", mi.get("broken_lb_rate")), 0.0))  # 断板率
    avg_zbc = float(_num(mi.get("avg_zt_zbc"), 0.0))
    ge3_ratio = float(_num(mi.get("zt_zbc_ge3_ratio"), 0.0))
    diverge_high = (avg_zbc >= 1.6) or (ge3_ratio >= 18)
    early_ratio = float(_num(mi.get("zt_early_ratio"), 0.0))
    seal_fund = float(_num(mi.get("avg_seal_fund_yi"), 0.0))

    # === 基底建议（按周期）===
    BASE = {
        "亢奋": {"posture": "进攻", "position": "5-7成"},
        "修复": {"posture": "试探进攻", "position": "3-5成"},
        "分歧": {"posture": "防守", "position": "1-3成或空仓"},
        "冰点": {"posture": "空仓等待", "position": "空仓"},
    }
    base = BASE.get(cycle_key, BASE["分歧"]).copy()

    # 当日“分歧”显式信号：降半档
    if day_state == "分歧" and cycle_key in ("修复", "亢奋"):
        base["posture"] = "谨慎进攻"
        base["position"] = "2-4成"

    # === 六维趋势摘要标签（用于“总结”）===
    tags: list[dict[str, str]] = []

    # 承接（封板率）
    if fb_dir == "up" and seal_streak >= 3:
        tags.append({"key": "承接", "value": "强势", "detail": f"封板率连升{seal_streak}天"})
    elif fb_dir == "up" and fb_pct > 5:
        tags.append({"key": "承接", "value": "偏强", "detail": ""})
    elif fb_dir == "down" and fb_pct < -10:
        tags.append({"key": "承接", "value": "转弱", "detail": ""})

    # 亏钱效应（跌停）
    if dt_dir == "down":
        if dt_pct < -40:
            tags.append({"key": "亏钱效应", "value": "快速收敛", "detail": ""})
        elif dt_pct < -15:
            tags.append({"key": "亏钱效应", "value": "收敛", "detail": ""})
    elif dt_dir == "up":
        if dt_pct > 30:
            tags.append({"key": "亏钱效应", "value": "加剧", "detail": ""})
        else:
            tags.append({"key": "亏钱效应", "value": "扩散", "detail": ""})

    # 接力生态（连板/晋级）
    if lb_dir == "up" and lb_pct > 40:
        tags.append({"key": "接力生态", "value": "恢复", "detail": ""})
    elif lb_dir == "down" and lb_pct < -30:
        tags.append({"key": "接力生态", "value": "萎缩", "detail": ""})

    if jj_dir == "down" and jj_pct < -15:
        tags.append({"key": "晋级", "value": "分化", "detail": ""})
    elif jj_dir == "up" and jj_pct > 10:
        tags.append({"key": "晋级", "value": "回暖", "detail": ""})

    # 赚钱效应（涨停动能）
    if zt_dir == "up" and zt_pct > 30:
        tags.append({"key": "赚钱效应", "value": "活跃", "detail": ""})
    elif zt_dir == "down" and zt_pct < -25:
        tags.append({"key": "赚钱效应", "value": "降温", "detail": ""})

    # 空间（高度）
    if height_breakout:
        tags.append({"key": "空间", "value": "突破", "detail": ""})
    elif maxlb_dir == "down" and maxlb_pct < -10:
        tags.append({"key": "空间", "value": "压缩", "detail": ""})

    # === tone（不报数）===
    if heat >= 70 and risk <= 35 and fb_dir in ("up", "flat"):
        tone = "情绪回暖，承接占优"
    elif heat >= 60 and risk <= 50:
        tone = "情绪修复中，节奏偏试探"
    elif risk >= 60 or (dt_dir == "up" and dt_pct > 30):
        tone = "情绪偏分歧，风险抬头"
    else:
        tone = "情绪偏谨慎，先看承接修复"

    # === 仓位微调（只依赖六维）===
    if dt_dir == "up" and dt_pct > 30:
        base["posture"] = "防守"
        base["position"] = "1-3成或空仓"
    elif cycle_key == "修复" and (lb_pct > 40 or jj_pct > 40) and dt_dir == "down":
        base["posture"] = "积极试探"
        base["position"] = "3-5成"

    summary_txt = f"今日{stage_title}，{tone}。"
    if tags:
        brief = "；".join([f"{t['key']}{t['value']}" for t in tags[:4]])
        summary_txt += f"{brief}。"

    posture_line = f"姿态：{base['posture']}（{base['position']}）"

    # 操作推演闭环（入场/加仓/撤退）
    if base["posture"] in ("防守",) or cycle_key in ("冰点",):
        action_txt = "动作：以防守为主，小仓只做分歧回封确认；不追高一致；行情转弱直接休息。"
    else:
        action_txt = (
            "动作：只做主线最强辨识度；"
            "入场=分歧回封/换手确认；"
            "加仓=承接继续走强且晋级延续；"
            "撤退=跌停/负反馈反向走强或分歧明显放大。"
        )

    # 兜底：当“亏钱扩散/断板反馈”偏高时，仓位自动降一档（不单独做风险提示区）
    if loss >= 15 or broken_rate >= 60 or diverge_high:
        action_txt += "（若负反馈偏高，仓位降一档）"

    action_line = f"{summary_txt}{posture_line}。{action_txt}"

    return {
        "cycle": stage_title,
        "score": round(score, 1),
        "heat": round(heat, 1),
        "risk": round(risk, 1),
        "posture": base["posture"],
        "position": base["position"],
        "action_line": action_line,
        "summary": summary_txt,
        "posture_line": posture_line,
        "action_guide": action_txt,
        "tags": tags,
    }

