#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3 龙头渡劫四类型识别引擎

四种渡劫:
1. 炸板渡劫 — 当日开板≥3次（回封可介入概率0.7, 否则0.3）
2. 巨量渡劫 — 换手>3日均2.5倍且>30%（封住0.65, 否则0.35）
3. 低开渡劫 — 低开>3%（封住=黄金买点0.75, 大阳0.55, 否则0.25）
4. 核按钮反包渡劫 — 昨日跌停今涨停（极端博弈0.5）

高位额外折扣: 7板以上*0.7, 5-6板*0.85
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class BoardPattern(Enum):
    """连板K线形态枚举"""
    YIZI = "一字板"
    TZI = "T字板"
    SHITI = "实体大阳线"
    LANBAN = "烂板"
    DUANBAN = "断板"


@dataclass
class DoujieResult:
    """渡劫诊断结果"""
    is_doujie: bool = False
    doujie_type: str = ""           # 炸板渡劫/巨量渡劫/低开渡劫/核按钮反包渡劫
    doujie_level: int = 0            # 1-5级
    survival_prob: float = 1.0       # 存活概率 0-1
    advice: str = "持有"
    confidence: int = 50             # 置信度 0-100


# ==================== K线形态分类 ====================

def classify_board_pattern(stock_data: Dict[str, Any]) -> BoardPattern:
    """根据开盘价/最低价/收盘价/涨停价/换手率 判断K线形态

    判断规则:
    - 一字板: open==zt_price and low==zt_price
    - T字板: open==zt_price and low<zt_price and close==zt_price
    - 烂板: turnover>15% and low<zt_price*0.97
    - 断板: close < zt_price
    - 否则: 实体大阳线
    """
    open_p = stock_data.get("open", 0)
    low = stock_data.get("low", 0)
    close = stock_data.get("close", 0)
    zt_price = stock_data.get("zt_price", 0)
    dt_price = stock_data.get("dt_price", 0)   # 跌停价
    turnover = stock_data.get("turnover", 0)     # 换手率%

    # 零值保护
    if zt_price is None or zt_price <= 0:
        return BoardPattern.SHITI

    # 断板: 收盘价 < 涨停价
    if close < zt_price * 0.995:  # 允许微小精度误差
        return BoardPattern.DUANBAN

    # 一字板: 开盘=最低=涨停价 (全天封死)
    if abs(open_p - zt_price) < 0.01 and abs(low - zt_price) < 0.01:
        return BoardPattern.YIZI

    # T字板: 开盘=涨停, 下探后回封
    if abs(open_p - zt_price) < 0.01 and low < zt_price * 0.995 and abs(close - zt_price) < 0.005:
        return BoardPattern.TZI

    # 烂板: 高换手 + 大幅下探
    if turnover > 15 and low < zt_price * 0.97:
        return BoardPattern.LANBAN

    # 默认实体大阳线
    return BoardPattern.SHITI


# ==================== 渡劫诊断核心 ====================

def _calc_high_position_discount(consecutive_boards: int) -> float:
    """计算高位额外折扣系数"""
    if consecutive_boards >= 7:
        return 0.70
    elif consecutive_boards >= 5:
        return 0.85
    return 1.0


def _check_zhaban_doujie(today: Dict[str, Any], history: List[Dict[str, Any]],
                           boards: int) -> Optional[Dict]:
    """检查炸板渡劫: 当日开板>=3次"""
    open_count = today.get("open_board_count", 0)  # 开板次数
    if open_count is None or open_count < 3:
        return None

    # 是否回封 (收盘价接近涨停价)
    close = today.get("close", 0)
    zt_price = today.get("zt_price", 0)
    is_sealed = zt_price > 0 and close >= zt_price * 0.995

    base_prob = 0.70 if is_sealed else 0.30
    discount = _calc_high_position_discount(boards)

    level = min(5, max(1, open_count))  # 开板次数映射为等级

    advice = "回封可关注" if is_sealed else "谨慎观望"

    return {
        "type": "炸板渡劫",
        "level": level,
        "base_prob": base_prob,
        "discount": discount,
        "survival_prob": round(base_prob * discount, 3),
        "advice": advice,
        "detail": f"当日开板{open_count}次, {'回封' if is_sealed else '未回封'}",
    }


def _check_juliang_doujie(today: Dict[str, Any], avg_turnover_3d: float,
                           boards: int) -> Optional[Dict]:
    """检查巨量渡劫: 换手>3日均2.5倍且>30%"""
    turnover = today.get("turnover", 0)
    if turnover is None or turnover <= 0:
        return None

    if avg_turnover_3d is None or avg_turnover_3d <= 0:
        avg_turnover_3d = turnover  # 无法计算时用自身值，避免除零

    ratio = turnover / avg_turnover_3d if avg_turnover_3d > 0 else 1.0

    if not (ratio > 2.5 and turnover > 30):
        return None

    close = today.get("close", 0)
    zt_price = today.get("zt_price", 0)
    is_sealed = zt_price > 0 and close >= zt_price * 0.995

    base_prob = 0.65 if is_sealed else 0.35
    discount = _calc_high_position_discount(boards)

    level = min(5, max(1, int(ratio)))  # 倍数越大等级越高

    advice = "巨量封住，关注承接" if is_sealed else "巨量未封，回避"

    return {
        "type": "巨量渡劫",
        "level": level,
        "base_prob": base_prob,
        "discount": discount,
        "survival_prob": round(base_prob * discount, 3),
        "advice": advice,
        "detail": f"换手{turnover:.1f}%, 3日均{avg_turnover_3d:.1f}%, 倍数{ratio:.1f}x",
    }


