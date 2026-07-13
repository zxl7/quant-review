#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3 题材催化分析引擎（Stock Catalyst Hunter 方法论固化）

把「事件 -> 实时搜索 -> 多层传导推理 -> A股题材/个股映射（概率+时间维度）」
的题材猎手方法论，固化为确定性评分算法，供 v3_mainstream 等主线判定模块消费。

解决的问题：
    v3_mainstream.judge_mainline / classify_theme_level 需要 market_share_pct /
    active_days / is_national_policy / has_complete_ladder 等「市场叙事信号」，
    但当前 ztgc 缓存不提供这些字段，导致主线常年退化为 NO_THEME、strength="无"。
    本引擎把这些信号从无到有地构造出来（基于外部注入的事件/叙事/个股输入），
    使主线判定层恢复可用。

设计约束（与系统一致）：
    - 纯函数 + 确定性评分：不在此做网络搜索。事件、叙事强度、个股映射等市场信号
      由外部注入（手动填写，或由未来的 catalyst 命令/缓存供给）。
    - 输出契约对齐 v3_mainstream.judge_mainline / classify_theme_level 所需字段，
      经 catalyst_sectors_to_mainline_input() 直接转换，无需改动消费方代码。
    - 数值工具统一复用 daily_review.utils.num，避免新增 _to_num 副本。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from daily_review.utils.num import to_float, to_int


# ==================== 枚举定义 ====================

class ClaimType(Enum):
    """事件性质（决定默认政策级与传导链起点）"""
    POLICY = "政策"
    GEOPOLITICS = "地缘冲突"
    SANCTION = "制裁/限制出口"
    ACCIDENT = "事故/突发"
    ORDER = "订单/中标"
    PERFORMANCE = "业绩"
    PRICE_RISE = "涨价"
    SUPPLY_SHORTAGE = "供给扰动/断供"
    RUMOR = "传闻"


class PolicyLevel(Enum):
    """政策/影响级别（题材强度的最高权重维度）"""
    NATIONAL = "国策级"
    INDUSTRY = "产业级"
    REGIONAL = "区域级"
    COMPANY = "公司级"
    SENTIMENT = "情绪级"


# 政策级 -> 0-10 基准分（题材强度计算用）
_POLICY_BASE_SCORE = {
    PolicyLevel.NATIONAL: 10.0,
    PolicyLevel.INDUSTRY: 8.0,
    PolicyLevel.REGIONAL: 6.0,
    PolicyLevel.COMPANY: 4.0,
    PolicyLevel.SENTIMENT: 3.0,
}

# 事件性质 -> 默认政策级（当外部未显式指定时）
_CLAIM_DEFAULT_POLICY = {
    ClaimType.POLICY: PolicyLevel.NATIONAL,
    ClaimType.GEOPOLITICS: PolicyLevel.NATIONAL,
    ClaimType.SANCTION: PolicyLevel.INDUSTRY,
    ClaimType.ACCIDENT: PolicyLevel.REGIONAL,
    ClaimType.ORDER: PolicyLevel.INDUSTRY,
    ClaimType.PERFORMANCE: PolicyLevel.COMPANY,
    ClaimType.PRICE_RISE: PolicyLevel.INDUSTRY,
    ClaimType.SUPPLY_SHORTAGE: PolicyLevel.INDUSTRY,
    ClaimType.RUMOR: PolicyLevel.SENTIMENT,
}


class LogicType(Enum):
    """个股关联逻辑类型（区分硬逻辑与题材炒作）"""
    INDUSTRIAL = "产业硬逻辑"
    POLICY = "政策逻辑"
    SUPPLY_DEMAND = "供需逻辑"
    SUBSTITUTION = "替代/国产替代"
    HISTORY_MAPPING = "历史映射"
    SENTIMENT = "题材炒作"


class TimeHorizon(Enum):
    """盘面时间维度"""
    TODAY = "当天"
    D1_3 = "1-3天"
    D1_2W = "1-2周"
    BAND = "波段"
    MID = "中期"


# ==================== 输入数据结构 ====================

@dataclass
class CatalystStock:
    """单只关联个股（由外部搜索/手动注入）"""
    code: str = ""
    name: str = ""
    logic_type: LogicType = LogicType.SENTIMENT
    reason: str = ""
    probability: float = 50.0      # 0-100 关联把握度（外部注入或默认）
    time_horizon: TimeHorizon = TimeHorizon.D1_3
    hardness: float = 5.0          # 0-10 逻辑硬度（硬逻辑 > 软联想）


