# quant-review 系统架构扫描与优化准备

更新时间：2026-06-06

## 0. 本轮已执行

- 已确认 `web` 为唯一主路线，旧模板/旧 HTML 注入链已下线。
- 已把发布层主实现从 `inject_data.py` 抽到 `daily_review/publish/web_bundle.py`。
- `inject_data.py` 现仅保留兼容 CLI / import 入口，便于渐进迁移而不打断 `qr.sh` 和 workflow。

## 1. 本次扫描范围

本次仅做系统扫描和架构优化准备，不改业务逻辑。重点查看了以下链路：

- Python 运行入口：`daily_review/cli.py`、`qr.sh`
- 模块执行框架：`daily_review/pipeline/*`、`daily_review/modules_v2/*`
- 数据注入与发布桥接：`inject_data.py`
- 个股研究/回测旁路：`scripts/build_stock_research_backtest.py`
- 缓存同步：`manage_cache.py`
- 线上发布：`.github/workflows/publish_pages.yml`
- 前端消费层：`web/src/App.vue`、`web/src/composables/useMarketData.ts`

## 2. 当前系统总览

系统已经不是单体页面，而是一个五段式链路：

1. 取数层
   - 主要来源是必盈接口，辅以东财/选股宝等辅助源。
   - 入口集中在 `daily_review/data/*`，但少量取数仍散落在 `daily_review/cli.py` 和脚本目录。

2. 计算层
   - 已有 `Context + Module + Runner` 的模块化骨架。
   - 主要分析模块位于 `daily_review/modules_v2/`，按 `sentiment/themes/ladder/plan` 分组。

3. 组装层
   - `daily_review/cli.py` 负责把原始数据、特征、模块执行、兼容字段、回测补算、缓存落盘串起来。
   - 当前它既是编排层，也是大量业务逻辑承载层。

4. 发布桥接层
   - `inject_data.py` 负责把 `cache/market_data-YYYYMMDD.json` 转成 `web/public` 和 `web/dist` 可消费数据。
   - 这里不只是“注入”，还承担了 schema 修复、别名归并、回测补算等职责。

5. 展示层
   - Vue3 前端通过 `useMarketData.ts` 从 `window.__MARKET_DATA__`、`market_data.js`、`market_data.json` 多路径兜底读取数据。
   - 页面层按 Tab 拆分较清楚，但类型约束较弱，主要依赖运行时字段存在。

## 3. 已有优点

- 已经有明确的模块化方向：`Context / Module / Runner` 是很好的重构支点。
- 分析模块已按领域分目录，后续可以继续朝“领域包”收口。
- 前后端已经通过 `marketData` 解耦，前端没有直接依赖 Python 内部实现。
- 发布链路已经迁到 GitHub Actions 主导，本地不再是唯一生产入口。
- 个股研究回测、盘中共振、题材主线等复杂能力已经能独立演进，说明领域能力沉淀是有效的。

## 4. 关键架构问题

### 4.1 编排层过重，`daily_review/cli.py` 成为新的巨石

当前 `daily_review/cli.py` 约 3111 行，混合了以下职责：

- 参数入口
- 交易日判断
- 在线/离线模式分支
- 缓存读写
- 原始数据拼装
- feature 注入
- module 执行
- 展示字段兼容
- 回测补算
- 盘中快照逻辑

这意味着：

- 业务修改经常需要回到同一个大文件
- 很难形成稳定的应用服务边界
- 单元测试颗粒度受限
- 新模式一多，分支复杂度会继续上涨

### 4.2 数据契约不够单一，`marketData` 同时承担“缓存/上下文/最终展示”三种角色

当前 `Context.from_market_data()` 直接从最终 `marketData` 反推 `raw/features/meta`，说明：

- 最终展示对象被反向当作中间运行上下文使用
- `marketData` 内部还夹带 `features/raw` 等运行时数据
- 局部重算和线上注入都在依赖“缓存里刚好还留着足够的内部字段”

直接后果：

- 数据边界不稳定
- 很多逻辑只能“兼容旧缓存”，而不是依赖明确 contract
- 发布物与计算中间态耦合过深

### 4.3 模块框架已存在，但依赖系统还不够严格

目前 `Runner` 是“声明顺序优先”的执行方式，不是真正严格的拓扑排序；同时存在多处模块共同写入同一个大对象，例如：

- 多个 plan 模块共同写 `marketData.v2`
- 多个模块依赖 `marketData` 中的兼容字段而不是更细粒度的 feature

这会导致：

