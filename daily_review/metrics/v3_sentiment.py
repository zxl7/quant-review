#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3 六维加权情绪评分引擎（对标规格书模块①）

六维: 涨停热度(20%) / 赚钱效应(25%) / 连板健康度(20%) / 负反馈(15%) / 主线清晰度(10%) / 崩溃前兆链(10%)
输出: 综合分(0-10) + 周期阶段 + 各维分项 + 置信度 + 警告列表
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─── 核心输出数据结构 ──────────────────────────────────────────────
@dataclass
class SentimentResult:
    """六维情绪评分的完整输出"""
    score: float = 0.0              # 综合分 0-10
    phase: str = ""                 # 周期阶段名称
    dim_scores: dict = field(default_factory=dict)  # 六维分项
    warnings: list = field(default_factory=list)     # 警告列表
    confidence: int = 50            # 置信度 0-100
    phase_detail: str = ""          # 阶段详细描述
    phase_strategy: str = ""        # 阶段对应策略


# ─── 阶段映射规则 ──────────────────────────────────────────────────
PHASE_RULES: List[tuple] = [
    (0, 2.0, "🧊 冰点",       "市场极度寒冷",           "空仓/试错"),
    (2.0, 4.0, "❄️ 冰点边缘",   "情绪低迷但有暖意",         "轻仓试错"),
    (4.0, 5.5, "🔄 弱修复",     "僵持格局，不上不下",       "看戏/观望"),
    (5.5, 7.0, "🔥 修复期",     "赚钱效应回暖",           "积极做多"),
    (7.0, 8.5, "🔥🔥 亢奋前期",  "赚钱效应良好",           "重仓出击"),
    (8.5, 10.1, "🚀 亢奋高潮",   "市场狂热",             "持仓/兑现"),
]


# ════════════════════════════════════════════════════════════════════
#  六个维度评分函数
# ════════════════════════════════════════════════════════════════════

def _score_zt_heat(zt_today: int, zt_yest: int) -> float:
    """
    涨停数量热度 0-10分。
    阈值: 100→10, 70→8.5, 50→7, 35→5.5, 20→4, 10→2.5, 否则1
    同时考虑昨日对比：若今日较昨日骤降，适当扣分。
    """
    thresholds = [
        (100, 10.0), (70, 8.5), (50, 7.0), (35, 5.5), (20, 4.0), (10, 2.5),
    ]

    if zt_today >= 100:
        base_score = 10.0
    elif zt_today <= 0:
        base_score = 1.0
    else:
        # 在阈值之间线性插值
        prev_val, prev_score = 0, 1.0
        for val, sc in thresholds:
            if zt_today >= val:
                prev_val, prev_score = val, sc
                break
        else:
            # 未达到任何阈值，用最后一个区间外推
            prev_val, prev_score = 10, 2.5

        # 找到 zt_today 所在区间的上界
        next_val, next_score = 200, 10.0  # 上界默认
        for i, (val, sc) in enumerate(thresholds):
            if zt_today < val:
                next_val, next_score = val, sc
                break
        else:
            next_val, next_score = 100, 10.0

        if next_val > prev_val and next_score != prev_score:
            ratio = (zt_today - prev_val) / (next_val - prev_val)
            base_score = prev_score + ratio * (next_score - prev_score)
        else:
            base_score = prev_score

    # 昨日对比扣分（环比骤降惩罚）
    if zt_yest > 0:
        drop_ratio = (zt_yest - zt_today) / max(1, zt_yest)
        if drop_ratio > 0.3:
            base_score -= 1.0 * min(drop_ratio, 1.0)  # 最多扣1分
        elif drop_ratio > 0.15:
            base_score -= 0.3

    return round(max(0.0, min(10.0, base_score)), 2)


