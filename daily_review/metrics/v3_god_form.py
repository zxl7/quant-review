#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3 神/形辨析体系

神 = 周期地位内核(难伪造): 周期位置/成交排名/主线地位/运行天数
形 = K线技术指标(可伪造): 放量阳线/连红/均线多头/放量/MACD金叉/KDJ超买

核心原则:
- 神>=7 且 形>=7 => 神形兼备（真龙概率极高）
- 神>=7 且 形<5  => 神似形不似（真龙潜形，短期技术待修复）
- 神<5  且 形>=7 => 形似神不似（警惕人造龙头!）
- 神<5  且 形<5  => 神形皆不符（非龙头）

神形降级: 若 god_score<4 但 overall>=7, 则 overall 降为 max(god_score, 4)
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class DragonScore:
    """龙头评分结果"""
    leading_score: float = 0.0      # 带领性 0-10
    breakthrough_score: float = 0.0  # 突破性 0-10
    uniqueness_score: float = 0.0   # 唯一性 0-10
    overall: float = 0.0            # 综合分 = min(三要素)
    grade: str = "D"                # S/A/B/C/D
    is_real_dragon: bool = False     # 是否真龙
    god_form_analysis: dict = field(default_factory=dict)  # 神形辨析详情
    confidence: int = 50             # 置信度 0-100


# ==================== 带领性评估 ====================

def _calc_leading_internal(stock: Dict, ctx: Dict) -> float:
    """带领性: 个股涨幅vs板块平均 + 板块内排名

    评分维度 (满分10):
    - 相对板块超额收益 (0-4分): 个股涨幅 - 板块均幅，每超1%加0.2分，上限4分
    - 板块内涨跌排名 (0-3分): 排名越靠前分数越高
    - 带动效应 (0-3分): 个股大涨时板块跟涨程度
    """
    score = 0.0

    # 1. 相对板块超额收益 (0-4分)
    stock_chg = stock.get("change_pct", 0) or 0       # 个股涨幅%
    sector_avg_chg = ctx.get("sector_avg_change", 0) or 0  # 板块平均涨幅
    excess = stock_chg - sector_avg_chg                 # 超额收益

    excess_score = min(4.0, max(0.0, excess * 0.2 + 1.0))  # 基础1分+超额加成
    score += excess_score

    # 2. 板块内排名 (0-3分)
    sector_rank = stock.get("sector_rank")               # 板块内排名(1-based)
    sector_total = ctx.get("sector_stock_count", 10)      # 板块个股总数

    if sector_rank is not None and sector_total > 0:
        rank_ratio = sector_rank / sector_total          # 越小越好
        rank_score = max(0.0, 3.0 - rank_ratio * 3.0)     # 前1名=3分, 后几名趋近0
        score += rank_score

    # 3. 带动效应 (0-3分)
    correlation = stock.get("sector_correlation")         # 与板块联动系数
    if correlation is not None:
        drive_score = correlation * 3.0                   # 完全联动=3分
        score += drive_score
    else:
        score += 1.5  # 无数据给中间分

    return round(min(10.0, max(0.0, score)), 2)


# ==================== 突破性评估 ====================