@dataclass
class CatalystInput:
    """催化事件的结构化输入（外部注入，本引擎不做搜索）"""
    event_summary: str = ""                       # 事件原文/摘要
    claim_type: ClaimType = ClaimType.RUMOR       # 事件性质
    is_fact: bool = False                         # 已发生事实 vs 未来预期
    policy_level: Optional[PolicyLevel] = None    # 可外部指定，否则自动归类
    affected_sectors: List[str] = field(default_factory=list)   # 受影响产业/商品
    affected_regions: List[str] = field(default_factory=list)   # 受影响区域
    narrative_strength: float = 5.0   # 0-10 市场叙事强度（资讯平台提及密度，外部注入）
    persistence_days: int = 1         # 叙事持续天数（active_days 代理）
    beneficiary_stocks: List[CatalystStock] = field(default_factory=list)  # 受益股
    risk_stocks: List[CatalystStock] = field(default_factory=list)        # 风险股
    history_mapping: bool = False      # 历史类似事件是否炒过
    substitution_logic: bool = False   # 是否含国产替代/替代逻辑
    supply_demand_shock: bool = False  # 是否供给/需求扰动
    # 可选：真实市场成交占比%（若有则优先，否则由 theme_strength 推导代理值）
    estimated_market_share_pct: Optional[float] = None


# ==================== 输出数据结构 ====================

@dataclass
class CatalystResult:
    """题材催化分析结果"""
    event_conclusion: str = ""
    main_benefit_directions: List[str] = field(default_factory=list)
    main_risk_directions: List[str] = field(default_factory=list)
    theme_strength: float = 0.0            # 0-10 题材综合强度
    policy_level: PolicyLevel = PolicyLevel.SENTIMENT
    transmission_layers: List[Dict] = field(default_factory=list)  # 传导链
    sectors: List[Dict] = field(default_factory=list)   # 直接对齐 judge_mainline
    stock_maps: List[Dict] = field(default_factory=list)  # 个股映射（已校准概率）
    confidence: int = 50                  # 0-100 输入完整度置信


# ==================== 核心评分函数（纯函数） ====================

def classify_policy_level(inp: CatalystInput) -> PolicyLevel:
    """判定政策/影响级别：外部指定优先，否则按事件性质默认归类。"""
    if inp.policy_level is not None:
        return inp.policy_level
    return _CLAIM_DEFAULT_POLICY.get(inp.claim_type, PolicyLevel.SENTIMENT)


def score_theme_strength(
    *,
    policy_level: PolicyLevel,
    narrative_strength: float,
    persistence_days: int,
    max_hardness: float,
) -> float:
    """
    题材综合强度（0-10），四维加权：
        - 政策级基准（30%）
        - 市场叙事强度（35%）
        - 叙事持续性（15%，persistence_days 折算）
        - 最硬逻辑硬度（20%，取受益股最高 hardness）
    权重合计 1.0，输出截断 [0, 10]。
    """
    policy_score = _POLICY_BASE_SCORE.get(policy_level, 3.0)
    narrative = max(0.0, min(10.0, to_float(narrative_strength, 5.0)))
    # 持续性：天数 * 1.2 截断到 10（8天≈9.6，10天封顶）
    persistence_score = max(0.0, min(10.0, to_float(persistence_days, 1) * 1.2))
    hardness_score = max(0.0, min(10.0, to_float(max_hardness, 5.0)))

    strength = (
        0.30 * policy_score
        + 0.35 * narrative
        + 0.15 * persistence_score
        + 0.20 * hardness_score
    )
    return round(max(0.0, min(10.0, strength)), 2)


def build_transmission_layers(inp: CatalystInput, policy_level: PolicyLevel) -> List[Dict]:
    """
    构建多层传导链（至少 2-3 层，对应题材猎手「直接影响 -> 二阶传导 -> A股映射」）。
    依据事件性质与逻辑标志生成结构化描述，不依赖实时搜索。
    """
    layers: List[Dict] = []

    # 第一层：事件直接影响
    direct = _describe_direct(inp)
    layers.append({"layer": 1, "type": "直接影响", "desc": direct})

    # 第二层：二阶传导（价格/成本/供需/政策/替代）
    second = _describe_second_order(inp)
    if second:
        layers.append({"layer": 2, "type": "二阶传导", "desc": second})

    # 第三层：A股映射（硬逻辑优先于情绪联想）
    a_map = _describe_a_share_mapping(inp, policy_level)
    layers.append({"layer": 3, "type": "A股映射", "desc": a_map})

    return layers