- 模块之间的真实依赖图不透明
- 执行顺序很重要，但顺序知识藏在 `ALL_MODULES` 列表里
- 后续新增模块时容易出现覆盖、串写、隐式回归

### 4.4 发布链路耦合过高，缓存职责分散在三个位置

当前至少同时存在三类缓存空间：

- `cache/`：本地计算输入输出
- `cache_online/`：远端构建依赖包
- `gh-pages/cache/`：线上持久历史缓存

而且：

- `publish_pages.yml` 本身约 620 行
- `publish_pages.yml` 内部还承担 09:25/09:27 竞价快照预抓阶段，需要继续保持和主发布链的一致性
- `manage_cache.py`、`qr.sh`、workflow 都在各自管理保留/同步规则

直接问题：

- 缓存源头不唯一
- 线上构建成功依赖很多隐含文件存在
- 同一份业务缓存的生命周期规则散落在多个文件里

### 4.5 `inject_data.py` 职责越界，桥接层承载了业务修复

`inject_data.py` 目前不只是格式转换，还做了：

- theme alias 汇总
- plan 文案字段裁剪
- `stockResearchBacktest` 完整性校验
- 回测缺失时现场补算

这说明桥接层已经在承担“数据修复器/兜底业务层”的职责。风险在于：

- 线上发布结果不完全由主 pipeline 决定
- 本地 cache 和线上最终页面可能不是同一个真相
- 问题定位会在“计算阶段”和“注入阶段”之间来回跳

### 4.6 个股研究回测是重要子系统，但仍在主模块体系之外

`scripts/build_stock_research_backtest.py` 约 1234 行，已经是一个独立子系统，包含：

- 历史样本读取
- 交易日推进
- 09:25-09:30 竞价窗口判定
- 价格历史缓存
- 实时行情预抓复用
- 回测结果汇总

但它仍以“外部脚本 + 注入/CLI 侧调用”的方式存在，而不是一等公民领域模块。结果是：

- 主系统和回测系统的数据契约靠约定维持
- 回测相关故障常常要跨 `cli.py / inject_data.py / workflow / gh-pages cache` 联调

### 4.7 前端数据读取较灵活，但 contract 边界偏弱

`useMarketData.ts` 会按多个路径回退：

- 直接读 `window.__MARKET_DATA__`
- 动态加载 `market_data.js`
- 再 fallback 到 `market_data.json`

这对容错有帮助，但也意味着：

- 数据来源并不单一
- 前端对 schema 的强约束不足
- 很多页面逻辑默认 `Record<string, any>`，重构时容易把问题拖到运行时

## 5. 建议的目标架构

建议把系统收口为六层，并明确每层只做一件事。

### 5.1 Source 层

职责：只访问外部数据源，不做业务判定。

建议目录：

- `daily_review/sources/biying/*`
- `daily_review/sources/eastmoney/*`
- `daily_review/sources/xuangubao/*`

约束：

- 所有 HTTP 调用都从这里进入
- 返回统一原始结构，不输出展示字段

### 5.2 Cache 层

职责：定义缓存 schema、命名、保留策略和读写接口。

建议目录：

- `daily_review/cache/models.py`
- `daily_review/cache/repositories/*`
- `daily_review/cache/policies.py`

目标：

- 不再让 `cli.py`、workflow、`manage_cache.py` 各自维护保留规则
- 统一声明哪些缓存是“运行缓存”、哪些是“发布缓存”、哪些是“历史归档缓存”

### 5.3 Domain 层

职责：放领域纯逻辑，不关心命令行、文件路径、前端结构。

建议按领域拆包：

- `daily_review/domain/sentiment/*`
- `daily_review/domain/themes/*`
- `daily_review/domain/ladder/*`
- `daily_review/domain/plan/*`
- `daily_review/domain/stock_research/*`
- `daily_review/domain/intraday/*`

目标：

- 把“个股回测”从脚本侧搬成正式领域包
- 让领域算法只依赖 input model，不依赖注入脚本

### 5.4 Application 层

职责：编排 use case，而不是堆业务细节。

建议拆成几个应用服务：

- `build_eod_market_data`
- `build_intraday_snapshot`
- `rebuild_modules_partial`
- `build_stock_research_backtest`
- `prepare_publish_bundle`

这里应该替代现在 `daily_review/cli.py` 的大部分流程胶水。

### 5.5 Contract 层

职责：定义明确的数据契约。

至少拆出三套 schema：

- `RawSnapshot`
- `FeatureSnapshot`
- `PublishedMarketData`

关键原则：

