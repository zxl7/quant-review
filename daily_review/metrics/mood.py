#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
情绪模块（热度 vs 风险 + 阶段 + 卡片）

设计目标：
- FULL：gen_report_v4 负责准备 features.mood_inputs（可复用的中间输入）
- PARTIAL：只改这个文件/阈值，即可重算 mood/moodStage/moodCards 并重新渲染
"""

from __future__ import annotations

from typing import Any, Dict, List

from .scoring import HeatRiskScore, calc_heat_risk
from daily_review.rules.shortline import ACTION_TEMPLATES, STAGE_CN, STAGE_RULES, STAGE_TO_TYPE


def class_for_good_rate(rate: float, hi: float = 60, mid: float = 40) -> str:
    if rate >= hi:
        return "red-text"
    if rate >= mid:
        return "orange-text"
    return "green-text"


def class_for_bad_rate(rate: float, hi: float = 30, mid: float = 15) -> str:
    if rate >= hi:
        return "red-text"
    if rate >= mid:
        return "orange-text"
    return "green-text"


def calc_stage(*, heat_score: float, risk_score: float, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    复刻当前 gen_report_v4 的阶段判定逻辑（便于保持输出一致），后续你可以只改这里的规则。
    """
    fb_rate = float(inputs.get("fb_rate", 0) or 0)
    zb_rate = float(inputs.get("zb_rate", 0) or 0)
    dt_count = int(inputs.get("dt_count", 0) or 0)
    jj_rate = float(inputs.get("jj_rate", 0) or 0)
    bf_count = int(inputs.get("bf_count", 0) or 0)
    rate_2to3 = float(inputs.get("rate_2to3", 0) or 0)
    rate_3to4 = float(inputs.get("rate_3to4", 0) or 0)
    height_gap = int(inputs.get("height_gap", 0) or 0)
    broken_lb_rate = float(inputs.get("broken_lb_rate", 0) or 0)
    zb_high_ratio = float(inputs.get("zb_high_ratio", 0) or 0)
    zt_early_ratio = float(inputs.get("zt_early_ratio", 0) or 0)
    max_lb = int(inputs.get("max_lb", 0) or 0)
    zt_count = int(inputs.get("zt_count", 0) or 0)
    effect_verdict_type = str(inputs.get("effect_verdict_type", "") or "")

    # 趋势（Δ）：用于“情绪流”更早确认（激进模式）
    mood_mode = str(inputs.get("mood_mode", "aggressive") or "aggressive")
    delta_heat = float(inputs.get("delta_heat", 0) or 0)
    delta_risk = float(inputs.get("delta_risk", 0) or 0)
    delta_jj = float(inputs.get("delta_jj_rate", 0) or 0)
    delta_loss = float(inputs.get("delta_loss", 0) or 0)
    jj_1b_rate = float(inputs.get("jj_1b_rate_adj", inputs.get("jj_1b_rate", 0)) or 0)

    def infer_cycle_stage() -> str:
        """
        情绪周期四阶段（最小可用版）：
        - ICE / START / FERMENT / CLIMAX
        """
        max_lb = int(inputs.get("max_lb", 0) or 0)
        zt_cnt = int(inputs.get("zt_count", 0) or 0)
        zb = float(inputs.get("zb_rate", 0) or 0)
        dt = int(inputs.get("dt_count", 0) or 0)

        # 先判最极端（高潮/冰点）
        if max_lb >= (STAGE_RULES["CLIMAX"].get("max_lb_ge") or 6) and zt_cnt >= (STAGE_RULES["CLIMAX"].get("zt_count_ge") or 80) and zb <= (STAGE_RULES["CLIMAX"].get("zb_rate_le") or 20):
            return "CLIMAX"
        if max_lb <= (STAGE_RULES["ICE"].get("max_lb_le") or 3) and zt_cnt < (STAGE_RULES["ICE"].get("zt_count_lt") or 30) and zb >= (STAGE_RULES["ICE"].get("zb_rate_ge") or 40) and dt >= (STAGE_RULES["ICE"].get("dt_count_ge") or 10):
            return "ICE"
        # 再判发酵/启动
        if max_lb >= (STAGE_RULES["FERMENT"].get("max_lb_ge") or 4) and zt_cnt >= (STAGE_RULES["FERMENT"].get("zt_count_ge") or 50) and zb <= (STAGE_RULES["FERMENT"].get("zb_rate_le") or 30):
            return "FERMENT"
        if max_lb >= (STAGE_RULES["START"].get("max_lb_ge") or 2) and zt_cnt >= (STAGE_RULES["START"].get("zt_count_ge") or 30):
            return "START"
        # 兜底：高度太低且涨停偏少时倾向 ICE，否则 START
        return "ICE" if (max_lb <= 2 and zt_cnt < 30) else "START"

    cycle = infer_cycle_stage()

    def decorate(out: Dict[str, Any]) -> Dict[str, Any]:
        """
        将“旧的当日态判定”与“新的周期阶段”融合输出：
        - title：{周期}·{当日态}
        - type：与周期映射对齐（ICE 更偏 fire，CLIMAX 更偏 good）
        - 附带 stance/mode 供 actionGuide/learningNotes 复用
        """
        base_title = str(out.get("title") or "-")
        # 当日态：从旧 title 粗映射（尽量不破坏原算法）
        if base_title in ("退潮", "冰点"):
            day_state = "退潮确认"
        elif base_title in ("高潮", "强修复"):
            day_state = "一致"
        elif base_title == "分歧":
            day_state = "分歧"
        else:
            day_state = "震荡"

        cycle_cn = STAGE_CN.get(cycle, "启动")
        title = f"{cycle_cn}·{day_state}"

        # type 对齐：周期优先，日态做修正
        t = str(out.get("type") or "warn")
        if day_state == "退潮确认":
            t = "fire"
        else:
            # 让周期决定主色
            t = STAGE_TO_TYPE.get(cycle, t) or t

        tpl = ACTION_TEMPLATES.get(cycle, {})
        stance = str(tpl.get("stance") or "")
        mode2 = str(tpl.get("mode") or "")

        detail = str(out.get("detail") or "").strip()
        if detail:
            detail = f"周期：{cycle_cn}｜{detail}"
        else:
            detail = f"周期：{cycle_cn}｜按{stance or '策略'}执行，重点看承接/分歧信号。"

        return {
            **out,
            "title": title,
            "type": t,
            "detail": detail,
            "cycle": cycle,
            "dayState": day_state,
            "stance": stance,
            "mode": mode2,
        }

    # 周期趋势（近 5~7 日）：更贴近“情绪周期上升/下降”的定义
    # 上升：连板高度↑ + 封板成功率↑ + 晋级承接↑
    trend_max_lb = float(inputs.get("trend_max_lb", 0) or 0)
    trend_fb = float(inputs.get("trend_fb_rate", 0) or 0)
    trend_jj = float(inputs.get("trend_jj_rate", 0) or 0)

    # 激进：先用“方向”给一个快速分流（用于早确认修复/转弱）
    if mood_mode == "aggressive":
        # 周期上升：即便当日有分歧，也倾向按“强修复/向上周期”处理（更激进）
        if trend_max_lb >= 1 and trend_fb >= 4 and trend_jj >= 4 and heat_score >= 60 and risk_score < 75 and dt_count <= 10:
            if heat_score >= 82 and max_lb >= 6:
                return decorate({"title": "高潮", "type": "good", "detail": "周期上升（高度/封板/承接同步走强），且空间打开，按高潮处理：聚焦主线核心，警惕分化回撤。"})
            return decorate({"title": "强修复", "type": "good", "detail": "周期上升（高度/封板/承接同步走强），即使盘中分歧也按强修复对待：低位/核心优先。"})

        # 周期下降：提前防守（更早识别退潮）
        if trend_max_lb <= -1 and trend_fb <= -4 and trend_jj <= -4 and risk_score >= 55:
            return decorate({"title": "退潮", "type": "fire", "detail": "周期下降（高度/封板/承接同步走弱），提前防守：减仓、少做接力，等待修复信号。"})

        # 早确认强修复：热度明显上升 + 风险明显下降 + 首板晋级开始修复
        if delta_heat >= 8 and delta_risk <= -6 and jj_1b_rate >= 18 and zt_early_ratio >= 45 and dt_count <= 8:
            return decorate({"title": "强修复", "type": "good", "detail": "热度上升且风险下降，首板晋级修复，按强修复对待：围绕主线核心做低位/回封确认。"})
        # 早确认高潮：热度高位继续抬升 + 空间打开 + 承接不差
        if heat_score >= 82 and delta_heat >= 6 and max_lb >= 6 and (jj_rate >= 40 or rate_2to3 >= 45) and risk_score <= 70:
            return decorate({"title": "高潮", "type": "good", "detail": "热度继续抬升且空间打开，情绪一致性强，注意高潮次日分化与高位回撤。"})
        # 早确认退潮：风险快速抬升 + 亏钱效应扩大（loss↑）
        if risk_score >= 70 and delta_risk >= 8 and delta_loss >= 5 and delta_heat <= 0:
            return decorate({"title": "退潮", "type": "fire", "detail": "风险快速上升且亏钱效应扩散，按退潮处理：减仓防守，少做情绪接力。"})

    # 风险/退潮信号
    risk_hits = 0
    if mood_mode == "aggressive":
        # 激进：风险阈值略抬高，避免轻微波动就判退潮
        risk_hits += 1 if dt_count >= 12 else 0
        risk_hits += 1 if broken_lb_rate >= 40 else 0
    else:
        risk_hits += 1 if dt_count >= 10 else 0
        risk_hits += 1 if broken_lb_rate >= 35 else 0
    # 断板率极高属于“结构性风险”，提高权重（这类场景容易被误判成“弱修复”）
    risk_hits += 1 if broken_lb_rate >= (60 if mood_mode == "aggressive" else 55) else 0
    risk_hits += 1 if zb_high_ratio >= 20 else 0
    risk_hits += 1 if zb_rate >= (32 if mood_mode == "aggressive" else 28) else 0
    risk_hits += 1 if height_gap >= (5 if mood_mode == "aggressive" else 4) else 0
    risk_hits += 1 if risk_score >= 60 else 0
    # 晋级差（承接弱）与“大面扩散”属于盘中最敏感的风险信号
    risk_hits += 1 if jj_rate <= (33 if mood_mode == "aggressive" else 35) else 0
    risk_hits += 1 if bf_count >= (12 if mood_mode == "aggressive" else 10) else 0

    # 趋势修正：风险在下降则降低 risk_hits；风险在上升则提高 risk_hits
    if delta_risk <= -6:
        risk_hits = max(0, risk_hits - 1)
    if delta_risk >= 6:
        risk_hits += 1

    # 强势/一致信号
    strong_hits = 0
    strong_hits += 1 if fb_rate >= (72 if mood_mode == "aggressive" else 78) else 0
    # 晋级率本身也应算作强势信号（比 2→3 更通用）
    strong_hits += 1 if jj_rate >= (40 if mood_mode == "aggressive" else 45) else 0
    strong_hits += 1 if rate_2to3 >= (50 if mood_mode == "aggressive" else 55) else 0
    strong_hits += 1 if rate_3to4 >= (30 if mood_mode == "aggressive" else 35) else 0
    strong_hits += 1 if zt_early_ratio >= (48 if mood_mode == "aggressive" else 55) else 0
    strong_hits += 1 if heat_score >= (70 if mood_mode == "aggressive" else 75) else 0
    # 短线高度突破：提高强势判定权重（6板及以上视为“空间打开”）
    strong_hits += 1 if max_lb >= (5 if mood_mode == "aggressive" else 6) else 0
    # 首板晋级修复：代表“试错盘在变强”（激进模式额外加分）
    if mood_mode == "aggressive":
        strong_hits += 1 if jj_1b_rate >= 18 else 0
        strong_hits += 1 if delta_heat >= 6 else 0
        strong_hits += 1 if delta_jj >= 5 else 0

    if heat_score <= 35 or (fb_rate < 55 and dt_count >= 15) or risk_score >= 80:
        return decorate({"title": "冰点", "type": "fire", "detail": "跌停与断板压力大，短线生态偏弱，等待情绪修复信号。"})

    # 赚钱效应兜底：如果“赚钱效应”模块明确给出 good，则情绪阶段不应过弱
    # 目的：避免出现“赚钱效应极好，但情绪阶段却偏弱”的割裂感（你反馈的场景）
    if effect_verdict_type == "good" and dt_count <= 5 and risk_score < 60:
        if zt_count >= 70 and max_lb >= 6:
            return decorate({"title": "高潮", "type": "good", "detail": "赚钱效应强且空间打开，注意高潮次日分化与高位回撤。"})
        return decorate({"title": "强修复", "type": "good", "detail": "赚钱效应良好，封板与承接偏强，适合围绕主线做低位/核心。"})
    if risk_hits >= 3 and strong_hits <= 1:
        return decorate({"title": "退潮", "type": "fire", "detail": "高位/连板承接走弱，风险信号集中，优先防守，少做接力。"})
    if strong_hits >= 4 and risk_hits <= 1:
        if heat_score >= 85 and (risk_score >= 45 or height_gap >= 3 or zb_rate >= 22):
            return decorate({"title": "高潮", "type": "good", "detail": "一致性强但易分化，注意高潮次日回撤与高位炸板风险。"})
        return decorate({"title": "强修复", "type": "good", "detail": "封板与晋级偏强，短线生态健康，低位与核心接力都有机会。"})
    # 中间态：分歧/弱修复
    # 规则：当“封板/早封”很强，但“晋级/断板/大面”偏差时，本质是结构性分歧，不应落到“弱修复”
    if risk_hits >= 2 and strong_hits >= 2:
        return decorate({"title": "分歧", "type": "warn", "detail": "封板不差但结构承接偏弱（晋级/断板/大面其一走坏），按分歧处理：降低仓位，做回封与低位确定性。"})
    if strong_hits >= 3 and (broken_lb_rate >= 45 or jj_rate <= 35):
        return decorate({"title": "分歧", "type": "warn", "detail": "一致性偏强但晋级/断板不跟随，属于“强分歧”：只做确认，不做情绪硬接力。"})
    return decorate({"title": "弱修复", "type": "warn", "detail": "有修复但承接一般（晋级偏弱），适合轻仓试错，重点观察晋级率与断板率是否改善。"})