def _score_money_effect(avg_chg: float, promote_rate: float) -> float:
    """
    昨日赚钱效应 0-10分（最重要维度）。
    涨幅权重60% + 晋级率40%

    avg_chg: 昨日涨停票今日平均涨幅%，越高越好
    promote_rate: 晋级率%，越高越好
    """
    # --- 涨幅子维度 0-10 ---
    if avg_chg >= 6.0:
        chg_score = 10.0
    elif avg_chg >= 4.0:
        chg_score = 7.0 + (avg_chg - 4.0) / 2.0 * 3.0  # 4→7, 6→10
    elif avg_chg >= 2.0:
        chg_score = 4.0 + (avg_chg - 2.0) / 2.0 * 3.0  # 2→4, 4→7
    elif avg_chg >= 0.0:
        chg_score = 2.0 + avg_chg / 2.0 * 2.0          # 0→2, 2→4
    elif avg_chg >= -2.0:
        chg_score = 1.0 + (avg_chg + 2.0) / 2.0 * 1.0   # -2→1, 0→2
    else:
        chg_score = max(0.0, 0.5 + avg_chg / 5.0)      # < -2, 最低趋近0

    # --- 晋级率子维度 0-10 ---
    if promote_rate >= 65:
        pro_score = 10.0
    elif promote_rate >= 45:
        pro_score = 7.0 + (promote_rate - 45.0) / 20.0 * 3.0
    elif promote_rate >= 25:
        pro_score = 4.0 + (promote_rate - 25.0) / 20.0 * 3.0
    elif promote_rate >= 10:
        pro_score = 2.0 + (promote_rate - 10.0) / 15.0 * 2.0
    else:
        pro_score = max(0.0, promote_rate / 10.0)

    combined = chg_score * 0.60 + pro_score * 0.40
    return round(max(0.0, min(10.0, combined)), 2)


def _score_lianban_health(lianban_cnt: int, max_h: int, height_hist: list) -> float:
    """
    连板梯队健康度 0-10分。
    数量35% + 高度40% + 趋势25%
    """
    # --- 数量子维度 0-10 ---
    cnt_thresholds = [(50, 10), (30, 8.5), (18, 7), (10, 5.5), (5, 4), (2, 2.5)]
    if lianban_cnt >= 50:
        cnt_score = 10.0
    elif lianban_cnt <= 0:
        cnt_score = 1.0
    else:
        cnt_score = 1.0  # default
        for val, sc in cnt_thresholds:
            if lianban_cnt >= val:
                cnt_score = sc
                break
        # 插值到下一档
        for i in range(len(cnt_thresholds)):
            if lianban_cnt < cnt_thresholds[i][0]:
                if i > 0:
                    lo_v, lo_s = cnt_thresholds[i - 1]
                    hi_v, hi_s = cnt_thresholds[i]
                    if hi_v > lo_v:
                        r = (lianban_cnt - lo_v) / (hi_v - lo_v)
                        cnt_score = lo_s + r * (hi_s - lo_s)
                break

    # --- 高度子维度 0-10 ---
    h_thresholds = [(8, 10), (6, 9), (5, 8), (4, 6.5), (3, 5), (2, 3.5)]
    if max_h >= 8:
        h_score = 10.0
    elif max_h <= 0:
        h_score = 1.0
    else:
        h_score = 1.0
        for val, sc in h_thresholds:
            if max_h >= val:
                h_score = sc
                break
        for i in range(len(h_thresholds)):
            if max_h < h_thresholds[i][0]:
                if i > 0:
                    lo_v, lo_s = h_thresholds[i - 1]
                    hi_v, hi_s = h_thresholds[i]
                    if hi_v > lo_v:
                        r = (max_h - lo_v) / (hi_v - lo_v)
                        h_score = lo_s + r * (hi_s - lo_s)
                break

    # --- 趋势子维度 0-10 ---
    if len(height_hist) >= 2:
        first = height_hist[0] if height_hist[0] is not None else 0
        last = height_hist[-1] if height_hist[-1] is not None else 0
        diff = last - first
        if diff >= 2:
            trend_score = 10.0  # 高度持续上升
        elif diff >= 1:
            trend_score = 7.5
        elif diff >= 0:
            trend_score = 6.0
        elif diff >= -1:
            trend_score = 4.0
        elif diff >= -2:
            trend_score = 2.5
        else:
            trend_score = 1.0
    else:
        trend_score = 5.0  # 无历史数据，给中性分

    combined = cnt_score * 0.35 + h_score * 0.40 + trend_score * 0.25
    return round(max(0.0, min(10.0, combined)), 2)


