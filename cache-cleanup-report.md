# Cache 清理与线上同步报告

- 最新报告日期：`2026-06-16`
- 线上目录模式：`minimal`
- 默认缓存保留天数：`7`

## 当前自动清理策略

- `manage_cache.py --apply` 会把 `cache/`、`cache_online/`、`daily_review/output/tonghuashun/` 的日期型缓存统一裁到最近 `7` 天。
- `v3_quality-*.md` 这类临时分析产物会直接删除。
- `recommendation_price_history.json` 与 `logs/*.log` 不按文件名滚动，但会在 `--apply` 时做内部裁剪。
- 个股回测 pushed source、净值账本、题材/交易日基础缓存这类长期依赖文件不会按 7 天误删。

## 当前保留

- `cache/abnormal_event_history-20260605.json`：保留最近 7 天 abnormal event history 缓存
- `cache/abnormal_event_history-20260608.json`：保留最近 7 天 abnormal event history 缓存
- `cache/abnormal_event_history-20260609.json`：保留最近 7 天 abnormal event history 缓存
- `cache/abnormal_event_history-20260610.json`：保留最近 7 天 abnormal event history 缓存
- `cache/abnormal_event_history-20260611.json`：保留最近 7 天 abnormal event history 缓存
- `cache/abnormal_event_history-20260612.json`：保留最近 7 天 abnormal event history 缓存
- `cache/abnormal_event_history-20260616.json`：保留最近 7 天 abnormal event history 缓存
- `cache/account_nav_history.jsonl`：账户净值账本历史，会长期保留
- `cache/account_strategy_metrics.json`：未知文件，保守保留
- `cache/backtest_history.json`：历史回测归档，先保守长期保留
- `cache/concept_fund_flow_cache.json`：板块排行兜底数据
- `cache/height_trend_cache.json`：高度趋势模块依赖
- `cache/index_kline_cache.json`：指数K线/量能模块依赖
- `cache/learning_notes_history.json`：学习语录去重历史
- `cache/market_data-20260605.json`：保留最近 7 天 market_data 快照
- `cache/market_data-20260608.json`：保留最近 7 天 market_data 快照
- `cache/market_data-20260609.json`：保留最近 7 天 market_data 快照
- `cache/market_data-20260610.json`：保留最近 7 天 market_data 快照
- `cache/market_data-20260611.json`：保留最近 7 天 market_data 快照
- `cache/market_data-20260612.json`：保留最近 7 天 market_data 快照
- `cache/market_data-20260616.json`：保留最近 7 天 market_data 快照
- `cache/money_flow_cache.json`：板块流入聚合依赖
- `cache/plate_rotate_cache.json`：板块轮动明细必需
- `cache/pools_cache.json`：离线重建涨停/跌停/炸板池必需
- `cache/stock_research_backtest_source.json`：个股回测 pushed source 历史源数据，会长期保留
- `cache/theme_cache.json`：题材映射必需
- `cache/theme_trend_cache.json`：题材持续性模块依赖
- `cache/trade_days_cache.json`：交易日缓存（gen_report_v4 兼容）
- `cache_online/eastmoney_theme_stocks-20260605.json`：保留最近 7 天 eastmoney theme stocks 缓存
- `cache_online/eastmoney_theme_stocks-20260608.json`：保留最近 7 天 eastmoney theme stocks 缓存
- `cache_online/eastmoney_theme_stocks-20260609.json`：保留最近 7 天 eastmoney theme stocks 缓存
- `cache_online/eastmoney_theme_stocks-20260610.json`：保留最近 7 天 eastmoney theme stocks 缓存
- `cache_online/eastmoney_theme_stocks-20260611.json`：保留最近 7 天 eastmoney theme stocks 缓存
- `cache_online/eastmoney_theme_stocks-20260612.json`：保留最近 7 天 eastmoney theme stocks 缓存
- `cache_online/eastmoney_theme_stocks-20260616.json`：保留最近 7 天 eastmoney theme stocks 缓存
- `cache_online/eastmoney_tomorrow_themes-20260605.json`：保留最近 7 天 eastmoney tomorrow themes 缓存
- `cache_online/eastmoney_tomorrow_themes-20260608.json`：保留最近 7 天 eastmoney tomorrow themes 缓存
- `cache_online/eastmoney_tomorrow_themes-20260609.json`：保留最近 7 天 eastmoney tomorrow themes 缓存
- `cache_online/eastmoney_tomorrow_themes-20260610.json`：保留最近 7 天 eastmoney tomorrow themes 缓存
- `cache_online/eastmoney_tomorrow_themes-20260611.json`：保留最近 7 天 eastmoney tomorrow themes 缓存
- `cache_online/eastmoney_tomorrow_themes-20260612.json`：保留最近 7 天 eastmoney tomorrow themes 缓存
- `cache_online/eastmoney_tomorrow_themes-20260616.json`：保留最近 7 天 eastmoney tomorrow themes 缓存
- `cache_online/manifest.json`：线上同步 manifest，会覆盖更新
- `cache_online/market_data-20260616.json`：未知文件，保守保留
- `cache_online/plate_rotate_cache.json`：线上/本地复用的轮动缓存
- `cache_online/pools_cache.json`：线上/本地复用的三池缓存
- `cache_online/recommendation_price_history.json`：价格历史缓存文件保留，但内部会裁到最近 7 个交易日
- `cache_online/theme_cache.json`：线上/本地复用的题材映射缓存
- `cache_online/ths_newhigh-20260612.json`：保留最近 7 天 ths newhigh 缓存
- `cache_online/ths_newhigh-20260616.json`：保留最近 7 天 ths newhigh 缓存
- `cache_online/trade_days_cache.json`：线上/本地复用的交易日缓存
- `cache_online/watchlist_cache-20260605.json`：保留最近 7 天 watchlist cache 缓存
- `cache_online/watchlist_cache-20260608.json`：保留最近 7 天 watchlist cache 缓存
- `cache_online/watchlist_cache-20260609.json`：保留最近 7 天 watchlist cache 缓存
- `cache_online/watchlist_cache-20260610.json`：保留最近 7 天 watchlist cache 缓存
- `cache_online/watchlist_cache-20260611.json`：保留最近 7 天 watchlist cache 缓存
- `cache_online/watchlist_cache-20260612.json`：保留最近 7 天 watchlist cache 缓存
- `cache_online/watchlist_cache-20260616.json`：保留最近 7 天 watchlist cache 缓存
- `cache_online/xuangubao_abnormal-20260605.json`：保留最近 7 天 xuangubao abnormal 缓存
- `cache_online/xuangubao_abnormal-20260608.json`：保留最近 7 天 xuangubao abnormal 缓存
- `cache_online/xuangubao_abnormal-20260609.json`：保留最近 7 天 xuangubao abnormal 缓存
- `cache_online/xuangubao_abnormal-20260610.json`：保留最近 7 天 xuangubao abnormal 缓存
- `cache_online/xuangubao_abnormal-20260611.json`：保留最近 7 天 xuangubao abnormal 缓存
- `cache_online/xuangubao_abnormal-20260612.json`：保留最近 7 天 xuangubao abnormal 缓存
- `cache_online/xuangubao_abnormal-20260616.json`：保留最近 7 天 xuangubao abnormal 缓存
- `cache_online/xuangubao_surge_plates-20260605.json`：保留最近 7 天 xuangubao surge plates 缓存
- `cache_online/xuangubao_surge_plates-20260608.json`：保留最近 7 天 xuangubao surge plates 缓存
- `cache_online/xuangubao_surge_plates-20260609.json`：保留最近 7 天 xuangubao surge plates 缓存
- `cache_online/xuangubao_surge_plates-20260610.json`：保留最近 7 天 xuangubao surge plates 缓存
- `cache_online/xuangubao_surge_plates-20260611.json`：保留最近 7 天 xuangubao surge plates 缓存
- `cache_online/xuangubao_surge_plates-20260612.json`：保留最近 7 天 xuangubao surge plates 缓存
- `cache_online/xuangubao_surge_plates-20260616.json`：保留最近 7 天 xuangubao surge plates 缓存
- `daily_review/output/tonghuashun/sync-2026-06-11.txt`：保留最近 7 天同花顺同步输出
- `daily_review/output/tonghuashun/sync-2026-06-12.txt`：保留最近 7 天同花顺同步输出
- `daily_review/output/tonghuashun/sync-2026-06-16.txt`：保留最近 7 天同花顺同步输出
- `data/account_nav_history.jsonl`：账户净值主账本，会长期保留
- `data/account_strategy_metrics.json`：未知文件，保守保留
- `logs/workflow-trigger.err.log`：工作流日志文件保留，但 apply 时会裁到最近 7 天
- `logs/workflow-trigger.log`：工作流日志文件保留，但 apply 时会裁到最近 7 天

## 当前可清理

- 无

## 线上依赖目录

- 目录：`cache_online/`
- 只放远端 `render/deploy` 需要上传的缓存文件
- 可直接整体上传，而不是从 `cache/` 手工挑文件
