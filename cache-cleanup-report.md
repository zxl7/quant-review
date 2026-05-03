# Cache 清理与线上同步报告

- 最新报告日期：`2026-04-30`
- 线上目录模式：`minimal`

## 当前脚本自动清理现状

- `qr.sh` 目前只会自动删除：旧的 `market_data-*.json`（保留最近 7 个）和历史 HTML。
- `qr.sh` 目前不会自动删除：`intraday_snapshots-*`、`intraday_slices-*`、`v3_quality-*.md`、`learning_notes_history.json`、`trade_days_cache.json` 等。

## 建议保留

- `concept_fund_flow_cache.json`：板块排行兜底数据
- `height_trend_cache.json`：高度趋势模块依赖
- `index_kline_cache.json`：指数K线/量能模块依赖
- `intraday_slices-20260430.json`：保留最近 2 个盘中切片
- `intraday_snapshots-20260429.json`：保留最近 2 个盘中快照
- `intraday_snapshots-20260430.json`：保留最近 2 个盘中快照
- `learning_notes_history.json`：学习语录去重历史
- `market_data-20260422.json`：最近 7 个 market_data 快照
- `market_data-20260423.json`：最近 7 个 market_data 快照
- `market_data-20260424.json`：最近 7 个 market_data 快照
- `market_data-20260427.json`：最近 7 个 market_data 快照
- `market_data-20260428.json`：最近 7 个 market_data 快照
- `market_data-20260429.json`：最近 7 个 market_data 快照
- `market_data-20260430.json`：最近 7 个 market_data 快照
- `money_flow_cache.json`：板块流入聚合依赖
- `plate_rotate_cache.json`：板块轮动明细必需
- `pools_cache.json`：离线重建涨停/跌停/炸板池必需
- `theme_cache.json`：题材映射必需
- `theme_trend_cache.json`：题材持续性模块依赖
- `trade_days_cache.json`：交易日缓存（gen_report_v4 兼容）

## 建议清理

- 无

## 线上依赖目录

- 目录：`cache_online/`
- 只放远端 `render/deploy` 需要上传的缓存文件
- 可直接整体上传，而不是从 `cache/` 手工挑文件
