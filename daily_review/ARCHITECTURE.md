## 目标

把 `gen_report_v4.py` 从“单文件巨石”升级为 **可拆分、可拼装、可部分更新、可单测** 的模块化架构，同时 **保持 HTML 结构稳定**（模板外置，数据注入）。

你的使用背景（收盘全量 + 开发阶段局部迭代）对应两种运行模式：
- **FULL（全量）**：抓取 + 计算全部模块 + 输出报告 + 落盘 `marketData` 与中间特征
- **PARTIAL（部分）**：读取缓存的 `marketData/features/raw` → 只重算指定模块 → 重渲染 HTML

---

## 分层架构（强约束）

### 1) 数据层（data）
职责：访问外部数据源（biyingapi），不做业务判断。
- `HttpClient`：GET + timeout + JSON
- Fetchers：指数、三池、个股题材等

**输出**：`raw.*`（原始数据），例如：
- `raw.pools.ztgc` / `raw.pools.dtgc` / `raw.pools.zbgc`
- `raw.index.kline` / `raw.index.snapshot`

### 2) 缓存层（cache）
职责：把 data 层结果落盘/复用，减少接口。
- pools_cache：7日涨停/跌停/炸板
- theme_cache：个股题材（code6 -> themes）
- height_trend_cache：高度趋势历史日
- market_data_cache：`marketData-YYYYMMDD.json`（用于 partial）

**原则**：缓存只存储“可重用的数据”，不存复杂业务对象。

### 3) 特征层（features）
职责：从 raw 提取“可复用的中间特征”，用于多个指标模块复用、以及 partial 重算输入。

例如（命名建议）：
- `features.style_inputs`（风格雷达输入）
- `features.mood_inputs`（热度/风险输入）
- `features.ladder_inputs`（晋级/断板输入）
- `features.theme_strength_inputs`（题材强度输入）

### 4) 指标层（metrics）
职责：纯函数/准纯函数计算，输入为 features/raw，输出为 metrics 或直接 patch 到 marketData。
例如：
- `metrics/style_radar.py`：强度计算
- `metrics/scoring.py`：热度 vs 风险
- `metrics/ladder.py`：天梯、晋级率、断板率
- `metrics/height_trend.py`：高度趋势（可用缓存）

### 5) 模块层（modules）
职责：把一个“分析模块”封装成可组合单元（可单测、可替换、可局部重跑）。
模块典型输出为对 `marketData` 的 **patch**（局部覆盖）。
例如：
- `modules/style_radar` 只负责生成/覆盖 `marketData.styleRadar`
- `modules/mood` 覆盖 `marketData.mood + marketData.moodStage + marketData.moodCards`

### 6) 渲染层（render）
职责：模板外置 + 注入 marketData，保证 HTML 结构稳定。
- `templates/report_template.html`（尽量不变）
- `render_html.py`：注入 JSON 输出 HTML

### 7) CLI 层（cli）
职责：模式选择、参数解析、执行 pipeline、输出文件。
- FULL：抓取 + 全模块计算 + 输出 + 落盘
- PARTIAL：读缓存 + 指定模块计算 + 输出

---

## 数据契约（Data Contract）

统一约定一个顶层对象：`Context`（运行上下文）

```jsonc
{
  "meta": { "date": "YYYY-MM-DD", "dateNote": "" },
  "raw": { /* 原始数据 */ },
  "features": { /* 可复用中间特征 */ },
  "marketData": { /* 前端渲染数据（最终注入 HTML） */ }
}
```

### raw（强建议只放“原始数据”）
- pools：zt/dt/zb 原始列表
- index：指数/量能K线
- themes：单股题材原始返回（可选，通常落盘缓存即可）

### features（强建议可重算、可落盘）
- 目的：避免“某模块要改，就必须全量重抓取/重计算”
- 例：`style_inputs`、`mood_inputs` 等均可独立重算

### marketData（渲染契约）
模板与前端（Vue/ECharts）依赖的结构，尽量稳定：
- `indices/panorama/volume/.../styleRadar/...`
模块输出只覆盖自己的 key，不改其他 key。

---

## 模块规范（每个“大分析模块”都遵循）

### Module 接口（建议）
- `name`: 模块名（唯一）
- `requires`: 依赖的上下文 key（声明式）
- `provides`: 该模块会产出的 marketData key（用于冲突检测）
- `compute(ctx) -> patch`：返回一个 dict patch（只包含需要覆盖的字段）

patch 合并策略：
- 默认 **浅合并**：`marketData[k] = patch[k]`
- 禁止模块跨界写入其他模块的 key

### 可单测原则
模块 `compute()` 尽量写成纯函数或准纯函数：
- 外部 IO（api/cache）必须在 data/cache 层完成
- 模块只消费 ctx.raw/ctx.features

---

## “可拼装”的依赖模型（DAG）

用 requires/provides 形成 DAG：
- FULL：按拓扑排序运行全部模块
- PARTIAL：只运行目标模块 + 其依赖链（自动补齐）

---

## 迁移策略（渐进式）

1) 先把每个“大块”拆成独立模块文件（即使内部仍调用旧函数）
2) 模块间通过 ctx.features/ctx.raw 传递，逐步去除 cross-call
3) 最后把 gen_report_v4.py 瘦身成：参数解析 → pipeline → render

---

## 模块清单（建议把所有“大分析块”都模块化）

> 目标：每个模块都能 **单独跑 / 单独测试 / 单独替换**，并且在 partial 时只重算它自己。

### 数据/缓存类
- pools（zt/dt/zb）：7日缓存 + 预热（data+cache）
- index_kline（成交额/交易日）：成交额日K推断交易日（data）
- theme_mapper（code->themes）：落盘缓存（cache）

### 分析模块类（modules）
- panorama：市场全景（涨停/炸板/跌停/封板率）
- volume_trend：近5日量能趋势
- ladder：连板天梯 + 晋级/断板（含昨日对比）
- height_trend：近7日高度趋势（历史缓存）
- theme_panels：涨停/炸板/跌停题材归因面板
- theme_strength：题材强度表（涨停/炸板/跌停 + 净强度）
- mood：热度 vs 风险 + 情绪阶段 + 情绪卡片
- style_radar：市场风格雷达（已完成算法拆分示例）
- top10：成交额TOP10 + 题材归因（可抽样）
- action_guide：行动指南（依赖前面多个模块产物）

### 渲染模块类（render）
- html_render：模板注入（稳定）