- 发布给前端的对象不再反向承担运行上下文
- 前端只消费 `PublishedMarketData`
- `inject_data.py` 不再临时补业务字段

### 5.6 Delivery 层

职责：CLI、GitHub Actions、前端加载三类交付入口。

建议：

- CLI 只做参数解析 + 调 application service
- workflow 只做环境准备 + 调统一命令
- 前端只从单一入口加载发布产物

## 6. 分阶段优化路线

### Phase 0：先固化规则，不急着拆文件

目标：先把“什么是真相”说清楚。

建议产出：

- 明确三类 contract：运行态、缓存态、发布态
- 列出哪些字段允许进入最终 `marketData`
- 列出哪些逻辑必须前移到 build 阶段，不能留给 inject 阶段

优先动作：

- 给 `stockResearchBacktest`、`theme_alias_map`、`marketData.meta` 补 schema 文档
- 标记 `inject_data.py` 中哪些逻辑属于暂时兜底，准备迁出

### Phase 1：拆编排层

目标：把 `daily_review/cli.py` 从“业务巨石”拆成应用服务入口。

建议优先抽离：

- trade date / mode resolve
- cache restore / persist
- raw snapshot build
- feature build
- module run
- publish bundle prepare

完成标准：

- `cli.py` 只保留命令参数、日志、服务调用
- 单次主流程可以通过 service 层直接测试

### Phase 2：收紧模块依赖图

目标：让模块真正依赖 feature 和 typed contract，而不是松散地改同一个大 dict。

建议动作：

- 给 `Module` 增加更细颗粒度 output 命名
- 减少多个模块共同写 `marketData.v2`
- 把 `Runner` 从“声明顺序执行”升级到“显式依赖拓扑排序”

完成标准：

- `ALL_MODULES` 只是注册表，不再承担隐式顺序知识
- 模块覆盖冲突可以在运行前暴露

### Phase 3：回测子系统独立化

目标：把个股研究回测从“旁路脚本”升级为正式子系统。

建议动作：

- 建立 `daily_review/domain/stock_research/`
- 把预抓 quote、样本源、回测构建、发布对象分成独立 service
- 给回测产物定义独立 schema 与 repository

完成标准：

- `inject_data.py` 不再负责补算回测
- workflow 只负责调用统一的 stock research service

### Phase 4：统一发布与缓存

目标：把缓存生命周期和发布流程真正统一。

建议动作：

- 明确 `cache/`、`cache_online/`、`gh-pages/cache/` 的单一职责
- 把保留策略沉到 Python 代码，不再散落在 shell 和 workflow
- 缩短 `publish_pages.yml`，把业务判断尽量收回应用命令

完成标准：

- workflow 负责调度，不负责核心业务分支
- 线上失败可以快速判断是“调度问题 / 缓存问题 / 计算问题 / 发布问题”

### Phase 5：前端 contract 收口

目标：让前端只面对稳定、可校验的发布对象。

建议动作：

- 给 `useMarketData.ts` 增加类型定义
- 减少多路径 fallback，收敛到单一发布入口
- 将页面对 `any` 和兼容字段的依赖逐步收敛

完成标准：

- 页面缺字段时能在开发阶段暴露，而不是线上兜底
- 前后端协作围绕 schema，而不是围绕“某次 cache 刚好长这样”

## 7. 优先级建议

如果只做一轮最值当的优化，建议顺序如下：

1. 先拆 `daily_review/cli.py`
2. 再清理 `inject_data.py` 的业务修复职责
3. 再把个股研究回测独立成正式领域包
4. 最后统一 workflow 和缓存策略

原因：

- 这三处是当前复杂度和故障定位成本最高的位置
- 也是后续继续加功能时最容易形成新耦合的位置

## 8. 本次扫描给出的结论

这套系统已经具备“模块化重构”的基础，但当前仍处于“骨架已搭好、编排和契约还没完全收口”的阶段。

最核心的问题不是算法模块不够多，而是：

- 真正的系统边界还不够硬
- 最终发布对象和运行中间态还没有彻底分离
- 编排层、注入层、工作流层都在替彼此兜底

后续架构优化应该遵循一个原则：

把“取数真相、缓存真相、计算真相、发布真相”各自固定下来，减少跨层补救，而不是继续在现有大文件上叠规则。

## 9. 建议下一步

建议下一轮直接做下面两件事之一：

1. 先拆 `daily_review/cli.py` 的应用服务层骨架
2. 先整理 `marketData / features / raw / stockResearchBacktest` 的正式 schema

如果希望风险更低，建议先做第 2 项，再做第 1 项。