def _describe_direct(inp: CatalystInput) -> str:
    """第一层：事件直接冲击的对象。"""
    sectors = "、".join(inp.affected_sectors) or "相关产业"
    regions = "、".join(inp.affected_regions)
    region_txt = f"（{regions}）" if regions else ""
    fact_txt = "已发生" if inp.is_fact else "预期"
    base = f"{inp.claim_type.value}{fact_txt}：直接冲击{sectors}{region_txt}"
    return base


def _describe_second_order(inp: CatalystInput) -> str:
    """第二层：沿产业链/政策链/区域链的传导。"""
    parts: List[str] = []
    if inp.supply_demand_shock:
        parts.append("供给端受扰 → 相关商品价格/成本波动，向下游利润传导")
    if inp.substitution_logic:
        parts.append("触发替代逻辑 → 国产替代/自主可控预期升温")
    if inp.claim_type in (ClaimType.POLICY, ClaimType.SANCTION):
        parts.append("政策或限制加码 → 行业准入/技术路线/出口结构重塑")
    if inp.claim_type == ClaimType.GEOPOLITICS:
        parts.append("地缘风险 → 能源/航运/避险资产价格预期先动")
    if inp.history_mapping:
        parts.append("历史类似事件曾形成板块映射，情绪记忆增强")
    if not parts:
        parts.append("影响沿产业链向上下游与关联商品扩散")
    return "；".join(parts)


def _describe_a_share_mapping(inp: CatalystInput, policy_level: PolicyLevel) -> str:
    """第三层：A股最可能交易的段落（硬逻辑优先）。"""
    if inp.beneficiary_stocks:
        hard = [s for s in inp.beneficiary_stocks if s.hardness >= 6]
        soft = [s for s in inp.beneficiary_stocks if s.hardness < 6]
        lead = "产业/供需/政策硬逻辑" if hard else "题材情绪联想"
        txt = f"市场优先交易{lead}："
        if hard:
            txt += "、".join(f"{s.name}({s.logic_type.value})" for s in hard[:3])
        if soft:
            txt += ("；" if hard else "") + f"短线情绪标的：{soft[0].name}"
        return txt
    if policy_level == PolicyLevel.NATIONAL:
        return "市场优先交易国策级方向的核心资产与龙头"
    return "暂缺个股映射（需外部搜索补充），先观察板块方向"


def adjust_stock_probability(
    *,
    stock: CatalystStock,
    theme_strength: float,
    confidence: int,
) -> float:
    """
    校准个股关联概率：
        - 基准 = 外部注入概率
        - 硬度修正：硬度每偏离 5 一个单位，±1.5 分（硬逻辑加成、软联想扣分）
        - 置信修正：输入完整度低时整体下修（乘以 0.7~1.0 系数）
    输出截断 [1, 99]。
    """
    base = max(1.0, min(99.0, to_float(stock.probability, 50.0)))
    hard_adj = (to_float(stock.hardness, 5.0) - 5.0) * 1.5
    conf_factor = 0.7 + 0.3 * (max(0, min(100, confidence)) / 100.0)
    adjusted = base * conf_factor + hard_adj
    return round(max(1.0, min(99.0, adjusted)), 1)


def compute_confidence(inp: CatalystInput) -> int:
    """输入完整度置信（0-100）：缺关键信号则下调，避免对空数据过度自信。"""
    score = 0
    if inp.event_summary.strip():
        score += 10
    if inp.claim_type != ClaimType.RUMOR:
        score += 10
    if to_float(inp.narrative_strength, 0) > 0:
        score += 20
    if to_int(inp.persistence_days, 0) > 1:
        score += 10
    if inp.beneficiary_stocks:
        score += 25
    if inp.risk_stocks:
        score += 10
    if inp.history_mapping or inp.substitution_logic or inp.supply_demand_shock:
        score += 15
    return max(10, min(100, score))


# ==================== 与 v3_mainstream 的契约转换 ====================

def _ladder_readiness(beneficiary: List[CatalystStock]) -> Dict[str, Any]:
    """根据受益股硬度推断梯队完整度（供 classify_theme_level 使用）。"""
    hard_cnt = sum(1 for s in beneficiary if to_float(s.hardness, 5) >= 6)
    return {
        "complete": hard_cnt >= 3,
        "partial": hard_cnt >= 1,
        "health_score": min(10.0, 2.0 + hard_cnt * 1.6),
    }


