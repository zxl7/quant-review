# 财富密码选股与竞价决策复现规格

> 版本口径：以当前项目实际代码为准。本文用于交给其他 AI 或开发者复现“财富密码”主链，不是交易建议，也不包含自动下单逻辑。

## 1. 核心定义

财富密码不是通过一个“推荐股票接口”直接获得股票，而是两阶段流程：

```text
收盘：必盈涨停池 ztgc
  -> 本地 ztAnalysis 因子计算
  -> relay 接力候选 + watch 观察候选
  -> 保存为下一交易日研究样本

次日 09:25：读取上一交易日生成的候选
  -> 批量读取实时竞价报价
  -> 比较预期涨幅、超预期阈值、竞价成交额
  -> buy / pending / reject / unavailable

收盘后：用历史日 K 计算次日、2 日、3 日结果
  -> 只做回测、命中率、策略汇总和净值评估
```

可以概括为：

```text
财富密码结论 = 本地收盘选股模型 × 次日竞价确认
```

它不会因为次日竞价上涨就把原本没有进入 `ztAnalysis.relay/watch` 的股票临时加入候选池。

## 2. 实际代码入口

| 责任 | 文件 |
| --- | --- |
| 必盈接口封装 | `daily_review/data/biying.py` |
| 收盘候选持久化、候选读取、竞价决策 | `scripts/build_stock_research_backtest.py` |
| 收盘时挂载和保留 `ztAnalysis` | `daily_review/application/stock_research_service.py` |
| `ztAnalysis` 总体计算 | `daily_review/metrics/zt_analysis.py` |
| 接力池/观察池选择器 | `daily_review/metrics/dragon_tactics_core.py` |

## 3. 数据接口

### 3.1 候选股票与市场池

必盈接口的基本形式是：

```text
{BIYING_BASE_URL}/hslt/{pool_name}/{date}
```

主要池：

| `pool_name` | 作用 | 是否是财富密码主候选全集 |
| --- | --- | --- |
| `ztgc` | 当日涨停股池 | 是 |
| `zbgc` | 炸板股池 | 否，辅助计算开板和风险 |
| `dtgc` | 跌停股池 | 否，辅助亏钱效应和市场闸门 |
| `qsgc` | 强势股池 | 否，辅助情绪/市场分析 |

财富密码的第一层股票全集严格是：

```python
candidate_universe = market_data["ztgc"]
```

`zbgc`、`dtgc`、`qsgc` 不应该被另一个实现直接拼进财富密码候选全集。

### 3.2 09:25 实时竞价

批量行情接口：

```text
{BIYING_BASE_URL}/hsrl/ssjy_more/{TOKEN}?stock_codes=600000,000001
```

当前实现最多每批请求 20 只股票。必要时再按批次循环。

单只行情兜底接口：

```text
{BIYING_BASE_URL}/hsrl/ssjy/{CODE6}/{TOKEN}
```

实际使用的原始字段：

| 原始字段 | 业务含义 |
| --- | --- |
| `dm` / `code` / `symbol` | 股票代码 |
| `mc` 或名称字段 | 股票名称 |
| `yc` | 昨收 |
| `o` | 开盘/竞价价格，优先使用 |
| `p` 或 `c` | 当前/最后价格，`o` 缺失时使用 |
| `cje` | 竞价成交额，单位元 |
| `t` | 报价时间 |
| `zbc` | 开板次数等辅助字段，当前竞价主判断不直接使用 |

归一化后的关键字段：

```json
{
  "code": "600000",
  "time": "2026-08-13 09:25:03",
  "prev_close": 10.0,
  "auction_price": 10.3,
  "auction_amount_yuan": 50000000,
  "auction_amount_yi": 0.5
}
```

### 3.3 历史收益评估

历史日 K 接口：

```text
{BIYING_BASE_URL}/hsstock/history/{CODE}/{period}/{adjust}/{TOKEN}?st=YYYYMMDD&et=YYYYMMDD
```

财富密码通常使用：

```text
period = d
adjust = f
```

它用于计算推荐股票的次日、持有 2 日、持有 3 日收益，不用于反向选择当天候选。

### 3.4 交易日和指数

交易日/指数相关接口：

```text
hsindex/latest/{code}/d/{token}?lt=N
hsindex/history/{code}/d/{token}?st=YYYYMMDD&et=YYYYMMDD
hsindex/real/time/{code}/{token}
```

这些接口用于确定交易日、市场环境和指数数据，不直接产生财富密码股票名单。