def build_cards(inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    复刻 gen_report_v4 当前的 moodCards 输出结构（值/label/note/valueClass）。
    """
    zt_count = int(inputs.get("zt_count", 0) or 0)
    zt_early_ratio = float(inputs.get("zt_early_ratio", 0) or 0)
    zt_early_count = int(inputs.get("zt_early_count", 0) or 0)

    avg_seal_fund_yi = float(inputs.get("avg_seal_fund_yi", 0) or 0)
    top_seal_names = str(inputs.get("top_seal_names", "") or "")

    hs_median = float(inputs.get("hs_median", 0) or 0)
    hs_ge15_ratio = float(inputs.get("hs_ge15_ratio", 0) or 0)

    rate_2to3 = float(inputs.get("rate_2to3", 0) or 0)
    yest_2b = int(inputs.get("yest_2b_count", 0) or 0)
    succ_2to3 = int(inputs.get("succ_2to3", 0) or 0)

    rate_3to4 = float(inputs.get("rate_3to4", 0) or 0)
    yest_3b = int(inputs.get("yest_3b_count", 0) or 0)
    succ_3to4 = int(inputs.get("succ_3to4", 0) or 0)

    height_gap = int(inputs.get("height_gap", 0) or 0)
    max_lb = int(inputs.get("max_lb", 0) or 0)
    second_lb = int(inputs.get("second_lb", 0) or 0)

    zb_high_ratio = float(inputs.get("zb_high_ratio", 0) or 0)
    zb_high_count = int(inputs.get("zb_high_count", 0) or 0)
    zb_count = int(inputs.get("zb_count", 0) or 0)
    zb_high_names = str(inputs.get("zb_high_names", "") or "")

    avg_zt_zbc = float(inputs.get("avg_zt_zbc", 0) or 0)
    zt_zbc_ge3_ratio = float(inputs.get("zt_zbc_ge3_ratio", 0) or 0)

    smallcap_ratio = float(inputs.get("smallcap_ratio", 0) or 0)
    smallcap_cnt = int(inputs.get("smallcap_cnt", 0) or 0)

    broken_lb_rate = float(inputs.get("broken_lb_rate", 0) or 0)
    yest_lb_count = int(inputs.get("yest_lb_count", 0) or 0)
    duanban_count = int(inputs.get("duanban_count", 0) or 0)

    return [
        {
            "value": f"{zt_early_ratio:.0f}%",
            "label": "早盘封板占比",
            "note": f"10点前首封 {zt_early_count} / 涨停 {zt_count}",
            "valueClass": class_for_good_rate(zt_early_ratio, hi=55, mid=35),
        },
        {
            "value": f"{avg_seal_fund_yi:.1f}亿",
            "label": "平均封板资金",
            "note": f"TOP3：{top_seal_names}",
            "valueClass": ("red-text" if avg_seal_fund_yi >= 2.0 else ("orange-text" if avg_seal_fund_yi >= 1.0 else "green-text")),
        },
        {
            "value": f"{hs_median:.1f}%",
            "label": "涨停换手(中位)",
            "note": f"高换手(≥15%) {hs_ge15_ratio:.0f}%",
            "valueClass": ("red-text" if hs_median >= 10 else ("orange-text" if hs_median >= 6 else "green-text")),
        },
        {
            "value": f"{rate_2to3:.0f}%",
            "label": "2进3成功率",
            "note": f"昨日2板 {yest_2b} → 今3板+ {succ_2to3}",
            "valueClass": class_for_good_rate(rate_2to3, hi=55, mid=35),
        },
        {
            "value": f"{rate_3to4:.0f}%",
            "label": "3进4成功率",
            "note": f"昨日3板 {yest_3b} → 今4板+ {succ_3to4}",
            "valueClass": class_for_good_rate(rate_3to4, hi=45, mid=25),
        },
        {
            "value": f"{height_gap}",
            "label": "高度差",
            "note": f"最高{max_lb}板 / 次高{second_lb}板",
            "valueClass": ("orange-text" if height_gap >= 3 else ("blue-text" if height_gap == 2 else "green-text")),
        },
        {
            "value": f"{zb_high_ratio:.1f}%",
            "label": "高位炸板占比(4板+)",
            "note": f"高位炸板 {zb_high_count} / 炸板 {zb_count}（{zb_high_names if zb_high_names else '无'}）",
            "valueClass": class_for_bad_rate(zb_high_ratio, hi=20, mid=8),
        },
        {
            "value": f"{avg_zt_zbc:.1f}",
            "label": "涨停炸板次数(均)",
            "note": f"高炸板(≥3次) {zt_zbc_ge3_ratio:.0f}%",
            "valueClass": class_for_bad_rate(zt_zbc_ge3_ratio, hi=18, mid=8),
        },
        {
            "value": f"{smallcap_ratio:.0f}%",
            "label": "小票活跃度(<50亿)",
            "note": f"小票 {smallcap_cnt} / 涨停 {zt_count}",
            "valueClass": class_for_good_rate(smallcap_ratio, hi=55, mid=35),
        },
        {
            "value": f"{broken_lb_rate:.0f}%",
            "label": "连板断板率",
            "note": f"昨日连板 {yest_lb_count} → 断板 {duanban_count}",
            "valueClass": class_for_bad_rate(broken_lb_rate, hi=35, mid=20),
        },
    ]


def rebuild_mood(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    统一输出：
    - mood
    - moodStage
    - moodCards
    """
    # 情绪判定/评分使用“平滑版”指标（避免样本小导致的剧烈跳变）
    # 展示卡片仍然使用 inputs 中的原始值（更符合直觉口径，且便于复盘对照）
    jj_rate_eff = float(inputs.get("jj_rate_adj", inputs.get("jj_rate", 0)) or 0)
    broken_lb_rate_eff = float(inputs.get("broken_lb_rate_adj", inputs.get("broken_lb_rate", 0)) or 0)

    score: HeatRiskScore = calc_heat_risk(
        fb_rate=float(inputs.get("fb_rate", 0) or 0),
        jj_rate=jj_rate_eff,
        zt_count=int(inputs.get("zt_count", 0) or 0),
        zt_early_ratio=float(inputs.get("zt_early_ratio", 0) or 0),
        zb_rate=float(inputs.get("zb_rate", 0) or 0),
        dt_count=int(inputs.get("dt_count", 0) or 0),
        bf_count=int(inputs.get("bf_count", 0) or 0),
        zb_high_ratio=float(inputs.get("zb_high_ratio", 0) or 0),
        broken_lb_rate=broken_lb_rate_eff,
    )

    # 阶段判定同样用“平滑版”输入（只影响判断，不影响卡片展示）
    stage_inputs = dict(inputs)
    stage_inputs["jj_rate"] = jj_rate_eff
    stage_inputs["broken_lb_rate"] = broken_lb_rate_eff
    stage_inputs["rate_2to3"] = float(inputs.get("rate_2to3_adj", inputs.get("rate_2to3", 0)) or 0)
    stage_inputs["rate_3to4"] = float(inputs.get("rate_3to4_adj", inputs.get("rate_3to4", 0)) or 0)
    stage = calc_stage(heat_score=score.heat, risk_score=score.risk, inputs=stage_inputs)
    cards = build_cards(inputs)
    return {
        "mood": {"heat": score.heat, "risk": score.risk, "score": score.sentiment},
        "moodStage": stage,
        "moodCards": cards,
    }
