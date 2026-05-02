#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
六维情绪 → 操作建议（Action Advisor）

目标：
- 用“原系统字段/原算法输出”的六个维度趋势变化，生成动态证据式复盘提示
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
    - summary / posture_line
    - evidences / tags（围绕六维趋势的动态证据与摘要标签）

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
    duanban_high_count = int(_num(mi.get("duanban_high_count"), 0))
    duanban_max_drop_hl = float(_num(mi.get("duanban_max_drop_hl"), 0.0))
    duanban_avg_drop_hl = float(_num(mi.get("duanban_avg_drop_hl"), 0.0))
    duanban_max_drop_hc = float(_num(mi.get("duanban_max_drop_hc"), 0.0))
    duanban_worst_name = str(mi.get("duanban_worst_name") or "").strip()
    duanban_worst_lb = int(_num(mi.get("duanban_worst_lb"), 0))
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

    # === 证据式输出：像复盘，不像模板 ===
    zt_now = int(_num(mi.get("zt_count"), zt_seq[-1] if zt_seq else 0))
    zt_prev = int(zt_seq[-2]) if len(zt_seq) >= 2 else zt_now
    dt_now = int(_num(mi.get("dt_count"), dt_seq[-1] if dt_seq else 0))
    dt_prev = int(dt_seq[-2]) if len(dt_seq) >= 2 else dt_now
    fb_now = float(_num(mi.get("fb_rate"), fb_seq[-1] if fb_seq else 0.0))
    lb_now = int(_num(mi.get("lianban_count"), lb_seq[-1] if lb_seq else 0))
    maxlb_now = int(_num(mi.get("max_lb"), maxlb_seq[-1] if maxlb_seq else 0))
    recent_high_7d = int(max(maxlb_seq[:-1])) if len(maxlb_seq) >= 2 else maxlb_now

    # === 关键状态 ===
    negative_loss = loss >= 18
    negative_broken = broken_rate >= 22 or duanban_max_drop_hl >= 14
    negative_dt = (dt_dir == "up" and dt_pct > 20 and dt_now >= max(8, dt_prev))
    negative_diverge = (avg_zbc >= 2.0 and ge3_ratio >= 25 and broken_rate >= 18)
    risk_expand = negative_loss or negative_broken or negative_dt or negative_diverge or risk >= 68

    # === 仓位微调（只依赖六维）===
    if dt_dir == "up" and dt_pct > 30:
        base["posture"] = "防守"
        base["position"] = "1-3成或空仓"
    elif cycle_key == "修复" and (lb_pct > 40 or jj_pct > 40) and dt_dir == "down":
        base["posture"] = "积极试探"
        base["position"] = "3-5成"
    elif cycle_key == "亢奋" and risk_expand:
        base["posture"] = "冲高兑现"
        base["position"] = "2-4成"

    posture_line = f"姿态：{base['posture']}（{base['position']}）"

    # === 动态证据池：先生成候选，再按权重调配输出 ===
    evidence_pool: list[dict[str, Any]] = []

    def _push_evidence(*, group: str, icon: str, score_v: float, text: str) -> None:
        if score_v <= 0 or not text:
            return
        evidence_pool.append(
            {
                "group": group,
                "icon": icon,
                "score": round(float(score_v), 2),
                "text": text,
            }
        )

    # 承接 / 封板
    if fb_now >= 80 and lb_now >= 15:
        _push_evidence(
            group="seal",
            icon="✅",
            score_v=70 + max(0, fb_now - 80) * 0.8 + max(0, lb_now - 15) * 1.2 + seal_streak * 2,
            text=f"封板率{fb_now:.0f}% + 连板{lb_now}只 = 短线资金信心回归",
        )
    elif fb_now >= 75:
        _push_evidence(
            group="seal",
            icon="✅",
            score_v=55 + max(0, fb_now - 75) * 1.4 + max(0, fb_pct) * 0.5 + seal_streak * 2,
            text=f"封板率{fb_now:.0f}% = 承接明显转强，接力情绪在修复",
        )
    elif fb_now <= 65:
        _push_evidence(
            group="seal",
            icon="⚠️",
            score_v=45 + max(0, 65 - fb_now) * 1.2 + abs(min(fb_pct, 0)) * 0.5,
            text=f"封板率{fb_now:.0f}% = 承接一般，修复力度还不够扎实",
        )

    # 亏钱效应 / 跌停
    if dt_prev > 0 and dt_now < dt_prev:
        shrink_text = "大幅收窄" if dt_now <= max(dt_prev * 0.5, dt_prev - 8) else "明显收窄"
        _push_evidence(
            group="loss",
            icon="✅",
            score_v=58 + (dt_prev - dt_now) * 4 + abs(min(dt_pct, 0)) * 0.35,
            text=f"跌停从{dt_prev}降到{dt_now} = 亏钱效应{shrink_text}",
        )
    elif dt_prev > 0 and dt_now > dt_prev:
        _push_evidence(
            group="loss",
            icon="⚠️",
            score_v=60 + (dt_now - dt_prev) * 4 + max(dt_pct, 0) * 0.35,
            text=f"跌停从{dt_prev}升到{dt_now} = 亏钱效应重新扩散",
        )

    # 龙头空间 / 高度
    # 规则：5板以上才谈“龙头空间”；是否打开/压制，参考最近7日历史高度
    if maxlb_now >= 5 and maxlb_now > recent_high_7d:
        _push_evidence(
            group="height",
            icon="✅",
            score_v=72 + (maxlb_now - recent_high_7d) * 12,
            text=f"高度打到{maxlb_now}板，突破近7日高点{recent_high_7d}板 = 龙头空间打开",
        )
    elif maxlb_now >= 5 and maxlb_now == recent_high_7d:
        _push_evidence(
            group="height",
            icon="✅",
            score_v=58 + maxlb_now * 3,
            text=f"高度维持在{maxlb_now}板，持平近7日高点 = 龙头空间保持打开",
        )
    elif recent_high_7d >= 5 and maxlb_now < recent_high_7d:
        _push_evidence(
            group="height",
            icon="⚠️",
            score_v=56 + (recent_high_7d - maxlb_now) * 10,
            text=f"当前高度仅{maxlb_now}板，低于近7日高点{recent_high_7d}板 = 龙头空间仍受压制",
        )
    elif maxlb_now < 5:
        _push_evidence(
            group="height",
            icon="⚠️",
            score_v=36 + max(0, 5 - maxlb_now) * 6,
            text=f"当前高度{maxlb_now}板 = 连板空间在修复，但龙头级别仍未出现",
        )

    # 赚钱效应 / 涨停
    if zt_prev > 0 and zt_now < zt_prev:
        if zt_now >= 60:
            _push_evidence(
                group="heat",
                icon="⚠️",
                score_v=42 + (zt_prev - zt_now) * 1.0 + abs(min(zt_pct, 0)) * 0.25,
                text=f"涨停从{zt_prev}降到{zt_now} = 热度微降但属于去伪存真",
            )
        else:
            _push_evidence(
                group="heat",
                icon="⚠️",
                score_v=55 + (zt_prev - zt_now) * 1.2 + abs(min(zt_pct, 0)) * 0.3,
                text=f"涨停从{zt_prev}降到{zt_now} = 热度回落较明显，不能把修复当高潮",
            )
    elif zt_prev > 0 and zt_now > zt_prev and zt_pct > 20:
        _push_evidence(
            group="heat",
            icon="✅",
            score_v=54 + (zt_now - zt_prev) * 1.0 + max(zt_pct, 0) * 0.3,
            text=f"涨停从{zt_prev}升到{zt_now} = 赚钱效应继续扩散",
        )

    # 接力链条 / 晋级率 / 连板生态
    if jj_dir == "up" and jj_pct > 10:
        _push_evidence(
            group="relay",
            icon="✅",
            score_v=50 + max(jj_pct, 0) * 0.6 + (10 if lb_dir == "up" else 0),
            text="晋级率回暖 = 接力链条开始恢复，不再只有首板热闹",
        )
    elif jj_dir == "down" and jj_pct < -12:
        _push_evidence(
            group="relay",
            icon="⚠️",
            score_v=52 + abs(jj_pct) * 0.5 + (8 if lb_dir == "down" else 0),
            text="晋级率走弱 = 接力链条还不稳，强修复未必能接住",
        )

    # 风险侧 / 炸板 / 亏钱扩散
    if negative_broken and negative_loss:
        extra = ""
        if duanban_worst_name and duanban_max_drop_hl > 0:
            extra = f"；代表股{duanban_worst_name}({duanban_worst_lb}板)高低点杀伤{duanban_max_drop_hl:.1f}%"
        _push_evidence(
            group="risk",
            icon="⚠️",
            score_v=64 + loss * 0.6 + broken_rate * 0.5 + duanban_max_drop_hl * 0.8,
            text=f"断板率{broken_rate:.1f}%且亏钱效应仍高 = 断板负反馈偏强{extra}",
        )
    elif negative_broken:
        if duanban_worst_name and duanban_max_drop_hl > 0:
            risk_text = (
                f"断板率{broken_rate:.1f}%；{duanban_worst_name}({duanban_worst_lb}板)"
                f"高低点杀伤{duanban_max_drop_hl:.1f}%"
                f"、高收到收盘回撤{duanban_max_drop_hc:.1f}% = 断板负反馈偏强"
            )
        elif duanban_avg_drop_hl > 0:
            risk_text = f"断板率{broken_rate:.1f}%；断板个股平均高低点杀伤{duanban_avg_drop_hl:.1f}% = 高位承接还不够稳"
        else:
            risk_text = f"断板率{broken_rate:.1f}%偏高 = 高位承接还不够稳，别把修复当成一致加速"
        _push_evidence(
            group="risk",
            icon="⚠️",
            score_v=58 + broken_rate * 0.7 + duanban_max_drop_hl * 0.8 + duanban_high_count * 4,
            text=risk_text,
        )
    elif negative_loss:
        _push_evidence(
            group="risk",
            icon="⚠️",
            score_v=58 + loss * 0.8,
            text=f"亏钱效应仍在高位（{loss:.0f}） = 修复能做，但节奏更适合右侧确认",
        )
    elif negative_dt:
        _push_evidence(
            group="risk",
            icon="⚠️",
            score_v=56 + max(dt_pct, 0) * 0.5,
            text=f"跌停回升到{dt_now}家 = 负反馈重新抬头，修复力度还要再观察",
        )
    elif negative_diverge or risk >= 68:
        _push_evidence(
            group="risk",
            icon="⚠️",
            score_v=52 + risk * 0.3,
            text="高位分歧信号仍在累积 = 可以看修复，但不适合情绪上头",
        )
    elif risk <= 35 and loss <= 10 and broken_rate <= 45:
        _push_evidence(
            group="risk",
            icon="✅",
            score_v=40 + max(0, 35 - risk) * 0.5 + max(0, 10 - loss) * 1.0,
            text="风险端没有继续抬头 = 修复环境相对可控",
        )

    # 同组只保留最高分候选，再全局排序取前 4
    best_by_group: dict[str, dict[str, Any]] = {}
    for item in evidence_pool:
        group = str(item.get("group") or "")
        if group not in best_by_group or float(item.get("score") or 0) > float(best_by_group[group].get("score") or 0):
            best_by_group[group] = item

    evidences = sorted(best_by_group.values(), key=lambda x: float(x.get("score") or 0), reverse=True)[:4]
    evidences = [{"icon": str(x["icon"]), "text": str(x["text"])} for x in evidences]

    pos_cnt = sum(1 for x in evidences if x.get("icon") == "✅")
    warn_cnt = sum(1 for x in evidences if x.get("icon") == "⚠️")
    picked_groups = {str(v.get("group")) for v in sorted(best_by_group.values(), key=lambda x: float(x.get("score") or 0), reverse=True)[:4]}

    if cycle_key == "修复" and {"seal", "loss", "height"} <= picked_groups and pos_cnt >= 3:
        headline = "这不是普通的反弹日，是情绪周期的一次确认："
    elif cycle_key == "亢奋" and pos_cnt >= 2 and ("height" in picked_groups or "heat" in picked_groups):
        headline = "这不是普通的强势日，更像情绪加速后的高位确认："
    elif cycle_key == "冰点" and warn_cnt >= 2:
        headline = "这不是普通的分歧，而是退潮是否止跌的关口："
    elif warn_cnt >= 3:
        headline = "这不是普通的震荡，而是风险是否重新扩散的观察点："
    else:
        headline = "今天不只是情绪波动，关键在于修复是否站稳："

    action_line = " ".join([headline] + [f"{x['icon']} {x['text']}" for x in evidences])

    return {
        "cycle": stage_title,
        "score": round(score, 1),
        "heat": round(heat, 1),
        "risk": round(risk, 1),
        "posture": base["posture"],
        "position": base["position"],
        "action_line": action_line,
        "summary": headline,
        "posture_line": posture_line,
        "evidences": evidences,
        "tags": tags,
    }
