# 异动接口字段说明

接口：`https://flash-api.xuangubao.cn/api/event/history`

说明：以下内容以当前系统代码实际使用为准，少量字段含义为根据命名和展示行为做的推断。

## 请求参数

- `count`：拉取条数
- `types`：事件类型列表，逗号分隔
- `timestamp`：游标时间，配合分页/续拉使用
- `_ts`：时间戳防缓存

## 顶层字段

| 字段 | 含义 |
| --- | --- |
| `event_type` | 事件类型编号 |
| `event_timestamp` | 事件发生时间戳 |
| `target` | 个股目标代码，当前用于点击跳转 |
| `stock_abnormal_event_data` | 个股异动详情对象 |
| `plate_abnormal_event_data` | 板块异动详情对象 |

## 事件类型

当前代码识别的类型：

- `10001` 封涨停板
- `10002` 封跌停板
- `10003` 打开涨停
- `10004` 打开跌停
- `10005` 逼近涨停
- `10006` 逼近跌停
- `10007` 将开涨停
- `10008` 将开跌停
- `10009` 大幅拉升
- `10010` 快速跳水
- `10014` 开板回封
- `11000` 板块拉升
- `11001` 板块跳水

## 板块异动对象 `plate_abnormal_event_data`

| 字段 | 含义 |
| --- | --- |
| `plate_name` | 板块名 |
| `pcp` | 板块当前涨跌幅，当前系统主展示值 |
| `mtm` | 板块分钟级/瞬时波动值，当前系统作为辅助展示值使用 |
| `related_stocks` | 关联个股列表 |

### `related_stocks[]`

| 字段 | 含义 |
| --- | --- |
| `name` | 个股名 |
| `symbol` | 个股代码 |
| `pcp` | 个股当前涨跌幅 |
| `mtm` | 个股分钟级/瞬时波动 |

## 个股异动对象 `stock_abnormal_event_data`

| 字段 | 含义 |
| --- | --- |
| `name` | 个股名 |
| `pcp` | 个股当前涨跌幅 |
| `mtm` | 个股分钟级/瞬时波动 |
| `related_plates` | 关联板块列表 |

### `related_plates[]`

| 字段 | 含义 |
| --- | --- |
| `plate_name` | 板块名 |
| `plate_pcp` | 板块当前涨跌幅 |

## 当前系统怎么用

- `pcp`：用于主涨幅展示和红绿着色
- `mtm`：用于补充“分时触发幅度”
- `related_stocks / related_plates`：用于关联说明和辅助判断
- `event_type`：用于决定标签文案和基础方向
- `event_timestamp`：用于排序、去重、分页续拉
- `target`：用于个股跳转雪球

## 还能继续挖的方向

- 是否还有接口未暴露的 `reason`、`strength`、`volume`、`order_amount`、`seal_amount` 一类字段
- `mtm` 和 `pcp` 是否分别对应“瞬时变化”和“当前涨跌幅”
- 是否存在板块级更细的分时字段
- 是否能从 `related_stocks` / `related_plates` 里继续提取梯队、共振、容量属性

## 备注

- 上面“字段含义”里，`pcp` / `mtm` 的解释是根据当前系统的使用方式推断出来的，不是官方接口文档。
- 如果后面你拿到一份真实响应样本，这份文档可以直接补成正式版。