## 4. 收盘阶段：生成 relay/watch

### 4.1 收盘前提

收盘候选只有在以下条件满足时才持久化：

1. 当前数据不是 `intraday` 模式。
2. 收盘数据已经准备完成。
3. `market_data.ztAnalysis.relay` 或 `market_data.ztAnalysis.watch` 至少一个非空。
4. 至少能转换出一行有效股票记录。

持久化文件：

```text
cache/stock_research_backtest_source.json
```

来源标记：

```text
ztAnalysis.relay/watch.close_push
```

每个推荐交易日记录的是上一收盘日生成的候选，并附带下一交易日 `trade_date10`。

### 4.2 单股特征

`ztAnalysis` 以 `ztgc` 为输入，为每只涨停股计算包括以下内容的特征：

- 连板高度 `lbc`。
- 开板次数 `open`。
- 成交额 `cjeYi`、换手率、流通市值和总市值。
- 市场环境、情绪阶段、晋级率、炸板率、最高板。
- 题材是否可交易、是否泛化题材、题材主线归属。
- 龙头角色、题材带领性、突破性、唯一性。
- 梯队前排数量、最高板、断层数量、是否有承接。
- 接力因子、容量因子、龙头因子、龙头哲学分、步阶上下文分。
- 断板风险、个股风险、市场潮汐信号和开仓闸门。

外部题材/异动数据可以作为交叉确认和小幅加分，但不能替代 `ztgc` 母池。

### 4.3 综合分模型

当前模型的主要权重为：

```text
raw_score =
    environment_score      * 0.16
  + sector_sentiment_score * 0.22
  + leader_factor_score    * 0.21
  + relay_factor_score     * 0.17
  + capacity_score         * 0.14
  + risk_control_score     * 0.08
  + opportunity_score      * 0.02
  + identity_edge
  + height_breakout_bonus
  + market_gate_adjust
  + tide_adjust
```

分数会被限制在有效范围内。`identity_edge`、梯队完整性、近期新高、题材交叉确认和潮汐状态会做修正；跟风、题材泛化、梯队断层、过高断板风险会扣分。

### 4.4 relay 接力候选

接力池按以下顺序寻找：

1. 高度突破。
2. 高标/核心目标。
3. 核心接力。
4. `1进2`，最多 3 只。
5. 按股票名称去重，严格池最多 8 只。

选择条件的代表性门槛：

#### 高度突破

```text
高度突破或超强龙头标记
连板数 >= 6
原始分 >= 72
龙头因子 >= 76
接力因子 >= 70
断板风险 < 68
步阶上下文 >= 70
开板次数 <= 2
潮汐接力闸门 >= -4
```

#### 核心接力

```text
有可交易题材
不是泛化题材
不是一字板
不是缩量封板
2 <= 连板数 <= 5
原始分 >= 60
开板次数 < 8
断板风险 < 76
步阶上下文 >= 38
潮汐接力闸门 >= 0
不是跟风，且属于题材驱动或核心
```

#### 高标龙头

```text
有可交易题材
不是泛化题材/一字板/缩量封板
3 <= 连板数 <= 5
原始分 >= 74
龙头因子 >= 72
龙头哲学分 >= 76
断板风险 < 68
开板次数 <= 2
题材梯队无断层
属于题材驱动
潮汐接力闸门 >= 0
```

#### 1进2

```text
连板数 == 1
有可交易题材，非泛化题材
不是一字板/缩量封板
开板次数 < 3
原始分 >= 72
步阶上下文 >= 55
龙头因子 >= 60
接力因子 >= 64
龙头哲学分 >= 66
容量因子 >= 68
质量分 >= 80
断板风险 < 68
```

如果严格池为空，依次降级：

```text
relaxed:  最多 3 只
broad:    最多 3 只
emergency:最多 3 只
none:     完全没有候选
```

降级不是无条件放行，仍会排除一字难参与、极高断板风险、过多开板、明显梯队断层和弱跟风。

### 4.5 watch 观察候选

观察池先排除已经进入 `relay` 的股票，再重点保留：

- 高标/题材核心。
- 高位分歧。
- 容量核心。
- 高断板风险、开板较多的风险观察。
- 步阶结构弱或缺少可交易题材的补充观察。
- 梯队中必须跟踪的核心股票。

观察池先取最多 10 只，再合并梯队必须观察项，按去重和排序后最终最多 8 只。

观察组的优先顺序：

```text
高标/题材核心
高位分歧
容量核心
风险观察
补充观察
```

