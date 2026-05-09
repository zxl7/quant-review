"""modules_v2：基于 pipeline.Module 协议的新模块实现（按 Tab 重新组织）。"""

# ════════════════ 短线情绪 (sentiment/) ════════════════
from .sentiment.mood import MOOD_MODULE
from .sentiment.sentiment_spec import SENTIMENT_SPEC_MODULE
from .sentiment.sentiment_v2 import SENTIMENT_V2_MODULE
from .sentiment.mood_signals import MOOD_SIGNALS_MODULE
from .sentiment.fear import FEAR_MODULE
from .sentiment.v3_sentiment import V3_SENTIMENT_MODULE
from .sentiment.v3_dujie import V3_DUJIE_MODULE
from .sentiment.effect import EFFECT_MODULE
from .sentiment.panorama import PANORAMA_MODULE
from .sentiment.market_panorama import MARKET_PANORAMA_MODULE
from .sentiment.v3_reflexivity import V3_REFLEXIVITY_MODULE
from .sentiment.volume import VOLUME_MODULE
from .sentiment.v3_collapse import V3_COLLAPSE_MODULE

# ════════════════ 板块题材 (themes/) ════════════════
from .themes.theme_panels import THEME_PANELS_MODULE
from .themes.theme_trend import THEME_TREND_MODULE
from .themes.theme_layers import THEME_LAYERS_MODULE
from .themes.theme_ladder_v2 import THEME_LADDER_V2_MODULE
from .themes.rotation import ROTATION_MODULE
from .themes.top10 import TOP10_MODULE

# ════════════════ 连板天梯 (ladder/) ════════════════
from .ladder.ladder import LADDER_MODULE
from .ladder.height_trend import HEIGHT_TREND_MODULE
from .ladder.ztgc import ZTGC_MODULE
from .ladder.v3_leader import V3_LEADER_MODULE
from .ladder.v3_mainstream import V3_MAINSTREAM_MODULE
from .ladder.leader import LEADER_MODULE
from .ladder.leader_dragon_v2 import LEADER_DRAGON_V2_MODULE

# ════════════════ 明日计划 (plan/) ════════════════
from .plan.action_guide import ACTION_GUIDE_MODULE
from .plan.strategy_v2 import STRATEGY_V2_MODULE
from .plan.position_v2 import POSITION_V2_MODULE
from .plan.psychology_v2 import PSYCHOLOGY_V2_MODULE
from .plan.v3_position import V3_POSITION_MODULE
from .plan.v3_rebound import V3_REBOUND_MODULE
from .plan.v3_fullpos import V3_FULLPOS_MODULE
from .plan.summary3 import SUMMARY3_MODULE
from .plan.learning_notes import LEARNING_NOTES_MODULE
from .plan.v3_trading import V3_TRADING_MODULE
from .plan.v3_rightside import V3_RIGHTSIDE_MODULE
from .plan.rebound_v2 import REBOUND_V2_MODULE
from .plan.resonance_v2 import RESONANCE_V2_MODULE
from .plan.rightside_v2 import RIGHTSIDE_V2_MODULE
from .plan.trade_nature_v2 import TRADE_NATURE_V2_MODULE

# ════════════════ v3 模块(对标v3.0算法规格书) ════════════════

try:
    from .sentiment.v3_sentiment import V3_SENTIMENT_MODULE
    from .sentiment.v3_dujie import V3_DUJIE_MODULE
    from .ladder.v3_leader import V3_LEADER_MODULE
    from .ladder.v3_mainstream import V3_MAINSTREAM_MODULE
    from .plan.v3_trading import V3_TRADING_MODULE
    from .plan.v3_rightside import V3_RIGHTSIDE_MODULE
    from .plan.v3_position import V3_POSITION_MODULE
    from .plan.v3_rebound import V3_REBOUND_MODULE
    from .plan.v3_fullpos import V3_FULLPOS_MODULE
    from .sentiment.v3_reflexivity import V3_REFLEXIVITY_MODULE
    from .sentiment.v3_collapse import V3_COLLAPSE_MODULE

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
    MARKET_PANORAMA_MODULE,
    LADDER_MODULE,
    ZTGC_MODULE,
    THEME_PANELS_MODULE,
    THEME_TREND_MODULE,
    VOLUME_MODULE,
    HEIGHT_TREND_MODULE,
    TOP10_MODULE,
    MOOD_MODULE,
    FEAR_MODULE,
    ROTATION_MODULE,
    THEME_LAYERS_MODULE,
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
