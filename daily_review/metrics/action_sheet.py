#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
metrics.action_sheet：操作单生成引擎

该模块将抽象的市场情绪指标转化为具体的交易指令。
遵循分层设计与函数式编程原则：
1. 数据适配层 (Data Adapter)：从原始 market_data 提取并规范化指标
2. 逻辑判定层 (Decision Logic)：纯函数判定立场、模式及规则
3. 构造层 (Builder)：组装最终的结构化操作单

设计原则：
- 不写股评，只给操作条件
- 每条指令都有明确的触发条件和仓位建议
- 纯数据驱动，逻辑透明
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ===========================================================================
# 1. 数据模型 (Data Models)
# ===========================================================================

@dataclass(frozen=True)
class MarketMetrics:
    """市场核心指标快照"""
    stage: str
    stage_type: str
    sublabel: str
    fb_rate: float
    jj_rate: float
    zb_rate: float
    zt_count: int
    dt_count: int
    bf_count: int
    max_lb: int
    broken_lb_rate: float
    rate_2to3: float
    heat: float
    risk: float
    vol_chg: float
    yest_zt_avg_chg: float
    main_theme: str
    theme_net: float
    theme_risk: float
    leader_name: str
    leader_b: int
    risk_trend_up: bool

@dataclass(frozen=True)
class ActionPlan:
    """操作计划结论"""
    stance: str
    mode: str
    one_line: str


# ===========================================================================
# 2. 逻辑判定层 (Decision Logic) - 纯函数
# ===========================================================================

def _n(v: Any, d: float = 0.0) -> float:
    """安全数值转换"""
    try:
        if v is None: return d
        if isinstance(v, str): v = v.replace("%", "").strip()
        return float(v)
    except Exception:
        return d

def determine_stance(m: MarketMetrics) -> str:
    """判定基本立场：进攻/防守/均衡"""
    if m.heat >= 70 and m.risk <= 40 and m.fb_rate >= 70:
        return "进攻"
    if m.risk >= 60 or m.bf_count >= 10 or m.fb_rate <= 55:
        return "防守"
    if m.stage_type == "good":
        return "进攻"
    if m.stage_type == "fire":
        return "防守"
    return "均衡"

def determine_mode(m: MarketMetrics, stance: str) -> str:
    """判定交易模式：接力/套利/低位试错/休息"""
    if m.stage_type == "fire" or stance == "休息" or m.risk_trend_up:
        return "休息"
    if m.theme_net < 9 or m.fb_rate < 55 or m.jj_rate < 25:
        return "低位试错"
    if m.zb_rate >= 28 or m.bf_count >= 8:
        return "套利"
    return "接力"

def generate_buy_list(m: MarketMetrics, mode: str) -> List[Dict[str, str]]:
    """生成买入指令列表"""
    if mode == "休息":
        return []
    
    buys = []
    # 1. 主线确认点
    if m.main_theme:
        pos = "≤2成" if mode == "低位试错" else ("≤3成" if mode == "接力" else "≤1成")
        buys.append({
            "condition": f"主线确认：{m.main_theme}净强≥{max(m.theme_net-1,0):.0f}",
            "target": f"{m.main_theme}题材内2进3确认 / 龙首回封",
            "position": pos,
            "reason": f"当前主线净强{m.theme_net:.1f}，风险{m.theme_risk:.1f}",
        })

    # 2. 高度打开后的接力
    if m.max_lb >= 5 and m.rate_2to3 >= 35:
        buys.append({
            "condition": f"龙头({m.leader_name})晋级{m.leader_b+1}板成功",
            "target": "同梯队补涨 / 分支龙首板",
            "position": "≤2成",
            "reason": f"空间已打开(最高{m.max_lb}板)，2进3成功率{m.rate_2to3:.0f}%",
        })

    # 3. 真修复信号
    if "真修复" in m.sublabel or (m.yest_zt_avg_chg >= 2.0 and m.stage in ("弱修复",)):
        buys.append({
            "condition": "昨日涨停股今平均涨幅仍>2%（资金在回流）",
            "target": "主线首板 / 1进2确认",
            "position": "≤2成",
            "reason": f"昨日涨停票今日均涨{m.yest_zt_avg_chg:+.1f}%，是真修复不是诱多",
        })
    return buys

def generate_empty_list(m: MarketMetrics) -> List[Dict[str, str]]:
    """生成空仓/观望触发条件"""
    empties = []
    if m.bf_count >= 15:
        empties.append({"trigger": f"大面扩散≥{m.bf_count}只", "action": "立刻停止新开仓，现有持仓减半"})
    if m.broken_lb_rate >= 50:
        empties.append({"trigger": f"连板断板率{m.broken_lb_rate:.0f}%≥50%", "action": "不做任何接力，高位票优先出"})
    if m.risk >= 75:
        empties.append({"trigger": f"综合风险分{m.risk:.0f}≥75", "action": "空仓观望"})
    if m.stage_type == "fire":
        empties.append({"trigger": f"情绪阶段：{m.stage}", "action": "休息为主，最多小仓打首板"})
    
    if not empties:
        empties.append({"trigger": "无明确风险信号", "action": "按模式执行，但单笔亏损超5%必砍"})
    return empties

