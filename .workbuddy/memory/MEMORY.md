# quant-review 系统认知

> 最后更新：2026-05-20

## 项目定位

A股短线量化复盘系统，基于必盈 API，生成 Vue3 单页 HTML 报告。服务于龙头战法交易体系。

## 技术栈

- Python 3.14（pipeline + CLI + 渲染）
- Vue3 + ECharts（前端 SPA，单文件 `templates/report_template.html`）
- 必盈 API 优先（`daily_review/data/biying.py`）
- macOS + Zsh，服务器 `/app/` 部署
- GitHub Actions 自动构建发布

## 核心数据流

```
必盈 API → fetch_pool(三池) → pools_cache.json
         → fetch_index_k → index_klines_cache
         → fetch_stock_themes → theme_cache

cli.py → run_fetch_and_rebuild / run_rebuild
       → Context.from_market_data(market_data)
       → pipeline 模块链（按声明顺序）
       → market_data JSON → 前端渲染
```

## 关键算法

1. **六维情绪评分**（mood_signals.py）：赚钱/亏钱效应双维度
2. **涨停数据分析**（buildZtAnalysis JS）：封单×开板×时间×题材×梯队×市值×成交额×温和放量×突破新高×板块共振
3. **接力池**（2-5板，一字板/缩量板排除）vs **观察池**（大容量/前龙头/强分歧）
4. **三态预期**：超预期/符合/低预期 + 竞价量能估算
5. **龙头三要素**：带领性、突破性、唯一性

## 已知问题

- `run_rebuild` 日期格式不匹配：`qr.sh render 20260508` → `"20260508"` vs pools_cache `"2026-05-08"` → mood_inputs 全零
- 根因已定位：`_load_pools_for_date` 按原始日期查缓存，`run_rebuild` 未标准化日期格式

## 用户偏好

- 必盈 API 优先，减少 akshare 依赖
- 简洁命令式中文沟通，结论先行
- 代码风格：dataclass + type hints + 纯函数 + 中文注释
- 新增代码追加文件末尾
- 前端审查：关注视觉层次、信息密度、交互体验
- 改造节制，控制范围和复杂度
