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
#   ./qr.sh fetch [YYYY-MM-DD]   # 在线取数 + 写入 cache + 离线渲染 html/复盘日记-YYYYMMDD-tab-v1.html
#   ./qr.sh gen  [YYYY-MM-DD]    # 仅在线取数生成缓存/带时分秒 HTML（不做离线渲染 tab-v1）
#   ./qr.sh render [YYYY-MM-DD]  # 只用 cache 离线渲染（不请求接口）
#   ./qr.sh sync-cache [YYYY-MM-DD] # 同步 cache_online/（远端自动构建依赖目录）
#   ./qr.sh deploy              # （可选）把最新 tab-v1 报告发布到 gh-pages/index.html
#
set -euo pipefail

DATE_ARG="${2:-}"

die() {
  echo "❌ $*" >&2
  exit 1
}

info() {
  echo "==> $*" >&2
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

cleanup_timestamp_html() {
  # 只保留 tab-v1，删除 gen_report_v4 生成的带时分秒版本（复盘日记-YYYYMMDD-HHMMSS.html）
  local yyyymmdd="$1"
  shopt -s nullglob
  local files=( "html/复盘日记-${yyyymmdd}-"[0-9][0-9][0-9][0-9][0-9][0-9].html )
  if ((${#files[@]})); then
    rm -f "${files[@]}"
  fi
  shopt -u nullglob
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
  # 将本地 cache 中远端构建需要的最小文件同步到 cache_online/
  # 默认不压缩；因为你的主流程是“本地构建 -> git 提交 -> 远端自动构建”
  local date10="$1"
  if [[ -f "manage_cache.py" ]]; then
    info "同步 cache_online/（供远端自动构建使用）: ${date10}"
    python3 manage_cache.py --date "${date10}" --mode minimal >/dev/null
  else
    info "跳过 cache_online 同步：未找到 manage_cache.py"
  fi
}

prune_html_keep_latest_report() {
  # 只保留最新一份「复盘日记-*.html」，其余历史报告全部删除
  local latest
  latest="$(ls -t html/复盘日记-*.html 2>/dev/null | head -n 1 || true)"
  [[ -n "${latest}" ]] || return 0
  shopt -s nullglob
  local files=( html/复盘日记-*.html )
  shopt -u nullglob
  for f in "${files[@]}"; do
    if [[ "${f}" != "${latest}" ]]; then
      rm -f "${f}"
    fi
  done
}

render_offline() {
  # 离线渲染：用 cache/market_data-YYYYMMDD.json + templates/report_template.html 生成 tab-v1 HTML
  local date10="$1"
  local yyyymmdd market_json template out_html
  yyyymmdd="$(date10_to_date8 "${date10}")"
  market_json="cache/market_data-${yyyymmdd}.json"
  template="templates/report_template.html"
  out_html="html/复盘日记-${yyyymmdd}-tab-v1.html"

  [[ -f "${market_json}" ]] || die "未找到 ${market_json}，请先执行：./qr.sh fetch ${date10}"

  # 收口阶段：离线渲染前先跑一遍 v2 pipeline 重建 market_data（不请求接口）
  # 这样你改算法/模块后，render 会直接反映最新结果。
  PYTHONPATH=. python3 -m daily_review.cli --date "${date10}" --rebuild

  echo "✅ 离线渲染完成: ${out_html}"
  # 本地策略：报告只保留最新一份
  prune_html_keep_latest_report
}

cmd_fetch() {
  load_dotenv_if_needed
  ensure_token

  info "在线取数生成缓存（会请求接口，有成本） -> 离线 pipeline 重建 -> 输出 tab-v1"
  if [[ -n "${DATE_ARG}" ]]; then
    # 新 FULL：走 daily_review.cli --fetch（data/cache 层），最终产物仍由 pipeline 生成
    PYTHONPATH=. python3 -m daily_review.cli --fetch --date "${DATE_ARG}"
    cleanup_timestamp_html "$(date10_to_date8 "${DATE_ARG}")"
    prune_cache_keep_latest_n 7
    prune_extra_cache_artifacts
    sync_online_cache_dir "${DATE_ARG}"
    return 0
  fi

  # 不指定日期：由 cli 负责自动回退到最近交易日
  PYTHONPATH=. python3 -m daily_review.cli --fetch

  # 用缓存里最新的 market_data-*.json 再离线渲染一份 v1（不再取数）
  local d8 d10
  d8="$(pick_latest_cache_date8)" || die "未找到 cache/market_data-*.json（gen_report_v4.py 未生成缓存？）"
  d10="$(date8_to_date10 "${d8}")"
  render_offline "${d10}"
  cleanup_timestamp_html "${d8}"
  prune_cache_keep_latest_n 7
  prune_extra_cache_artifacts
  sync_online_cache_dir "${d10}"
}

cmd_gen() {
  # 仅运行 gen_report_v4.py：
  # - 会请求接口
  # - 会生成 cache/market_data-YYYYMMDD.json
  # - 以及 html/复盘日记-YYYYMMDD-HHMMSS.html（留档）
  # 用途：你在本地调试“取数/落缓存”时，想跳过离线重建（pipeline）与渲染流程。
  load_dotenv_if_needed
  ensure_token

  info "仅在线取数并生成缓存（不做离线 pipeline 重建/渲染）"
  if [[ -n "${DATE_ARG}" ]]; then
    # 兼容：暂时仍保留 gen_report_v4，但推荐用 daily_review.cli --fetch
    python3 gen_report_v4.py "${DATE_ARG}"
    sync_online_cache_dir "${DATE_ARG}"
  else
    python3 gen_report_v4.py
    local d8 d10
    d8="$(pick_latest_cache_date8)" || die "未找到 cache/market_data-*.json（gen_report_v4.py 未生成缓存？）"
    d10="$(date8_to_date10 "${d8}")"
    sync_online_cache_dir "${d10}"
  fi
}

cmd_render() {
  load_dotenv_if_needed
  if [[ -n "${DATE_ARG}" ]]; then
    render_offline "${DATE_ARG}"
    prune_cache_keep_latest_n 7
    prune_extra_cache_artifacts
    sync_online_cache_dir "${DATE_ARG}"
    return 0
  fi

  local d8 d10
  d8="$(pick_latest_cache_date8)" || die "未找到 cache/market_data-*.json，请先执行：./qr.sh fetch"
  d10="$(date8_to_date10 "${d8}")"
  render_offline "${d10}"
  prune_cache_keep_latest_n 7
  prune_extra_cache_artifacts
  sync_online_cache_dir "${d10}"
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
    PYTHONPATH=. python3 -m daily_review.watch_runtime --date "$(date10_to_date8 "${date_arg}")" --publish
  else
    PYTHONPATH=. python3 -m daily_review.watch_runtime --publish
  fi
  prune_extra_cache_artifacts
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
  report_html="$(ls -t ./html/*tab-v1.html 2>/dev/null | head -n 1 || true)"
  [[ -n "${report_html}" ]] || die "未找到可发布的报告文件：./html/*tab-v1.html"

  local tmp
  tmp="$(mktemp -t deploy_pages.XXXXXX.html)"
  cp -f "${report_html}" "${tmp}"

  info "切到 ${pages_branch} 并覆盖 ${pages_file}"
  git switch "${pages_branch}"
  cd "${repo_root}"
  mkdir -p "$(dirname "${pages_file}")" 2>/dev/null || true
  install -m 644 "${tmp}" "${pages_file}"
  rm -f "${tmp}"

  git add "${pages_file}"
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
  ./qr.sh fetch [YYYY-MM-DD]   在线取数 + 生成缓存 + 离线渲染 tab-v1 HTML
  ./qr.sh gen  [YYYY-MM-DD]    仅在线取数生成缓存/留档 HTML（不做离线渲染）
  ./qr.sh render [YYYY-MM-DD]  仅用 cache 离线渲染（不请求接口）
  ./qr.sh watch-slice [YYYY-MM-DD]  仅生成实时盯盘切片 JSON（供页面动态读取）
  ./qr.sh deploy               （可选）发布最新 tab-v1 到 gh-pages/index.html
EOF
}

main() {
  local cmd="${1:-}"
  case "${cmd}" in
    fetch)  cmd_fetch ;;
    gen)    cmd_gen ;;
    render) cmd_render ;;
    sync-cache) cmd_sync_cache ;;
    watch-slice) cmd_watch_slice ;;
    deploy) cmd_deploy ;;
    -h|--help|help|"") usage ;;
    *) die "未知命令：${cmd}（用 ./qr.sh help 查看用法）" ;;
  esac
}

main "$@"
