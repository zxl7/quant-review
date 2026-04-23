# 短线思路落地 Plan（v1）

基于《短线龙头交易知识库》（2026-04-15）对现有复盘系统的“增量融合”设计稿。目标是**1+1>2**：用“指标→阶段→策略→提醒”闭环，把主观经验变成可计算、可调参、可迭代的系统能力。

---

## 0. 现状与改造原则

### 0.1 现状（你现在的系统）
- **数据**：三池/指数/题材缓存 → pipeline 生成 `marketData` → HTML 渲染。
- **情绪**：`features.mood_inputs` → `metrics/mood.py` → `marketData.moodStage/moodCards`
- **计划**：`render_html.build_action_guide_v2` 生成 `marketData.actionGuideV2`
- **提醒**：`render_html.build_learning_notes` 输出 `marketData.learningNotes`（含去重历史）

### 0.2 改造原则
1) **不硬塞文字**：只把“可验证的信号”写进系统；文案由信号触发。
2) **两层判定**：`周期(趋势)` + `当日(状态)`，解决“单日强弱”和“周期方向”割裂。
3) **可配置**：阈值、权重、策略模板做成规则表（单处维护）。
4) **最小可用 → 逐步增强**：先落地稳定版（不引入新接口），再扩展更强因子。

---

## 1) 情绪周期判定（moodStage 升级）

### 1.1 指标集（落地到 features）
> 你文档中的“周期判断指标”，映射到系统可计算字段；分为「已有」与「建议补齐」。

#### 已有（你现在基本都有）
- `zt_count`：涨停家数
- `max_lb`：最高板
- `zb_rate`：炸板率
- `dt_count`：跌停家数（或负反馈代理）
- `jj_rate`：晋级率（昨日连板 → 今日连板的比例/或等价承接指标）
- `broken_lb_rate`：连板断板率
- `zt_early_ratio`：早封占比（10点前）
- `zb_high_ratio`：高位炸板占比（4板+）

#### 建议补齐（让阶段更“像周期”）
1) `tier_integrity_score`（梯队完整性 0~100）
   - 输入：`lb_2/lb_3/lb_4p/lb_5p`（由涨停池 lbc 统计）
   - 解释：龙头(5+)→中军(3-4)→跟风(2)→首板 的结构是否完整
2) `risk_spike`（风险突刺 0/1 或 0~100）
   - 触发：`zb_rate` 明显上升 + `dt_count` 上升 + `broken_lb_rate` 上升（可用 delta 或阈值组合）
   - 解释：用于“更快确认转弱/退潮”的信号

> 注：如果你要做盘中盯盘，这两项也天然适配时间序列。

### 1.2 阶段定义：四阶段 + 当日态
文档四阶段：**冰点/启动/发酵/高潮**。为了兼容你现有 UI（good/warn/fire），建议拆成：

- `cycleStage`（周期阶段）：冰点 / 启动 / 发酵 / 高潮
- `dayState`（当日状态）：一致 / 分歧 / 退潮确认
- 最终输出到 `marketData.moodStage`：
  - title：优先展示「周期阶段+当日态」的融合（例：启动·分歧）
  - type：映射到 good/warn/fire（供主题色/风格联动）

### 1.3 阈值表（建议初版）
> 下面阈值来自你文档的描述 + 你现有口径，先做“可用版”，上线后再用你自己的历史分布校准。

```yaml
cycle_stage_rules:
  ICE:
    max_lb: "<=3"
    zt_count: "<30"
    zb_rate: ">=40"
    dt_count: ">=10"
  START:
    max_lb: "2~4"
    zt_count: "30~50"
    zb_rate: "25~45"
  FERMENT:
    max_lb: "4~6"
    zt_count: "50~80"
    zb_rate: "<=30"
  CLIMAX:
    max_lb: ">=6"
    zt_count: ">=80"
    zb_rate: "<=20"
```

### 1.4 1+1>2 的关键：趋势层（周期方向）
引入 5~7 日趋势（你已有 `trend_*`），给出 `cycleTrend`：
- 上升：`trend_max_lb↑ + trend_fb↑ + trend_jj↑`
- 下降：`trend_max_lb↓ + trend_fb↓ + trend_jj↓`

