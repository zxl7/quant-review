"""
连板天梯 Tab（ladder/）

包含连板天梯、高度趋势、涨停观察、龙头识别、主流划分等模块。
对应 HTML 报告的第三个 Tab。

模块列表：
- ladder: 连板天梯主模块
- height_trend: 高度趋势
- ztgc: 涨停观察（涨停股池）
- leader: 龙头识别（老版本）
- leader_dragon_v2: 龙头 dragon v2
- v3_leader: v3 龙头神形辨析
- v3_mainstream: v3 主流三级划分
"""

from .ladder import LADDER_MODULE
from .height_trend import HEIGHT_TREND_MODULE
from .ztgc import ZTGC_MODULE
from .leader import LEADER_MODULE
from .leader_dragon_v2 import LEADER_DRAGON_V2_MODULE
from .v3_leader import V3_LEADER_MODULE
from .v3_mainstream import V3_MAINSTREAM_MODULE

__all__ = [
    "LADDER_MODULE",
    "HEIGHT_TREND_MODULE",
    "ZTGC_MODULE",
    "LEADER_MODULE",
    "LEADER_DRAGON_V2_MODULE",
    "V3_LEADER_MODULE",
    "V3_MAINSTREAM_MODULE",
]
