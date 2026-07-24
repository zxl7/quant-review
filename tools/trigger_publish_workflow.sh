#!/usr/bin/env bash
set -euo pipefail

# Retired: GitHub Actions owns intraday scheduling. A local launchd dispatch of
# publish_pages.yml starts a full rebuild and can overwrite the live runtime.
echo "quant-review local workflow trigger is retired; use GitHub Actions schedules only."
