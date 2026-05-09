#!/bin/bash
# simulate_ci.sh
# 本地模拟 GitHub Actions CI 执行环境（轻量级，无需 Docker）
# 使用：./simulate_ci.sh [fetch|intraday|push] [YYYY-MM-DD]

set -euo pipefail

MODE="${1:-fetch}"
RUN_DATE="${2:-}"
DRY_RUN=false

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "本地 CI 模拟"
echo "模式: ${MODE}"
[ -n "${RUN_DATE}" ] && echo "日期: ${RUN_DATE}"
echo "=========================================="
echo ""

# ─── 步骤 0: 环境检查 ───────────────────────
echo -e "${YELLOW}[0/6]${NC} 环境检查"
echo "  系统时区: $(date +%Z)"
echo "  Python: $(python3 --version 2>/dev/null || echo '未找到')"
echo "  工作目录: $(pwd)"
echo ""

# ─── 步骤 1: 设置环境变量（模拟 CI env）─────
echo -e "${YELLOW}[1/6]${NC} 设置环境变量（模拟 CI）"
export TZ=Asia/Shanghai
export FORCE_JAVASCRIPT_ACTIONS_TO_NODE24="true"
echo "  TZ=Asia/Shanghai"
echo "  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true"
if [ -z "${BIYING_TOKEN:-}" ]; then
    echo -e "  ${RED}⚠️  BIYING_TOKEN 未设置${NC}"
    echo "  请先: export BIYING_TOKEN=你的token"
    exit 2
fi
echo -e "  ${GREEN}✓${NC} BIYING_TOKEN 已设置"
echo ""

# ─── 步骤 2: 恢复缓存（模拟 CI 的 cache restore）──
echo -e "${YELLOW}[2/6]${NC} 恢复缓存（模拟 CI 从 cache_online/ 和 gh-pages 恢复）"
mkdir -p cache
mkdir -p cache_online
mkdir -p site_prev/cache