def generate_risk_line(m: MarketMetrics) -> str:
    """生成风险红线警告"""
    lines = []
    if m.stage_type == "fire":
        lines.append(f"当前处于「{m.stage}」，任何追高都是送钱")
    if m.max_lb >= 6:
        lines.append(f"最高板已达{m.max_lb}板，高潮次日分化概率大")
    if m.zb_rate >= 30:
        lines.append(f"炸板率{m.zb_rate:.0f}%偏高，追板容易被埋")
    if m.vol_chg <= -15:
        lines.append(f"量能萎缩{m.vol_chg:+.0f}%，缩量行情不追高")
    if not lines:
        lines.append("单笔止损线：买入价跌5%无条件离场")
    return "；".join(lines)


# ===========================================================================
# 3. 构造层 (Builder)
# ===========================================================================

def build_action_sheet(market_data: Dict[str, Any]) -> Dict[str, Any]:
    """操作单主入口"""
    md = market_data or {}
    
    # 1. 提取并规范化指标 (Data Extraction)
    m = _extract_metrics(md)
    
    # 2. 执行逻辑判定 (Logic Execution)
    stance = determine_stance(m)
    mode = determine_mode(m, stance)
    
    emoji_map = {"进攻": "🟢", "防守": "🔴", "均衡": "🟡"}
    one_line = f"{emoji_map.get(stance,'')} {m.stage}{'·'+m.sublabel if m.sublabel else ''} | 主线:{m.main_theme or '未识别'} | 龙头:{m.leader_name}({m.leader_b}板) | 建议:{stance}"
    
    # 3. 组装结果 (Assembly)
    return {
        "summary": {
            "stage": m.stage,
            "sublabel": m.sublabel,
            "stance": stance,
            "mode": mode,
            "oneLine": one_line,
        },
        "buy": generate_buy_list(m, mode),
        "hold": [], 
        "empty": generate_empty_list(m),
        "riskLine": generate_risk_line(m),
        "keyNumbers": {
            "zt": m.zt_count,
            "fb": round(m.fb_rate, 1),
            "jj": round(m.jj_rate, 1),
            "zb": round(m.zb_rate, 1),
            "dt": m.dt_count,
            "heat": round(m.heat, 0),
            "risk": round(m.risk, 0),
            "maxLb": m.max_lb,
            "volChg": round(m.vol_chg, 1),
        },
        "meta": {
            "precision": "data_driven",
            "note": "操作单基于当日收盘数据自动生成，仅供参考。交易决策请结合盘面实时变化。",
        },
    }

def _extract_metrics(md: dict) -> MarketMetrics:
    """从 market_data 深度提取所有业务指标"""
    mi = (md.get("features") or {}).get("mood_inputs") or {}
    delta = md.get("delta") or {}
    stage_info = md.get("moodStage") or {}
    
    # 主线提取
    tp = md.get("themePanels") or {}
    theme_rows = tp.get("strengthRows") or []
    main_theme, theme_net, theme_risk = "", 0.0, 0.0
    if theme_rows:
        best = max(theme_rows, key=lambda r: _n(r.get("net"), 0) - _n(r.get("risk"), 0) * 0.6)
        main_theme, theme_net, theme_risk = str(best.get("name") or ""), _n(best.get("net")), _n(best.get("risk"))

    # 龙头提取
    ladder = md.get("ladder") or []
    leader_name, leader_b = "—", 0
    if ladder:
        leader_b = max(int(_n(r.get("badge"))) for r in ladder)
        tops = [r.get("name", "") for r in ladder if int(_n(r.get("badge"))) == leader_b]
        leader_name = "、".join(tops[:2]) if tops else "—"

    return MarketMetrics(
        stage=stage_info.get("title") or "-",
        stage_type=stage_info.get("type") or "warn",
        sublabel=stage_info.get("sublabel") or "",
        fb_rate=_n(mi.get("fb_rate")),
        jj_rate=_n(mi.get("jj_rate")),
        zb_rate=_n(mi.get("zb_rate")),
        zt_count=int(_n(mi.get("zt_count"))),
        dt_count=int(_n(mi.get("dt_count"))),
        bf_count=int(_n(mi.get("bf_count"))),
        max_lb=int(_n(mi.get("max_lb"))),
        broken_lb_rate=_n(mi.get("broken_lb_rate")),
        rate_2to3=_n(mi.get("rate_2to3")),
        heat=_n((md.get("mood") or {}).get("heat")),
        risk=_n((md.get("mood") or {}).get("risk")),
        vol_chg=_n(((md.get("volume") or {}).get("change"))),
        yest_zt_avg_chg=_n(mi.get("yest_zt_avg_chg")),
        main_theme=main_theme,
        theme_net=theme_net,
        theme_risk=theme_risk,
        leader_name=leader_name,
        leader_b=leader_b,
        risk_trend_up=(_n(delta.get("zb_rate")) >= 1.0) or (_n(delta.get("loss")) >= 2)
    )
