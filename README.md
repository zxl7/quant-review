# quant-review

A 股短线量化复盘系统，服务龙头战法交易体系。基于必盈 API 取数 → Python pipeline 加工 → Vue3 单文件渲染，生成盘后复盘报告。

---

## 一、技术架构：三层分离

```
┌──────────────────────────────────────────────────────────┐
│  Layer 1  数据源                                         │
│  biying API → pools_cache / theme_cache / index 日K      │
│  （daily_review/data/biying.py）                         │
├──────────────────────────────────────────────────────────┤
│  Layer 2  数据加工                                       │
│  Python pipeline 模块链（15+ 模块）                       │
│  ├─ 情绪：六维评分 / 周期四阶段 / 渡劫 / 崩溃链           │
│  ├─ 题材：板块热力图 / 轮动 / 三象限                      │
│  ├─ 连板：天梯 / 高度趋势 / 龙头神形 / 主流三级           │
│  ├─ 预测：仓位五档 / 反弹三阶段 / 交易性质 / 行动指南      │
│  └─ 盯盘：盘中切片 / 快照 / 异动                          │
│  （daily_review/modules_v2/）                            │
├──────────────────────────────────────────────────────────┤
│  Layer 3  渲染                                           │
│  Vue3 + ECharts + Vite → vite-plugin-singlefile → 单 HTML │
│  （web/src/  — 7 Tab：情绪 / 题材 / 连板 / 预测 / 实时     │
│                    / 异动 / 快讯）                         │
└──────────────────────────────────────────────────────────┘
```

**数据与渲染完全分离**：Layer 1/2 产出 `cache/market_data-YYYYMMDD.json`（纯 JSON），Layer 3 消费这个 JSON 渲染。Python pipeline 不知道页面的 DOM 结构，Vue3 组件不知道数据怎么来的。中间通过 `marketData` 这一个接口协议解耦。

---

## 二、本地使用

### 前置

```bash
# Python 依赖
pip install -r requirements.txt

# 必盈 Token（二选一）
cp .env.example .env   # 编辑填入 BIYING_TOKEN
# 或 export BIYING_TOKEN="xxx"
```

### 命令

```bash
chmod +x ./qr.sh

# 在线取数 + 生成报告（调 API，有成本）
./qr.sh fetch                # 自动取最近交易日
./qr.sh fetch 2026-05-20     # 指定日期

# 离线重建（不调 API，纯本地算）
./qr.sh render               # 用缓存里最新的 market_data
./qr.sh render 20260520      # 指定日期（8 位紧凑格式）

# Vue3 前端开发
cd web && npm run dev         # 启动 Vite → http://localhost:5173
cd web && npm run build       # 产出 dist/index.html（单文件）
```

输出：
- `cache/market_data-YYYYMMDD.json` — 结构化数据
- `web/dist/index.html` — 渲染后的前端入口
- `web/dist/market_data.json` / `web/dist/market_data.js` — 前端运行时数据

---

## 三、线上部署（GitHub Actions）

工作流 `.github/workflows/publish_pages.yml` 自动执行：

1. `./qr.sh fetch` — 从必盈 API 取数
2. pipeline 重建 market_data JSON
3. 注入运行时数据并生成 `web/dist`
4. push 到 `gh-pages` 分支 → GitHub Pages 自动发布

**一次性配置**：
- Settings → Secrets → 添加 `BIYING_TOKEN`、`BIYING_BASE_URL`
- Settings → Pages → Source: Deploy from branch, `gh-pages` / `/(root)`

**触发**：
- `push` 到 `main` 分支自动发布
- GitHub Actions `schedule` 在工作日北京时间盘中/收盘时段自动跑
- `workflow_dispatch` 可手动补跑，默认就是全量更新；只有需要竞价补抓时才传 `stock_research_query_tag=fore`

现在建议以 GitHub Actions 为唯一生产调度入口，本地不再依赖 `launchd`/`gh workflow run` 常驻触发。

---

## 四、注意事项

1. **必盈 API 优先**：所有数据取数走 `data/biying.py`，不要新增 akshare 调用。
2. **Token 安全**：`.env` 已在 `.gitignore`，不要提交。GitHub Secrets 同理。
3. **交易日回退**：非交易日执行 `fetch` 时自动回退到最近交易日。
4. **render 日期格式**：`./qr.sh render` 接受 8 位紧凑格式（`20260520`），`fetch` 接受 `YYYY-MM-DD`。
5. **离线 render 需要缓存**：如果本地没有对应日期的 `cache/market_data-*.json`，先跑一次 `./qr.sh fetch`。
6. **modules_v2 按 Tab 组织**：`sentiment/` `themes/` `ladder/` `plan/` `watch/` 五个子包，`__init__.py` 集中导出 `ALL_MODULES`。
7. **AI 分析模块**：代码在 `daily_review/ai/`，已实现但未接入 pipeline（GitHub Actions 无 AI runtime）。以后需要时在 `cli.py` 恢复 `_inject_ai_analysis()` 调用即可。
8. **Vue3 前端**：`web/src/` 当前通过 `import ...?raw` 读旧版 HTML 的 CSS 和测试数据。正式切 Vue3 部署时需清理 `useMarketData.ts` 中的硬编码文件 import，改为纯 `window.__MARKET_DATA__` 注入。

---

## 关键文件

| 文件 | 作用 |
|------|------|
| `qr.sh` | 统一 CLI 入口 |
| `daily_review/cli.py` | fetch / rebuild / intraday 调度 |
| `daily_review/data/biying.py` | 必盈 API 数据源 |
| `daily_review/modules_v2/` | pipeline 模块（15+） |
| `daily_review/render/render_html.py` | 衍生展示字段构造（供 web 数据注入复用） |
| `web/` | **Vue3 新版前端**（Vite + ECharts + singlefile） |
| `web/src/composables/useMarketData.ts` | 数据接口层 |
| `.github/workflows/publish_pages.yml` | 自动部署 |