def _check_dikai_doujie(today: Dict[str, Any], yesterday: Optional[Dict[str, Any]],
                         boards: int) -> Optional[Dict]:
    """检查低开渡劫: 低开>3%"""
    open_p = today.get("open", 0)
    prev_close = 0

    if yesterday is not None:
        prev_close = yesterday.get("close", 0)
    else:
        prev_close = today.get("prev_close", 0)

    if prev_close <= 0 or open_p <= 0:
        return None

    dip_pct = (prev_close - open_p) / prev_close * 100  # 低开幅度%
    if dip_pct <= 3:
        return None

    close = today.get("close", 0)
    zt_price = today.get("zt_price", 0)
    is_sealed = zt_price > 0 and close >= zt_price * 0.995

    # 收盘涨幅判断
    chg_pct = (close - prev_close) / prev_close * 100 if prev_close > 0 else 0

    if is_sealed:
        base_prob = 0.75  # 黄金买点
        advice = "黄金低开反包，重点关注"
    elif chg_pct > 5:
        base_prob = 0.55  # 大阳线
        advice = "低开大阳，可关注"
    else:
        base_prob = 0.25
        advice = "低开后无力，回避"

    discount = _calc_high_position_discount(boards)
    level = min(5, max(1, int(dip_pct / 2)))

    return {
        "type": "低开渡劫",
        "level": level,
        "base_prob": base_prob,
        "discount": discount,
        "survival_prob": round(base_prob * discount, 3),
        "advice": advice,
        "detail": f"低开{dip_pct:.1f}%, {'涨停' if is_sealed else f'涨幅{chg_pct:.1f}%'}",
    }


def _check_heanniu_fanbao_doujie(today: Dict[str, Any],
                                  yesterday: Optional[Dict[str, Any]],
                                  boards: int) -> Optional[Dict]:
    """检查核按钮反包渡劫: 昨日跌停今涨停"""
    if yesterday is None:
        return None

    yst_close = yesterday.get("close", 0)
    yst_dt_price = yesterday.get("dt_price", 0)
    today_zt_price = today.get("zt_price", 0)
    today_close = today.get("close", 0)

    # 昨日跌停 (收盘价接近跌停价)
    is_yesterday_dt = (
        yst_dt_price > 0
        and yst_close <= yst_dt_price * 1.02  # 允许微小误差
    )
    # 今日涨停
    is_today_zt = (
        today_zt_price > 0
        and today_close >= today_zt_price * 0.995
    )

    if not (is_yesterday_dt and is_today_zt):
        return None

    base_prob = 0.50  # 极端博弈
    discount = _calc_high_position_discount(boards)

    return {
        "type": "核按钮反包渡劫",
        "level": 4,  # 固定为高级别
        "base_prob": base_prob,
        "discount": discount,
        "survival_prob": round(base_prob * discount, 3),
        "advice": "极端博弈，仅限高手",
        "detail": "昨日跌停→今日涨停反包",
    }


def diagnose_doujie(stock_history: List[Dict[str, Any]]) -> DoujieResult:
    """判断连板股是否正在经历渡劫。输入最近N日K线数据列表

    Args:
        stock_history: 按时间正序排列的K线数据列表，每项包含:
            open, high, low, close, volume, amount, turnover,
            zt_price, dt_price, prev_close, open_board_count 等字段

    Returns:
        DoujieResult: 渡劫诊断结果
    """
    if not stock_history or len(stock_history) < 1:
        return DoujieResult(is_doujie=False, confidence=20,
                            advice="数据不足，无法判断")

    today = stock_history[-1]
    yesterday = stock_history[-2] if len(stock_history) >= 2 else None

    # 计算3日均换手
    turnovers = [d.get("turnover", 0) for d in stock_history[-4:-1] if d.get("turnover")]
    avg_turnover_3d = sum(turnovers) / len(turnovers) if turnovers else None

    # 计算连续涨停板数 (简化: 从历史数据中推断)
    consecutive_boards = 0
    for d in reversed(stock_history):
        zt = d.get("zt_price", 0)
        c = d.get("close", 0)
        if zt > 0 and c >= zt * 0.995:
            consecutive_boards += 1
        else:
            break

    # 逐一检查四种渡劫类型
    candidates = []

    result_zhaban = _check_zhaban_doujie(today, stock_history, consecutive_boards)
    if result_zhaban:
        candidates.append(result_zhaban)

    result_juliang = _check_juliang_doujie(today, avg_turnover_3d, consecutive_boards)
    if result_juliang:
        candidates.append(result_juliang)

    result_dikai = _check_dikai_doujie(today, yesterday, consecutive_boards)
    if result_dikai:
        candidates.append(result_dikai)

    result_heanniu = _check_heanniu_fanbao_doujie(today, yesterday, consecutive_boards)
    if result_heanniu:
        candidates.append(result_heanniu)

    # 无渡劫
    if not candidates:
        pattern = classify_board_pattern(today)
        return DoujieResult(
            is_doujie=False,
            survival_prob=1.0,
            advice="持有",
            confidence=70,
        )

    # 取存活概率最低的（最危险的）作为主诊断
    best = min(candidates, key=lambda x: x["survival_prob"])

    # 置信度基于数据完整度
    data_completeness = 50
    required_fields = ["open", "high", "low", "close", "volume", "turnover"]
    present = sum(1 for f in required_fields if today.get(f) is not None)
    data_completeness += min(40, present * 8)
    if len(stock_history) >= 3:
        data_completeness += 10

    return DoujieResult(
        is_doujie=True,
        doujie_type=best["type"],
        doujie_level=best["level"],
        survival_prob=best["survival_prob"],
        advice=best["advice"],
        confidence=min(100, int(data_completeness)),
    )


