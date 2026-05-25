# 明日观察池推导 Spec

> 狸猫猎手 · 龙头格局版复盘体系第7模块
> 2026-05-25 确立

---

## 一、数据输入

### 1.1 个股标准化字段

```python
@dataclass
class Stock:
    code: str          # 代码 如 002938
    name: str          # 名称 如 鹏鼎控股
    lbc: int           # 真实连板数（pools_cache.lbc）
    cje: float         # 成交额（亿元）
    sector: str        # 板块归属（选股宝 plate）
    gain_pct: float    # 涨跌幅%
    seal_score: int    # 封板评分（0-100，来自 quant-review）
    seal_capital: float # 封单金额（亿元）
    turnover: float    # 换手率%
    reason: str        # 涨停原因（选股宝 reason / 东财 入选理由）
    is_main_line: bool # 是否属于当日主线
```

### 1.2 板块聚合数据

```python
@dataclass
class SectorStat:
    name: str          # 板块名
    count: int         # 涨停数
    avg_gain: float    # 平均涨幅
    top_stocks: list   # 最强表态（Top3 股票）
    sub_sectors: list  # 产业链子方向
```

### 1.3 数据来源映射

| 字段 | 来源 | 路径 |
|------|------|------|
| lbc | pools_cache.json | `lbc` |
| cje | pools_cache / 选股宝 | `cje` / `amount` |
| seal_score | pools_cache.json | `score` |
| seal_capital | pools_cache.json | `seal_capital` |
| turnover | pools_cache.json | `turnover` |
| sector | 选股宝异动接口 | `plate` / `hy` |
| reason | 选股宝异动 / 东财 | `reason` / 入选理由 |
| label | 东财 getStockList | `label`（如"2天2板"） |
| count | sector_stats 聚合 | `count` |

---

## 二、推导流程（5步）

### Step 1: 主线判定 `identify_main_line()`

```
输入：选股宝 sector_stats + 东财主题 Top10

逻辑：
  1. 按涨停数排序，取 TOP3 板块
  2. 检查板块间是否存在产业链联动

联动检测 — 预定义产业链映射表：
  CHAIN_MAP = {
      "半导体": ["先进封装", "CPO", "PCB", "光模块", "存储芯片", "大基金", "科特估", "MLCC", "玻璃基板"],
      "新能源": ["新能源车", "锂电池", "光伏", "储能", "充电桩", "固态电池"],
      "机器人": ["机器人", "减速器", "传感器", "PEEK材料", "机器视觉"],
      "AI算力":  ["光通信", "液冷服务器", "云计算", "数据中心", "算力租赁"],
  }

判定规则：
  - 若某链条内 ≥3 个子方向有涨停 → 合并为该主线
  - TOP3板块中若有重叠归属 → 融合为一个主线
  - 否则各自为独立支线

输出：主线名 + 主线涨停股列表 + 支线排序表
```

### Step 2: 梯队构建 `build_tiers(main_line)`

```
输入：主线涨停股列表 + pools_cache.lbc

逻辑：
  tier = {1: [], 2: [], 3: [], 4: []}

  1. 按 lbc 分组到各层
  2. 计算晋级率：
     1进2% = tier[2]今日数 / 昨日首板数
     2进3% = tier[3]今日数 / 昨日tier[2]数
     3进4% = tier[4]今日数 / 昨日tier[3]数
  3. 标记梯队缺口（如 3板=0 → "缺先锋龙"）
  4. 先锋龙候选 = tier[2] 中 seal_score≥60 的股票，按评分降序，取 Top3

输出：
  {
      "tiers": tier,
      "promotion_rates": {"1to2": 0.28, "2to3": 0.14, "3to4": 0.25},
      "gap": 3,           # 缺口的板数（None=无缺口）
      "pioneer_candidates": [stock, ...]  # 先锋龙候选
  }
```

### Step 3: 候选池生成 `generate_candidate_pool()`

```
来源（4路收口，目标 15-20 只）：

  a) 主线首板 Top5
     - 从 tier[1] 中筛选 is_main_line=True
     - 按 cje 降序，取 Top5
     - 标注"容量核心"

  b) 主线2板 全部
     - tier[2] 中 is_main_line=True
     - 全部纳入
     - 标注"先锋龙候选"

  c) 支线龙头
     - 非主线方向，每个方向取涨停数最多的前 2 只
     - 标注"支线龙头"

  d) 独立逻辑 Top1
     - 非主/支线，但板块涨停 ≥5 只
     - 取最强 1 只
     - 标注"独立逻辑"

过滤规则：
  - ST 股 → 直接排除
  - cje < 5亿 → 排除（流动性不足）
  - seal_score < 30 → 排除（封板质量太差，易炸板）

输出：候选池 list[Stock]（15-20只）
```

### Step 4: 精选评分 `score_and_rank(pool)`

