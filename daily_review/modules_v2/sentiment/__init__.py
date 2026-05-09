"""
短线情绪 Tab（sentiment/）

包含市场情绪、恐慌指数、情绪评分、渡劫识别、崩溃链检测等模块。
对应 HTML 报告的第一个 Tab。

模块列表：
- mood: 市场情绪（老版本）
- mood_signals: 情绪信号
- sentiment_v2: v2 情绪计分卡
- sentiment_spec: 情绪规格说明
- fear: 恐慌指数
- effect: 效应分析
- panorama: 全景图（老版本）
- market_panorama: 市场全景图
- volume: 成交量分析
- v3_sentiment: v3 六维情绪评分
- v3_dujie: 渡劫识别
- v3_reflexivity: Y=F(X)反身性模型
- v3_collapse: 崩溃链检测
"""

from .mood import MOOD_MODULE
from .mood_signals import MOOD_SIGNALS_MODULE
from .sentiment_v2 import SENTIMENT_V2_MODULE
from .sentiment_spec import SENTIMENT_SPEC_MODULE
from .fear import FEAR_MODULE
from .effect import EFFECT_MODULE
from .panorama import PANORAMA_MODULE
from .market_panorama import MARKET_PANORAMA_MODULE
from .volume import VOLUME_MODULE
from .v3_sentiment import V3_SENTIMENT_MODULE
from .v3_dujie import V3_DUJIE_MODULE
from .v3_reflexivity import V3_REFLEXIVITY_MODULE
from .v3_collapse import V3_COLLAPSE_MODULE

__all__ = [
    "MOOD_MODULE",
    "MOOD_SIGNALS_MODULE",
    "SENTIMENT_V2_MODULE",
    "SENTIMENT_SPEC_MODULE",
    "FEAR_MODULE",
    "EFFECT_MODULE",
    "PANORAMA_MODULE",
    "MARKET_PANORAMA_MODULE",
    "VOLUME_MODULE",
    "V3_SENTIMENT_MODULE",
    "V3_DUJIE_MODULE",
    "V3_REFLEXIVITY_MODULE",
    "V3_COLLAPSE_MODULE",
]
