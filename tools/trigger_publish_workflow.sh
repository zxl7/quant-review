#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

HOME_DIR="${HOME:-/Users/zxl}"
APP_DIR="${HOME_DIR}/Library/Application Support/quant-review-workflow-trigger"
WORKFLOW="publish_pages.yml"
REF="main"
REPO="zxl7/quant-review"
STATE_DIR="${APP_DIR}/state"
LOG_DIR="${APP_DIR}/logs"
STATE_FILE="${STATE_DIR}/last_workflow_trigger"

mkdir -p "${STATE_DIR}" "${LOG_DIR}"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

weekday="$(date '+%u')"
if [ "${weekday}" -gt 5 ]; then
  log "skip: weekend"
  exit 0
fi

hour="$(date '+%H')"
minute="$(date '+%M')"
now_min=$((10#${hour} * 60 + 10#${minute}))

mode="skip"
if [ "${now_min}" -ge $((9 * 60 + 30)) ] && [ "${now_min}" -le $((11 * 60 + 30)) ]; then
  mode="intraday"
elif [ "${now_min}" -ge $((13 * 60)) ] && [ "${now_min}" -lt $((15 * 60)) ]; then
  mode="intraday"
elif [ "${now_min}" -ge $((15 * 60 + 12)) ] && [ "${now_min}" -le $((15 * 60 + 31)) ]; then
  mode="eod"
fi

if [ "${mode}" = "skip" ]; then
  log "skip: outside trading window"
  exit 0
fi

slot="$(date '+%Y%m%d-%H%M')"
if [ -f "${STATE_FILE}" ] && [ "$(cat "${STATE_FILE}")" = "${slot}" ]; then
  log "skip: already triggered ${slot}"
  exit 0
fi

if ! command -v gh >/dev/null 2>&1; then
  log "error: gh command not found"
  exit 127
fi

if ! gh auth status >/dev/null 2>&1; then
  log "error: gh is not authenticated"
  exit 2
fi

log "trigger: repo=${REPO} workflow=${WORKFLOW} ref=${REF} mode=${mode}"
gh workflow run "${WORKFLOW}" --repo "${REPO}" --ref "${REF}"
printf '%s' "${slot}" > "${STATE_FILE}"
log "ok: workflow dispatch requested"
