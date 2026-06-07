"""
Vue3 数据注入兼容入口（inject_data.py）

当前主实现已迁移到 `daily_review.publish.web_bundle`：
- 这里保留原有 CLI 入口
- 保留关键函数名，避免零散脚本/导入路径直接失效
"""

from __future__ import annotations

from daily_review.publish.web_bundle import (
    ROOT,
    _build_theme_alias_map,
    _build_watchlist_stock_index,
    _ensure_mood_history,
    _ensure_stock_research_backtest,
    _enhance_with_watchlist,
    _is_complete_stock_research_backtest,
    _prune_plan_text_fields,
    _resolve_data_path,
    _resolve_eastmoney_tomorrow_path,
    _resolve_intraday_resonance_path,
    _resolve_watchlist_path,
    build_web_data,
    inject,
    main,
    refresh_dev_data,
)

__all__ = [
    "ROOT",
    "_build_theme_alias_map",
    "_build_watchlist_stock_index",
    "_ensure_mood_history",
    "_ensure_stock_research_backtest",
    "_enhance_with_watchlist",
    "_is_complete_stock_research_backtest",
    "_prune_plan_text_fields",
    "_resolve_data_path",
    "_resolve_eastmoney_tomorrow_path",
    "_resolve_intraday_resonance_path",
    "_resolve_watchlist_path",
    "build_web_data",
    "inject",
    "main",
    "refresh_dev_data",
]


if __name__ == "__main__":
    raise SystemExit(main())