规则：当「趋势」与「当日」冲突时，用趋势做最终偏置：
- 趋势上升但当日分歧：标题可为 **发酵·分歧**，但 type 不要直接 fire（避免错杀）
- 趋势下降但当日修复：标题可为 **冰点·修复**，但 actionGuide 仍强调轻仓

---

## 2) 明日计划 / 行动指南（actionGuideV2 升级）

### 2.1 目标：把“阶段→策略模板”变成骨架
将 `actionGuideV2` 拆成三段，且每段可由阶段模板生成：
- `observe`：盯盘关注（主线/龙头/承接/风险）
- `do`：可做动作（主线核心、低位试错、仓位建议）
- `avoid`：禁止事项（高潮不追、退潮不接力、分歧不硬接）

### 2.2 阶段策略模板（初版）
```yaml
action_templates:
  ICE:
    stance: "防守"
    core: ["空仓观望或轻仓试探", "只做首板/1进2确认", "不做接力"]
  START:
    stance: "试错"
    core: ["关注1→2确认", "围绕新题材苗头", "不追高只做确认"]
  FERMENT:
    stance: "进攻"
    core: ["主线清晰后做龙头", "分歧转一致/回封加仓", "做核心辨识度"]
  CLIMAX:
    stance: "兑现"
    core: ["警惕次日分化", "不追一致末端", "高位只做卖点/减仓"]
```

### 2.3 触发条件（动态降级/升级）
把文档中的“强转弱/弱转强/分歧转一致”映射为可计算触发：
- **降级**：`risk_spike=1` 或 `zb_rate` 超阈值 或 `loss` 扩散超阈值
- **升级**：`fb_rate` 不掉速 + `jj_rate` 不掉速 + 主线净强优势扩大

输出方式建议：
- `actionGuideV2.meta.title` 里明确：周期阶段/主线/模式/仓位建议
- `confirm/retreat` 的阈值用动态容忍度（你现在已有 tol 思路），让“阶段决定容忍度”

---

## 3) 学习笔记/复盘提醒（learningNotes 升级）

### 3.1 目标
每天输出 2~3 条，不重复、且**跟随当日触发信号**：
- 1 条跟随周期阶段（ICE/START/FERMENT/CLIMAX）
- 1 条跟随当日风险（risk_spike / 高位断板 / 炸板放大）
- 1 条跟随主线与龙头结构（高度打开/梯队断层/主线集中度变化）

### 3.2 提醒卡片库（结构化）
建议把提醒定义为结构化卡片（便于扩展与去重）：
```yaml
note_cards:
  - id: "ice_001"
    when: { cycleStage: ["ICE"] }
    text: "冰点/退潮期：不做接力，重点盯“首板→1进2”的确认信号。"
  - id: "climax_001"
    when: { cycleStage: ["CLIMAX"] }
    text: "高潮期：超级高手卖出龙头。不要追一致末端，准备兑现。"
  - id: "risk_spike_001"
    when: { risk_spike: [1] }
    text: "风险突刺：炸板/跌停/断板共振时先保命，别硬接分歧。"
```

选取策略：
- 先筛选满足条件的卡片
- 按优先级挑 2~3 条
- 写入 `learning_notes_history.json` 做去重

---

## 4) 工程落地拆分（建议 PR 顺序）
1) **规则表落地**：新增 `daily_review/rules/*.py`（或 YAML/JSON）集中维护阈值与模板
2) **features 补指标**：`tier_integrity_score`、`risk_spike`、`lb_2/3/4p/5p`
3) **moodStage 改造**：引入「周期阶段+趋势偏置+当日态」，输出 title/type/detail
4) **actionGuideV2 改造**：按阶段模板输出策略骨架，并用触发条件动态调整
5) **learningNotes 改造**：结构化卡片库 + 条件触发 + 去重
6) **验收**：生成 `partial-mood-action_guide-learning_notes.html` 对比页

---

## 5) 你需要确认的 3 个口径（开始编码前）
1) 四阶段映射到 UI 的 `type`：
   - 建议：ICE->fire，START->warn，FERMENT->good，CLIMAX->good（但提示分化）
2) “大面/亏钱效应”的代理：
   - 你目前多用 dt_count/bf_count；是否要引入更严格的大面定义（需要额外数据源）？
3) 主线选取：
   - 继续沿用你现在的 `strengthRows` 净强-风险口径（推荐），还是要叠加“一级题材权重”？

