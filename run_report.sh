#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# 兼容入口：只做“在线取数/生成缓存”（不做离线渲染）
#
# 用法：
#   ./run_report.sh [YYYY-MM-DD]
#
set -euo pipefail
exec ./qr.sh gen "${1:-}"