def _score_negative_feedback(
    zab_cnt: int,
    zab_rate: float,
    nuclear_cnt: int,
    dt_cnt: int,
) -> float:
    """
    负反馈强度 0-10分（越高越安全）。
    炸板35% + 核按钮35% + 跌停30%
    """
    # --- 炸板子维度（越高越差）---
    if zab_rate <= 15:
        zab_score = 10.0
    elif zab_rate <= 25:
        zab_score = 8.0 - (zab_rate - 15.0) / 10.0 * 2.0
    elif zab_rate <= 38:
        zab_score = 6.0 - (zab_rate - 25.0) / 13.0 * 2.5
    elif zab_rate <= 50:
        zab_score = 3.5 - (zab_rate - 38.0) / 12.0 * 2.0
    else:
        zab_score = max(0.0, 1.5 - (zab_rate - 50.0) / 20.0)

    # --- 核按钮子维度（越多越差）---
    if nuclear_cnt == 0:
        nuc_score = 10.0
    elif nuclear_cnt <= 2:
        nuc_score = 8.0 - nuclear_cnt * 1.0
    elif nuclear_cnt <= 5:
        nuc_score = 6.0 - (nuclear_cnt - 2) * 0.8
    elif nuclear_cnt <= 10:
        nuc_score = 3.6 - (nuclear_cnt - 5) * 0.5
    else:
        nuc_score = max(0.0, 1.1 - (nuclear_cnt - 10) * 0.15)

    # --- 跌停子维度（越多越差）---
    if dt_cnt == 0:
        dt_score = 10.0
    elif dt_cnt <= 5:
        dt_score = 9.0 - dt_cnt * 0.2
    elif dt_cnt <= 12:
        dt_score = 8.0 - (dt_cnt - 5) * 0.35
    elif dt_cnt <= 25:
        dt_score = 5.55 - (dt_cnt - 12) * 0.27
    elif dt_cnt <= 40:
        dt_score = 2.05 - (dt_cnt - 25) * 0.11
    else:
        dt_score = max(0.0, 0.4 - (dt_cnt - 40) * 0.03)

    combined = zab_score * 0.35 + nuc_score * 0.35 + dt_score * 0.30
    return round(max(0.0, min(10.0, combined)), 2)


def _score_theme(clear: bool, strength: str, rotation_freq: int) -> float:
    """
    主线清晰度 0-10分。
    强度70% + 轮动稳定性30%
    """
    # --- 主线强度 0-10 ---
    strength_map = {
        "强": 10.0,
        "中": 6.5,
        "弱": 3.5,
        "无": 1.0,
    }
    s_score = strength_map.get(strength, 3.0)

    # 如果明确标记了主线清晰，加分
    if clear and strength in ("强", "中"):
        s_score = min(10.0, s_score + 1.5)

    # --- 轮动稳定性 0-10（切换次数越少越稳定）---
    if rotation_freq <= 0:
        rot_score = 10.0
    elif rotation_freq <= 1:
        rot_score = 8.5
    elif rotation_freq <= 2:
        rot_score = 6.5
    elif rotation_freq <= 3:
        rot_score = 4.5
    else:
        rot_score = max(1.0, 3.0 - (rotation_freq - 3) * 0.8)

    combined = s_score * 0.70 + rot_score * 0.30
    return round(max(0.0, min(10.0, combined)), 2)


def _score_collapse_chain(d: Any) -> float:
    """
    崩溃前兆链检测（满分10逐级扣分）:

    L1-追涨亏损(yest_zt_avg_chg<1%, 扣2分)
    L2-活跃骤降(今日涨停较昨日降>30%, 扣2分)
    L3-诱多形态(指数冲高回落, 扣2分, 有数据才判断)
    L4-高位补跌(高度>=5且核按钮>=2, 扣2分)
    L5-大面积崩溃(跌停>=30, 直接归零)
    天地板额外扣3分
    """
    score = 10.0

    # L1: 追涨亏损 — 昨日涨停票今天不赚钱
    if d.yest_zt_avg_chg < 1.0:
        deduction = min(2.0, 2.0 * max(0, (1.0 - d.yest_zt_avg_chg)) / 3.0)
        score -= deduction

    # L2: 活跃骤降 — 今日涨停数较昨日大幅下降
    if d.zt_count_yesterday > 0:
        drop_pct = (d.zt_count_yesterday - d.zt_count) / d.zt_count_yesterday
        if drop_pct > 0.30:
            score -= 2.0
        elif drop_pct > 0.15:
            score -= 1.0

    # L3: 诱多形态 — 需要扩展字段有数据才判断
    if d.has_trap_pattern:
        score -= 2.0

    # L4: 高位补跌 — 连板高度高但核按钮也多
    if d.max_lianban >= 5 and d.yest_duanban_nuclear >= 2:
        score -= 2.0
    elif d.max_lianban >= 4 and d.yest_duanban_nuclear >= 3:
        score -= 1.5

    # L5: 大面积崩溃 — 跌停家数过多
    if d.dt_count >= 30:
        score = 0.0  # 直接归零
    elif d.dt_count >= 20:
        score -= 3.0
    elif d.dt_count >= 12:
        score -= 1.5

    # 天地板额外扣分
    if d.has_tiandiban:
        score -= 3.0

    return round(max(0.0, min(10.0, score)), 2)


