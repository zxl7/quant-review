#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
操作单（action_sheet）：把泛泛的"行动指南"变成具体的操作指令。

设计原则：
- 不写股评，只给操作条件
- 每条都有明确的触发条件和仓位建议
- 纯数据驱动，不依赖任何外部输入
- 产品化：不记录个人持仓，这是通用短线工具
"""

from __future__ import annotations

from typing import Any, Dict, List


def _n(v: Any, d: float = 0.0) -> float:
    try:
        if v is None:
            return d
        if isinstance(v, str):
            v = v.replace("%", "").strip()
        return float(v)
    except Exception:
        return d


def build_action_sheet(market_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 market_data 生成具体操作单。

    输出结构：
    {
      "summary": {stage, stance, mode, oneLine},
      "buy": [{condition, target, position, reason}],
      "hold": [],
      "empty": [],       # 空仓/观望
      "riskLine": str,    # 风险红线
      "meta": {...}
    }
    """
    md = market_data or {}
    mi = ((md.get("features") or {}).get("mood_inputs") or {})
    delta = md.get("delta") or {}

    # ===== 基础数据提取 =====
    stage = (md.get("moodStage") or {}).get("title") or "-"
    stage_type = (md.get("moodStage") or {}).get("type") or "warn"
    sublabel = (md.get("moodStage") or {}).get("sublabel") or ""

    fb = _n(mi.get("fb_rate"))
    jj = _n(mi.get("jj_rate"))
    zb = _n(mi.get("zb_rate"))
    zt_cnt = int(_n(mi.get("zt_count")))
    dt_cnt = int(_n(mi.get("dt_count")))
    bf_count = int(_n(mi.get("bf_count")))
    max_lb = int(_n(mi.get("max_lb")))
    broken_lb_rate = _n(mi.get("broken_lb_rate"))
    rate_2to3 = _n(mi.get("rate_2to3"))

    heat = _n((md.get("mood") or {}).get("heat"))
    risk = _n((md.get("mood") or {}).get("risk"))
    vol_chg = _n(((md.get("volume") or {}).get("change")))

    # 主线信息
    tp = md.get("themePanels") or {}
    theme_rows = tp.get("strengthRows") or []
    main_theme = ""
    theme_net = 0.0
    theme_risk = 0.0
    if theme_rows:
        best = max(theme_rows, key=lambda r: _n(r.get("net"), 0) - _n(r.get("risk"), 0) * 0.6)
        main_theme = best.get("name") or ""
        theme_net = _n(best.get("net"))
        theme_risk = _n(best.get("risk"))

    # 龙头信息
    ladder = md.get("ladder") or []
    leader_name = "—"
    leader_b = 0
    if ladder:
        leader_b = max(int(_n(r.get("badge"))) for r in ladder)
        tops = [r.get("name", "") for r in ladder if int(_n(r.get("badge"))) == leader_b]
        leader_name = "、".join(tops[:2]) if tops else "—"

    # ===== 判定基本立场 =====
    if stage_type == "good":
        stance = "进攻"
    elif stage_type == "fire":
        stance = "防守"
    else:
        stance = "均衡"
    if heat >= 70 and risk <= 40 and fb >= 70:
        stance = "进攻"
    elif risk >= 60 or bf_count >= 10 or fb <= 55:
        stance = "防守"

    # 模式判定
    mode = "休息"
    dzb = _n(delta.get("zb_rate"))
    dloss = _n(delta.get("loss"))
    risk_trend_up = (dzb >= 1.0) or (dloss >= 2)

    if stage_type != "fire" and stance != "休息" and not risk_trend_up:
        if theme_net < 9 or fb < 55 or jj < 25:
            mode = "低位试错"
        elif zb >= 28 or bf_count >= 8:
            mode = "套利"
        else:
            mode = "接力"

    # ===== 一句话总结 =====
    emoji_map = {
        "进攻": "🟢",
        "防守": "🔴",
        "均衡": "🟡",
    }
    one_line = f"{emoji_map.get(stance,'')} {stage}{'·' + sublabel if sublabel else ''} | 主线:{main_theme or '未识别'} | 龙头:{leader_name}({leader_b}板) | 建议:{stance}"

    # ===== 构建买入条件 =====
    buy_list: List[Dict[str, str]] = []

    if mode != "休息":
        # 条件1：主线确认点
        if main_theme:
            cond_detail = f"{main_theme}净强≥{max(theme_net-1,0):.0f}"
            pos = "≤2成" if mode == "低位试错" else ("≤3成" if mode == "接力" else "≤1成")
            buy_list.append({
                "condition": f"主线确认：{cond_detail}",
                "target": f"{main_theme}题材内2进3确认 / 龙首回封",
                "position": pos,
                "reason": f"当前主线净强{theme_net:.1f}，风险{theme_risk:.1f}",
            })

        # 条件2：高度打开后的接力
        if max_lb >= 5 and rate_2to3 >= 35:
            buy_list.append({
                "condition": f"龙头({leader_name})晋级{leader_b+1}板成功",
                "target": "同梯队补涨 / 分支龙首板",
                "position": "≤2成",
                "reason": f"空间已打开(最高{max_lb}板)，2进3成功率{rate_2to3:.0f}%",
            })

        # 条件3：真修复信号
        yest_chg = _n(mi.get("yest_zt_avg_chg"))
        if "真修复" in sublabel or (yest_chg >= 2.0 and stage in ("弱修复",)):
            buy_list.append({
                "condition": "昨日涨停股今平均涨幅仍>2%（资金在回流）",
                "target": "主线首板 / 1进2确认",
                "position": "≤2成",
                "reason": f"昨日涨停票今日均涨{yest_chg:+.1f}%，是真修复不是诱多",
            })

    # ===== 空仓/观望条件 =====
    empty_list: List[Dict[str, str]] = []

    # 风险触发
    if bf_count >= 15:
        empty_list.append({"trigger": f"大面扩散≥{bf_count}只", "action": "立刻停止新开仓，现有持仓减半"})
    if broken_lb_rate >= 50:
        empty_list.append({"trigger": f"连板断板率{broken_lb_rate:.0f}%≥50%", "action": "不做任何接力，高位票优先出"})
    if risk >= 75:
        empty_list.append({"trigger": f"综合风险分{risk:.0f}≥75", "action": "空仓观望"})
    if stage_type == "fire":
        empty_list.append({"trigger": f"情绪阶段：{stage}", "action": "休息为主，最多小仓打首板"})

    if not empty_list:
        empty_list.append({"trigger": "无明确风险信号", "action": "按模式执行，但单笔亏损超5%必砍"})

    # ===== 风险红线 =====
    risk_lines = []
    if stage_type == "fire":
        risk_lines.append(f"当前处于「{stage}」，任何追高都是送钱")
    if max_lb >= 6:
        risk_lines.append(f"最高板已达{max_lb}板，高潮次日分化概率大")
    if zb >= 30:
        risk_lines.append(f"炸板率{zb:.0f}%偏高，追板容易被埋")
    if vol_chg <= -15:
        risk_lines.append(f"量能萎缩{vol_chg:+.0f}%，缩量行情不追高")
    if not risk_lines:
        risk_lines.append("单笔止损线：买入价跌5%无条件离场")

    return {
        "summary": {
            "stage": stage,
            "sublabel": sublabel,
            "stance": stance,
            "mode": mode,
            "oneLine": one_line,
        },
        "buy": buy_list,
        "hold": [],  # 不记录个人持仓，这是产品化工具
        "empty": empty_list,
        "riskLine": "；".join(risk_lines),
        "keyNumbers": {
            "zt": zt_cnt,
            "fb": round(fb, 1),
            "jj": round(jj, 1),
            "zb": round(zb, 1),
            "dt": dt_cnt,
            "heat": round(heat, 0),
            "risk": round(risk, 0),
            "maxLb": max_lb,
            "volChg": round(vol_chg, 1) if vol_chg else 0,
        },
        "meta": {
            "precision": "data_driven",
            "note": "操作单基于当日收盘数据自动生成，仅供参考。交易决策请结合盘面实时变化。",
        },
    }