# 从 cache_online 恢复（模拟 CI 的 "Seed cache from repository cache_online/"）
if [ -d "cache_online" ] && [ "$(ls -A cache_online 2>/dev/null)" ]; then
    cp -f cache_online/*.json cache/ 2>/dev/null || true
    echo "  ✓ 从 cache_online/ 恢复缓存"
fi

# 从 site_prev 恢复（模拟 CI 的 "Restore history cache from gh-pages"）
if [ -d "site_prev/cache" ]; then
    cp -f site_prev/cache/market_data-*.json cache/ 2>/dev/null || true
    cp -f site_prev/cache/pools_cache.json cache/ 2>/dev/null || true
    cp -f site_prev/cache/theme_cache.json cache/ 2>/dev/null || true
    cp -f site_prev/cache/plate_rotate_cache.json cache/ 2>/dev/null || true
    cp -f site_prev/cache/index_kline_cache.json cache/ 2>/dev/null || true
    cp -f site_prev/cache/height_trend_cache.json cache/ 2>/dev/null || true
    cp -f site_prev/cache/theme_trend_cache.json cache/ 2>/dev/null || true
    echo "  ✓ 从 site_prev/cache/ 恢复历史缓存"
fi

# 清理：只保留最近 7 个 market_data
files=( $(ls -1 cache/market_data-*.json 2>/dev/null | sort || true) )
if [ ${#files[@]} -gt 7 ]; then
    rm -f "${files[@]:0:${#files[@]}-7}"
    echo "  ✓ 清理旧缓存（保留最近 7 个）"
fi
echo ""

# ─── 步骤 3: 检查交易日（模拟 CI 的 "Check A-share trade day"）──
echo -e "${YELLOW}[3/6]${NC} 检查 A 股交易日"
if [ -z "${RUN_DATE}" ]; then
    # 使用 Python 检查（和 CI 一样）
    RUN_DATE=$(TZ=Asia/Shanghai python3 -c "
import os, json, sys
from pathlib import Path

cache_dir = Path('cache')
def collect_local_trade_days():
    out = set()
    p = cache_dir / 'trade_days_cache.json'
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding='utf-8'))
            days = data.get('days') or []
            for d in days:
                if isinstance(d, str) and len(d) == 10:
                    out.add(d)
    except Exception:
        pass
    p = cache_dir / 'pools_cache.json'
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding='utf-8'))
            pools = (data.get('pools') or {}) if isinstance(data, dict) else {}
            for pn in ('ztgc', 'dtgc', 'zbgc', 'qsgc'):
                mp = pools.get(pn) or {}
                if isinstance(mp, dict):
                    for d in mp.keys():
                        if isinstance(d, str) and len(d) == 10:
                            out.add(d)
    except Exception:
        pass
    return sorted(out)

try:
    from daily_review.calendar import is_trade_day
    today = '$(date +%Y-%m-%d)'
    if is_trade_day(today):
        print(today)
    else:
        # 回退到最近交易日
        local_dates = collect_local_trade_days()
        dates = [d for d in local_dates if d <= today]
        if dates:
            print(dates[-1])
        else:
            print(today)
except Exception:
    # fallback
    from datetime import datetime, timedelta
    d = datetime.now()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    print(d.strftime('%Y-%m-%d'))
" 2>/dev/null || date +%Y-%m-%d)
fi
echo "  运行日期: ${RUN_DATE}"
echo ""

# ─── 步骤 4: 执行核心流程（模拟 CI 的 "Generate latest report"）──
echo -e "${YELLOW}[4/6]${NC} 执行核心流程"
echo "  命令: ./qr.sh ${MODE} ${RUN_DATE}"
echo "------------------------------------------"
chmod +x ./qr.sh 2>/dev/null || true

if [ "${MODE}" = "intraday" ]; then
    ./qr.sh fetch "${RUN_DATE}"
    PYTHONPATH=. python3 -m daily_review.watch_runtime --date "$(echo "${RUN_DATE}" | tr -d '-')" --publish 2>/dev/null || true
elif [ "${MODE}" = "push" ]; then
    # push 模式：强制在线拉取
    ./qr.sh fetch "${RUN_DATE}"
else
    # fetch 模式（默认）
    ./qr.sh fetch "${RUN_DATE}"
fi
echo "------------------------------------------"
echo ""

# ─── 步骤 5: 准备站点目录（模拟 CI 的 "Prepare Pages site"）──
echo -e "${YELLOW}[5/6]${NC} 准备 Pages 站点目录"
mkdir -p site
rm -rf site/*.html site/*.json 2>/dev/null || true

# 找最新的 HTML（和 CI 逻辑一样）
if [ "${MODE}" = "intraday" ]; then
    report_html="$(ls -t ./html/*-intra.html ./html/*-intraday-tab-v1.html ./html/*intraday*.html 2>/dev/null | head -n 1 || true)"
    [ -z "${report_html}" ] && report_html="$(ls -t ./html/*tab-v1.html 2>/dev/null | head -n 1 || true)"
else
    report_html="$(ls -t ./html/*tab-v1.html 2>/dev/null | head -n 1 || true)"
fi

if [ -z "${report_html}" ]; then
    echo -e "  ${RED}⚠️  未找到 HTML 报告${NC}"
    ls -la ./html/ 2>/dev/null || echo "  html/ 目录为空"
else
    cp -f "${report_html}" ./site/
    cp -f "${report_html}" ./site/index.html
    echo "  ✓ ${report_html} -> site/index.html"
fi
cp -f ./html/latest_intraday.json ./site/ 2>/dev/null || true
cp -f ./html/latest_intraday_slices.json ./site/ 2>/dev/null || true
touch ./site/.nojekyll
echo ""

# ─── 步骤 6: 同步到 site_prev（模拟 CI 的 push to gh-pages）──
echo -e "${YELLOW}[6/6]${NC} 同步到 site_prev/（模拟 push 到 gh-pages）"
mkdir -p site_prev
rm -f site_prev/*.html 2>/dev/null || true
cp -f ./site/.nojekyll site_prev/.nojekyll 2>/dev/null || true
cp -f ./site/index.html site_prev/index.html 2>/dev/null || true
for f in ./site/*.html; do
    [ -f "$f" ] && cp -f "$f" site_prev/ 2>/dev/null || true
done
mkdir -p site_prev/cache
cp -f cache/market_data-*.json site_prev/cache/ 2>/dev/null || true
cp -f cache/pools_cache.json site_prev/cache/ 2>/dev/null || true
cp -f cache/theme_cache.json site_prev/cache/ 2>/dev/null || true
echo "  ✓ 同步完成"
echo ""

# ─── 完成 ───────────────────────────────
echo "=========================================="
echo -e "${GREEN}✓ 本地 CI 模拟完成${NC}"
echo ""
echo "📂 输出文件:"
echo "  HTML: site/index.html"
echo "  cache: cache/*.json"
echo "  site_prev: site_prev/ (模拟 gh-pages 分支)"
echo ""
echo "🔍 下一步:"
echo "  查看报告: open site/index.html"
echo "  查看缓存: ls -la cache/"
echo "  模拟推送: (需手动 git push 到 gh-pages)"
echo "=========================================="
