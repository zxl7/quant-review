#!/bin/bash
# simulate_ci_with_docker.sh
# 用 Docker 模拟 GitHub Actions CI 环境（ubuntu-latest + Python 3.11）
# 使用：./simulate_ci_with_docker.sh [fetch|intraday] [YYYY-MM-DD]

set -euo pipefail

MODE="${1:-fetch}"
RUN_DATE="${2:-$(date +%Y-%m-%d)}"
IMAGE="python:3.11-bookworm"

echo "=========================================="
echo "Docker CI 模拟"
echo "模式: ${MODE}"
echo "日期: ${RUN_DATE}"
echo "镜像: ${IMAGE}"
echo "=========================================="

# 检查 Docker 是否可用
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker 未运行，请先启动 Docker Desktop"
    echo "   或者直接用: ./simulate_ci.sh （无需 Docker）"
    exit 1
fi

# 准备缓存目录（模拟 CI 的 cache_online 恢复）
mkdir -p cache_online
mkdir -p cache
mkdir -p html
mkdir -p site_prev/cache

echo ""
echo "📂 步骤1: 恢复缓存（模拟 CI 从 cache_online/ 和 gh-pages 恢复）"
if [ -d "cache_online" ] && [ "$(ls -A cache_online 2>/dev/null)" ]; then
    cp -f cache_online/*.json cache/ 2>/dev/null || true
    echo "  ✓ 从 cache_online/ 恢复缓存"
fi

echo ""
echo "🐳 步骤2: 启动 Docker 容器（${IMAGE}）"
echo "  工作目录: /workspace"
echo "  挂载: $(pwd) -> /workspace"
echo ""

docker run --rm \
    -v "$(pwd):/workspace" \
    -w /workspace \
    -e BIYING_TOKEN="${BIYING_TOKEN:-}" \
    -e BIYING_BASE_URL="${BIYING_BASE_URL:-https://api.biyingapi.com}" \
    -e TZ=Asia/Shanghai \
    "${IMAGE}" \
    bash -c '
        set -euo pipefail
        echo "✓ Python 版本: $(python3 --version)"
        echo "✓ 工作目录: $(pwd)"
        echo "✓ TZ: $(date)"
        echo ""
        
        # 检查 token
        if [ -z "${BIYING_TOKEN}" ]; then
            echo "❌ 未设置 BIYING_TOKEN 环境变量"
            echo "   请先: export BIYING_TOKEN=你的token"
            exit 2
        fi
        echo "✓ BIYING_TOKEN 已设置"
        echo ""
        
        # 安装依赖（如果有 requirements.txt）
        if [ -f "requirements.txt" ]; then
            echo "📦 安装 Python 依赖..."
            pip3 install -q -r requirements.txt
            echo ""
        fi
        
        # 设置脚本可执行权限
        chmod +x ./qr.sh 2>/dev/null || true
        
        # 执行核心流程
        echo "🚀 步骤3: 执行 ./qr.sh '"'${MODE}'"' '"'${RUN_DATE}'"'"
        echo "------------------------------------------"
        
        if [ "${MODE}" = "intraday" ]; then
            ./qr.sh fetch "${RUN_DATE}"
            python3 -m daily_review.watch_runtime --date "$(echo "${RUN_DATE}" | tr -d "-")" --publish 2>/dev/null || true
        else
            ./qr.sh fetch "${RUN_DATE}"
        fi
        
        echo "------------------------------------------"
        echo ""
        echo "✓ Docker 内执行完成"
        echo ""
        echo "📂 输出文件:"
        ls -la html/*.html 2>/dev/null || echo "  (无 HTML 输出)"
        ls -la cache/*.json 2>/dev/null || echo "  (无 cache 输出)"
    '

echo ""
echo "=========================================="
echo "✓ Docker 模拟完成"
echo "  查看输出: ls -la html/"
echo "  查看缓存: ls -la cache/"
echo "=========================================="
