#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
export TZ="Asia/Shanghai"

readonly REPO="zxl7/quant-review"
readonly REF="main"
readonly APP_DIR="/Users/zxl/Library/Application Support/quant-review-workflow-trigger"
readonly STATE_DIR="${APP_DIR}/state"

dry_run="false"
if [ "${1:-}" = "--dry-run" ]; then
  dry_run="true"
  now_hhmm="${2:-}"
  if ! [[ "${now_hhmm}" =~ ^[0-9]{4}$ ]]; then
    echo "usage: $0 --dry-run HHMM" >&2
    exit 2
  fi
else
  now_hhmm="$(date '+%H%M')"
fi

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

in_window() {
  local target="$1"
  local current_minutes=$((10#${now_hhmm:0:2} * 60 + 10#${now_hhmm:2:2}))
  local target_minutes=$((10#${target:0:2} * 60 + 10#${target:2:2}))
  [ "${current_minutes}" -ge "${target_minutes}" ] && [ "${current_minutes}" -le $((target_minutes + 2)) ]
}

run_dispatch() {
  local dispatch_key="$1"
  local workflow="$2"
  shift 2

  local date_key
  date_key="$(date '+%Y%m%d')"
  local state_file="${STATE_DIR}/${date_key}-${dispatch_key}"
  if [ -f "${state_file}" ]; then
    return 0
  fi

  if [ "${dry_run}" = "true" ]; then
    printf 'dispatch=%s workflow=%s args=' "${dispatch_key}" "${workflow}"
    printf '%q ' "$@"
    printf '\n'
    return 0
  fi

  # 兜底只分发既有 workflow，不在本机执行取数、构建或覆盖线上产物。
  log "trigger: key=${dispatch_key} workflow=${workflow} ref=${REF}"
  gh workflow run "${workflow}" --repo "${REPO}" --ref "${REF}" "$@"
  printf '%s\n' "${dispatch_key}" > "${state_file}"
  log "ok: workflow dispatch requested key=${dispatch_key}"
}

if [ "${dry_run}" != "true" ]; then
  weekday="$(date '+%u')"
  if [ "${weekday}" -gt 5 ]; then
    exit 0
  fi
fi

matched="false"

# 上午会话需要同时启动竞价守窗和盘中运行时，两条链分别记录状态，失败后可单独重试。
if in_window "0614"; then
  matched="true"
  if [ "${dry_run}" != "true" ]; then
    mkdir -p "${STATE_DIR}"
    gh auth status -h github.com >/dev/null
  fi
  run_dispatch "morning-auction" "auction_prefetch.yml" \
    -f scheduled_clock="06:14:00" \
    -f wait_for_auction="true"
  run_dispatch "morning-runtime" "intraday_runtime.yml" \
    -f mode="remaining" \
    -f session="morning"
fi

open_fallbacks=(
  "0929|0926|26 9 * * 1-5"
  "0934|0931|31 9 * * 1-5"
  "0939|0936|36 9 * * 1-5"
)
for fallback in "${open_fallbacks[@]}"; do
  IFS='|' read -r fallback_clock business_slot schedule_slot <<< "${fallback}"
  if in_window "${fallback_clock}"; then
    matched="true"
    if [ "${dry_run}" != "true" ]; then
      mkdir -p "${STATE_DIR}"
      gh auth status -h github.com >/dev/null
    fi
    run_dispatch "open-${business_slot}" "publish_pages.yml" \
      -f run_stage="open" \
      -f stock_research_query_tag="fore" \
      -f schedule_slot="${schedule_slot}"
  fi
done

# 下午兜底在主 schedule 三分钟后进入同一并发通道，仍由既有逻辑等待到 13:00。
if in_window "0946"; then
  matched="true"
  if [ "${dry_run}" != "true" ]; then
    mkdir -p "${STATE_DIR}"
    gh auth status -h github.com >/dev/null
  fi
  run_dispatch "afternoon-runtime" "intraday_runtime.yml" \
    -f mode="remaining" \
    -f session="afternoon"
fi

eod_fallbacks=(
  "1510|1507|7 15 * * 1-5"
  "1616|1613|13 16 * * 1-5"
  "1722|1719|19 17 * * 1-5"
  "1830|1827|27 18 * * 1-5"
)
for fallback in "${eod_fallbacks[@]}"; do
  IFS='|' read -r fallback_clock business_slot schedule_slot <<< "${fallback}"
  if in_window "${fallback_clock}"; then
    matched="true"
    if [ "${dry_run}" != "true" ]; then
      mkdir -p "${STATE_DIR}"
      gh auth status -h github.com >/dev/null
    fi
    run_dispatch "eod-${business_slot}" "publish_pages.yml" \
      -f run_stage="eod" \
      -f schedule_slot="${schedule_slot}"
  fi
done

if [ "${dry_run}" = "true" ] && [ "${matched}" = "false" ]; then
  echo "dispatch=none"
fi
