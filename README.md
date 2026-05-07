# quant-review（复盘日记生成器）

一个脚本覆盖日常使用：在线取数生成、离线渲染、（可选）本地发布到 `gh-pages`。
输出 HTML 在 `html/` 目录（运行产物默认不提交 Git，见 `.gitignore`）。

## 环境要求

- Python 3.10+（建议）

## 重要：配置 BIYING_TOKEN（敏感信息不要提交）

推荐使用 `.env`（脚本会自动加载）：

```bash
cp .env.example .env
# 编辑 .env，填入 BIYING_TOKEN
```

也支持环境变量：

```bash
export BIYING_TOKEN="你的token"
export BIYING_BASE_URL="https://api.biyingapi.com"   # 可选
```

说明：
- `.env` 已在 `.gitignore` 中忽略，不要把真实 token 提交到 Git
- Python 侧同样支持自动加载 `.env`（见 `daily_review/env.py`）

---

## 本地使用（推荐统一入口：qr.sh）

给脚本执行权限：
```bash
chmod +x ./qr.sh
```

### 1) 在线取数 + 生成最新报告（有成本）
```bash
./qr.sh fetch                # 自动回退到最近交易日
./qr.sh fetch 2026-04-17     # 指定日期（YYYY-MM-DD）
```

输出：
- `cache/market_data-YYYYMMDD.json`
- `html/复盘日记-YYYYMMDD-tab-v1.html`

### 2) 只离线渲染（无成本，不请求接口）
```bash
./qr.sh render               # 使用 cache 里最新的 market_data-*.json
./qr.sh render 2026-04-17
```

### 3) 仅在线取数/计算（便于你本地调试计算逻辑）
```bash
./qr.sh gen                  # 只跑 gen_report_v4.py（会取数，会写 cache，会生成留档 HTML）
./qr.sh gen 2026-04-17
```

### 兼容旧脚本名（可选）
如果你习惯旧命令，也保留了壳脚本（内部转调 `qr.sh`）：
- `./fetch_report.sh` ≈ `./qr.sh fetch`
- `./review.sh` ≈ `./qr.sh render`
- `./run_report.sh` ≈ `./qr.sh gen`

---

## 自动发布到 GitHub Pages（推荐：GitHub Actions）

仓库内已提供工作流：`.github/workflows/publish_pages.yml`，会：
- 云端执行 `./qr.sh fetch` 生成最新 HTML
- 将最新产物写入 `gh-pages` 分支（`index.html` + 同步保留当日报告文件）
- GitHub Pages 使用 **Deploy from branch: gh-pages（/root）** 发布

### 一次性配置
1) GitHub → 仓库 → Settings → Pages  
   Source 选择：**Deploy from a branch**  
   Branch 选择：`gh-pages` / `/(root)`

2) GitHub → 仓库 → Settings → Secrets and variables → Actions → New repository secret
   - Name: `BIYING_TOKEN`（必填）
   - Name: `BIYING_BASE_URL`（可选）

### 触发方式
- **提交代码触发**：push 到 `main` 会自动发布
- **定时触发**：工作日定时（时间用脚本按北京时间 15:01 放行；cron 本身为 UTC）

---

## 常见问题

### 1) 为什么日期会自动变化？
当输入日期是周末/非交易日，取数脚本会自动回退到最近交易日，并在日志里提示。

### 2) 离线渲染提示找不到 `market_data-YYYYMMDD.json`
说明本地还没有这一天的缓存。先跑一次：
```bash
./qr.sh fetch 2026-04-17
```

---

## 关键文件

- `qr.sh`：统一入口脚本
- `gen_report_v4.py`：在线取数/计算主脚本（生成 cache + 留档 HTML）
- `daily_review/render/render_html.py`：离线渲染器（模板注入）
- `templates/report_template.html`：主模板

---

## 语录合集（可选）

为了让复盘更“有手感”，仓库里维护了一份可持续扩充的语录合集：

- `心法.md`：短线/龙头/情绪周期相关的核心口诀与摘录

你可以把它当作：
- 复盘后的“自检清单”
- 行为约束（避免临时起意）
- 训练用语料（长期维护、不断迭代）
