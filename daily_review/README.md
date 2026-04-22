## daily_review 模块化（A方案：模板外置）

### 当前进度（已完成）
- `templates/report_template.html`：作为外置模板，保留原有 DOM/CSS/JS，仅新增占位符：
  - `__REPORT_DATE__`
  - `__DATE_NOTE__`
  - `/*__MARKET_DATA_JSON__*/ null`
- `daily_review/render/render_html.py`：渲染器脚本，负责把 marketData JSON 注入模板并输出 HTML。

### 下一步（待做）
1. 把 `gen_report_v4.py` 中 “marketData 组装” 提取成 Python `dict`（例如 `market_data = {...}`）
2. `gen_report_v4.py` 最终不再拼接大段 HTML，而是调用 `render_html_template()` 输出报告
3. 增量把抓取/缓存/题材/指标拆成独立模块

### 开发阶段：部分更新（只重算某个模块）
前置：先跑一次全量更新，使得 `cache/market_data-YYYYMMDD.json` 存在。

示例：只更新“市场风格雷达”
```bash
PYTHONPATH=. python3 daily_review/cli.py --date 2026-04-17 --only style_radar
```

约定：
- 全量更新会把“模块复用所需的中间特征”写入 `marketData.features`（如 `features.style_inputs`）
- partial 更新只允许改动对应模块输出 key（例如 `styleRadar`），避免影响其他模块
