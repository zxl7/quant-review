#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# 兼容入口：
# - ./run.sh              -> ./qr.sh fetch
# - ./run.sh 2026-05-19   -> ./qr.sh fetch 2026-05-19
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -eq 0 ]; then
  exec "${ROOT_DIR}/qr.sh" fetch
fi

exec "${ROOT_DIR}/qr.sh" fetch "$@"