def _calc_breakthrough_internal(stock: Dict) -> float:
    """突破性: 新高/均线突破/放量突破/连板本身

    评分维度 (满分10):
    - 新高突破 (0-3分): 是否创历史/阶段新高
    - 均线系统 (0-3分): 均线多头排列程度
    - 放量突破 (0-2分): 成交量放大倍数
    - 连板高度 (0-2分): 连续涨停板数量
    """
    score = 0.0

    # 1. 新高突破 (0-3分)
    is_new_high = stock.get("is_new_high")
    is_period_high = stock.get("is_period_high")  # 阶段新高(如60日)

    if is_new_high:
        score += 3.0
    elif is_period_high:
        score += 2.0
    else:
        # 用近期最高价对比判断
        high = stock.get("high", 0) or 0
        period_high = stock.get("period_high", 0) or 0
        if period_high > 0 and high >= period_high * 0.98:
            score += 1.5

    # 2. 均线系统 (0-3分)
    ma5 = stock.get("ma5", 0) or 0
    ma10 = stock.get("ma10", 0) or 0
    ma20 = stock.get("ma20", 0) or 0
    ma60 = stock.get("ma60", 0) or 0

    ma_scores = 0
    valid_ma = 0
    if ma10 > 0:
        valid_ma += 1
        if ma5 > 0 and ma5 > ma10:
            ma_scores += 1
    if ma20 > 0:
        valid_ma += 1
        if ma10 > 0 and ma10 > ma20:
            ma_scores += 1
    if ma60 > 0:
        valid_ma += 1
        if ma20 > 0 and ma20 > ma60:
            ma_scores += 1

    if valid_ma > 0:
        score += (ma_scores / valid_ma) * 3.0

    # 3. 放量突破 (0-2分)
    vol = stock.get("volume", 0) or 0
    avg_vol = stock.get("avg_volume_5d", 0) or 0

    if avg_vol > 0 and vol > 0:
        vol_ratio = vol / avg_vol
        if vol_ratio >= 3.0:
            score += 2.0
        elif vol_ratio >= 2.0:
            score += 1.5
        elif vol_ratio >= 1.5:
            score += 1.0
        else:
            score += 0.5
    else:
        score += 0.5

    # 4. 连板高度 (0-2分)
    consecutive_boards = stock.get("consecutive_boards", 0) or 0
    if consecutive_boards >= 7:
        score += 2.0
    elif consecutive_boards >= 5:
        score += 1.5
    elif consecutive_boards >= 3:
        score += 1.0
    elif consecutive_boards >= 1:
        score += 0.5

    return round(min(10.0, max(0.0, score)), 2)


# ==================== 唯一性评估 ====================

def _calc_uniqueness_internal(stock: Dict, ctx: Dict) -> float:
    """唯一性: 板块龙头地位/成交占比/辨识度/主线地位

    评分维度 (满分10):
    - 板块龙头地位 (0-3分): 是否为板块公认龙头
    - 成交额占比 (0-3分): 个股成交占板块总成交比例
    - 辨识度/市场知名度 (0-2分): 市场讨论度/辨识度指标
    - 主线地位 (0-2分): 所处题材是否为主线
    """
    score = 0.0

    # 1. 板块龙头地位 (0-3分)
    is_sector_leader = stock.get("is_sector_leader")
    leader_status = stock.get("leader_status")  # dragon/dragon_2/follower/none

    if is_sector_leader is True or leader_status == "dragon":
        score += 3.0
    elif leader_status == "dragon_2":
        score += 2.0
    elif leader_status == "follower":
        score += 1.0
    else:
        # 通过排名推断
        rank = stock.get("sector_rank")
        if rank is not None and rank <= 3:
            score += 2.0
        elif rank is not None and rank <= 8:
            score += 1.0

    # 2. 成交额占比 (0-3分)
    amount = stock.get("amount", 0) or 0           # 成交额
    sector_total_amount = ctx.get("sector_total_amount", 0) or 0

    if sector_total_amount > 0 and amount > 0:
        ratio = amount / sector_total_amount
        if ratio >= 0.30:                          # 占比30%+
            score += 3.0
        elif ratio >= 0.15:
            score += 2.0
        elif ratio >= 0.08:
            score += 1.0
        else:
            score += 0.3
    else:
        score += 1.0  # 无数据给中间分

    # 3. 辨识度/市场关注度 (0-2分)
    attention = stock.get("attention_score")       # 关注度得分
    hot_rank = stock.get("hot_rank")               # 热榜排名

    if attention is not None:
        score += min(2.0, attention / 50.0)
    elif hot_rank is not None:
        if hot_rank <= 5:
            score += 2.0
        elif hot_rank <= 20:
            score += 1.0
        else:
            score += 0.3
    else:
        score += 0.5

    # 4. 主线地位 (0-2分)
    theme_level = ctx.get("theme_level")            # 主流级别
    is_mainline = stock.get("is_mainline")

    if theme_level == "mainstream" or is_mainline is True:
        score += 2.0
    elif theme_level == "sub_stream":
        score += 1.3
    elif theme_level == "minor_stream":
        score += 0.5
    else:
        score += 0.3

    return round(min(10.0, max(0.0, score)), 2)


# ==================== 神 vs 形辨析 ====================