# ════════════════════════════════════════════════════════════════════
#  辅助函数
# ════════════════════════════════════════════════════════════════════

def _map_phase(score: float) -> dict:
    """根据综合分数映射周期阶段"""
    for lo, hi, name, detail, strategy in PHASE_RULES:
        if lo <= score < hi:
            return {"name": name, "detail": detail, "strategy": strategy}
    # 兜底
    return {
        "name": "❄️ 冰点",
        "detail": "市场极度寒冷",
        "strategy": "空仓/试错",
    }


def _calc_score_confidence(scores: dict, d: Any) -> int:
    """计算综合置信度"""
    # 内联实现，避免相对导入问题
    import statistics

    def _calc_confidence(
        *,
        data_completeness: float = 100.0,
        sample_size_score: float = 100.0,
        dimension_consistency: float = 100.0,
        timeliness: float = 100.0,
        extra_deductions: float = 0.0,
    ) -> int:
        raw = (
            data_completeness * 0.30 +
            sample_size_score * 0.25 +
            dimension_consistency * 0.25 +
            timeliness * 0.20
        ) - extra_deductions
        return max(10, min(100, int(round(raw))))

    def _assess_consistency(dim_scores: dict) -> float:
        values = list(dim_scores.values())
        if not values:
            return 50.0
        try:
            std = statistics.stdev(values)
        except statistics.StatisticsError:
            std = 0.0
        if std <= 1.0:
            return 100.0
        elif std <= 2.0:
            return 85.0
        elif std <= 3.0:
            return 65.0
        else:
            return 40.0

    # 数据完整度
    completeness_items = [
        d.zt_count, d.dt_count, d.lianban_count, d.max_lianban,
        d.yest_zt_avg_chg, d.yest_lianban_promote_rate,
    ]
    filled = sum(1 for v in completeness_items if v is not None and v != 0)
    data_completeness = (filled / len(completeness_items)) * 100

    # 样本量得分（基于涨停数和连板数）
    total_active = d.zt_count + d.lianban_count
    if total_active >= 80:
        sample_size = 100.0
    elif total_active >= 40:
        sample_size = 80.0
    elif total_active >= 15:
        sample_size = 55.0
    else:
        sample_size = 30.0

    # 维度一致性
    dim_values = {k: v for k, v in scores.items() if isinstance(v, (int, float))}
    consistency_score = _assess_consistency(dim_values)

    # 时效性（假设当前调用即为当日收盘后）
    timeliness = 95.0

    # 特殊事件扣分
    extra = 0.0
    if d.has_waipan_shock:
        extra += 5.0  # 外盘冲击降低可信度
    if d.is_weekend_ahead:
        extra += 3.0  # 周末前数据可能有提前反应

    return _calc_confidence(
        data_completeness=data_completeness,
        sample_size_score=sample_size,
        dimension_consistency=consistency_score,
        timeliness=timeliness,
        extra_deductions=extra,
    )


