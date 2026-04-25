# 量化复盘系统 v2（PRD 驱动）全量改造 Plan

> 约束：**数据以现有系统为准**（marketData + raw.pools + themePanels + features）；允许新增 **Python 计算字段**；关键指标要求 **口径可追溯且可复算（“精准”）**。  
> 设计：遵循 **impeccable**（克制、层级分明、渐进披露、移动端不牺牲信息）。

---

## 0. 当前可用“精确”原始字段（已验证）

来自 `marketData.raw.pools`：

- `ztgc[]`：包含 `dm(代码) / mc(名称) / lbc(连板数) / fbt(首次封板时间) / lbt(最终封板时间) / zbc(炸板次数)` 等
- `zbgc[]`：包含 `dm / mc / fbt / zbc / zdf(涨跌幅) / ztp(涨停价)` 等
- `dtgc[]`：包含 `dm / mc / ...`

这意味着以下 PRD 指标可在 **不新增外部接口** 的情况下精准计算（而非“猜测”）：

- `earlySealRate`：`ztgc` 中 `fbt` ∈ [09:30, 10:00] 占比
- `lateSealRate`：`fbt` ∈ [13:00, 15:00] 占比
- `sealTimeDist`：按 `fbt` 分桶分布
- `highBoardExplodeRate`：高位（≥N板）在 `zbgc` 中占比 /（高位 `ztgc+zbgc`）
- `avgExplodeTimes`：`zbc` 分布（炸板次数均值/分位）
- “回封质量”proxy（可精确复算）：在 `ztgc` 中 `zbc>0` 视为“经历炸板仍最终封住”

---

## 1. 目标架构（PRD 4.1）

### sentiment（短线情绪）

1) 全景概览（精简版）  
2) **盘面三象限**（Scatter + 近5日轨迹）【P0】  
3) **分歧与承接引擎**（时间/空间/资金 + 承接质量）【P1】  
4) **风险与亏钱扩散引擎**（扩散图谱 + 穿透 + 明细）【P1】  
5) 结构拆解 v2（梯队完整性/盈亏分布/异动检测）【P2】  
6) 高位风险预警（条件显示）【P2】  
7) 风格雷达（保持）

### themes（板块题材）

8) **多板块情绪热力图（超级模块）**【P0】  
9) 成交额 TOP10（保持）

ladder / plan：保持（后续只做口径/冗余清理）。

---

## 2. 实施路线（按优先级）

### Phase A（P0）— 先把“核心框架”搭起来

**A1. 多板块情绪热力图（themes）**

- 数据源：`themePanels.strengthRows + leaders + sectors`
- Python 新增：`metrics/sector_heatmap.py` 输出 `marketData.sectorHeatmap`
- Template：`sec-hot` 替换为「多板块情绪热力图」渲染组件（已做雏形，改为 python 输出驱动）
- 验收：  
  - 可展开、默认展开 Top2  
  - 显示 zt/zb/dt、净强度、风险、龙头标签  
  - 给出“结构性机会提示”（全局 vs 局部热度差）

**A2. 盘面三象限（sentiment）**

- 数据源（精确可复算）：  
  - 承接轴：`jj_rate_adj`（或 `jj_rate`）  
  - 一致性轴：`earlySealRate`（来自 `ztgc.fbt`）  
  - 风险轴：高位炸板率（来自 `zbgc + lbc`）+ 跌停/大面（来自 `dtgc`/现有 fear）  
  - 气泡大小：`volume.values/total`
  - 轨迹：近 5 日从缓存 `cache/market_data-*.json` 组装
- Python 新增：`metrics/three_quadrants.py` 输出 `marketData.threeQuadrants`
- Template：新增 `sec-quadrants`（ECharts scatter + 轨迹线 + 解释框）

### Phase B（P1）— 两个“引擎”

**B1. 风险与亏钱扩散（RiskEngine）**

- 数据源：`dtgc + zbgc + ztgc + zt_code_themes/theme_mapper + sectors`
- Python 新增：`metrics/risk_diffusion.py` 输出 `marketData.riskEngine`
- UI：辐射图谱（按题材聚合）+ 跌停穿透（昨日涨停中跌停占比）+ 大面明细表

**B2. 分歧与承接（DivergenceEngine）**

- timeDim：`early/mid/late` 由 `ztgc.fbt` 分桶
- spaceDim：高/中/低位炸板率由 `lbc` 分层 + `zbgc` 统计
- fundDim（必须精确）：  
  - 若后续通过 a-stock-realtime 能拿到“全市场大单净流”，则做全市场  
  - 否则定义为 **Top10 成交额样本的大单净流（可精确复算）**，并在 UI 标注“样本口径”

### Phase C（P2）— 增强与清冗余

- 高位风险（≥4板条件显示）  
- 结构拆解 v2（梯队完整性/盈亏分布/异动检测）  
- 冗余清理：封板率/炸板率/晋级率出现次数符合 PRD（重复项删除或改为衍生判断）

---

## 3. 数据拉取策略（Use Skill: a-stock-realtime）

目标：补齐 fundDim 等缺口，且保证“可复算”。

- 优先复用现有 pipeline 的取数结果（`qr.sh fetch`）
- 仅对缺失字段增量调用接口（例如：Top10 样本的大单资金流）
- 每个新增字段在 `marketData.meta` 记录：数据源、时间戳、口径说明

---

## 4. 交付与验证

- 每完成一个 Phase：渲染最近交易日（默认本地最新）并给出 HTML 预览链接  
- 同时输出 `CHANGELOG`（列出：新增字段、口径说明、模块替换关系）  
- 保证无控制台报错、移动端布局可用、冗余指标不回潮