# ==================== 生命周期识别 ====================

class LifeCyclePhase(Enum):
    """龙头生命周期阶段"""
    STARTUP = ("启动期", (1, 2))
    ACCELERATION = ("加速期", (3, 4))
    DIVERGENCE = ("分歧期", (5, None))
    CLIMAX = ("见顶期", (None, None))
    DECLINE = ("退潮期", (None, None))

    def __init__(self, label: str, board_range: Tuple[Optional[int], Optional[int]]):
        self.label = label
        self.board_range = board_range


def identify_life_cycle(stock_info: Dict[str, Any]) -> tuple:
    """返回 (LifeCyclePhase, detail_str)

    Args:
        stock_info: 股票信息字典，至少包含:
            - consecutive_boards: 连续涨停板数
            - 可选: board_pattern (BoardPattern), turnover, volume等
    """
    boards = stock_info.get("consecutive_boards", 0)
    pattern = stock_info.get("board_pattern")

    if boards <= 0:
        return LifeCyclePhase.STARTUP, f"尚未连板({boards}板)"

    # 基于连板数的初步判断
    if boards <= 2:
        phase = LifeCyclePhase.STARTUP
        detail = f"{phase.label}(第{boards}板)"
    elif boards <= 4:
        phase = LifeCyclePhase.ACCELERATION
        detail = f"{phase.label}(第{boards}板)"
    elif boards <= 6:
        phase = LifeCyclePhase.DIVERGENCE
        detail = f"{phase.label}(第{boards}板)"
    elif boards <= 8:
        phase = LifeCyclePhase.CLIMAX
        detail = f"{phase.label}(第{boards}板)"
    else:
        phase = LifeCyclePhase.DECLINE
        detail = f"{phase.label}(第{boards}板，高危)"

    # 结合K线形态微调
    if pattern == BoardPattern.DUANBAN:
        phase = LifeCyclePhase.DECLINE
        detail += " → 已断板确认退潮"
    elif pattern == BoardPattern.LANBAN and boards >= 4:
        if phase != LifeCyclePhase.DECLINE:
            phase = LifeCyclePhase.DIVERGENCE
            detail += " → 烂板加剧分歧"

    return phase, detail


# ==================== 批量诊断 ====================

def batch_diagnose_dujie(stocks: List[Dict[str, Any]]) -> List[Dict]:
    """批量诊断多只股票的渡劫状态。

    Args:
        stocks: 股票列表，每只需含 history 字段 (List[Dict])
                以及 name/code 字段用于标识

    Returns:
        List[Dict]: 每只股票的诊断结果字典
    """
    results = []
    for stock in stocks:
        history = stock.get("history", [])
        code = stock.get("code", stock.get("name", "unknown"))

        doujie_result = diagnose_doujie(history)

        # 补充生命周期分析
        if history:
            today = history[-1]
            boards = 0
            for d in reversed(history):
                zt = d.get("zt_price", 0)
                c = d.get("close", 0)
                if zt > 0 and c >= zt * 0.995:
                    boards += 1
                else:
                    break

            pattern = classify_board_pattern(today)
            lifecycle_phase, lifecycle_detail = identify_life_cycle({
                "consecutive_boards": boards,
                "board_pattern": pattern,
            })
        else:
            pattern = None
            lifecycle_phase, lifecycle_detail = identify_life_cycle(
                {"consecutive_boards": 0})

        results.append({
            "code": code,
            "name": stock.get("name", ""),
            "doujie": {
                "is_doujie": doujie_result.is_doujie,
                "type": doujie_result.doujie_type,
                "level": doujie_result.doujie_level,
                "survival_prob": doujie_result.survival_prob,
                "advice": doujie_result.advice,
                "confidence": doujie_result.confidence,
            },
            "board_pattern": pattern.value if pattern else "未知",
            "lifecycle": {
                "phase": lifecycle_phase.name,
                "label": lifecycle_phase.label,
                "detail": lifecycle_detail,
            },
        })

    return results
