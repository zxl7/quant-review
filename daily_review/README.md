## daily_review 模块化（历史方案记录）

这份文档描述的是早期“模板外置 + HTML 渲染”的迁移设想。

当前主路线已经切到 `web/`：
- 页面入口是 `web/dist/index.html`
- 运行时数据由 `daily_review.publish.web_bundle` 构建，并通过 `inject_data.py` 兼容入口写入 `web/dist/market_data.json` / `market_data.js`
- `daily_review/render/render_html.py` 现阶段主要保留字段衍生 helper，供 web 注入复用

### 备注
历史模板链已下线；当前若继续收口，重点应放在：
1. `daily_review/render/render_html.py` 中是否还有只服务历史 HTML 的 helper
2. `daily_review/cli.py` / `README` 中与旧 HTML 输出相关的残余描述

### 开发阶段：部分更新（只重算某个模块）
前置：先跑一次全量更新，使得 `cache/market_data-YYYYMMDD.json` 存在。

示例：只更新“市场风格雷达”
```bash
PYTHONPATH=. python3 daily_review/cli.py --date 2026-04-17 --only style_radar
```

约定：
- 全量更新会把“模块复用所需的中间特征”写入 `marketData.features`（如 `features.style_inputs`）
- partial 更新只允许改动对应模块输出 key（例如 `styleRadar`），避免影响其他模块
