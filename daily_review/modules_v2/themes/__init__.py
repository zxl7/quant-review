"""
板块题材 Tab（themes/）

包含板块面板、题材趋势、板块轮动、板块梯队、板块层级等模块。
对应 HTML 报告的第二个 Tab。

模块列表：
- theme_panels: 板块面板
- theme_trend: 题材趋势
- theme_layers: 板块层级
- theme_ladder_v2: 板块梯队 v2
- rotation: 板块轮动
- top10: 板块 Top10
"""

from .theme_panels import THEME_PANELS_MODULE
from .theme_trend import THEME_TREND_MODULE
from .theme_layers import THEME_LAYERS_MODULE
from .theme_ladder_v2 import THEME_LADDER_V2_MODULE
from .rotation import ROTATION_MODULE
from .top10 import TOP10_MODULE

__all__ = [
    "THEME_PANELS_MODULE",
    "THEME_TREND_MODULE",
    "THEME_LAYERS_MODULE",
    "THEME_LADDER_V2_MODULE",
    "ROTATION_MODULE",
    "TOP10_MODULE",
]
