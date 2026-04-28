"""modules_v2：基于 pipeline.Module 协议的新模块实现（逐步迁移）。"""

# ═════════════════ 旧模块(保留) ═════════════════
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
from .sentiment_v2 import SENTIMENT_V2_MODULE
from .leader_dragon_v2 import LEADER_DRAGON_V2_MODULE
from .theme_ladder_v2 import THEME_LADDER_V2_MODULE
from .position_v2 import POSITION_V2_MODULE
from .rightside_v2 import RIGHTSIDE_V2_MODULE
from .resonance_v2 import RESONANCE_V2_MODULE
from .trade_nature_v2 import TRADE_NATURE_V2_MODULE
from .rebound_v2 import REBOUND_V2_MODULE
from .psychology_v2 import PSYCHOLOGY_V2_MODULE
from .strategy_v2 import STRATEGY_V2_MODULE

# ═════════════════ v3 模块(对标v3.0算法规格书) ═════════════════

try:
    from .v3_sentiment import V3_SENTIMENT_MODULE
    from .v3_dujie import V3_DUJIE_MODULE
    from .v3_leader import V3_LEADER_MODULE
    from .v3_mainstream import V3_MAINSTREAM_MODULE
    from .v3_trading import V3_TRADING_MODULE
    from .v3_rightside import V3_RIGHTSIDE_MODULE
    from .v3_position import V3_POSITION_MODULE
    from .v3_rebound import V3_REBOUND_MODULE
    from .v3_fullpos import V3_FULLPOS_MODULE
    from .v3_reflexivity import V3_REFLEXIVITY_MODULE
    from .v3_collapse import V3_COLLAPSE_MODULE

    # v3 模块列表（按执行顺序排列，依赖前置模块先执行）
    V3_MODULES = [
        V3_COLLAPSE_MODULE,      # 崩溃链检测（最早，供其他模块参考）
        V3_SENTIMENT_MODULE,     # 六维情绪评分（核心）
        V3_DUJIE_MODULE,          # 渡劫识别
        V3_LEADER_MODULE,         # 龙头神形辨析
        V3_MAINSTREAM_MODULE,     # 主流三级划分
        V3_TRADING_MODULE,       # 交易性质分类
        V3_RIGHTSIDE_MODULE,      # 右侧交易确认
        V3_POSITION_MODULE,       # 养家仓位五档
        V3_REBOUND_MODULE,        # 反弹三阶段策略
        V3_FULLPOS_MODULE,        # 满仓三条件共振
        V3_REFLEXIVITY_MODULE,   # Y=F(X)反身性模型
    ]
except ImportError:
    # v3 模块依赖可能尚未完全就绪，静默降级
    V3_MODULES = []

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
    # v2 情绪计分卡应覆盖 spec v1 的兼容输出
    SENTIMENT_V2_MODULE,
    LEADER_DRAGON_V2_MODULE,
    THEME_LADDER_V2_MODULE,
    POSITION_V2_MODULE,
    RIGHTSIDE_V2_MODULE,
    RESONANCE_V2_MODULE,
    TRADE_NATURE_V2_MODULE,
    REBOUND_V2_MODULE,
    PSYCHOLOGY_V2_MODULE,
    STRATEGY_V2_MODULE,
    SENTIMENT_SPEC_MODULE,
    ACTION_GUIDE_MODULE,
    SUMMARY3_MODULE,
    LEARNING_NOTES_MODULE,
    # v3 模块追加到执行链末尾（不替换旧模块，新旧并存）
] + (V3_MODULES if V3_MODULES else [])