def _generate_warnings(scores: dict, d: Any) -> list:
    """生成警告列表"""
    warnings = []

    # 赚钱效应极低
    money = scores.get("money_effect", 0)
    if isinstance(money, (int, float)) and money < 3.0:
        warnings.append(f"⚠️ 赚钱效应极差({money:.1f}/10): 昨日打板票普遍亏钱")

    # 负反馈过高
    neg = scores.get("negative_feedback", 0)
    if isinstance(neg, (int, float)) and neg < 3.0:
        warnings.append(f"⚠️ 负反馈严重({neg:.1f}/10): 炸板/核按钮/跌停风险极高")

    # 崩溃前兆链低分
    collapse = scores.get("collapse_chain", 0)
    if isinstance(collapse, (int, float)) and collapse <= 4.0:
        warnings.append(
            f"⚠️ 崩溃前兆链亮红灯({collapse:.1f}/10): "
            "存在多重崩盘信号"
        )

    # 天地板警告
    if d.has_tiandiban:
        warnings.append("⚠️ 今日出现天地板: 极端亏钱信号")

    # 地天板提示（偏正面但需注意波动性）
    if d.has_ditianban:
        warnings.append("ℹ️ 今日出现地天板: 波动极大，注意风控")

    # 外盘冲击
    if d.has_waipan_shock:
        warnings.append("⚠️ 外盘冲击: 明日可能跳空，需关注隔夜消息")

    # 炸板率异常
    if d.zab_rate > 40:
        warnings.append(f"⚠️ 炸板率{d.zab_rate:.0f}%偏高: 打板被埋概率大")

    # 核按钮密集
    if d.yest_duanban_nuclear >= 5:
        warnings.append(
            f"⚠️ 核按钮{d.yest_duanban_nuclear}家: "
            "断板票遭核按钮打击严重"
        )

    # 高度与晋级矛盾
    if d.max_lianban >= 5 and d.yest_lianban_promote_rate < 25:
        warnings.append(
            "⚠️ 连板高度高但晋级率低: 龙头可能孤军奋战，补涨乏力"
        )

    # 主线模糊且轮动快
    if not d.main_theme_clear and d.theme_rotation_freq >= 3:
        warnings.append(
            "⚠️ 主线模糊且频繁轮动: 追涨极易吃面"
        )

    return warnings


# ════════════════════════════════════════════════════════════════════
#  主入口
# ════════════════════════════════════════════════════════════════════

# 权重定义（总和=100%）
_DIM_WEIGHTS = {
    "zt_heat": 0.20,          # 涨停热度
    "money_effect": 0.25,     # 赚钱效应（最核心）
    "lianban_health": 0.20,   # 连板健康度
    "negative_feedback": 0.15,# 负反馈强度
    "theme": 0.10,            # 主线清晰度
    "collapse_chain": 0.10,   # 崩溃前兆链
}


def calc_sentiment_score(d: Any) -> SentimentResult:
    """
    六维加权评分主入口。

    Args:
        d: SentimentInput 实例（或具有相同字段的兼容对象）

    Returns:
        SentimentResult 包含综合分、阶段、各维分项、警告和置信度
    """
    # ─── 计算六个维度 ──────────────────────────────────────────
    scores = {}

    scores["zt_heat"] = _score_zt_heat(
        zt_today=d.zt_count,
        zt_yest=d.zt_count_yesterday,
    )
    scores["money_effect"] = _score_money_effect(
        avg_chg=d.yest_zt_avg_chg,
        promote_rate=d.yest_lianban_promote_rate,
    )
    scores["lianban_health"] = _score_lianban_health(
        lianban_cnt=d.lianban_count,
        max_h=d.max_lianban,
        height_hist=list(d.height_history or []),
    )
    scores["negative_feedback"] = _score_negative_feedback(
        zab_cnt=d.zab_count,
        zab_rate=d.zab_rate,
        nuclear_cnt=d.yest_duanban_nuclear,
        dt_cnt=d.dt_count,
    )
    scores["theme"] = _score_theme(
        clear=d.main_theme_clear,
        strength=str(d.main_theme_strength),
        rotation_freq=d.theme_rotation_freq,
    )
    scores["collapse_chain"] = _score_collapse_chain(d)

    # ─── 加权求和 ──────────────────────────────────────────────
    raw_score = sum(
        scores.get(key, 0.0) * weight
        for key, weight in _DIM_WEIGHTS.items()
    )
    final_score = round(max(0.0, min(10.0, raw_score)), 2)

    # ─── 阶段映射 ──────────────────────────────────────────────
    phase_info = _map_phase(final_score)

    # ─── 置信度计算 ────────────────────────────────────────────
    confidence = _calc_score_confidence(scores, d)

    # ─── 警告生成 ──────────────────────────────────────────────
    warnings = _generate_warnings(scores, d)

    return SentimentResult(
        score=final_score,
        phase=phase_info["name"],
        dim_scores=scores,
        warnings=warnings,
        confidence=confidence,
        phase_detail=phase_info["detail"],
        phase_strategy=phase_info["strategy"],
    )
