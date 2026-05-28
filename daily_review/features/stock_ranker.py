#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
features.stock_ranker：算法建议（买入 · 观察）核心评分引擎

该模块负责对主线成员股进行深度精选评分，生成具体的买入和观察建议。
采用分层设计：
1. 数据层 (Data Models & Adapters)：定义结构化的评分上下文
2. 算子层 (Scoring Operators)：纯函数实现的维度评分逻辑
3. 策略层 (Advisor Logic)：基于评分结果的分类与筛选策略
4. 表现层 (Presentation)：结果的序列化与摘要生成

遵循函数式编程原则：
- 核心评分逻辑均为纯函数，不依赖外部 I/O
- 使用数据驱动，输入明确，输出可预测
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Dict, List, Tuple

from daily_review.features.ladder_builder import LadderResult, MainLine, TierCell


# ===========================================================================
# 1. 数据层 (Data Models)
# ===========================================================================

Action = Literal["buy", "watch", "skip"]

@dataclass(frozen=True)
class ScoringMetrics:
    """评分所需的原始指标上下文（不可变数据对象）"""
    cell: TierCell
    main_line: MainLine
    sector_zt_count: int
    leaders_score: float
    in_ml_top_sector: str
    in_ml_top_conf: float
    market_gate: str = ""
    market_cycle: str = ""
    market_day_state: str = ""
    market_posture: str = ""
    market_score: float = 0.0
    zt_placement: str = ""
    zt_factor_score: float = 0.0
    zt_leader_factor: float = 0.0
    zt_relay_factor: float = 0.0
    zt_capacity_factor: float = 0.0
    zt_risk_control: float = 0.0
    zt_leader_philosophy: float = 0.0
    zt_break_risk: float = 0.0
    zt_score_band: str = ""