def _analyze_god_vs_form(stock: Dict, market_context: Dict) -> dict:
    """神vs形辨析核心

    返回: {form_score, god_score, form_items, god_items, verdict, fake_risk, fake_warning}
    """

    # --- 形 (Form) 分项 ---
    form_items = {}

    # F1: 放量阳线 (0-2分)
    chg_pct = stock.get("change_pct", 0) or 0
    vol_ratio = stock.get("vol_ratio", 1) or 1
    if chg_pct > 5 and vol_ratio >= 1.5:
        form_items["放量阳线"] = 2.0
    elif chg_pct > 3 and vol_ratio >= 1.2:
        form_items["放量阳线"] = 1.3
    elif chg_pct > 0:
        form_items["放量阳线"] = 0.7
    else:
        form_items["放量阳线"] = 0.0

    # F2: 连红 (0-2分)
    red_days = stock.get("consecutive_red_days", 0) or 0
    if red_days >= 5:
        form_items["连红天数"] = 2.0
    elif red_days >= 3:
        form_items["连红天数"] = 1.3
    elif red_days >= 1:
        form_items["连红天数"] = 0.7
    else:
        form_items["连红天数"] = 0.0

    # F3: 均线多头 (0-2分)
    ma_bullish = stock.get("ma_bullish_count", 0) or 0  # 多头均线数
    form_items["均线多头"] = round(min(2.0, ma_bullish * 0.5), 2)

    # F4: 放量程度 (0-2分)
    if vol_ratio >= 3.0:
        form_items["放量程度"] = 2.0
    elif vol_ratio >= 2.0:
        form_items["放量程度"] = 1.3
    elif vol_ratio >= 1.3:
        form_items["放量程度"] = 0.7
    else:
        form_items["放量程度"] = 0.3

    # F5: MACD金叉 (0-1分)
    macd_golden = stock.get("macd_golden_cross")
    form_items["MACD金叉"] = 1.0 if macd_golden else 0.0

    # F6: KDJ超买 (0-1分) - 注意：超买在龙头战法中可能是正面信号
    kdj_overbought = stock.get("kdj_overbought")
    form_items["KDJ超买"] = 0.8 if kdj_overbought else 0.2

    form_score = sum(form_items.values())
    max_form = 10.0
    form_normalized = min(10.0, (form_score / max_form) * 10.0) if max_form > 0 else 0

    # --- 神 (God) 分项 ---
    god_items = {}

    # G1: 周期位置 (0-3分)
    cycle_position = market_context.get("cycle_position", "")  # 冰点/修复/亢奋/分歧
    cycle_map = {
        "冰点": 1.0, "修复": 2.0, "分歧": 2.5, "亢奋": 3.0,
        "startup": 1.5, "acceleration": 2.5, "divergence": 2.0, "climax": 1.0,
    }
    cycle_score = cycle_map.get(str(cycle_position).lower(), 1.5)
    god_items["周期位置"] = round(cycle_score, 2)

    # G2: 成交排名 (0-3分)
    market_rank = stock.get("market_volume_rank") or stock.get("market_rank")
    if market_rank is not None:
        if market_rank <= 5:
            god_items["成交排名"] = 3.0
        elif market_rank <= 20:
            god_items["成交排名"] = 2.0
        elif market_rank <= 50:
            god_items["成交排名"] = 1.0
        else:
            god_items["成交排名"] = 0.3
    else:
        god_items["成交排名"] = 1.0

    # G3: 主线地位 (0-2分)
    theme_level = market_context.get("theme_level", "")
    theme_god_map = {
        "mainstream": 2.0, "sub_stream": 1.3, "minor_stream": 0.5, "no_theme": 0.1,
    }
    god_items["主线地位"] = theme_god_map.get(str(theme_level).lower(), 0.5)

    # G4: 运行天数/持续性 (0-2分)
    run_days = stock.get("theme_run_days", 0) or market_context.get("theme_run_days", 0) or 0
    if run_days >= 10:
        god_items["运行天数"] = 2.0
    elif run_days >= 5:
        god_items["运行天数"] = 1.3
    elif run_days >= 2:
        god_items["运行天数"] = 0.7
    else:
        god_items["运行天数"] = 0.2

    god_score = sum(god_items.values())

    # --- 综合判词 ---
    god_norm = min(10.0, god_score)
    form_norm = min(10.0, form_normalized)

    if god_norm >= 7 and form_norm >= 7:
        verdict = "神形兼备（真龙概率极高）"
        fake_risk = "低"
        fake_warning = ""
    elif god_norm >= 7 and form_norm < 5:
        verdict = "神似形不似（真龙潜形，短期技术待修复）"
        fake_risk = "低"
        fake_warning = "注意短期技术面修复节奏"
    elif god_norm < 5 and form_norm >= 7:
        verdict = "形似神不似（警惕人造龙头!）"
        fake_risk = "高"
        fake_warning = "⚠️ 技术面完美但缺乏核心地位支撑，疑似资金造势"
    elif god_norm < 5 and form_norm < 5:
        verdict = "神形皆不符（非龙头）"
        fake_risk = "中"
        fake_warning = ""
    else:  # 中间状态
        verdict = "神形参半（需进一步观察）"
        fake_risk = "中"
        fake_warning = ""

    return {
        "form_score": round(form_norm, 2),
        "god_score": round(god_norm, 2),
        "form_items": form_items,
        "god_items": god_items,
        "verdict": verdict,
        "fake_risk": fake_risk,
        "fake_warning": fake_warning,
    }


