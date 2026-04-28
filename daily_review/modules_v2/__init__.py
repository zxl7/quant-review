"""modules_v2：基于 pipeline.Module 协议的新模块实现（逐步迁移）。"""

from .mood import MOOD_MODULE
from .style_radar import STYLE_RADAR_MODULE
from .leader import LEADER_MODULE
from .panorama import PANORAMA_MODULE
from .ladder import LADDER_MODULE
from .theme_panels import THEME_PANELS_MODULE
from .volume import VOLUME_MODULE
from .height_trend import HEIGHT_TREND_MODULE
from .ztgc import ZTGC_MODULE
from .top10 import TOP10_MODULE
from .theme_trend import THEME_TREND_MODULE
from .effect import EFFECT_MODULE
from .fear import FEAR_MODULE
from .rotation import ROTATION_MODULE
from .theme_layers import THEME_LAYERS_MODULE
from .action_guide import ACTION_GUIDE_MODULE
from .summary3 import SUMMARY3_MODULE
from .learning_notes import LEARNING_NOTES_MODULE
from .mood_signals import MOOD_SIGNALS_MODULE
from .sentiment_spec import SENTIMENT_SPEC_MODULE

ALL_MODULES = [
    PANORAMA_MODULE,
    LADDER_MODULE,
    ZTGC_MODULE,
    THEME_PANELS_MODULE,
    THEME_TREND_MODULE,
    VOLUME_MODULE,
    HEIGHT_TREND_MODULE,
    TOP10_MODULE,
    MOOD_MODULE,
    EFFECT_MODULE,
    FEAR_MODULE,
    ROTATION_MODULE,
    THEME_LAYERS_MODULE,
    STYLE_RADAR_MODULE,
    LEADER_MODULE,
    MOOD_SIGNALS_MODULE,
    SENTIMENT_SPEC_MODULE,
    ACTION_GUIDE_MODULE,
    SUMMARY3_MODULE,
    LEARNING_NOTES_MODULE,
]