def catalyst_sectors_to_mainline_input(inp: CatalystInput, theme_strength: float) -> List[Dict]:
    """
    把催化输入转为 judge_mainline 可直接消费的 sectors 列表。

    每个 sector 含：
        name / market_share_pct / active_days / is_national_policy /
        has_complete_ladder / has_partial_ladder / ladder_info
    从而让 classify_theme_level 不再因缺字段而退化为 NO_THEME。

    market_share_pct：优先用外部注入的 estimated_market_share_pct；
    否则由 theme_strength 推导代理值（strength*2，封顶 25%），明确为代理。
    """
    policy_level = classify_policy_level(inp)
    ladder = _ladder_readiness(inp.beneficiary_stocks)

    if inp.estimated_market_share_pct is not None:
        share = to_float(inp.estimated_market_share_pct, 0.0)
    else:
        share = min(25.0, theme_strength * 2.0)

    sectors: List[Dict] = []
    names = inp.affected_sectors or ["催化题材"]
    for name in names:
        sectors.append({
            "name": name,
            "market_share_pct": round(share, 2),
            "active_days": to_int(inp.persistence_days, 1),
            "is_national_policy": policy_level == PolicyLevel.NATIONAL,
            "has_complete_ladder": ladder["complete"],
            "has_partial_ladder": ladder["partial"],
            "ladder_info": {
                "health_score": round(ladder["health_score"], 2),
                "health_grade": ("A" if ladder["health_score"] >= 8
                                else "B" if ladder["health_score"] >= 6
                                else "C" if ladder["health_score"] >= 4
                                else "D"),
            },
        })
    return sectors


# ==================== 主入口 ====================

def analyze_catalyst(inp: CatalystInput) -> CatalystResult:
    """
    题材催化分析主入口：事件判定 -> 多层传导 -> 题材强度 -> 个股映射校准。

    纯确定性计算，不触发任何网络请求。
    """
    policy_level = classify_policy_level(inp)
    max_hardness = (
        max((to_float(s.hardness, 5.0) for s in inp.beneficiary_stocks), default=5.0)
        if inp.beneficiary_stocks else 5.0
    )

    theme_strength = score_theme_strength(
        policy_level=policy_level,
        narrative_strength=inp.narrative_strength,
        persistence_days=inp.persistence_days,
        max_hardness=max_hardness,
    )

    confidence = compute_confidence(inp)
    layers = build_transmission_layers(inp, policy_level)
    sectors = catalyst_sectors_to_mainline_input(inp, theme_strength)

    # 个股映射（校准概率）
    stock_maps: List[Dict] = []
    for s in inp.beneficiary_stocks + inp.risk_stocks:
        stock_maps.append({
            "code": s.code,
            "name": s.name,
            "logic_type": s.logic_type.value,
            "probability": adjust_stock_probability(
                stock=s, theme_strength=theme_strength, confidence=confidence
            ),
            "time_horizon": s.time_horizon.value,
            "hardness": s.hardness,
            "reason": s.reason,
            "role": "受益" if s in inp.beneficiary_stocks else "风险",
        })

    # 方向归纳
    benefit = list(inp.affected_sectors)
    if inp.substitution_logic:
        benefit.append("国产替代/自主可控")
    risk = [f"{s.name}（{s.reason}）" for s in inp.risk_stocks] or ["暂无明显风险方向"]

    conclusion = (
        f"{inp.claim_type.value}事件：题材强度 {theme_strength}/10，"
        f"政策级 {policy_level.value}，"
        f"主受益方向 {'、'.join(benefit) or '待定'}。"
    )

    return CatalystResult(
        event_conclusion=conclusion,
        main_benefit_directions=benefit,
        main_risk_directions=risk,
        theme_strength=theme_strength,
        policy_level=policy_level,
        transmission_layers=layers,
        sectors=sectors,
        stock_maps=stock_maps,
        confidence=confidence,
    )


# ==================== 序列化（缓存读写用） ====================

def _enum_val(v: Any, default: Any) -> Any:
    return v.value if isinstance(v, Enum) else default


def _stock_to_dict(s: "CatalystStock") -> Dict[str, Any]:
    return {
        "code": s.code,
        "name": s.name,
        "logic_type": _enum_val(s.logic_type, "题材炒作"),
        "reason": s.reason,
        "probability": s.probability,
        "time_horizon": _enum_val(s.time_horizon, "1-3天"),
        "hardness": s.hardness,
    }


def _stock_from_dict(d: Dict[str, Any]) -> "CatalystStock":
    try:
        lt = LogicType(d.get("logic_type", "题材炒作"))
    except Exception:
        lt = LogicType.SENTIMENT
    try:
        th = TimeHorizon(d.get("time_horizon", "1-3天"))
    except Exception:
        th = TimeHorizon.D1_3
    return CatalystStock(
        code=str(d.get("code", "")),
        name=str(d.get("name", "")),
        logic_type=lt,
        reason=str(d.get("reason", "")),
        probability=to_float(d.get("probability", 50), 50),
        time_horizon=th,
        hardness=to_float(d.get("hardness", 5), 5),
    )