## 5. 财富密码样本结构

每个收盘候选至少保留以下信息：

```json
{
  "date10": "2026-08-12",
  "trade_date10": "2026-08-13",
  "code": "600000",
  "name": "示例股",
  "bucket": "relay",
  "bucket_label": "接力候选",
  "score": 82,
  "main_line": "主线题材",
  "lbc": 3,
  "relay_rank": 1,
  "watch_rank": 0,
  "relay_selection_mode": "strict",
  "leader_factor_score": 80,
  "relay_factor_score": 76,
  "leader_philosophy_score": 78,
  "capacity_factor_score": 72,
  "step_context_score": 68,
  "break_risk": 35,
  "tide_relay_gate": 4,
  "hit_rules": ["主线接力", "高标龙头"],
  "block_reasons": [],
  "reason_text": "...",
  "expectation": {
    "expected_text": "+1% ~ +3%",
    "super_text": "高开>=+3%，竞价成交额>=0.50亿",
    "low_text": "低于预期",
    "expected_range": [1.0, 3.0],
    "super_gap_min": 3.0,
    "auction_amount_min_yi": 0.5
  }
}
```

注意：`expected_range`、`super_gap_min`、`auction_amount_min_yi` 不是另设一套全局固定值，而是从每只股票的 `reason` 文本中解析。

## 6. 次日 09:25 竞价验证

### 6.1 参与验证的股票

只验证上一推荐日最新样本中的股票：

```python
latest_rows = rows if row["date10"] == latest_recommendation_date else []
codes = [row["code"] for row in latest_rows]
```

不从东财题材池、今日热点接口或其他旁路接口临时扩充股票。

### 6.2 合法报价时间

正式竞价快照必须满足：

```text
09:25:00 <= quote_time < 09:30:00
```

并且报价日期必须与目标交易日一致，至少有有效价格和有效成交额。

窗口外普通模式不请求远端竞价接口，只使用已经落地的有效竞价快照；避免将 11:30 盘中行情包装成 09:25 竞价结果。

窗口外的同日补抓可以标记为：

```text
source = forced_query
quality = recovered / forced_query
```

它可以用于同日恢复展示，但不能改变“正式 09:25 竞价快照缺失”的事实。

未来交易日保护：如果目标交易日大于当前系统日期，禁止用今天的实时行情匹配未来候选。

### 6.3 计算字段

```python
gap_pct = (auction_price - prev_close) / prev_close * 100
auction_amount_yi = auction_amount_yuan / 100_000_000
```

当前高开过猛保护阈值：

```text
CAUTION_GAP_PCT = 5.0
```

如果 `gap_pct > 5%`，即使达到原本的买入条件，也先归入观察，不直接放入买入结论。

### 6.4 精确分类伪代码

```python
def evaluate(record, quote):
    exp = record["expectation"]

    if quote is None:
        return unavailable("报价缺失")

    prev_close = quote["prev_close"]
    auction_price = quote["auction_price"]
    auction_amount_yi = quote["auction_amount_yi"]

    if prev_close <= 0 or auction_price <= 0 or auction_amount_yi <= 0:
        return unavailable("价格/量能不完整")

    gap_pct = (auction_price - prev_close) / prev_close * 100
    super_ok = (
        exp["super_gap_min"] is not None
        and gap_pct >= exp["super_gap_min"]
    )
    expected_ok = (
        exp["expected_range"] is not None
        and exp["expected_range"][0] <= gap_pct <= exp["expected_range"][1]
    )
    amount_ok = (
        exp["auction_amount_min_yi"] <= 0
        or auction_amount_yi >= exp["auction_amount_min_yi"]
    )
    too_hot = gap_pct > 5.0

    if super_ok and amount_ok:
        if too_hot:
            return pending("谨慎接力")
        return buy("超预期")

    if expected_ok:
        if too_hot:
            return pending("谨慎接力")
        return buy("符合预期")

    if super_ok and not amount_ok:
        return reject("量能不达标")

    return reject("未达买点")
```

当前实现的一个重要细节：普通 `expected_range` 分支本身不额外强制检查 `amount_ok`；竞价金额门槛是在“超预期”分支中明确拦截的。复现时不要擅自把量能条件扩展到普通预期分支，否则结果会和当前系统不同。

### 6.5 输出结构