```python
评分维度（每维 0-5 分，总分 max=30）：

SCORE_DIMENSIONS = {
    "主线贴合度": lambda s: (
        5 if s.is_main_line and s.lbc >= 2    # 主线核心（有连板）
        else 4 if s.is_main_line               # 主线首板
        else 3 if s.sector in SUB_MAIN_LINES   # 强支线
        else 1                                  # 其他
    ),
    "梯队位置": lambda s: (
        5 if s in pioneer_candidates           # 先锋龙候选（2板高评分）
        else 4 if s.lbc == 1 and s.cje >= 100  # 容量核心（大成交额首板）
        else 3 if s.lbc >= 3                   # 空间板
        else 2                                  # 普通首板
    ),
    "板块强度": lambda s: (
        5 if sector_stats[s.sector].count == max_counts  # 涨停数 TOP1
        else 3 if sector_stats[s.sector].count >= top3_threshold  # TOP3
        else 1
    ),
    "封板质量": lambda s: (
        5 if s.seal_score >= 90
        else 3 if s.seal_score >= 70
        else 1 if s.seal_score >= 50
        else 0
    ),
    "换手健康度": lambda s: (
        5 if 3 <= s.turnover <= 15   # 适中换手，筹码稳定
        else 3 if 15 < s.turnover <= 30  # 分歧换手，需谨慎
        else 1                        # <3%（一字板无参与机会）或 >30%（分歧过大）
    ),
    "成交额量级": lambda s: (
        5 if s.cje >= 100   # 百亿级，机构和游资共存
        else 3 if s.cje >= 30  # 中等流动性
        else 1 if s.cje >= 10
        else 0
    ),
}

加分项（可选，总分上限 +3）：
  PIONEER_BONUS = 2   # 先锋龙加成：同板块 lbc 最高 + 评分 Top3
  INDEPENDENT_BONUS = 1  # 独立逻辑：非主线但板块涨停 ≥5 只
  GEM_BONUS = 1       # 20cm 溢价：创业板/科创板涨停

总评分 = sum(6维) + sum(加分项)
```

### Step 5: 方向去重 + 输出 `ensure_diversity(ranked)`

```
输入：按总分降序排列的候选池
输出：5 只精选标的

逻辑：
  1. 取 Top5 按总分
  2. 统计 5 只的方向分布（unique 方向数）
  3. 若方向数 < 3：
     - 从第6名开始依次检查
     - 跳过与已入选同方向的标的
     - 替换 Top5 中评分最低的同方向标的
     - 直到方向数 ≥ 3
  4. 输出结构：
     {
         priority: int,      # 1-5，优先级
         name: str,
         code: str,
         direction: str,     # 所属方向
         tier_position: str, # 梯队定位（如"2板先锋龙候选"）
         score: int,         # 总评分
         reason: str,        # 一句话入选理由
     }
```

---

## 三、输出结构

```python
@dataclass
class WatchlistItem:
    priority: int       # 1-5
    name: str
    code: str
    direction: str      # 如 "半导体封测"
    tier_position: str  # 如 "2板先锋龙候选"
    score: int          # 总评分
    reason: str         # 一句话逻辑
    key_data: dict      # {cje, seal_score, turnover, lbc}
```

---

## 四、完整流程图

```
七路数据源
  │
  ├─ pools_cache.json ────────→ lbc / cje / seal_score / turnover
  ├─ market_data.json ────────→ 涨停数 / 封板率 / 情绪评分
  ├─ 选股宝异动接口 ──────────→ sector / reason / gain_pct
  ├─ 东财 getFryTomorrowList ─→ 热门主题排名（主线验证）
  ├─ 东财 getStockList ───────→ label（连板状态标签） / 入选理由
  └─ theme_trend_cache.json ──→ 7日题材趋势（主线持续性验证）
  │
  ▼
Step 1: identify_main_line()
  ├─ 涨停数 TOP3 板块
  ├─ 产业链联动检测（CHAIN_MAP）
  └─ 输出：主线名 + 主线股列表 + 支线排序
  │
  ▼
Step 2: build_tiers()
  ├─ 按 lbc 分层
  ├─ 计算晋级率
  ├─ 标记缺口
  └─ 输出：梯队结构 + 先锋龙候选
  │
  ▼
Step 3: generate_candidate_pool()
  ├─ 主线首板 Top5（按 cje）
  ├─ 主线 2板 全部
  ├─ 支线龙头（每方向 Top2）
  ├─ 独立逻辑 Top1
  ├─ 过滤：ST、cje<5亿、seal_score<30
  └─ 输出：候选池 15-20 只
  │
  ▼
Step 4: score_and_rank()
  ├─ 6 维评分（主线贴合度/梯队位置/板块强度/封板质量/换手健康度/成交额量级）
  ├─ 3 项加分（先锋龙/独立逻辑/20cm）
  └─ 输出：按总分降序排列
  │
  ▼
Step 5: ensure_diversity()
  ├─ 取 Top5
  ├─ 检查方向覆盖 ≥3
  ├─ 不足则替换同方向低分标的
  └─ 输出：最终 5 只观察池
```

---

## 五、注意事项

1. **所有数字必须来自 API 数据，禁止编造** — 评分的每个维度都基于真实的 lbc / cje / seal_score
2. **维度权重相等** — 当前不给任何维度加权，依赖数据说话
3. **产业链映射表需持续维护** — `CHAIN_MAP` 是关键，新的产业链关系出现时要手动补充
4. **排行榜与情绪对冲** — 若情绪评分 < 40，观察池中优先选低换手、高分数的稳健标的；若情绪 > 70，可放宽换手和分数阈值
5. **T+1 制度约束** — 所有推荐基于"明早竞价后验证"的前提，不是"收盘就买"