def catalyst_input_to_dict(inp: "CatalystInput") -> Dict[str, Any]:
    """CatalystInput -> JSON 可序列化 dict（供缓存写入）。"""
    return {
        "event_summary": inp.event_summary,
        "claim_type": _enum_val(inp.claim_type, "传闻"),
        "is_fact": inp.is_fact,
        "policy_level": _enum_val(inp.policy_level, None) if inp.policy_level is not None else None,
        "affected_sectors": list(inp.affected_sectors),
        "affected_regions": list(inp.affected_regions),
        "narrative_strength": inp.narrative_strength,
        "persistence_days": inp.persistence_days,
        "beneficiary_stocks": [_stock_to_dict(s) for s in inp.beneficiary_stocks],
        "risk_stocks": [_stock_to_dict(s) for s in inp.risk_stocks],
        "history_mapping": inp.history_mapping,
        "substitution_logic": inp.substitution_logic,
        "supply_demand_shock": inp.supply_demand_shock,
        "estimated_market_share_pct": inp.estimated_market_share_pct,
    }


def catalyst_input_from_dict(d: Dict[str, Any]) -> "CatalystInput":
    """JSON dict -> CatalystInput（供缓存读取，带字段容错）。"""
    pl = d.get("policy_level")
    try:
        claim = ClaimType(d.get("claim_type", "传闻"))
    except Exception:
        claim = ClaimType.RUMOR
    try:
        pol = PolicyLevel(pl) if pl else None
    except Exception:
        pol = None
    return CatalystInput(
        event_summary=str(d.get("event_summary", "")),
        claim_type=claim,
        is_fact=bool(d.get("is_fact", False)),
        policy_level=pol,
        affected_sectors=list(d.get("affected_sectors") or []),
        affected_regions=list(d.get("affected_regions") or []),
        narrative_strength=to_float(d.get("narrative_strength", 5), 5),
        persistence_days=to_int(d.get("persistence_days", 1), 1),
        beneficiary_stocks=[_stock_from_dict(x) for x in (d.get("beneficiary_stocks") or [])],
        risk_stocks=[_stock_from_dict(x) for x in (d.get("risk_stocks") or [])],
        history_mapping=bool(d.get("history_mapping", False)),
        substitution_logic=bool(d.get("substitution_logic", False)),
        supply_demand_shock=bool(d.get("supply_demand_shock", False)),
        estimated_market_share_pct=(
            to_float(d["estimated_market_share_pct"], 0)
            if d.get("estimated_market_share_pct") is not None else None
        ),
    )


# ==================== 自检（仅在直接运行时执行） ====================

if __name__ == "__main__":
    # 示例：日本限制半导体材料出口（对应题材猎手示例2）
    sample = CatalystInput(
        event_summary="日本可能限制部分半导体材料对华出口",
        claim_type=ClaimType.SANCTION,
        is_fact=False,
        affected_sectors=["光刻胶", "半导体材料", "电子化学品"],
        narrative_strength=7.5,
        persistence_days=3,
        beneficiary_stocks=[
            CatalystStock(code="300576", name="容大感光", logic_type=LogicType.SUBSTITUTION,
                          reason="光刻胶国产替代核心标的", probability=71,
                          time_horizon=TimeHorizon.D1_2W, hardness=7.5),
            CatalystStock(code="300236", name="上海新阳", logic_type=LogicType.SUBSTITUTION,
                          reason="半导体材料链自主可控", probability=69,
                          time_horizon=TimeHorizon.BAND, hardness=7.0),
        ],
        risk_stocks=[
            CatalystStock(code="", name="依赖进口高端材料制造环节", logic_type=LogicType.INDUSTRIAL,
                          reason="受限环节成本与供应风险", probability=60,
                          time_horizon=TimeHorizon.MID, hardness=6.0),
        ],
        substitution_logic=True,
        history_mapping=True,
    )
    res = analyze_catalyst(sample)
    print(f"结论: {res.event_conclusion}")
    print(f"题材强度: {res.theme_strength}/10 | 政策级: {res.policy_level.value} | 置信: {res.confidence}")
    print("传导链:")
    for ly in res.transmission_layers:
        print(f"  L{ly['layer']} [{ly['type']}] {ly['desc']}")
    print(f"主线 sectors（供 judge_mainline）: {res.sectors}")
    print("个股映射:")
    for m in res.stock_maps:
        print(f"  {m['name']} | {m['role']} | 概率 {m['probability']}% | {m['time_horizon']} | {m['logic_type']}")