```json
{
  "reference_date": "2026-08-12",
  "trade_date": "2026-08-13",
  "entry_window": "09:25-09:30",
  "quote_time": "2026-08-13 09:25:03",
  "source_module": "ztAnalysis.relay/watch",
  "quote_source": "biying hsrl/ssjy_more",
  "candidate_count": 10,
  "quoted_count": 10,
  "buy_count": 2,
  "pending_count": 3,
  "rejected_count": 4,
  "unavailable_count": 1,
  "buy_list": [],
  "pending_list": [],
  "rejected_list": [],
  "unavailable_list": [],
  "diagnostics": {
    "requested": 10,
    "received": 10,
    "remote_received": 10,
    "fallback_used": 0,
    "missing": [],
    "source": "remote",
    "as_of": "2026-08-13 09:25:03",
    "request_window": "09:25-09:30"
  }
}
```

四个结果桶含义：

| 桶 | 含义 |
| --- | --- |
| `buy_list` | 竞价落入预期或超预期，且没有高开过猛保护 |
| `pending_list` | 条件达到但高开超过5%，先观察承接 |
| `rejected_list` | 涨幅未达预期或超预期时量能不达标 |
| `unavailable_list` | 没有报价，或价格/成交额无效，不能判断 |

## 7. 排序规则

候选排序不是简单按竞价涨幅排序。主要顺序为：

```text
relay 优先于 watch
-> relayRank / watchRank
-> watchGroup 优先级
-> 命中 高标龙头 / 主线接力 / 高度突破
-> 命中 1进2
-> 龙头因子高者
-> 接力因子高者
-> 龙头哲学分高者
-> 步阶上下文高者
-> 断板风险低者
-> 惩罚泛化题材
-> 梯队断层少者
-> 连板数高者
-> 综合分高者
-> 股票代码稳定排序
```

最终决策列表先按信号级别排列：

```text
super -> expected -> pending -> reject -> unavailable
```

同一信号级别内再使用原候选优先级。

## 8. 历史闭环评估

对已经有竞价结果的股票，用 `hsstock/history` 查询交易日 K 线，计算：

```text
next_day_return_pct
hold_2d_return_pct
hold_3d_return_pct
```

无效 K 线、停牌、非正价格不进入有效收益计算。结果用于：

- 命中率。
- 平均收益。
- 策略汇总。
- 账户净值。

历史评估是事后验证，不参与当前候选生成，也不能用未来收益反向污染收盘筛选。

## 9. 不要混入主链的数据

以下数据可以服务其他页面或作为辅助信息，但不是财富密码标准候选来源：

- 今日热点的 `surge_stock/plates` 和 `surge_stock/stocks`。
- 东方财富今日/明日题材池。
- `event/history` 异动事件。
- `stock_label/labels` 个股标签。
- `watchlist/picks_advisor` 推票接口。
- 盘中热点板块列表。

如果实现者把这些接口中的股票直接合并进财富密码，得到的就不再是当前项目的财富密码逻辑，而是另一套混合推荐模型。

## 10. 关键边界条件

1. 收盘没有有效 `ztAnalysis.relay/watch` 时，不应写入空推荐源覆盖上一份有效源。
2. 盘中模式通常沿用上一份收盘候选，不重新生成次日接力池。
3. 报价时间不在 09:25-09:30 时，不能标记为正式竞价。
4. `forced_query` 是窗口外同日恢复，不是正式竞价成功。
5. 跨日缓存、未来交易日实时行情和报价时间不明的数据不能参与竞价结论。
6. 报价缺失时输出 `unavailable`，不能输出“低于预期”或“买入”。
7. 这是决策辅助和回测系统，不自动下单，也不保证买入收益。

## 11. 推荐复现顺序

如果另一个 AI 要从零复现，建议严格按以下顺序实现：

1. 实现 `hslt/ztgc/{date}` 请求和统一股票代码。
2. 为每只 `ztgc` 股票计算连板、开板、成交额、题材、龙头、风险和梯队字段。
3. 实现 `relay_height_breakout_ok`、`relay_core_ok`、`relay_high_mark_ok`、`relay_one_to_two_ok`。
4. 按 `strict -> relaxed -> broad -> emergency` 生成最多 8 只 `relay`。
5. 排除 `relay` 后生成最多 8 只 `watch`。
6. 为每行生成 `reason`，并解析预期区间、超预期阈值和竞价金额门槛。
7. 次日 09:25 使用 `hsrl/ssjy_more`，每批最多20只。
8. 严格校验报价时间、交易日、价格和成交额。
9. 按本文伪代码生成四个结果桶。
10. 用历史日 K 计算后验收益，单独生成回测指标和净值。

