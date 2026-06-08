#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

branch="${1:-$(git branch --show-current)}"
if [[ -z "${branch}" ]]; then
  echo "error: unable to detect current branch" >&2
  exit 1
fi

msg="${2:-25分个股竞价数据抓取～}"

echo "trigger branch: ${branch}"
echo "trigger message: ${msg}"

git commit --allow-empty -m "${msg}"
git push origin "${branch}"

echo "ok: empty trigger push sent to origin/${branch}"
