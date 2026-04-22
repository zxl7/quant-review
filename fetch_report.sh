#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# 兼容入口：历史脚本名保留，实际调用统一入口 qr.sh
#
# 用法：
#   ./fetch_report.sh [YYYY-MM-DD]
#
set -euo pipefail
exec ./qr.sh fetch "${1:-}"

