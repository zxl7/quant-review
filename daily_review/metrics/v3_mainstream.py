#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3 主流三级划分 + 板块梯队构建系统

主流级别:
- MAINSTREAM(主流/国策长线): 国策级 + 持续>=10天 + 市场占比>=15% + 有完整梯队
- SUB_STREAM(支流/中线): 持续>=3天 + 市场占比>=5%
- MINOR_STREAM(次主流/隔日超短): 持续>=1天
- NO_THEME(无主题): 其他

各级别对应策略参数(THEME_LEVEL_STRATEGY):
主流: 持仓1-4周, 仓位50-100%, 打板/半路/低吸
支线: 持仓3-7天, 仓位20-50%, 打板为主
次主流: 持仓1-2天, 仓位10-20%, 只能打板
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ==================== 主流级别定义 ====================

class ThemeLevel(Enum):
    """题材主流级别"""
    MAINSTREAM = ("主流", "国策长线")
    SUB_STREAM = ("支流", "中线")
    MINOR_STREAM = ("次主流", "隔日超短")
    NO_THEME = ("无主题", "")

    def __init__(self, label: str, strategy_desc: str):
        self.label = label
        self.strategy_desc = strategy_desc


THEME_LEVEL_STRATEGY: Dict[ThemeLevel, Dict[str, str]] = {
    ThemeLevel.MAINSTREAM: {
        "hold_period": "1-4周",
        "position": "50-100%",
        "tactics": "打板/半路/低吸",
        "risk_level": "中等",
        "target_return": "20-50%",
    },
    ThemeLevel.SUB_STREAM: {
        "hold_period": "3-7天",
        "position": "20-50%",
        "tactics": "打板为主",
        "risk_level": "中高",
        "target_return": "10-20%",
    },
    ThemeLevel.MINOR_STREAM: {
        "hold_period": "1-2天",
        "position": "10-20%",
        "tactics": "只能打板",
        "risk_level": "高",
        "target_return": "5-10%",
    },
    ThemeLevel.NO_THEME: {
        "hold_period": "不参与",
        "position": "0%",
        "tactics": "空仓观望",
        "risk_level": "-",
        "target_return": "0%",
    },
}


# ==================== 主流级别判定 ====================

def classify_theme_level(info: Dict[str, Any]) -> ThemeLevel:
    """根据题材信息判断主流级别

    信号加权体系:
    - 国策级(+2权重)
    - 持续活跃>=10天(+2), >=5天(+1), >=3天(+0.5)
    - 市场成交占比>=15%(+2), >=8%(+1), >=5%(+0.5)
    - 有完整梯队(龙1/龙2/龙3+跟风)(+2), 部分梯队(+1)
    - 总分>=5 → MAINSTREAM, >=3 → SUB_STREAM, >=1 → MINOR_STREAM, else → NO_THEME

    Args:
        info: 题材信息字典，关键字段:
            - is_national_policy: bool 是否国策级
            - active_days: int 持续活跃天数
            - market_share_pct: float 市场成交占比%
            - has_complete_ladder: bool 是否有完整梯队
            - has_partial_ladder: bool 是否有部分梯队
            - sector_name: str 板块名称
    """
    score = 0.0

    # 1. 国策级 (+2)
    is_national = info.get("is_national_policy", False)
    if is_national:
        score += 2.0

    # 2. 持续活跃天数
    active_days = info.get("active_days", 0) or 0
    if active_days >= 10:
        score += 2.0
    elif active_days >= 5:
        score += 1.0
    elif active_days >= 3:
        score += 0.5

    # 3. 市场成交占比
    market_share = info.get("market_share_pct", 0) or 0
    if market_share >= 15:
        score += 2.0
    elif market_share >= 8:
        score += 1.0
    elif market_share >= 5:
        score += 0.5

    # 4. 梯队完整性
    has_full_ladder = info.get("has_complete_ladder", False)
    has_partial = info.get("has_partial_ladder", False)
    if has_full_ladder:
        score += 2.0
    elif has_partial:
        score += 1.0

    # 判定等级
    if score >= 5.0:
        return ThemeLevel.MAINSTREAM
    elif score >= 3.0:
        return ThemeLevel.SUB_STREAM
    elif score >= 1.0:
        return ThemeLevel.MINOR_STREAM
    else:
        return ThemeLevel.NO_THEME


# ==================== 板块梯队构建 ====================

@dataclass
class LadderPosition:
    """梯队位置"""
    role: str = ""          # dragon / dragon_2 / dragon_3 / follower / outsider
    rank_in_sector: int = 0 # 板块内排名
    reason: str = ""         # 定位原因


