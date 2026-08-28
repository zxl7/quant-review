#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

readonly LABEL="com.zxl.quant-review.workflow-trigger"
readonly APP_DIR="/Users/zxl/Library/Application Support/quant-review-workflow-trigger"
readonly LAUNCH_AGENT="/Users/zxl/Library/LaunchAgents/${LABEL}.plist"
readonly GUI_DOMAIN="gui/$(id -u)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v gh >/dev/null 2>&1; then
  echo "error: gh command not found" >&2
  exit 127
fi
if ! gh auth status -h github.com >/dev/null 2>&1; then
  echo "error: gh is not authenticated; run: gh auth login -h github.com" >&2
  exit 2
fi

plutil -lint "${SCRIPT_DIR}/${LABEL}.plist" >/dev/null
install -d -m 755 "${APP_DIR}/state" "${APP_DIR}/logs" "/Users/zxl/Library/LaunchAgents"
install -m 755 "${SCRIPT_DIR}/trigger_publish_workflow.sh" "${APP_DIR}/trigger_publish_workflow.sh"
install -m 644 "${SCRIPT_DIR}/${LABEL}.plist" "${LAUNCH_AGENT}"

# 安装前精确卸载同名服务，避免旧 ProgramArguments 继续指向桌面仓库。
if launchctl print "${GUI_DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "${GUI_DOMAIN}/${LABEL}"
fi
launchctl bootstrap "${GUI_DOMAIN}" "${LAUNCH_AGENT}"
launchctl enable "${GUI_DOMAIN}/${LABEL}"

echo "ok: installed ${LABEL}"
launchctl print "${GUI_DOMAIN}/${LABEL}" | sed -n '1,80p'