@dataclass
class StockScore:
    """个股评分结果模型"""
    code: str
    name: str
    action: Action
    score: int                              # 总分 0-100
    main_line: str                          # 所属主线名
    primary_sector: str                     # 主线内最强板块
    primary_confidence: float
    breakdown: dict[str, int] = field(default_factory=dict)
    bonus: int = 0
    bonus_reasons: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    lbc: int = 0
    cje_yi: float = 0.0
    seal_fund_yi: float = 0.0
    turnover: float = 0.0
    leaders_score: float = 0.0
    env_adjust: int = 0
    relay_adjust: int = 0
    risk_penalty: int = 0
    zt_placement: str = ""
    style_tag: str = ""
    style_confidence: int = 0
    relay_power_score: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换为前端消费的字典格式"""
        return {
            "code": self.code,
            "name": self.name,
            "action": self.action,
            "score": self.score,
            "main_line": self.main_line,
            "primary_sector": self.primary_sector,
            "primary_confidence": round(self.primary_confidence, 3),
            "breakdown": self.breakdown,
            "bonus": self.bonus,
            "bonus_reasons": self.bonus_reasons,
            "reasons": self.reasons,
            "cautions": self.cautions,
            "lbc": self.lbc,
            "cje_yi": round(self.cje_yi, 2),
            "seal_fund_yi": round(self.seal_fund_yi, 2),
            "turnover": round(self.turnover, 2),
            "leaders_score": round(self.leaders_score, 2),
            "env_adjust": self.env_adjust,
            "relay_adjust": self.relay_adjust,
            "risk_penalty": self.risk_penalty,
            "zt_placement": self.zt_placement,
            "style_tag": self.style_tag,
            "style_confidence": self.style_confidence,
            "relay_power_score": self.relay_power_score,
        }

@dataclass
class MainLinePicks:
    """单条主线的精选结果"""
    main_line: str
    confidence: float
    is_chain: bool
    constituents: list[str] = field(default_factory=list)
    buy: list[StockScore] = field(default_factory=list)
    watch: list[StockScore] = field(default_factory=list)
    summary: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "main_line": self.main_line,
            "confidence": round(self.confidence, 3),
            "is_chain": self.is_chain,
            "constituents": self.constituents,
            "buy": [s.to_dict() for s in self.buy],
            "watch": [s.to_dict() for s in self.watch],
            "summary": self.summary,
            "diagnostics": self.diagnostics,
        }

@dataclass
class PicksAdvisorResult:
    """最终算法建议结果集"""
    date: str
    main_line_picks: list[MainLinePicks] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "main_line_picks": [m.to_dict() for m in self.main_line_picks],
            "diagnostics": self.diagnostics,
        }


# ===========================================================================
# 2. 算子层 (Scoring Operators) - 纯函数
# ===========================================================================

def calc_mainline_fit(conf: float, lbc: int) -> int:
    """维度1: 主线贴合度 (0-20)"""
    if conf >= 0.6 and lbc >= 2: return 20
    if conf >= 0.6: return 16
    if conf >= 0.4 and lbc >= 2: return 14
    if conf >= 0.4: return 10
    if conf > 0: return 6
    return 0

def calc_tier_position(lbc: int, leaders_score: float, cje_yi: float) -> int:
    """维度2: 梯队位置 (0-20)"""
    if lbc == 2 and leaders_score >= 60: return 20     # 先锋龙候选
    if lbc >= 3: return 17                           # 空间板
    if lbc == 2: return 14                           # 普通2板
    if lbc == 1 and cje_yi >= 100: return 16         # 容量核心
    if lbc == 1 and cje_yi >= 30: return 10          # 强首板
    return 6                                         # 普通首板

def calc_volume_score(cje_yi: float) -> int:
    """维度3: 量能量级 (0-15)"""
    if cje_yi >= 100: return 15
    if cje_yi >= 50: return 12
    if cje_yi >= 30: return 9
    if cje_yi >= 10: return 5
    if cje_yi >= 3: return 2
    return 0

def calc_seal_quality(leaders_score: float, seal_fund_yi: float) -> int:
    """维度4: 封板质量 (0-15)"""
    if leaders_score >= 90: return 15
    if leaders_score >= 75: return 11
    if leaders_score >= 60: return 8
    if leaders_score >= 40: return 4
    if seal_fund_yi >= 3: return 6
    return 0

def calc_sector_resonance(zt_count: int) -> int:
    """维度5: 板块强度/共振 (0-10)"""
    if zt_count >= 8: return 10
    if zt_count >= 5: return 7
    if zt_count >= 3: return 4
    return 1

def calc_turnover_health(turnover: float) -> int:
    """维度6: 换手健康度 (0-10)"""
    if 3 <= turnover <= 15: return 10
    if 15 < turnover <= 30: return 6
    if 0 < turnover < 3: return 3
    if turnover > 30: return 2
    return 0

def calc_bonus(metrics: ScoringMetrics) -> tuple[int, list[str]]:
    """特殊加分项 (0-10)"""
    bonus = 0
    reasons = []
    # 先锋龙加成
    if metrics.in_ml_top_conf > 0 and metrics.cell.lbc >= 2 and metrics.leaders_score >= 60:
        bonus += 5
        reasons.append("先锋龙")
    # 独立逻辑
    if metrics.in_ml_top_conf < 0.6 and metrics.sector_zt_count >= 5:
        bonus += 2
        reasons.append("独立逻辑")
    # 20cm 溢价
    if metrics.cell.code.startswith(("300", "688")):
        bonus += 3
        reasons.append("20cm")
    # 首板核心补偿：强辨识度/强封单/强板块的首板，不应被一刀切压没
    if (
        metrics.cell.lbc == 1
        and metrics.in_ml_top_conf >= 0.55
        and metrics.sector_zt_count >= 4
        and (metrics.leaders_score >= 90 or metrics.cell.seal_fund_yi >= 1.5)
    ):
        bonus += 5
        reasons.append("首板核心")
    return min(bonus, 10), reasons


def calc_env_adjust(metrics: ScoringMetrics) -> tuple[int, list[str]]:
    """环境修正：把市场节奏接入原始六维评分。"""
    cell = metrics.cell
    adjust = 0
    reasons: list[str] = []

    gate = metrics.market_gate
    if gate == "进攻窗口":
        adjust += 5 if cell.lbc >= 2 else 2
        reasons.append("进攻窗口")
    elif gate == "接力可做":
        adjust += 3 if cell.lbc >= 2 else 1
        reasons.append("接力可做")
    elif gate == "只做核心":
        adjust -= 2 if cell.lbc >= 2 else 0
        reasons.append("只做核心")
    elif gate in {"防守观察", "休息优先"}:
        adjust -= 5 if cell.lbc >= 2 else 2
        reasons.append("环境防守")

    if metrics.market_cycle == "FERMENT":
        if cell.lbc in (1, 2):
            adjust += 2
            reasons.append("发酵期")
        elif cell.lbc >= 3:
            adjust -= 1
    elif metrics.market_cycle == "START":
        adjust += 2 if cell.lbc <= 2 else 0
    elif metrics.market_cycle == "ICE":
        adjust -= 6 if cell.lbc >= 2 else 3
        reasons.append("冰点")

    if "分歧" in metrics.market_day_state:
        if cell.lbc >= 3:
            adjust -= 4
            reasons.append("分歧高位")
        elif cell.zbc >= 3 or cell.turnover > 30:
            adjust -= 3
            reasons.append("分歧放大")
        else:
            adjust -= 1
    elif "一致" in metrics.market_day_state and cell.lbc == 2:
        adjust += 1

    posture = metrics.market_posture
    if posture in {"防守", "空仓等待"}:
        adjust -= 6
    elif posture in {"控仓试错", "谨慎试错", "谨慎进攻"}:
        adjust -= 2 if cell.lbc >= 2 else 0
    elif posture in {"进攻", "积极试探", "试探进攻"}:
        adjust += 2 if cell.lbc >= 2 else 1

    return max(-12, min(10, adjust)), reasons[:3]


def calc_relay_overlay(metrics: ScoringMetrics) -> tuple[int, list[str], list[str]]:
    """复用 ztAnalysis 的接力/龙头/风险因子。"""
    adjust = 0
    reasons: list[str] = []
    cautions: list[str] = []

    if metrics.zt_placement == "relay":
        adjust += 12
        reasons.append("接力池确认")
    elif metrics.zt_placement == "watch":
        adjust += 5
        reasons.append("观察池候选")

    if metrics.zt_leader_factor >= 80:
        adjust += 4
        reasons.append("龙头因子强")
    elif metrics.zt_leader_factor and metrics.zt_leader_factor < 55 and metrics.cell.lbc >= 2:
        adjust -= 3
        cautions.append("龙头因子弱")

    if metrics.zt_relay_factor >= 80:
        adjust += 4
        reasons.append("接力链条强")
    elif metrics.zt_relay_factor and metrics.zt_relay_factor < 60 and metrics.cell.lbc >= 2:
        adjust -= 2
        cautions.append("接力链条弱")

    if metrics.zt_capacity_factor >= 80 and metrics.cell.cje_yi >= 20:
        adjust += 3
        reasons.append("容量承接强")

    if metrics.zt_leader_philosophy >= 90:
        adjust += 4
        reasons.append("辨识度高")
    elif metrics.zt_leader_philosophy and metrics.zt_leader_philosophy < 65 and metrics.cell.lbc >= 2:
        adjust -= 2
        cautions.append("辨识度一般")

    if metrics.zt_risk_control and metrics.zt_risk_control < 55:
        adjust -= 5
        cautions.append("风险控制弱")

    if metrics.zt_break_risk >= 68:
        adjust -= 6
        cautions.append("断板风险偏高")

    return max(-16, min(22, adjust)), reasons[:4], cautions[:3]


def calc_risk_penalty(metrics: ScoringMetrics) -> tuple[int, list[str]]:
    """额外风险惩罚，直接决定 buy/watch 边界。"""
    cell = metrics.cell
    penalty = 0
    cautions: list[str] = []

    if cell.zbc >= 8:
        penalty += 12
        cautions.append("炸板过多")
    elif cell.zbc >= 4:
        penalty += 5
        cautions.append("炸板偏多")

    if cell.turnover > 35:
        penalty += 6
        cautions.append("换手过热")
    elif cell.turnover > 25:
        penalty += 3
        cautions.append("换手偏高")

    if cell.lbc >= 3 and metrics.market_gate in {"防守观察", "休息优先"}:
        penalty += 6
    if cell.lbc == 1 and metrics.in_ml_top_conf < 0.5 and metrics.cell.cje_yi < 20:
        penalty += 4
        cautions.append("首板强度一般")
    if metrics.zt_placement == "" and cell.lbc == 1 and cell.cje_yi < 10:
        penalty += 3
    # 核心首板的风险折减：允许强辨识度票保留上桌资格
    if (
        cell.lbc == 1
        and cell.zbc <= 4
        and metrics.in_ml_top_conf >= 0.55
        and (metrics.leaders_score >= 90 or metrics.cell.seal_fund_yi >= 1.5)
    ):
        penalty = max(0, penalty - 3)
    return penalty, cautions[:3]


def infer_style_tag(metrics: ScoringMetrics) -> tuple[str, int]:
    """给建议增加交易风格标签。"""
    c = metrics.cell
    if metrics.zt_placement == "relay" and c.lbc >= 2:
        if metrics.zt_leader_philosophy >= 88 or metrics.zt_leader_factor >= 84:
            return "龙头博弈", 92
        return "接力", 82
    if c.cje_yi >= 50 or metrics.zt_capacity_factor >= 78:
        return "容量", 78
    if c.lbc == 1:
        return "低位试错", 72
    return "跟随观察", 60


def calc_relay_power_score(metrics: ScoringMetrics, bd: dict[str, int]) -> int:
    """正式的接力动力分：反映短线接力执行价值，不直接等于总分。"""
    c = metrics.cell
    score = 24.0

    # 1. 位阶与接力资格
    if c.lbc >= 3:
        score += 16
    elif c.lbc == 2:
        score += 13
    elif c.lbc == 1:
        score += 5

    if metrics.zt_placement == "relay":
        score += 10
    elif metrics.zt_placement == "watch":
        score += 5

    # 2. 承接与换手
    score += min(max(c.turnover, 0.0), 30.0) * 0.35 if 3 <= c.turnover <= 30 else (1 if 0 < c.turnover < 3 else -5)
    if c.seal_fund_yi >= 3:
        score += 8
    elif c.seal_fund_yi >= 1:
        score += 5
    elif c.seal_fund_yi >= 0.3:
        score += 2

    # 3. 量能区间更偏向短线接力常见舒适区
    if 8 <= c.cje_yi <= 40:
        score += 6
    elif 40 < c.cje_yi <= 100:
        score += 4
    elif c.cje_yi > 100:
        score += 1
    elif c.cje_yi < 5:
        score -= 3

    # 4. 复用 ztAnalysis 因子
    score += metrics.zt_relay_factor * 0.12
    score += metrics.zt_leader_factor * 0.08
    score += metrics.zt_capacity_factor * 0.05
    score += metrics.zt_leader_philosophy * 0.05

    # 5. 主线与板块加成
    score += bd.get("板块", 0) * 0.8
    score += bd.get("换手", 0) * 0.45
    if metrics.in_ml_top_conf >= 0.6:
        score += 3

    # 6. 风险扣分
    if c.zbc >= 5:
        score -= 10
    elif c.zbc >= 3:
        score -= 6
    elif c.zbc >= 1:
        score -= 2
    if metrics.zt_break_risk >= 68:
        score -= 8
    elif metrics.zt_break_risk >= 55:
        score -= 4
    if c.turnover > 35:
        score -= 6

    return max(0, min(100, round(score)))


# ===========================================================================
# 3. 策略层 (Advisor Logic)
# ===========================================================================

def score_stock(metrics: ScoringMetrics) -> StockScore:
    """
    对个股进行全维度评分并生成理由。
    """
    c = metrics.cell
    
    # 1. 基础六维评分
    bd = {
        "贴合度": calc_mainline_fit(metrics.in_ml_top_conf, c.lbc),
        "梯队": calc_tier_position(c.lbc, metrics.leaders_score, c.cje_yi),
        "量能": calc_volume_score(c.cje_yi),
        "封板": calc_seal_quality(metrics.leaders_score, c.seal_fund_yi),
        "板块": calc_sector_resonance(metrics.sector_zt_count),
        "换手": calc_turnover_health(c.turnover)
    }
    
    # 2. 特殊加分
    bonus, bonus_reasons = calc_bonus(metrics)
    env_adjust, env_reasons = calc_env_adjust(metrics)
    relay_adjust, relay_reasons, relay_cautions = calc_relay_overlay(metrics)
    risk_penalty, risk_cautions = calc_risk_penalty(metrics)
    total_score = max(0, min(100, sum(bd.values()) + bonus + env_adjust + relay_adjust - risk_penalty))
    relay_power_score = calc_relay_power_score(metrics, bd)
    
    # 3. 生成理由与警示
    reasons = _gen_reasons_v2(metrics, bd)
    cautions = _gen_cautions_v2(metrics, bd)
    for text in [*env_reasons, *relay_reasons]:
        if text and text not in reasons:
            reasons.append(text)
    for text in [*relay_cautions, *risk_cautions]:
        if text and text not in cautions:
            cautions.append(text)
    
    return StockScore(
        code=c.code,
        name=c.name,
        action="skip",
        score=total_score,
        main_line=metrics.main_line.name,
        primary_sector=metrics.in_ml_top_sector,
        primary_confidence=metrics.in_ml_top_conf,
        breakdown=bd,
        bonus=bonus,
        bonus_reasons=bonus_reasons,
        reasons=reasons,
        cautions=cautions,
        lbc=c.lbc,
        cje_yi=c.cje_yi,
        seal_fund_yi=c.seal_fund_yi,
        turnover=c.turnover,
        leaders_score=metrics.leaders_score,
        env_adjust=env_adjust,
        relay_adjust=relay_adjust,
        risk_penalty=risk_penalty,
        zt_placement=metrics.zt_placement,
        style_tag=infer_style_tag(metrics)[0],
        style_confidence=infer_style_tag(metrics)[1],
        relay_power_score=relay_power_score,
    )

def _gen_reasons_v2(m: ScoringMetrics, bd: dict[str, int]) -> list[str]:
    """生成买入/观察理由（纯逻辑控制）"""
    out: list[str] = []
    # 主线地位
    if m.in_ml_top_sector:
        tag = "核心" if m.in_ml_top_conf >= 0.6 else ""
        out.append(f"{m.in_ml_top_sector}{tag}")
    # 梯队特征
    if m.cell.lbc >= 3:
        out.append(f"{m.cell.lbc}板高位")
    elif m.cell.lbc == 2:
        out.append(f"2板{'先锋' if bd.get('梯队', 0) >= 20 else '候选'}")
    elif m.cell.lbc == 1 and m.cell.cje_yi >= 100:
        out.append(f"容量核心({m.cell.cje_yi:.0f}亿)")
    # 量能与封单
    if m.cell.lbc >= 2 and m.cell.cje_yi >= 30:
        out.append(f"{m.cell.cje_yi:.0f}亿量能")
    if m.cell.seal_fund_yi >= 3:
        out.append(f"封单{m.cell.seal_fund_yi:.1f}亿")
    elif m.zt_placement == "relay":
        out.append("接力候选")
    # 强度
    if bd.get("板块", 0) >= 7:
        out.append("板块强共振")
    return out[:4]

def _gen_cautions_v2(m: ScoringMetrics, bd: dict[str, int]) -> list[str]:
    """生成警示项（风险控制）"""
    out: list[str] = []
    if m.cell.turnover > 30:
        out.append(f"换手{m.cell.turnover:.0f}%(分歧大)")
    elif m.cell.turnover < 3 and m.cell.lbc >= 2:
        out.append("一字板(无参与)")
    if m.cell.zbc >= 3:
        out.append(f"炸板{m.cell.zbc}次")
    if bd.get("贴合度", 0) <= 6:
        out.append("主线归属弱")
    if m.zt_break_risk >= 68:
        out.append("断板风险高")
    return out[:3]


# ===========================================================================
# 4. 表现层 (Presentation/Integration)
# ===========================================================================

def build_picks_advisor(
    *,
    ladder: LadderResult,
    market_data: dict[str, Any] | None = None,
    top_k_lines: int = 3,
    buy_n: int = 3,
    watch_n: int = 5,
    min_main_line_conf: float = 0.40,
) -> PicksAdvisorResult:
    """
    算法建议（买入 · 观察）主入口。
    
    流程：
    1. 环境准备：提取领导者评分映射、个股池与板块计数
    2. 主线循环：针对每条主线，筛选合规成员并执行 score_stock
    3. 决策筛选：根据得分排序，分配 BUY/WATCH 动作
    4. 结果组装：生成摘要并封装为结果对象
    """
    # 1. 环境准备 (Environment Preparation)
    ls_map = _build_leaders_score_map(market_data) if market_data else {}
    zt_map = _build_zt_analysis_map(market_data) if market_data else {}
    env_ctx = _build_market_env_context(market_data) if market_data else {}
    all_cells = {c.code: c for tier in ladder.tiers.values() for c in tier}
    
    # 预计算板块涨停数
    sec_counts: dict[str, int] = {}
    for c in all_cells.values():
        for s, _ in c.sectors:
            sec_counts[s] = sec_counts.get(s, 0) + 1

    # 2. 主线决策 (Main Line Strategy)
    main_line_picks: list[MainLinePicks] = []
    used_codes: set[str] = set()

    for ml in ladder.main_lines:
        if ml.confidence < min_main_line_conf or len(main_line_picks) >= top_k_lines:
            continue

        # 筛选并评分主线成员
        ml_members: list[StockScore] = []
        for cell in all_cells.values():
            if cell.code in used_codes:
                continue
            
            # 确定该股在当前主线下的最佳契合板块
            ml_pairs = [(s, c) for s, c in cell.sectors if s in ml.constituents]
            if not ml_pairs:
                continue
            
            best_sec, best_conf = max(ml_pairs, key=lambda x: x[1])
            best_sec_zt = max((sec_counts.get(s, 0) for s, _ in ml_pairs), default=0)
            
            # 执行评分算子
            metrics = ScoringMetrics(
                cell=cell,
                main_line=ml,
                sector_zt_count=best_sec_zt,
                leaders_score=ls_map.get(cell.code, 0.0),
                in_ml_top_sector=best_sec,
                in_ml_top_conf=best_conf,
                market_gate=str(env_ctx.get("gate") or ""),
                market_cycle=str(env_ctx.get("cycle") or ""),
                market_day_state=str(env_ctx.get("day_state") or ""),
                market_posture=str(env_ctx.get("posture") or ""),
                market_score=float(env_ctx.get("score") or 0.0),
                zt_placement=str((zt_map.get(cell.code) or {}).get("placement") or ""),
                zt_factor_score=float((zt_map.get(cell.code) or {}).get("factor_score") or 0.0),
                zt_leader_factor=float((zt_map.get(cell.code) or {}).get("leader_factor") or 0.0),
                zt_relay_factor=float((zt_map.get(cell.code) or {}).get("relay_factor") or 0.0),
                zt_capacity_factor=float((zt_map.get(cell.code) or {}).get("capacity_factor") or 0.0),
                zt_risk_control=float((zt_map.get(cell.code) or {}).get("risk_control") or 0.0),
                zt_leader_philosophy=float((zt_map.get(cell.code) or {}).get("leader_philosophy") or 0.0),
                zt_break_risk=float((zt_map.get(cell.code) or {}).get("break_risk") or 0.0),
                zt_score_band=str((zt_map.get(cell.code) or {}).get("score_band") or ""),
            )
            ml_members.append(score_stock(metrics))

        if not ml_members:
            continue

        # 3. 筛选策略 (Selection Strategy)
        ml_members.sort(
            key=lambda s: (
                s.score,
                1 if s.zt_placement == "relay" else 0,
                s.lbc,
                s.cje_yi,
            ),
            reverse=True,
        )

        line_penalty = _main_line_penalty(ml, ml_members, env_ctx)
        if line_penalty:
            for s in ml_members:
                s.score = max(0, s.score - line_penalty)
                s.cautions = list(dict.fromkeys([*s.cautions, f"{ml.name}主线降级"]))

        ml_members.sort(key=_selection_sort_key, reverse=True)

        buy_candidates = [s for s in ml_members if _is_buy_candidate(s)]
        if not buy_candidates and ml_members:
            fallback = ml_members[0]
            if fallback.score >= 50 and fallback.risk_penalty <= 10 and fallback.style_tag != "跟随观察":
                buy_candidates = [fallback]
        if not buy_candidates:
            buy_candidates = _fallback_buy_candidates(ml, ml_members, env_ctx, limit=buy_n)

        buy = _pick_balanced_candidates(
            buy_candidates,
            limit=buy_n,
            style_caps={"龙头博弈": 1, "接力": 1, "容量": 1, "低位试错": 1, "跟随观察": 1},
        )

        buy_codes = {s.code for s in buy}
        watch_floor = _watch_floor(ml, line_penalty, env_ctx)
        watch_candidates = [
            s for s in ml_members
            if s.code not in buy_codes and _is_watch_candidate(s) and s.score >= watch_floor
        ]
        if not watch_candidates:
            watch_candidates = [
                s for s in ml_members
                if s.code not in buy_codes and s.score >= max(42, watch_floor - 3)
            ][:2]
        if not watch_candidates and ml_members:
            watch_candidates = _fallback_watch_candidates(ml_members, buy_codes, limit=min(2, watch_n))

        watch = _pick_balanced_candidates(
            watch_candidates,
            limit=watch_n,
            style_caps={"龙头博弈": 1, "接力": 2, "容量": 2, "低位试错": 2, "跟随观察": 2},
        )
        
        for s in buy: s.action = "buy"
        for s in watch: s.action = "watch"
        for s in buy + watch: used_codes.add(s.code)

        # 4. 组装结果 (Assembly)
        main_line_picks.append(
            MainLinePicks(
                main_line=ml.name,
                confidence=ml.confidence,
                is_chain=ml.is_chain,
                constituents=ml.constituents,
                buy=buy,
                watch=watch,
                summary=_build_summary_v2(ml, buy, watch),
                diagnostics={
                    "member_count": len(ml_members),
                    "avg_score": round(sum(s.score for s in ml_members) / len(ml_members), 1),
                    "env_gate": env_ctx.get("gate"),
                    "relay_hits": sum(1 for s in ml_members if s.zt_placement == "relay"),
                    "line_penalty": line_penalty,
                }
            )
        )

    # 5. 诊断与返回 (Diagnostics)
    return PicksAdvisorResult(
        date=ladder.date,
        main_line_picks=main_line_picks,
        diagnostics={
            "total_buy": sum(len(m.buy) for m in main_line_picks),
            "total_watch": sum(len(m.watch) for m in main_line_picks),
            "main_lines_processed": len(main_line_picks),
            "market_gate": env_ctx.get("gate"),
            "market_cycle": env_ctx.get("cycle"),
        }
    )


# ===========================================================================
# 5. 辅助工具 (Internal Helpers)
# ===========================================================================

def _build_leaders_score_map(market_data: dict[str, Any]) -> dict[str, float]:
    """提取市场数据中的领导者评分映射"""
    out: dict[str, float] = {}
    leaders = market_data.get("leaders", [])
    if not isinstance(leaders, list): return out
    for it in leaders:
        if not isinstance(it, dict): continue
        code = str(it.get("code") or it.get("dm") or "")
        digits = "".join(c for c in code if c.isdigit())[-6:]
        if digits:
            out[digits] = float(it.get("score") or 0.0)
    return out


def _build_zt_analysis_map(market_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    zt = market_data.get("ztAnalysis") if isinstance(market_data, dict) else None
    if not isinstance(zt, dict):
        return out
    for placement in ("relay", "watch"):
        rows = zt.get(placement)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("code") or "").strip()
            if not code:
                continue
            digits = "".join(ch for ch in code if ch.isdigit())[-6:]
            if not digits:
                continue
            out[digits] = {
                "placement": placement,
                "factor_score": float(row.get("factorScore") or row.get("score") or 0.0),
                "leader_factor": float(row.get("leaderFactorScore") or 0.0),
                "relay_factor": float(row.get("relayFactorScore") or 0.0),
                "capacity_factor": float(row.get("capacityFactorScore") or 0.0),
                "risk_control": float(row.get("riskControlScore") or 0.0),
                "leader_philosophy": float(row.get("leaderPhilosophyScore") or 0.0),
                "break_risk": float(row.get("breakRisk") or 0.0),
                "score_band": str(row.get("scoreBand") or ""),
            }
    return out


def _build_market_env_context(market_data: dict[str, Any]) -> dict[str, Any]:
    mood_stage = market_data.get("moodStage") if isinstance(market_data, dict) else {}
    action_advisor = market_data.get("actionAdvisor") if isinstance(market_data, dict) else {}
    zt_meta = ((market_data.get("ztAnalysis") or {}).get("meta") or {}) if isinstance(market_data, dict) else {}
    gate = ((zt_meta.get("marketGate") or {}).get("label") or "")
    score = ((zt_meta.get("environment") or {}).get("score") or 0.0)
    return {
        "gate": str(gate),
        "cycle": str((mood_stage or {}).get("cycle") or ""),
        "day_state": str((mood_stage or {}).get("dayState") or ""),
        "posture": str((action_advisor or {}).get("posture") or ""),
        "score": float(score or 0.0),
    }


def _style_rank(tag: str) -> int:
    return {
        "龙头博弈": 5,
        "接力": 4,
        "容量": 3,
        "低位试错": 2,
        "跟随观察": 1,
    }.get(tag, 0)


def _main_line_penalty(ml: MainLine, members: list[StockScore], env_ctx: dict[str, Any]) -> int:
    """弱主线整条降级，避免弱线硬塞买入。"""
    avg_score = sum(s.score for s in members) / len(members) if members else 0.0
    relay_hits = sum(1 for s in members if s.zt_placement == "relay")
    gate = str(env_ctx.get("gate") or "")
    penalty = 0
    if ml.confidence < 0.58:
        penalty += 4
    if avg_score < 42:
        penalty += 4
    if relay_hits == 0 and ml.confidence < 0.68:
        penalty += 3
    if gate in {"只做核心", "防守观察", "休息优先"} and not any(s.lbc >= 2 for s in members):
        penalty += 2
    return penalty


def _is_buy_candidate(score: StockScore) -> bool:
    if score.style_tag == "龙头博弈":
        return score.score >= 64 and score.risk_penalty <= 14
    if score.zt_placement == "relay":
        return score.score >= 66 and score.risk_penalty <= 12
    if score.style_tag == "容量":
        return score.score >= 60 and score.cje_yi >= 30 and score.risk_penalty <= 10
    if score.lbc >= 2:
        return score.score >= 62 and score.env_adjust >= -4 and score.risk_penalty <= 10
    return score.score >= 58 and score.cje_yi >= 20 and score.risk_penalty <= 8


def _is_watch_candidate(score: StockScore) -> bool:
    if score.score >= 52:
        return True
    if score.zt_placement == "watch" and score.score >= 47:
        return True
    if score.style_tag == "容量" and score.score >= 48 and score.cje_yi >= 20:
        return True
    return score.lbc >= 2 and score.score >= 46


def _watch_floor(ml: MainLine, line_penalty: int, env_ctx: dict[str, Any]) -> int:
    """观察池也要有质量底线，弱线不做低分凑数。"""
    floor = 44
    gate = str(env_ctx.get("gate") or "")
    if ml.confidence < 0.68:
        floor += 2
    if line_penalty >= 6:
        floor += 3
    elif line_penalty >= 3:
        floor += 1
    if gate in {"只做核心", "防守观察", "休息优先"}:
        floor += 2
    return floor


def _selection_sort_key(score: StockScore) -> tuple[float, ...]:
    """排序仍以分数为核心，风格和位置只做增强，不反客为主。"""
    return (
        float(score.score),
        1.5 if score.zt_placement == "relay" else 0.0,
        1.0 if score.style_tag == "龙头博弈" else 0.0,
        0.6 if score.style_tag == "接力" else 0.0,
        0.3 if score.style_tag == "容量" else 0.0,
        float(min(score.lbc, 6)),
        float(min(score.cje_yi / 20.0, 6.0)),
        -float(score.risk_penalty),
    )


def _pick_balanced_candidates(
    candidates: list[StockScore],
    *,
    limit: int,
    style_caps: dict[str, int] | None = None,
) -> list[StockScore]:
    """主线内优先做风格分散，避免同风格扎堆；不够时再回补。"""
    if limit <= 0 or not candidates:
        return []

    ordered = sorted(candidates, key=_selection_sort_key, reverse=True)
    caps = style_caps or {}
    picked: list[StockScore] = []
    used_codes: set[str] = set()
    style_counts: dict[str, int] = {}

    for item in ordered:
        if len(picked) >= limit:
            break
        if item.code in used_codes:
            continue
        tag = item.style_tag or ""
        cap = caps.get(tag, limit)
        if style_counts.get(tag, 0) >= cap:
            continue
        picked.append(item)
        used_codes.add(item.code)
        style_counts[tag] = style_counts.get(tag, 0) + 1

    if len(picked) >= limit:
        return picked

    for item in ordered:
        if len(picked) >= limit:
            break
        if item.code in used_codes:
            continue
        picked.append(item)
        used_codes.add(item.code)

    return picked


def _fallback_buy_candidates(
    ml: MainLine,
    members: list[StockScore],
    env_ctx: dict[str, Any],
    *,
    limit: int,
) -> list[StockScore]:
    """
    成员较少的主线，用相对排序兜底。
    目的不是放松全市场标准，而是让小主线也能给出更接近实战推演的前三顺位。
    """
    if limit <= 0 or not members:
        return []
    gate = str(env_ctx.get("gate") or "")
    if gate not in {"进攻窗口", "接力可做"}:
        return []
    if ml.confidence < 0.62:
        return []
    if len(members) > 6:
        return []

    ordered = sorted(
        members,
        key=lambda s: (
            1 if s.zt_placement in {"relay", "watch"} else 0,
            1 if s.primary_confidence >= 0.8 else 0,
            s.relay_power_score,
            s.score,
            -s.risk_penalty,
            s.cje_yi,
        ),
        reverse=True,
    )
    relaxed: list[StockScore] = []
    for item in ordered:
        if item.risk_penalty >= 8:
            continue
        if item.score < 30 and item.relay_power_score < 45:
            continue
        if item.cje_yi < 3:
            continue
        relaxed.append(item)
        if len(relaxed) >= limit:
            break
    return relaxed


def _fallback_watch_candidates(
    members: list[StockScore],
    excluded_codes: set[str],
    *,
    limit: int,
) -> list[StockScore]:
    """弱主线兜底给出代表票，避免页面只剩主线标题没有个股。"""
    if limit <= 0:
        return []
    candidates = [s for s in members if s.code not in excluded_codes]
    ordered = sorted(
        candidates,
        key=lambda s: (
            1 if s.zt_placement in {"relay", "watch"} else 0,
            s.relay_power_score,
            s.score,
            s.lbc,
            s.cje_yi,
        ),
        reverse=True,
    )
    return ordered[:limit]

def _build_summary_v2(ml: MainLine, buy: list[StockScore], watch: list[StockScore]) -> str:
    """生成主线精选的一句话总结"""
    if not buy: return f"{ml.name}主线暂无明确买入标的"
    
    buy_part = " / ".join(f"{s.name}({s.reasons[0] if s.reasons else '精选'})" for s in buy[:3])
    summary = f"{ml.name}主线，买入 {buy_part}"
    
    if watch:
        watch_part = " · ".join(s.name for s in watch[:4])
        summary += f"，观察 {watch_part}"
    
    return summary
