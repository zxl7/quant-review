"""
明日计划 Tab（plan/）

包含行动指南、策略建议、仓位管理、心理建设、交易性质、反弹策略、右侧交易等模块。
对应 HTML 报告的第四个 Tab。

模块列表：
- action_guide: 行动指南
- strategy_v2: 策略建议 v2
- position_v2: 仓位管理 v2
- psychology_v2: 心理建设 v2
- v3_position: v3 养家仓位五档
- v3_rebound: v3 反弹三阶段策略
- v3_fullpos: v3 满仓三条件共振
- v3_trading: v3 交易性质分类
- v3_rightside: v3 右侧交易确认
- rebound_v2: 反弹策略 v2
- resonance_v2: 共振策略 v2
- rightside_v2: 右侧交易 v2
- trade_nature_v2: 交易性质 v2
- summary3: 总结 v3
- learning_notes: 学习笔记
"""

from .action_guide import ACTION_GUIDE_MODULE
from .strategy_v2 import STRATEGY_V2_MODULE
from .position_v2 import POSITION_V2_MODULE
from .psychology_v2 import PSYCHOLOGY_V2_MODULE
from .v3_position import V3_POSITION_MODULE
from .v3_rebound import V3_REBOUND_MODULE
from .v3_fullpos import V3_FULLPOS_MODULE
from .v3_trading import V3_TRADING_MODULE
from .v3_rightside import V3_RIGHTSIDE_MODULE
from .rebound_v2 import REBOUND_V2_MODULE
from .resonance_v2 import RESONANCE_V2_MODULE
from .rightside_v2 import RIGHTSIDE_V2_MODULE
from .trade_nature_v2 import TRADE_NATURE_V2_MODULE
from .summary3 import SUMMARY3_MODULE
from .learning_notes import LEARNING_NOTES_MODULE

__all__ = [
    "ACTION_GUIDE_MODULE",
    "STRATEGY_V2_MODULE",
    "POSITION_V2_MODULE",
    "PSYCHOLOGY_V2_MODULE",
    "V3_POSITION_MODULE",
    "V3_REBOUND_MODULE",
    "V3_FULLPOS_MODULE",
    "V3_TRADING_MODULE",
    "V3_RIGHTSIDE_MODULE",
    "REBOUND_V2_MODULE",
    "RESONANCE_V2_MODULE",
    "RIGHTSIDE_V2_MODULE",
    "TRADE_NATURE_V2_MODULE",
    "SUMMARY3_MODULE",
    "LEARNING_NOTES_MODULE",
]