# ==================== 龙头评级 ====================

def _grade_dragon_internal(overall: float) -> str:
    """评级: >=8.5->S, >=7->A, >=5.5->B, >=4->C, else->D"""
    if overall >= 8.5:
        return "S"
    elif overall >= 7.0:
        return "A"
    elif overall >= 5.5:
        return "B"
    elif overall >= 4.0:
        return "C"
    else:
        return "D"


# ==================== 主入口 ====================

def calc_three_elements(stock: Dict, market_context: Dict) -> DragonScore:
    """龙头三要素量化主入口

    Args:
        stock: 个股数据字典，需包含:
            - change_pct: 涨跌幅%
            - volume, amount: 成交量和成交额
            - consecutive_boards: 连板数
            - ma5/ma10/ma20/ma60: 均线
            - is_new_high/is_period_high: 是否新高
            - sector_rank: 板块排名
            - is_sector_leader: 是否板块龙头
            - leader_status: dragon/dragon_2/follower/none
            - attention_score/hot_rank: 关注度
            - vol_ratio: 量比
            - consecutive_red_days: 连红天数
            - macd_golden_cross: MACD金叉
            - kdj_overbought: KDJ超买
            - theme_run_days: 题材运行天数
            - market_volume_rank: 全市场成交排名

        market_context: 市场上下文字典，需包含:
            - sector_avg_change: 板块平均涨幅
            - sector_stock_count: 板块个股总数
            - sector_total_amount: 板块总成交额
            - sector_correlation: 板块联动系数
            - theme_level: 主流级别
            - cycle_position: 周期位置
            - theme_run_days: 题材持续天数

    Returns:
        DragonScore: 完整的龙头评分结果
    """
    # 三要素分别打分
    leading = _calc_leading_internal(stock, market_context)
    breakthrough = _calc_breakthrough_internal(stock)
    uniqueness = _calc_uniqueness_internal(stock, market_context)

    # 综合分 = 三者取最小（木桶效应）
    overall_raw = min(leading, breakthrough, uniqueness)

    # 神形辨析
    god_form = _analyze_god_vs_form(stock, market_context)
    god_score = god_form["god_score"]

    # 神形降级: 若 god_score < 4 但 overall >= 7, 则 overall 降为 max(god, 4)
    if god_score < 4.0 and overall_raw >= 7.0:
        overall = max(god_score, 4.0)
    else:
        overall = overall_raw

    grade = _grade_dragon_internal(overall)

    # 判定是否真龙: S或A级且神形兼备
    is_real_dragon = (grade in ("S", "A")
                      and god_form.get("fake_risk") == "低")

    # 置信度评估
    confidence = 50
    required_stock_keys = [
        "change_pct", "volume", "consecutive_boards",
        "sector_rank", "amount",
    ]
    present_stock = sum(1 for k in required_stock_keys if stock.get(k) is not None)
    confidence += min(25, present_stock * 5)

    required_ctx_keys = [
        "sector_avg_change", "sector_stock_count",
        "theme_level", "cycle_position",
    ]
    present_ctx = sum(1 for k in required_ctx_keys
                      if market_context.get(k) is not None)
    confidence += min(25, present_ctx * 6)

    return DragonScore(
        leading_score=round(leading, 2),
        breakthrough_score=round(breakthrough, 2),
        uniqueness_score=round(uniqueness, 2),
        overall=round(overall, 2),
        grade=grade,
        is_real_dragon=is_real_dragon,
        god_form_analysis=god_form,
        confidence=min(100, confidence),
    )
