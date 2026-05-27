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
    return min(bonus, 10), reasons


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
    total_score = sum(bd.values()) + bonus
    
    # 3. 生成理由与警示
    reasons = _gen_reasons_v2(metrics, bd)
    cautions = _gen_cautions_v2(metrics, bd)
    
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
        leaders_score=metrics.leaders_score
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
                in_ml_top_conf=best_conf
            )
            ml_members.append(score_stock(metrics))

        if not ml_members:
            continue

        # 3. 筛选策略 (Selection Strategy)
        ml_members.sort(key=lambda s: (s.score, s.lbc, s.cje_yi), reverse=True)
        
        buy = ml_members[:buy_n]
        watch = ml_members[buy_n : buy_n + watch_n]
        
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
                    "avg_score": round(sum(s.score for s in ml_members) / len(ml_members), 1)
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
            "main_lines_processed": len(main_line_picks)
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

def _build_summary_v2(ml: MainLine, buy: list[StockScore], watch: list[StockScore]) -> str:
    """生成主线精选的一句话总结"""
    if not buy: return f"{ml.name}主线暂无明确买入标的"
    
    buy_part = " / ".join(f"{s.name}({s.reasons[0] if s.reasons else '精选'})" for s in buy[:3])
    summary = f"{ml.name}主线，买入 {buy_part}"
    
    if watch:
        watch_part = " · ".join(s.name for s in watch[:4])
        summary += f"，观察 {watch_part}"
    
    return summary