def build_sector_ladder(stocks: List[Dict]) -> Dict:
    """构建板块梯队

    排序依据优先级:
    1. 连板数 (越多越靠前)
    2. 当日涨跌幅 (越大越靠前)
    3. 成交额 (越大越靠前)

    返回结构:
    {
        "dragon": {...},          // 龙1
        "dragon_2": {...},        // 龙2
        "dragon_3": {...},        // 龙3
        "followers": [...],       // 跟风股列表
        "outsiders": [...],       // 掉队/无关股
        "total_count": int,
        "health_score": float,    // 梯队健康度 0-10
        "health_grade": str,      // A/B/C/D
        "ladder_details": [...]   // 全部定位明细
    }
    """
    if not stocks:
        return {
            "dragon": None,
            "dragon_2": None,
            "dragon_3": None,
            "followers": [],
            "outsiders": [],
            "total_count": 0,
            "health_score": 0.0,
            "health_grade": "D",
            "ladder_details": [],
        }

    # 排序: 连板数 desc, 涨跌幅 desc, 成交额 desc
    def sort_key(s: Dict) -> Tuple:
        boards = s.get("consecutive_boards", 0) or 0
        chg = s.get("change_pct", 0) or 0
        amt = s.get("amount", 0) or 0
        return (-boards, -chg, -amt)

    sorted_stocks = sorted(stocks, key=sort_key)
    total = len(sorted_stocks)

    # 角色分配
    ladder_details = []
    n = total

    for idx, stock in enumerate(sorted_stocks):
        position = LadderPosition()
        position.rank_in_sector = idx + 1

        if idx == 0:
            position.role = "dragon"
            position.reason = "板块龙头(综合排序第一)"
        elif idx == 1:
            position.role = "dragon_2"
            position.reason = "补涨龙二"
        elif idx == 2:
            position.role = "dragon_3"
            position.reason = "补涨龙三"
        elif idx < max(6, n // 3):  # 前1/3或至少前6只为跟风
            position.role = "follower"
            position.reason = f"跟风股(排名{idx + 1})"
        else:
            position.role = "outsider"
            position.reason = f"掉队/无关(排名{idx + 1})"

        ladder_details.append({
            **stock,
            "_ladder_role": position.role,
            "_ladder_reason": position.reason,
            "_rank": idx + 1,
        })

    # 提取各角色
    dragon = ladder_details[0] if n >= 1 else None
    dragon_2 = ladder_details[1] if n >= 2 else None
    dragon_3 = ladder_details[2] if n >= 3 else None
    followers = [d for d in ladder_details[3:]
                 if d["_ladder_role"] == "follower"]
    outsiders = [d for d in ladder_details
                 if d["_ladder_role"] == "outsider"]

    # 计算梯队健康度 (0-10)
    health_score = _calc_ladder_health(dragon, dragon_2, dragon_3,
                                       followers, total)

    # 健康度评级
    if health_score >= 8.0:
        health_grade = "A"
    elif health_score >= 6.0:
        health_grade = "B"
    elif health_score >= 4.0:
        health_grade = "C"
    else:
        health_grade = "D"

    return {
        "dragon": dragon,
        "dragon_2": dragon_2,
        "dragon_3": dragon_3,
        "followers": followers,
        "outsiders": outsiders,
        "total_count": total,
        "health_score": round(health_score, 2),
        "health_grade": health_grade,
        "ladder_details": ladder_details,
    }


def _calc_ladder_health(dragon: Optional[Dict], dragon_2: Optional[Dict],
                         dragon_3: Optional[Dict], followers: List[Dict],
                         total: int) -> float:
    """计算梯队健康度 (0-10)

    评估维度:
    - 龙头存在且有强度 (0-3分)
    - 龙一二三完整性 (0-3分)
    - 跟风数量和力度 (0-2分)
    - 整体规模 (0-2分)
    """
    score = 0.0

    # 1. 龙头质量 (0-3分)
    if dragon is not None:
        d_boards = dragon.get("consecutive_boards", 0) or 0
        d_chg = dragon.get("change_pct", 0) or 0
        if d_boards >= 3 and d_chg >= 5:
            score += 3.0
        elif d_boards >= 2 or d_chg >= 3:
            score += 2.0
        elif d_chg > 0:
            score += 1.0
        else:
            score += 0.3  # 龙头但没涨

    # 2. 龙一二三完整性 (0-3分)
    if dragon_3 is not None:
        score += 3.0
    elif dragon_2 is not None:
        score += 2.0
    elif dragon is not None:
        score += 1.0

    # 3. 跟风数量和质量 (0-2分)
    follower_cnt = len(followers)
    positive_followers = sum(1 for f in followers
                             if (f.get("change_pct", 0) or 0) > 0)

    if follower_cnt >= 5 and positive_followers >= 3:
        score += 2.0
    elif follower_cnt >= 3 and positive_followers >= 2:
        score += 1.3
    elif follower_cnt >= 1:
        score += 0.7

    # 4. 整体规模 (0-2分)
    if total >= 10:
        score += 2.0
    elif total >= 5:
        score += 1.3
    elif total >= 3:
        score += 0.7

    return min(10.0, max(0.0, score))


# ==================== 主线判断 ====================

def judge_mainline(sectors: List[Dict], sentiment_score: float) -> Dict:
    """判断是否存在明确主线。

    条件:
    - 第一板块占比 >= 20%
    - 梯队健康度 >= 3
    - 持续活跃 >= 2天

    Args:
        sectors: 板块列表，每项应含:
            - name: 板块名称
            - market_share_pct: 市场成交占比%
            - active_days: 持续活跃天数
            - stocks: 该板块个股列表 (用于构建梯队)
            - 或 ladder_info: 已构建好的梯队信息
        sentiment_score: 当前市场情绪分 (0-100)，影响主线判断阈值

    Returns:
        {
            exists: bool,
            top_sector: str or None,
            level: ThemeLevel or None,
            conditions: dict,      # 各条件满足情况
            strength: str,          # 强/中/弱/无
            strategy: dict or None, # 对应策略参数
        }
    """
    if not sectors:
        return {
            "exists": False,
            "top_sector": None,
            "level": ThemeLevel.NO_THEME,
            "conditions": {},
            "strength": "无",
            "strategy": THEME_LEVEL_STRATEGY[ThemeLevel.NO_THEME],
        }

    # 找出市场占比最大的板块
    sorted_sectors = sorted(
        sectors,
        key=lambda s: s.get("market_share_pct", 0) or 0,
        reverse=True,
    )
    top = sorted_sectors[0]

    top_name = top.get("name", "未知板块")
    top_share = top.get("market_share_pct", 0) or 0
    active_days = top.get("active_days", 0) or 0

    # 构建或获取梯队
    ladder = top.get("ladder_info")
    if ladder is None and "stocks" in top:
        ladder = build_sector_ladder(top["stocks"])
    elif ladder is None:
        ladder = {"health_score": 0, "health_grade": "D"}

    health_score = ladder.get("health_score", 0) or 0

    # 条件检查（情绪高时适当放宽条件）
    sentiment_adj = 0.8 if sentiment_score >= 70 else 0.0  # 亢奋时放宽阈值

    cond_share_ok = top_share >= (20.0 - sentiment_adj * 5)
    cond_health_ok = health_score >= 3.0
    cond_active_ok = active_days >= 2

    conditions = {
        "top_share": {
            "value": round(top_share, 2),
            "threshold": round(20.0 - sentiment_adj * 5, 1),
            "passed": cond_share_ok,
        },
        "ladder_health": {
            "value": round(health_score, 2),
            "threshold": 3.0,
            "passed": cond_health_ok,
        },
        "active_days": {
            "value": active_days,
            "threshold": 2,
            "passed": cond_active_ok,
        },
        "sentiment_adjustment": sentiment_adj > 0,
    }

    passed_count = sum(1 for v in conditions.values()
                       if isinstance(v, dict) and v.get("passed"))

    # 判断是否存在主线
    if passed_count >= 3:
        exists = True
        level = classify_theme_level(top)
        strength = "强"
    elif passed_count >= 2:
        exists = True
        level = ThemeLevel.SUB_STREAM
        strength = "中"
    elif passed_count >= 1 and cond_share_ok:
        exists = True
        level = ThemeLevel.MINOR_STREAM
        strength = "弱"
    else:
        exists = False
        level = ThemeLevel.NO_THEME
        strength = "无"

    return {
        "exists": exists,
        "top_sector": top_name,
        "level": level,
        "conditions": conditions,
        "strength": strength,
        "strategy": THEME_LEVEL_STRATEGY[level] if exists else THEME_LEVEL_STRATEGY[ThemeLevel.NO_THEME],
        "top_sector_detail": {
            "name": top_name,
            "share_pct": round(top_share, 2),
            "active_days": active_days,
            "health_score": round(health_score, 2),
            "health_grade": ladder.get("health_grade", "D"),
        } if exists else None,
    }
