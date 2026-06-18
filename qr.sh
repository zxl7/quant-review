#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# quant-review 统一入口脚本（合并原来的多个 *.sh）
#
# 设计目标：
# - 一个入口覆盖：在线取数生成、离线渲染、（可选）本地发布 gh-pages
# - 自动加载 .env（仅当环境变量未设置时）
# - 尽量函数式：小函数 + 明确入参/出参，副作用集中在命令末端
#
# 用法：
#   ./qr.sh fetch [YYYY-MM-DD]   # 在线取数 + pipeline 重建 + web 数据缓存
#   ./qr.sh render [YYYY-MM-DD]  # 只用 cache 离线重建 + web 构建/数据刷新（不请求接口）
#   ./qr.sh sync-cache [YYYY-MM-DD] # 同步 cache_online/（远端自动构建依赖目录）
#   ./qr.sh deploy              # （可选）把 web/dist/index.html 发布到 gh-pages/index.html
#
set -euo pipefail

DATE_ARG="${2:-}"
EXTRA_ARG="${3:-}"
STOCK_RESEARCH_QUERY_TAG=""

normalize_optional_args() {
  local second="${2:-}"
  local third="${3:-}"
  DATE_ARG=""
  EXTRA_ARG=""
  STOCK_RESEARCH_QUERY_TAG=""

  if [[ -n "${second}" && "${second}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    DATE_ARG="${second}"
    EXTRA_ARG="${third}"
  else
    EXTRA_ARG="${second}"
  fi

  if [[ -n "${EXTRA_ARG}" ]]; then
    STOCK_RESEARCH_QUERY_TAG="$(printf '%s' "${EXTRA_ARG}" | tr '[:upper:]' '[:lower:]')"
  fi
  if [[ -n "${STOCK_RESEARCH_QUERY_TAG}" ]]; then
    export STOCK_RESEARCH_QUERY_TAG
  else
    unset STOCK_RESEARCH_QUERY_TAG 2>/dev/null || true
  fi
}

cli_query_tag_args() {
  local query_tag="${STOCK_RESEARCH_QUERY_TAG:-}"
  if [[ -n "${query_tag}" ]]; then
    printf '%s\n' "--stock-research-query-tag" "${query_tag}"
  fi
}

run_daily_review_cli() {
  local query_tag="${STOCK_RESEARCH_QUERY_TAG:-}"
  if [[ -n "${query_tag}" ]]; then
    PYTHONPATH=. python3 -u -m daily_review.cli "$@" --stock-research-query-tag "${query_tag}"
  else
    PYTHONPATH=. python3 -u -m daily_review.cli "$@"
  fi
}

die() {
  echo "❌ $*" >&2
  exit 1
}

info() {
  echo "==> $*" >&2
}

warn() {
  echo "⚠️  $*" >&2
}

script_dir() {
  # 纯函数：输出脚本所在目录（绝对路径）
  cd "$(dirname "${BASH_SOURCE[0]}")" && pwd
}

load_dotenv_if_needed() {
  # 自动加载根目录 .env（仅当 BIYING_TOKEN 尚未设置时）
  local root dotenv
  root="$(script_dir)"
  dotenv="${root}/.env"
  if [[ -z "${BIYING_TOKEN:-}" && -f "${dotenv}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${dotenv}"
    set +a
  fi
}

ensure_token() {
  # 纯函数式校验：缺失即失败（不继续做任何副作用操作）
  [[ -n "${BIYING_TOKEN:-}" ]] || die "未设置 BIYING_TOKEN：请 export 或在项目根目录创建 .env（参考 .env.example）"
}

pick_latest_cache_date8() {
  # 从 cache/market_data-*.json 中找最新日期（按文件修改时间），输出 YYYYMMDD
  local latest_file base date8
  latest_file="$(ls -1t cache/market_data-*.json 2>/dev/null | head -n 1 || true)"
  [[ -n "${latest_file}" ]] || return 1
  base="$(basename "${latest_file}")"     # market_data-YYYYMMDD.json
  date8="${base#market_data-}"            # YYYYMMDD.json
  date8="${date8%.json}"                  # YYYYMMDD
  [[ "${date8}" =~ ^[0-9]{8}$ ]] || return 1
  echo "${date8}"
}

date8_to_date10() {
  # 纯函数：YYYYMMDD -> YYYY-MM-DD
  local d8="$1"
  echo "${d8:0:4}-${d8:4:2}-${d8:6:2}"
}

date10_to_date8() {
  # 纯函数：YYYY-MM-DD -> YYYYMMDD
  echo "$1" | tr -d '-'
}

refresh_watchlist_cache() {
  # 拉异动/板块/明日主题接口 + 跑 M3/M4/M5 推票
  # 产出 cache_online/watchlist_cache-YYYYMMDD.json，由 publish web bundle 注入前端 picks_advisor
  # 调用约束：必须在 sync_online_cache_dir 之后（因 fetch_watchlist 从 cache_online/ 读 pools/market_data，
  #          且 sync_online_cache_dir 会先清空 cache_online/）
  local date10="$1"
  local extra_arg="${2:-}"
  if [[ ! -f "tools/fetch_watchlist.py" ]]; then
    info "跳过 watchlist 推票生成：未找到 tools/fetch_watchlist.py"
    return 0
  fi
  info "生成算法推票缓存: ${date10}${extra_arg:+ ${extra_arg}}"
  if [[ -n "${extra_arg}" ]]; then
    PYTHONPATH=. python3 tools/fetch_watchlist.py --date "${date10}" "${extra_arg}" \
      || warn "fetch_watchlist 失败，将沿用已有 watchlist_cache（若存在）"
  else
    PYTHONPATH=. python3 tools/fetch_watchlist.py --date "${date10}" \
      || warn "fetch_watchlist 失败，将沿用已有 watchlist_cache（若存在）"
  fi
}

sync_account_nav_ledger_file() {
  # 账户净值长期账本：每天只沉淀一条模拟涨跌幅/净值记录，
  # 前端净值曲线统一从 data/account_nav_history.jsonl / cache/account_nav_history.jsonl 读取。
  if [[ ! -f "scripts/build_account_nav_ledger.py" ]]; then
    info "跳过账户净值账本同步：未找到 scripts/build_account_nav_ledger.py"
    return 0
  fi
  info "同步账户净值账本: data/account_nav_history.jsonl"
  PYTHONPATH=. python3 scripts/build_account_nav_ledger.py >/dev/null || die "账户净值账本同步失败"
}

sync_account_strategy_metrics_file() {
  # 策略表现长期统计：每天沉淀一条推荐日汇总记录，页面优先从长期文件读取。
  if [[ ! -f "scripts/build_account_strategy_metrics.py" ]]; then
    info "跳过策略表现统计同步：未找到 scripts/build_account_strategy_metrics.py"
    return 0
  fi
  info "同步策略表现统计: data/account_strategy_metrics.json"
  PYTHONPATH=. python3 scripts/build_account_strategy_metrics.py >/dev/null || die "策略表现统计同步失败"
}

prune_cache_keep_latest_n() {
  # 只保留最近 N 个 market_data-YYYYMMDD.json（按文件名排序，等价于日期排序）
  local n="${1:-7}"
  shopt -s nullglob
  local files=( cache/market_data-*.json )
  shopt -u nullglob
  if ((${#files[@]} == 0)); then
    return 0
  fi
  # 按日期排序（文件名中 YYYYMMDD）
  IFS=$'\n' files=( $(printf "%s\n" "${files[@]}" | sort) )
  unset IFS
  if ((${#files[@]} > n)); then
    rm -f "${files[@]:0:${#files[@]}-n}"
  fi
}

prune_extra_cache_artifacts() {
  # 额外清理：
  # - intraday_snapshots / intraday_slices 只保留最近 2 份
  # - v3_quality-*.md 视为临时分析产物，全部删除
  shopt -s nullglob
  local snaps=( cache/intraday_snapshots-*.json )
  local slices=( cache/intraday_slices-*.json )
  local v3m=( cache/v3_quality-*.md )
  shopt -u nullglob

  if ((${#snaps[@]} > 2)); then
    IFS=$'\n' snaps=( $(printf "%s\n" "${snaps[@]}" | sort) )
    unset IFS
    rm -f "${snaps[@]:0:${#snaps[@]}-2}"
  fi

  if ((${#slices[@]} > 2)); then
    IFS=$'\n' slices=( $(printf "%s\n" "${slices[@]}" | sort) )
    unset IFS
    rm -f "${slices[@]:0:${#slices[@]}-2}"
  fi

  if ((${#v3m[@]} > 0)); then
    rm -f "${v3m[@]}"
  fi
}

sync_online_cache_dir() {
  # 将本地 cache 中远端构建需要的最小文件同步到 cache_online/，
  # 并按 7 天窗口清理本地/线上日期型缓存。
  # 默认不压缩；因为你的主流程是“本地构建 -> git 提交 -> 远端自动构建”
  local date10="$1"
  if [[ -f "manage_cache.py" ]]; then
    info "同步 cache_online/ 并清理 7 天外缓存: ${date10}"
    python3 manage_cache.py --date "${date10}" --mode minimal --retention-days 7 --apply >/dev/null
  else
    info "跳过 cache_online 同步：未找到 manage_cache.py"
  fi
}

build_web_dist() {
  # 仅 Vite 构建 + inject_data 写旁路数据。
  # 调用约束：调用方必须先保证 cache/market_data-${yyyymmdd}.json 已是目标日期最新的 pipeline 产物。
  # 这个函数本身不重算 pipeline，是 render_offline 拆出来的"末端打包"段。
  local yyyymmdd="$1"
  (cd web && npm run build) || die "Vue3 构建失败"
  python3 inject_data.py "${yyyymmdd}" || die "web 数据生成失败"
  echo "✅ Web 构建完成: web/dist/index.html"
}

render_offline() {
  # 离线 rebuild + Web 构建 + 数据文件刷新。
  # 适用：./qr.sh render（没走 fetch，需要先离线重算 pipeline）。
  # 注意：./qr.sh fetch 不要再调本函数——daily_review.cli --fetch 内部已经 rebuild 过，
  #   重复 rebuild 会让 _inject_prd_v2_metrics 又跑一次（~1 分钟）。fetch 路径请直接调 build_web_dist。
  local date10="$1"
  local yyyymmdd market_json
  yyyymmdd="$(date10_to_date8 "${date10}")"
  market_json="cache/market_data-${yyyymmdd}.json"

  [[ -f "${market_json}" ]] || die "未找到 ${market_json}，请先执行：./qr.sh fetch ${date10}"

  # 离线重建 pipeline（不请求接口）
  PYTHONPATH=. python3 -u -m daily_review.cli --date "${date10}" --rebuild

  build_web_dist "${yyyymmdd}"
}

cmd_fetch() {
  load_dotenv_if_needed
  ensure_token

  info "在线取数生成缓存（会请求接口，有成本） -> 离线 pipeline 重建 -> web 数据缓存"
  if [[ -n "${DATE_ARG}" ]]; then
    # daily_review.cli --fetch 内部已经 rebuild 过，下面只补 web 构建即可（不再重复 rebuild）
    run_daily_review_cli --fetch --date "${DATE_ARG}"
    prune_cache_keep_latest_n 7
    prune_extra_cache_artifacts
    sync_online_cache_dir "${DATE_ARG}"
    refresh_watchlist_cache "${DATE_ARG}"
    sync_account_nav_ledger_file
    sync_account_strategy_metrics_file
    build_web_dist "$(date10_to_date8 "${DATE_ARG}")"
    return 0
  fi

  # 不指定日期：由 cli 负责自动回退到最近交易日
  run_daily_review_cli --fetch

  # 用缓存里最新的 market_data-*.json 再做 web 构建（不再取数，也不重复 rebuild）
  local d8 d10
  d8="$(pick_latest_cache_date8)" || die "未找到 cache/market_data-*.json（尚未生成缓存？）"
  d10="$(date8_to_date10 "${d8}")"
  # 先 sync 到 cache_online（会清空目录），再生成 watchlist 推票，最后构建 web
  sync_online_cache_dir "${d10}"
  refresh_watchlist_cache "${d10}"
  sync_account_nav_ledger_file
  sync_account_strategy_metrics_file
  build_web_dist "${d8}"
  prune_cache_keep_latest_n 7
  prune_extra_cache_artifacts
  python3 inject_data.py "${d8}" --dev-only 2>/dev/null || true
}

cmd_gen() {
  # 仅在线取数：走 daily_review.cli --fetch
  load_dotenv_if_needed
  ensure_token

  info "仅在线取数并生成缓存（不做离线 pipeline 重建/渲染）"
  if [[ -n "${DATE_ARG}" ]]; then
    run_daily_review_cli --fetch --date "${DATE_ARG}"
    sync_online_cache_dir "${DATE_ARG}"
    refresh_watchlist_cache "${DATE_ARG}"
    sync_account_nav_ledger_file
    sync_account_strategy_metrics_file
  else
    run_daily_review_cli --fetch
    local d8 d10
    d8="$(pick_latest_cache_date8)" || die "未找到 cache/market_data-*.json（尚未生成缓存？）"
    d10="$(date8_to_date10 "${d8}")"
    sync_online_cache_dir "${d10}"
    refresh_watchlist_cache "${d10}"
    sync_account_nav_ledger_file
    sync_account_strategy_metrics_file
  fi
}

cmd_render() {
  load_dotenv_if_needed
  if [[ -n "${DATE_ARG}" ]]; then
    # 先 sync + 用本地缓存重算 watchlist，再刷新 web 数据
    sync_online_cache_dir "${DATE_ARG}"
    refresh_watchlist_cache "${DATE_ARG}" "--skip-fetch"
    run_daily_review_cli --date "${DATE_ARG}" --rebuild
    sync_account_nav_ledger_file
    sync_account_strategy_metrics_file
    build_web_dist "$(date10_to_date8 "${DATE_ARG}")"
    prune_cache_keep_latest_n 7
    prune_extra_cache_artifacts
    return 0
  fi

  local d8 d10
  d8="$(pick_latest_cache_date8)" || die "未找到 cache/market_data-*.json，请先执行：./qr.sh fetch"
  d10="$(date8_to_date10 "${d8}")"
  sync_online_cache_dir "${d10}"
  refresh_watchlist_cache "${d10}" "--skip-fetch"
  run_daily_review_cli --date "${d10}" --rebuild
  sync_account_nav_ledger_file
  sync_account_strategy_metrics_file
  build_web_dist "${d8}"
  prune_cache_keep_latest_n 7
  prune_extra_cache_artifacts
  python3 inject_data.py "${d8}" --dev-only 2>/dev/null || true
}

cmd_build_web() {
  load_dotenv_if_needed
  local d8 d10
  if [[ -n "${DATE_ARG}" ]]; then
    d8="$(date10_to_date8 "${DATE_ARG}")"
    d10="${DATE_ARG}"
  else
    d8="$(pick_latest_cache_date8)" || die "未找到 cache/market_data-*.json，请先执行：./qr.sh fetch"
    d10="$(date8_to_date10 "${d8}")"
  fi
  # 确保数据存在
  if [[ ! -f "cache/market_data-${d8}.json" ]]; then
    die "数据缓存不存在: cache/market_data-${d8}.json，请先执行：./qr.sh fetch ${d10}"
  fi
  # build-web 也要先重算算法缓存，确保 web 入口消费最新 tide/coreTide/watchlist。
  sync_online_cache_dir "${d10}"
  refresh_watchlist_cache "${d10}" "--skip-fetch"
  sync_account_nav_ledger_file
  sync_account_strategy_metrics_file
  info "Web 构建 + 算法数据刷新 -> web/dist/index.html"
  (cd web && npm run build) || die "Vue3 构建失败"
  python3 inject_data.py "${d8}" || die "web 数据生成失败"
  info "构建完成: web/dist/index.html"
}

cmd_sync_cache() {
  load_dotenv_if_needed
  local d8 d10
  if [[ -n "${DATE_ARG}" ]]; then
    d10="${DATE_ARG}"
  else
    d8="$(pick_latest_cache_date8)" || die "未找到 cache/market_data-*.json，请先执行：./qr.sh fetch 或 ./qr.sh render"
    d10="$(date8_to_date10 "${d8}")"
  fi
  sync_online_cache_dir "${d10}"
  info "已同步远端依赖目录: cache_online/"
}

cmd_watch_slice() {
  load_dotenv_if_needed
  ensure_token
  local date_arg="${DATE_ARG:-}"
  info "生成实时盯盘切片 JSON（独立请求层，不重建整份报告）"
  if [[ -n "${date_arg}" ]]; then
    PYTHONPATH=. python3 -u -m daily_review.watch_runtime --date "$(date10_to_date8 "${date_arg}")"
  else
    PYTHONPATH=. python3 -u -m daily_review.watch_runtime
  fi
  prune_extra_cache_artifacts
}

cmd_deploy_intraday() {
  local pages_branch
  pages_branch="${PAGES_BRANCH:-gh-pages}"

  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "请在 Git 仓库内执行。"

  local repo_root current_branch
  repo_root="$(git rev-parse --show-toplevel)"
  current_branch="$(git branch --show-current)"
  [[ -n "${current_branch}" ]] || die "当前不在任何分支（detached HEAD）。"
  cd "${repo_root}"

  [[ -f "./web/public/intraday_runtime.json" ]] || die "未找到盘中运行时文件：./web/public/intraday_runtime.json"

  local tmp_runtime
  local tmp_resonance
  local tmp_slice_dir
  tmp_runtime="$(mktemp -t intraday_runtime.XXXXXX.json)"
  cp -f "./web/public/intraday_runtime.json" "${tmp_runtime}"
  tmp_slice_dir="$(mktemp -d -t intraday_slices.XXXXXX)"
  cp -f ./cache/intraday_slices-*.json "${tmp_slice_dir}/" 2>/dev/null || true
  tmp_resonance=""
  if [[ -f "./web/public/intraday_resonance.json" ]]; then
    tmp_resonance="$(mktemp -t intraday_resonance.XXXXXX.json)"
    cp -f "./web/public/intraday_resonance.json" "${tmp_resonance}"
  fi

  info "切到 ${pages_branch} 并同步盘中轻量运行时"
  git switch "${pages_branch}"
  cd "${repo_root}"
  install -m 644 "${tmp_runtime}" "intraday_runtime.json"
  rm -f "${tmp_runtime}"
  if [[ -n "${tmp_resonance}" && -f "${tmp_resonance}" ]]; then
    install -m 644 "${tmp_resonance}" "intraday_resonance.json"
    rm -f "${tmp_resonance}"
  fi
  mkdir -p cache
  cp -f "${tmp_slice_dir}"/intraday_slices-*.json ./cache/ 2>/dev/null || true
  rm -rf "${tmp_slice_dir}"

  git add intraday_runtime.json intraday_resonance.json cache/intraday_slices-*.json 2>/dev/null || true
  git commit -m "deploy: intraday runtime $(date '+%F %T')" || true
  git push

  info "切回 ${current_branch}"
  git switch "${current_branch}"
  cd "${repo_root}"

  echo "✅ 盘中轻量发布完成：已同步 intraday_runtime.json 到 ${pages_branch}"
}

cmd_deploy() {
  # 可选：本地发布到 gh-pages（仍沿用之前 deploy_pages.sh 的思路）
  # 说明：如果你主要用 GitHub Actions 发布，可以不需要该命令。
  local pages_branch pages_file allow_dirty
  pages_branch="${PAGES_BRANCH:-gh-pages}"
  pages_file="${PAGES_FILE:-index.html}"
  allow_dirty="${ALLOW_DIRTY:-0}"

  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "请在 Git 仓库内执行。"

  local repo_root current_branch
  repo_root="$(git rev-parse --show-toplevel)"
  current_branch="$(git branch --show-current)"
  [[ -n "${current_branch}" ]] || die "当前不在任何分支（detached HEAD）。"
  cd "${repo_root}"

  if [[ "${allow_dirty}" != "1" ]]; then
    if ! git diff --quiet || ! git diff --cached --quiet; then
      git status --porcelain >&2
      die "当前工作区有未提交修改，请先提交/暂存/清理后再发版（或设置 ALLOW_DIRTY=1）。"
    fi
  fi

  local report_html
  report_html="./web/dist/index.html"
  [[ -f "${report_html}" ]] || die "未找到可发布的 web 构建入口：./web/dist/index.html"
  [[ -f "./web/dist/market_data.json" ]] || die "未找到运行时数据文件：./web/dist/market_data.json"
  [[ -f "./web/dist/market_data.js" ]] || die "未找到运行时数据文件：./web/dist/market_data.js"

  local tmp
  tmp="$(mktemp -t deploy_pages.XXXXXX.html)"
  cp -f "${report_html}" "${tmp}"

  info "切到 ${pages_branch} 并覆盖 ${pages_file}"
  git switch "${pages_branch}"
  cd "${repo_root}"
  mkdir -p "$(dirname "${pages_file}")" 2>/dev/null || true
  install -m 644 "${tmp}" "${pages_file}"
  rm -f "${tmp}"
  install -m 644 "./web/dist/market_data.json" "market_data.json"
  install -m 644 "./web/dist/market_data.js" "market_data.js"
  mkdir -p cache
  if [[ -f "./data/account_nav_history.jsonl" ]]; then
    install -m 644 "./data/account_nav_history.jsonl" "cache/account_nav_history.jsonl"
  elif [[ -f "./cache/account_nav_history.jsonl" ]]; then
    install -m 644 "./cache/account_nav_history.jsonl" "cache/account_nav_history.jsonl"
  fi
  if [[ -f "./data/account_strategy_metrics.json" ]]; then
    install -m 644 "./data/account_strategy_metrics.json" "cache/account_strategy_metrics.json"
  elif [[ -f "./cache/account_strategy_metrics.json" ]]; then
    install -m 644 "./cache/account_strategy_metrics.json" "cache/account_strategy_metrics.json"
  fi
  for f in tomorrow_picks.json tomorrow_picks.js eastmoney_tomorrow.json intraday_resonance.json intraday_runtime.json; do
    if [[ -f "./web/dist/${f}" ]]; then
      install -m 644 "./web/dist/${f}" "${f}"
    elif [[ -f "./web/public/${f}" ]]; then
      install -m 644 "./web/public/${f}" "${f}"
    fi
  done

  git add "${pages_file}" market_data.json market_data.js \
    tomorrow_picks.json tomorrow_picks.js eastmoney_tomorrow.json intraday_resonance.json intraday_runtime.json \
    cache/account_nav_history.jsonl cache/account_strategy_metrics.json 2>/dev/null || true
  git commit -m "deploy: $(date '+%F %T')" || true
  git push

  info "切回 ${current_branch}"
  git switch "${current_branch}"
  cd "${repo_root}"

  echo "✅ 发版完成：已覆盖 ${pages_branch}/${pages_file}"
}

usage() {
  cat <<'EOF'
用法：
  ./qr.sh fetch [YYYY-MM-DD]   在线取数 + 算法推票 + pipeline 重建 + web 数据缓存
  ./qr.sh render [YYYY-MM-DD]  仅用 cache 离线重建 + 推票重算(--skip-fetch) + Vue3 构建（不请求接口）
  ./qr.sh build-web [YYYY-MM-DD]  仅 Vue3 构建 + web 数据刷新（不跑 pipeline，改 UI 用）
  ./qr.sh watch-slice [YYYY-MM-DD]  仅生成实时盯盘切片 JSON（供页面动态读取）
  ./qr.sh deploy-intraday        （可选）仅发布盘中轻量运行时到 gh-pages
  ./qr.sh deploy               （可选）发布 web/dist/index.html 到 gh-pages/index.html
EOF
}

main() {
  normalize_optional_args "$@"
  local cmd="${1:-}"
  case "${cmd}" in
    "")     cmd_fetch ;;
    fetch)  cmd_fetch ;;
    gen)    cmd_gen ;;
    render) cmd_render ;;
    build-web) cmd_build_web ;;
    sync-cache) cmd_sync_cache ;;
    watch-slice) cmd_watch_slice ;;
    deploy-intraday) cmd_deploy_intraday ;;
    deploy) cmd_deploy ;;
    -h|--help|help) usage ;;
    *) die "未知命令：${cmd}（用 ./qr.sh help 查看用法）" ;;
  esac
}

main "$@"
