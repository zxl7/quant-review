"""AI 分析模块 — 数据加工层（Layer 2）

数据源 → 结构化数据 → AI 分析 → 渲染层
"""

from .analyzer import AIAnalyzer, analyze_market_data

__all__ = ["AIAnalyzer", "analyze_market_data"]
