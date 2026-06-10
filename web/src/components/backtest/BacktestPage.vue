<script setup lang="ts">
import { computed, ref } from "vue"
import { useMarketData } from "../../composables/useMarketData"
import ShortReminderFooter from "../common/ShortReminderFooter.vue"
const { marketData } = useMarketData()
const backtestSource = computed<any>(() => {
  const md = marketData.value as any
  return md || {}
})

const emptyPayload = {
  schema: "stock_research_backtest_v2",
  meta: {
    title: "个股回测",
    subtitle: "",
    entry_window: "09:25-09:30",
    source_module: "ztAnalysis.relay/watch",
    generated_at_bj: "",
    generated_from: [],
    latest_recommendation_date: "",
    active_trade_date: "",
  },
  summary: {
    total_samples: 0,
    source_samples: 0,
    filtered_non_backtest_samples: 0,
    eligible_samples: 0,
    expected_count: 0,
    super_count: 0,
    wait_reseal_count: 0,
    rejected_count: 0,
    unique_codes: 0,
    trade_days: 0,
    priced_codes: 0,
    missing_price_codes: [],
    realtime_candidate_count: 0,
    realtime_buy_count: 0,
    realtime_pending_count: 0,
    realtime_unavailable_count: 0,
  },
  assumptions: [],
  breakdowns: {
    by_mainline: [],
    by_open_status: [],
  },
  metrics: {},
  lifecycle: {
    stage: "empty",
    stage_label: "暂无数据",
    stage_note: "",
    quote_state: "pending_source",
    quote_state_label: "等待推送",
    quote_state_note: "",
    has_current_plan: false,
    has_historical_records: false,
    has_realtime_snapshot: false,
    latest_recommendation_date: "",
    active_trade_date: "",
    latest_historical_recommendation_date: "",
    realtime_reference_date: "",
    quote_time: "",
  },
  currentPoolRecords: [],
  displayRecords: [],
  historicalSnapshots: [],
  records: [],
  diagnostics: {},
  realtimeBuy: {
    reference_date: "",
    trade_date: "",
    entry_window: "09:25-09:30",
    quote_time: "",
    candidate_count: 0,
    quoted_count: 0,
    buy_count: 0,
    direct_super_count: 0,
    direct_expected_count: 0,
    pending_count: 0,
    rejected_count: 0,
    unavailable_count: 0,
    buy_list: [],
    pending_list: [],
    rejected_list: [],
    unavailable_list: [],
    diagnostics: {},
  },
}

function isEntryWindowTime(text: unknown) {
  const raw = String(text || "").trim()
  if (!raw) return false
  const hhmmss = raw.includes(" ") ? raw.split(" ").pop() || "" : raw
  const parts = hhmmss.slice(0, 8).split(":")
  if (parts.length < 3) return false
  const [hour, minute, second] = parts.map((part) => Number(part))
  if (![hour, minute, second].every((n) => Number.isInteger(n))) return false
  const total = hour * 3600 + minute * 60 + second
  return total >= 9 * 3600 + 25 * 60 && total < 9 * 3600 + 30 * 60
}

function isCompleteBacktestPayload(raw: any) {
  if (!raw || typeof raw !== "object") return false
  if (String(raw.schema || "") !== "stock_research_backtest_v2") return false
  if (!raw.meta || typeof raw.meta !== "object") return false
  if (!raw.summary || typeof raw.summary !== "object") return false
  if (!raw.lifecycle || typeof raw.lifecycle !== "object") return false
  if (!raw.realtimeBuy || typeof raw.realtimeBuy !== "object") return false
  if (!Array.isArray(raw.currentPoolRecords)) return false
  if (!Array.isArray(raw.displayRecords)) return false
  if (!Array.isArray(raw.records)) return false
  return true
}

const payload = computed<any>(() => {
  const raw = backtestSource.value?.stockResearchBacktest
  return isCompleteBacktestPayload(raw) ? raw : emptyPayload
})

const meta = computed(() => payload.value?.meta || emptyPayload.meta)
const summary = computed(() => payload.value?.summary || emptyPayload.summary)
const lifecycle = computed<any>(() => (payload.value?.lifecycle && typeof payload.value.lifecycle === "object" ? payload.value.lifecycle : emptyPayload.lifecycle))
const assumptions = computed<string[]>(() => (Array.isArray(payload.value?.assumptions) ? payload.value.assumptions : []))
const mainlineBreakdown = computed<any[]>(() => (Array.isArray(payload.value?.breakdowns?.by_mainline) ? payload.value.breakdowns.by_mainline.slice(0, 8) : []))
const statusBreakdown = computed<any[]>(() => (Array.isArray(payload.value?.breakdowns?.by_open_status) ? payload.value.breakdowns.by_open_status : []))
const missingPriceCodes = computed<string[]>(() => (Array.isArray(summary.value?.missing_price_codes) ? summary.value.missing_price_codes : []))

const realtimeBuy = computed<any>(() => {
  const raw = payload.value?.realtimeBuy
  return raw && typeof raw === "object" ? raw : emptyPayload.realtimeBuy
})
const historicalSnapshots = computed<any[]>(() => (Array.isArray(payload.value?.historicalSnapshots) ? payload.value.historicalSnapshots : []))
const hasValidPayload = computed(() => isCompleteBacktestPayload(backtestSource.value?.stockResearchBacktest))
const activeTradeDate = computed(() => String(meta.value?.active_trade_date || realtimeBuy.value?.trade_date || "").trim())
const realtimeTitleDate = computed(() => String(activeTradeDate.value || realtimeBuy.value?.reference_date || latestRecommendationDate.value || "").trim())
const realtimeCardTitle = computed(() => (realtimeTitleDate.value ? `竞价结果 — ${realtimeTitleDate.value} 9:25` : "竞价结果"))
const backtestUpdatedAt = computed(() => meta.value?.generated_at_bj || backtestSource.value?.meta?.generatedAt || (marketData.value as any)?.meta?.generatedAt || "-")
const quoteUpdatedAt = computed(() => realtimeBuy.value?.quote_time || "-")
function sortSnapshotRows(rows: any[]) {
  const rank: Record<string, number> = { super: 0, expected: 1, pending: 2, reject: 3, unavailable: 4 }
  rows.sort((a, b) => {
    const ra = rank[String(a?.signal_status || "")] ?? 9
    const rb = rank[String(b?.signal_status || "")] ?? 9
    if (ra !== rb) return ra - rb
    return (b?.score ?? 0) - (a?.score ?? 0)
  })
  return rows
}
const realtimeCandidates = computed<any[]>(() => {
  const buy = Array.isArray(realtimeBuy.value?.buy_list) ? realtimeBuy.value.buy_list : []
  const rejected = Array.isArray(realtimeBuy.value?.rejected_list) ? realtimeBuy.value.rejected_list : []
  const pending = Array.isArray(realtimeBuy.value?.pending_list) ? realtimeBuy.value.pending_list : []
  const unavailable = Array.isArray(realtimeBuy.value?.unavailable_list) ? realtimeBuy.value.unavailable_list : []
  return sortSnapshotRows([...buy, ...pending, ...rejected, ...unavailable])
})

function metricScope(item: any, scope: "all" | "tradable") {
  const scopes = item?.data?.scopes
  if (scopes && typeof scopes === "object" && scopes[scope] && typeof scopes[scope] === "object") return scopes[scope]
  return item?.data || {}
}

const currentPoolRecords = computed<any[]>(() => {
  const rows = Array.isArray(payload.value?.currentPoolRecords) ? [...payload.value.currentPoolRecords] : []
  rows.sort((a, b) => {
    const scoreDiff = toNum(b?.score, 0) - toNum(a?.score, 0)
    if (scoreDiff) return scoreDiff
    return String(a?.code || "").localeCompare(String(b?.code || ""))
  })
  return rows
})

function historicalStatusRank(status?: string) {
  const key = String(status || "")
  if (key === "super") return 0
  if (key === "expected") return 1
  if (key === "pending" || key === "wait_reseal") return 2
  if (key === "reject") return 3
  return 9
}

const records = computed<any[]>(() => {
  const rows = Array.isArray(payload.value?.records) ? [...payload.value.records] : []
  rows.sort((a, b) => {
    const dateDiff = String(b?.date10 || "").localeCompare(String(a?.date10 || ""))
    if (dateDiff) return dateDiff
    const statusDiff =
      historicalStatusRank(a?.performance?.open_check?.status) - historicalStatusRank(b?.performance?.open_check?.status)
    if (statusDiff) return statusDiff
    const scoreDiff = toNum(b?.score, 0) - toNum(a?.score, 0)
    if (scoreDiff) return scoreDiff
    return String(a?.code || "").localeCompare(String(b?.code || ""))
  })
  return rows
})
const displayRecords = computed<any[]>(() => {
  const rows = Array.isArray(payload.value?.displayRecords) ? [...payload.value.displayRecords] : []
  rows.sort((a, b) => {
    const dateDiff = String(b?.date10 || "").localeCompare(String(a?.date10 || ""))
    if (dateDiff) return dateDiff
    const statusDiff =
      historicalStatusRank(a?.performance?.open_check?.status) - historicalStatusRank(b?.performance?.open_check?.status)
    if (statusDiff) return statusDiff
    const scoreDiff = toNum(b?.score, 0) - toNum(a?.score, 0)
    if (scoreDiff) return scoreDiff
    return String(a?.code || "").localeCompare(String(b?.code || ""))
  })
  return rows
})
const latestRecommendationDate = computed(() => String(meta.value?.latest_recommendation_date || realtimeBuy.value?.reference_date || "").trim())
const selectedRecommendationDateInput = ref("")
const availableRecommendationDates = computed<string[]>(() => {
  const dates = new Set<string>()
  for (const row of currentPoolRecords.value) {
    const date10 = String(row?.date10 || "").trim()
    if (date10) dates.add(date10)
  }
  for (const row of displayRecords.value) {
    const date10 = String(row?.date10 || "").trim()
    if (date10) dates.add(date10)
  }
  return Array.from(dates).sort((a, b) => b.localeCompare(a))
})
const selectedRecommendationDate = computed(() => {
  const raw = String(selectedRecommendationDateInput.value || "").trim()
  if (raw && availableRecommendationDates.value.includes(raw)) return raw
  if (latestRecommendationDate.value && availableRecommendationDates.value.includes(latestRecommendationDate.value)) return latestRecommendationDate.value
  return availableRecommendationDates.value[0] || latestRecommendationDate.value || ""
})
const latestHistoricalRecommendationDate = computed(() => String(lifecycle.value?.latest_historical_recommendation_date || "").trim())
const effectiveHistoricalDate = computed(() => {
  if (isViewingCurrentRecommendation.value && latestHistoricalRecommendationDate.value) return latestHistoricalRecommendationDate.value
  return selectedRecommendationDate.value
})
const selectedDayRecordsAll = computed<any[]>(() =>
  records.value.filter((row) => String(row?.date10 || "") === effectiveHistoricalDate.value)
)
const selectedDayDisplayRecords = computed<any[]>(() =>
  displayRecords.value.filter((row) => String(row?.date10 || "") === effectiveHistoricalDate.value)
)
const currentRecords = computed<any[]>(() => {
  const currentRows = currentPoolRecords.value.filter((row) => String(row?.date10 || "") === selectedRecommendationDate.value)
  const rows = currentRows.length ? [...currentRows] : [...selectedDayDisplayRecords.value]
  rows.sort((a, b) => {
    const scoreDiff = toNum(b?.score, 0) - toNum(a?.score, 0)
    if (scoreDiff) return scoreDiff
    return String(a?.code || "").localeCompare(String(b?.code || ""))
  })
  return rows
})
const historicalRecords = computed<any[]>(() => selectedDayDisplayRecords.value)
const currentEligibleCount = computed(() => currentRecords.value.filter((row) => !!row?.performance?.open_check?.can_enter).length)
const metrics = computed(() => buildDateScopedMetrics(selectedDayRecordsAll.value))
const hasCurrentPlan = computed(() => hasValidPayload.value && currentRecords.value.length > 0)
const hasHistoricalRecords = computed(() => historicalRecords.value.length > 0)
const isViewingCurrentRecommendation = computed(() => !selectedRecommendationDate.value || selectedRecommendationDate.value === latestRecommendationDate.value)
const historicalSnapshotMap = computed<Record<string, any>>(() => {
  const out: Record<string, any> = {}
  for (const item of historicalSnapshots.value) {
    const key = String(item?.reference_date || "").trim()
    if (key) out[key] = item
  }
  return out
})
const selectedHistoricalSnapshot = computed<any | null>(() => {
  const key = effectiveHistoricalDate.value
  return key ? historicalSnapshotMap.value[key] || null : null
})
const historicalCandidates = computed<any[]>(() => {
  const source = selectedHistoricalSnapshot.value || {}
  const buy = Array.isArray(source?.buy_list) ? source.buy_list : []
  const rejected = Array.isArray(source?.rejected_list) ? source.rejected_list : []
  const pending = Array.isArray(source?.pending_list) ? source.pending_list : []
  const unavailable = Array.isArray(source?.unavailable_list) ? source.unavailable_list : []
  return sortSnapshotRows([...buy, ...pending, ...rejected, ...unavailable])
})
const hasRealtimeSnapshot = computed(() => {
  if (!hasValidPayload.value) return false
  if (selectedRecommendationDate.value && selectedRecommendationDate.value !== String(realtimeBuy.value?.reference_date || "").trim()) return false
  if (!realtimeBuy.value?.reference_date) return false
  if (!isEntryWindowTime(realtimeBuy.value?.quote_time)) return false
  return realtimeCandidates.value.length > 0
})
const showingRealtimeSnapshot = computed(() => hasRealtimeSnapshot.value)
const hasSelectedSnapshot = computed(() => hasRealtimeSnapshot.value || historicalCandidates.value.length > 0)
const allCandidates = computed<any[]>(() => (showingRealtimeSnapshot.value ? realtimeCandidates.value : historicalCandidates.value))
const hasAnyRenderableSection = computed(() => hasCurrentPlan.value || hasHistoricalRecords.value || hasSelectedSnapshot.value)
const lifecycleStage = computed(() => String(lifecycle.value?.stage || "empty"))
const lifecycleStageLabel = computed(() => String(lifecycle.value?.stage_label || "暂无数据"))
const lifecycleStageNote = computed(() => String(lifecycle.value?.stage_note || "").trim())
const lifecycleQuoteLabel = computed(() => String(lifecycle.value?.quote_state_label || "等待推送"))
const lifecycleQuoteNote = computed(() => String(lifecycle.value?.quote_state_note || "").trim())
const currentPlanTitleDate = computed(() => String(activeTradeDate.value || latestRecommendationDate.value || "").trim())
const snapshotTradeDate = computed(() => {
  if (showingRealtimeSnapshot.value) return realtimeTitleDate.value
  return String(selectedHistoricalSnapshot.value?.trade_date || effectiveHistoricalDate.value || "").trim()
})
const snapshotCardTitle = computed(() => {
  if (showingRealtimeSnapshot.value) return realtimeTitleDate.value ? `竞价结果 — ${realtimeTitleDate.value} 9:25` : "竞价结果"
  return snapshotTradeDate.value ? `竞价回放 — ${snapshotTradeDate.value}` : "竞价回放"
})
const currentPlanCardTitle = computed(() => {
  if (!selectedRecommendationDate.value) return currentPlanTitleDate.value ? `待验证池 — ${currentPlanTitleDate.value}` : "待验证池"
  if (isViewingCurrentRecommendation.value) return currentPlanTitleDate.value ? `待验证池 — ${currentPlanTitleDate.value}` : `待验证池 — ${selectedRecommendationDate.value}`
  return `推荐池回看 — ${selectedRecommendationDate.value}`
})
const currentPlanSubtitle = computed(() => {
  if (isViewingCurrentRecommendation.value) return "这里展示今天收盘后推送进回测 JSON 的待验证样本。9:25 没有真实快照前，只看预案，不展示历史收益。"
  return `这里按推荐日回看 ${selectedRecommendationDate.value} 的推荐和预期条件，方便对照下方表现。`
})
const realtimeSubtitle = computed(() => {
  if (!isViewingCurrentRecommendation.value) {
    if (selectedHistoricalSnapshot.value) {
      return `这里根据收盘后回测记录恢复 ${effectiveHistoricalDate.value} 推荐在 ${selectedHistoricalSnapshot.value?.trade_date || "-"} 开盘的命中结果与当日收益，原始 9:25 快照缺失也不会断层。`
    }
    return `当前只保留最新推荐日 ${String(realtimeBuy.value?.reference_date || "-")} 的 9:25 竞价快照；所选推荐日请看下方开盘判断和收益表现。`
  }
  if (hasRealtimeSnapshot.value && quoteUpdatedAt.value && quoteUpdatedAt.value !== "-") {
    return `竞价快照：${quoteUpdatedAt.value}｜高开超5%先观察，不直接追。`
  }
  if (selectedHistoricalSnapshot.value) {
    return `当前上方展示 ${selectedRecommendationDate.value} 的待验证池；下方默认回看最近已完成的 ${effectiveHistoricalDate.value} 竞价结果与收益。`
  }
  if (hasCurrentPlan.value && latestRecommendationDate.value) {
    return `盘后样本已更新到 ${latestRecommendationDate.value}，明日 09:25-09:30 再补真实竞价命中结果。`
  }
  return "高开超5%先观察，不直接追。"
})
const strategySubtitle = computed(() => {
  const dateLabel = effectiveHistoricalDate.value ? `结果口径 ${effectiveHistoricalDate.value}｜` : ""
  const updatedAt = String(backtestUpdatedAt.value || "").trim()
  return updatedAt && updatedAt !== "-"
    ? `${dateLabel}收益口径：高开超5%样本先观察，不计入直接开盘买入，再统计 T+1 / T+2 / T+3 收盘卖出。最新刷新：${updatedAt}`
    : `${dateLabel}收益口径：高开超5%样本先观察，不计入直接开盘买入，再统计 T+1 / T+2 / T+3 收盘卖出。`
})
const stageClass = computed(() => {
  const stage = lifecycleStage.value
  if (stage === "auction_snapshot_ready") return "is-super"
  if (stage === "post_close_wait_auction") return "is-expected"
  if (stage === "auction_snapshot_missing") return "is-reject"
  return "is-neutral"
})
const quoteClass = computed(() => {
  const state = String(lifecycle.value?.quote_state || "")
  if (state === "ready") return "is-super"
  if (state === "window_live" || state === "waiting_trade_day" || state === "waiting_window") return "is-expected"
  if (state === "missing") return "is-reject"
  return "is-neutral"
})
const summaryCards = computed(() => [
  {
    key: "recommendation",
    label: "当前查看",
    value: selectedRecommendationDate.value || latestRecommendationDate.value || "-",
    note: availableRecommendationDates.value.length > 1 ? `可切换 ${availableRecommendationDates.value.length} 个推荐日` : (activeTradeDate.value ? `待验证交易日 ${activeTradeDate.value}` : "当前暂无待验证交易日"),
  },
  {
    key: "history",
    label: "历史统计刷新",
    value: String(latestHistoricalRecommendationDate.value || latestRecommendationDate.value || "-"),
    note: hasHistoricalRecords.value ? `当前结果查看 ${effectiveHistoricalDate.value}｜展示 ${historicalRecords.value.length} 条｜纳入统计 ${selectedDayRecordsAll.value.length} 条` : "当前还没有历史回测样本",
  },
  {
    key: "pool",
    label: "待验证池",
    value: `${currentRecords.value.length}`,
    note: currentEligibleCount.value > 0 ? `可入场候选 ${currentEligibleCount.value} 条` : "当前以盘后样本展示为主",
  },
  {
    key: "snapshot",
    label: showingRealtimeSnapshot.value ? "9:25 快照" : "竞价回放",
    value: hasSelectedSnapshot.value ? `${allCandidates.value.length}` : "-",
    note: showingRealtimeSnapshot.value ? `快照时间 ${quoteUpdatedAt.value}` : (selectedHistoricalSnapshot.value?.diagnostics?.note || "历史回放未恢复"),
  },
])
const emptyStateText = computed(() => {
  if (!hasValidPayload.value) return "当前暂无有效回测数据，明天 09:25-09:30 落地后会自动显示对应内容。"
  if (hasCurrentPlan.value) return "收盘后推送的个股研究样本已经落进回测 JSON，当前先展示明天待验证池；到明天 09:25-09:30 再补真实竞价命中结果。"
  if (!realtimeBuy.value?.reference_date) return "当前推荐还没到次日 09:25-09:30，明天窗口内会落地实时行情。"
  if (!isEntryWindowTime(realtimeBuy.value?.quote_time)) return "当前暂无有效竞价快照，等明天 09:25-09:30 落地后再显示命中结果。"
  return "当前没有可展示的回测结果。"
})
const realtimeEmptyText = computed(() => {
  if (!hasValidPayload.value) return "当前暂无有效回测数据。"
  if (!isViewingCurrentRecommendation.value) return "所选推荐日没有原始 9:25 快照，但如果历史回测已落地，会在这里恢复命中结果。"
  if (!hasCurrentPlan.value) return "当前还没有待验证池数据，先执行一次复盘脚本生成个股回测 JSON。"
  if (!realtimeBuy.value?.reference_date) return "当前是收盘后待验证阶段，明天 09:25-09:30 会补充实时量价和命中结果。"
  if (!isEntryWindowTime(realtimeBuy.value?.quote_time)) return "当前还没到有效竞价快照时间，明天 09:25-09:30 会自动显示真实命中结果。"
  return "当前没有命中结果。"
})
const historicalSnapshotNotice = computed(() => {
  if (showingRealtimeSnapshot.value) return ""
  return String(selectedHistoricalSnapshot.value?.diagnostics?.note || "").trim()
})

function avgOf(values: number[]) {
  if (!values.length) return 0
  return Math.round((values.reduce((sum, item) => sum + item, 0) / values.length) * 100) / 100
}

function buildDateScopedMetrics(rows: any[]) {
  const tradableRows = rows.filter((row) => !!row?.performance?.open_check?.can_enter)
  const defs = [
    { key: "next_day", label: "隔日收益" },
    { key: "hold_2d", label: "2日收益" },
    { key: "hold_3d", label: "3日收益" },
  ]
  return defs.map((item) => {
    const coveredRows = tradableRows.filter((row) => String(row?.performance?.[item.key]?.status || "") === "covered")
    const returns = coveredRows.map((row) => toNum(row?.performance?.[item.key]?.return_pct, 0))
    const wins = returns.filter((val) => val > 0)
    const flats = returns.filter((val) => val === 0)
    const losses = returns.filter((val) => val < 0)
    const byStatus: Record<string, any> = {}
    for (const statusKey of ["super", "expected", "pending", "wait_reseal", "reject"]) {
      const statusRows = coveredRows.filter((row) => String(row?.performance?.open_check?.status || "") === statusKey)
      const statusReturns = statusRows.map((row) => toNum(row?.performance?.[item.key]?.return_pct, 0))
      const statusWins = statusReturns.filter((val) => val > 0).length
      byStatus[statusKey] = {
        avg_return: avgOf(statusReturns),
        win_rate: statusReturns.length ? Math.round((statusWins / statusReturns.length) * 1000) / 10 : 0,
      }
    }
    const eligible = tradableRows.length
    const covered = coveredRows.length
    return {
      key: item.key,
      label: item.label,
      data: {
        scopes: {
          tradable: {
            eligible,
            covered,
            coverage: eligible ? Math.round((covered / eligible) * 1000) / 10 : 0,
            win_count: wins.length,
            flat_count: flats.length,
            loss_count: losses.length,
            win_rate: covered ? Math.round((wins.length / covered) * 1000) / 10 : 0,
            avg_return: avgOf(returns),
            avg_win_return: avgOf(wins),
            avg_loss_return: avgOf(losses),
            by_open_status: byStatus,
          },
        },
      },
    }
  })
}

const entryRate = computed(() => {
  const total = toNum(summary.value?.total_samples, 0)
  const eligible = toNum(summary.value?.eligible_samples, 0)
  if (total <= 0) return 0
  return Math.round((eligible / total) * 1000) / 10
})

function toNum(v: unknown, d = 0) {
  try {
    if (v === undefined || v === null || v === "") return d
    if (typeof v === "string") return Number(String(v).replace("%", "").replace("亿", "").trim()) || d
    const n = Number(v)
    return Number.isFinite(n) ? n : d
  } catch {
    return d
  }
}

function signedClass(val: unknown) {
  if (val === undefined || val === null) return "orange-text"
  const n = Number(String(val).replace("%", "").trim())
  if (Number.isNaN(n)) return "orange-text"
  if (n > 0) return "red-text"
  if (n < 0) return "green-text"
  return "orange-text"
}

function formatSigned(val: unknown, digits = 1) {
  if (val === undefined || val === null || val === "") return "-"
  const n = Number(val)
  if (!Number.isFinite(n)) return "-"
  const sign = n > 0 ? "+" : ""
  return `${sign}${n.toFixed(digits).replace(/\.0$/, "")}`
}

function formatPlain(val: unknown, digits = 2) {
  if (val === undefined || val === null || val === "") return "-"
  const n = Number(val)
  if (!Number.isFinite(n)) return "-"
  return n.toFixed(digits).replace(/\.00$/, "").replace(/(\.\d)0$/, "$1")
}

function formatMonthDay(val: unknown) {
  const raw = String(val || "").trim()
  if (!raw) return "-"
  const matched = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (!matched) return raw
  return `${matched[2]}-${matched[3]}`
}

function xqUrl(code?: string | null) {
  const raw = String(code || "").trim()
  if (!raw) return "https://xueqiu.com"
  const upper = raw.toUpperCase()
  if (upper.includes(".")) {
    const [num, suffix] = upper.split(".")
    const market = suffix === "SH" ? "SH" : suffix === "SZ" ? "SZ" : suffix === "BJ" ? "BJ" : ""
    return market ? `https://xueqiu.com/S/${market}${num}` : `https://xueqiu.com/S/${upper}`
  }
  if (raw.startsWith("6") || raw.startsWith("9")) return `https://xueqiu.com/S/SH${raw}`
  if (raw.startsWith("4") || raw.startsWith("8")) return `https://xueqiu.com/S/BJ${raw}`
  return `https://xueqiu.com/S/SZ${raw}`
}

function openStatusClass(status?: string) {
  const key = String(status || "")
  if (key === "super") return "is-super"
  if (key === "expected") return "is-expected"
  if (key === "pending" || key === "wait_reseal") return "is-wait"
  if (key === "reject") return "is-reject"
  return "is-neutral"
}

function openStatusLabel(status?: string, label?: string) {
  if (label) return label
  const key = String(status || "")
  if (key === "super") return "超预期"
  if (key === "expected") return "符合预期"
  if (key === "pending") return "观察"
  if (key === "wait_reseal") return "待确认"
  if (key === "reject") return "低预期"
  return "暂无判断"
}

function decisionLabel(signalStatus?: string, decisionStatus?: string, fallbackLabel?: string) {
  const s = String(signalStatus || "")
  const d = String(decisionStatus || "")
  if (s === "super") return "买入"
  if (s === "expected") return "买入"
  if (s === "pending") return "观察"
  if (s === "reject") return "低预期"
  if (d === "pending") return "观察"
  if (d === "unavailable") return "报价缺失"
  if (fallbackLabel) return fallbackLabel
  return "待判断"
}

function snapshotReturnText(row: any) {
  const status = String(row?.next_day_status || "")
  if (status === "covered") return `${formatSigned(row?.next_day_return_pct, 2)}%`
  if (status === "skipped") return "未入场"
  if (status === "pending") return "待补齐"
  if (status === "missing") return "缺失"
  return row?.next_day_label || "-"
}

function snapshotReturnClass(row: any) {
  const status = String(row?.next_day_status || "")
  if (status === "covered") return signedClass(row?.next_day_return_pct)
  return "orange-text"
}

function strategyReturnText(performance: any, key: string) {
  const item = performance && typeof performance === "object" ? performance[key] || {} : {}
  const status = String(item?.status || "")
  if (status === "covered") return `${formatSigned(item?.return_pct, 2)}%`
  if (status === "pending") return "待补齐"
  if (status === "skipped") return "未入场"
  if (status === "missing") return "缺失"
  return item?.label || "-"
}

function strategyReturnNote(performance: any, key: string) {
  const item = performance && typeof performance === "object" ? performance[key] || {} : {}
  const status = String(item?.status || "")
  if (status === "covered") return `${item?.entry_date || "-"} 开盘买入 -> ${item?.exit_date || "-"} 收盘`
  return String(item?.note || item?.label || "-")
}

function strategyReturnClass(performance: any, key: string) {
  const item = performance && typeof performance === "object" ? performance[key] || {} : {}
  const status = String(item?.status || "")
  if (status === "covered") return signedClass(item?.return_pct)
  return "orange-text"
}
</script>

<template>
  <div class="bt-page">
    <div class="card" v-if="!hasAnyRenderableSection">
      <div class="card-header">
        <div>
          <div class="card-title">个股回测</div>
          <div class="bt-subtitle">收盘后先看推送进 JSON 的待验证数据，次日 09:25-09:30 再补真实竞价命中结果。</div>
        </div>
      </div>
      <div class="summary-box">
        <div class="summary-text">{{ emptyStateText }}</div>
      </div>
    </div>

    <template v-else>
    <div class="card bt-summary-card">
      <div class="card-header">
        <div>
          <div class="card-title">个股回测状态</div>
          <div class="bt-subtitle">{{ lifecycleStageNote || strategySubtitle }}</div>
        </div>
        <div class="bt-filter-box" v-if="availableRecommendationDates.length">
          <label class="bt-filter-label" for="bt-recommendation-date">推荐日</label>
          <select id="bt-recommendation-date" class="bt-filter-select" v-model="selectedRecommendationDateInput">
            <option v-for="date10 in availableRecommendationDates" :key="date10" :value="date10">
              {{ date10 }}{{ date10 === latestRecommendationDate ? " · 最新" : "" }}
            </option>
          </select>
        </div>
      </div>

      <div class="bt-pill-row">
        <span class="bt-pill" :class="stageClass">{{ lifecycleStageLabel }}</span>
        <span class="bt-pill" :class="quoteClass">{{ lifecycleQuoteLabel }}</span>
      </div>

      <div class="bt-kpi-grid">
        <div class="bt-kpi-card" v-for="item in summaryCards" :key="item.key">
          <div class="bt-kpi-label">{{ item.label }}</div>
          <div class="bt-kpi-value">{{ item.value }}</div>
          <div class="bt-kpi-note">{{ item.note }}</div>
        </div>
      </div>

      <div class="summary-box" v-if="lifecycleQuoteNote">
        <div class="summary-text">{{ lifecycleQuoteNote }}</div>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">{{ snapshotCardTitle }}</div>
          <div class="bt-subtitle">{{ realtimeSubtitle }}</div>
        </div>
      </div>

      <div class="summary-box" v-if="historicalSnapshotNotice">
        <div class="summary-text">{{ historicalSnapshotNotice }}</div>
      </div>

      <div class="summary-box" v-if="!hasSelectedSnapshot">
        <div class="summary-text">{{ realtimeEmptyText }}</div>
      </div>

      <div class="bt-table-wrap" v-else-if="isViewingCurrentRecommendation">
        <table class="ladder-table">
          <thead>
            <tr>
              <th>标的</th>
              <th>排名</th>
              <th>池子</th>
              <th>主线</th>
              <th>昨收</th>
              <th>开盘</th>
              <th>涨幅</th>
              <th>成交额</th>
              <th>量能阈值</th>
              <th>命中</th>
              <th>条件</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in allCandidates" :key="'cand-' + row.code">
              <td class="bt-name-cell">
                <div class="bt-name-line">
                  <a v-if="row.code" class="stock-link" :class="signedClass(row.gap_pct)" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
                  <span v-else :class="signedClass(row.gap_pct)">{{ row.name || "-" }}</span>
                </div>
                <div class="bt-name-sub">{{ row.code || "-" }} ｜ {{ row.score ?? "-" }}</div>
              </td>
              <td>{{ row.daily_rank || "-" }}</td>
              <td>{{ row.bucket_label || row.bucket || "-" }}</td>
              <td class="bt-left-cell">
                <div>{{ row.main_line || "-" }}</div>
              </td>
              <td>{{ formatPlain(row.prev_close, 2) }}元</td>
              <td :class="signedClass(row.gap_pct)">{{ formatPlain(row.auction_price, 2) }}元</td>
              <td :class="signedClass(row.gap_pct)">{{ formatSigned(row.gap_pct, 2) }}%</td>
              <td>{{ formatPlain(row.auction_amount_yi, 2) }}亿</td>
              <td>{{ formatPlain(row.auction_amount_need_yi, 2) }}亿</td>
              <td>
                <span class="bt-pill" :class="openStatusClass(row.signal_status)">{{ decisionLabel(row.signal_status, row.decision_status) }}</span>
              </td>
              <td class="bt-cond-cell">
                <span class="bt-pill" :class="openStatusClass(row.signal_status)" style="margin-right:4px">{{ row.signal_label || '-' }}</span>
                <span class="bt-cell-sub">{{ row.rule_text || "-" }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="bt-table-wrap" v-else>
        <table class="ladder-table">
          <thead>
            <tr>
              <th>标的</th>
              <th>排名</th>
              <th>池子</th>
              <th>主线</th>
              <th>开盘判断</th>
              <th>涨幅</th>
              <th>当日收益</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in allCandidates" :key="'hist-cand-' + row.code">
              <td class="bt-name-cell">
                <div class="bt-name-line">
                  <a v-if="row.code" class="stock-link" :class="signedClass(row.gap_pct)" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
                  <span v-else :class="signedClass(row.gap_pct)">{{ row.name || "-" }}</span>
                </div>
                <div class="bt-name-sub">{{ row.code || "-" }} ｜ {{ row.score ?? "-" }}</div>
              </td>
              <td>{{ row.daily_rank || "-" }}</td>
              <td>{{ row.bucket_label || row.bucket || "-" }}</td>
              <td class="bt-left-cell">{{ row.main_line || "-" }}</td>
              <td>
                <span class="bt-pill" :class="openStatusClass(row.signal_status)">{{ decisionLabel(row.signal_status, row.decision_status, row.signal_label) }}</span>
              </td>
              <td :class="signedClass(row.gap_pct)">{{ formatSigned(row.gap_pct, 2) }}%</td>
              <td :class="snapshotReturnClass(row)">{{ snapshotReturnText(row) }}</td>
              <td class="bt-cond-cell">
                <div class="bt-cell-sub">{{ row.note || "-" }}</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card" v-if="hasCurrentPlan">
      <div class="card-header">
        <div>
          <div class="card-title">{{ currentPlanCardTitle }}</div>
          <div class="bt-subtitle">{{ currentPlanSubtitle }}</div>
        </div>
      </div>

      <div class="bt-table-wrap bt-table-wrap-plan">
        <table class="ladder-table bt-plan-table">
          <thead>
            <tr>
              <th>推荐日</th>
              <th>排名</th>
              <th>标的</th>
              <th>池子</th>
              <th>主线</th>
              <th>超预期</th>
              <th>预期</th>
              <th>低预期</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in currentRecords" :key="'plan-' + row.trade_date10 + '-' + row.code">
              <td class="bt-date-col">{{ formatMonthDay(row.date10) }}</td>
              <td>{{ row.daily_rank || "-" }}</td>
              <td class="bt-name-cell">
                <div class="bt-name-line">
                  <a v-if="row.code" class="stock-link" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
                  <span v-else>{{ row.name || "-" }}</span>
                </div>
                <div class="bt-name-sub">{{ row.code || "-" }} ｜ {{ row.score ?? "-" }} ｜ {{ row.score_sub_label || row.style_tag || "-" }}</div>
              </td>
              <td>{{ row.bucket_label || row.bucket || "-" }}</td>
              <td class="bt-left-cell">
                <div>{{ row.main_line || "-" }}</div>
                <div class="bt-cell-sub">{{ row.hy || row.plate_name || "-" }}</div>
              </td>
              <td class="bt-left-cell">{{ row.expectation?.super_text || "-" }}</td>
              <td class="bt-left-cell">{{ row.expectation?.expected_text || "-" }}</td>
              <td class="bt-left-cell">{{ row.expectation?.low_text || "-" }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card" v-if="hasHistoricalRecords">
      <div class="card-header">
        <div>
          <div class="card-title">策略表现</div>
          <div class="bt-subtitle">{{ strategySubtitle }}</div>
        </div>
      </div>

      <div class="bt-metrics-grid">
        <div class="bt-metric-card" v-for="item in metrics" :key="item.key">
          <div class="section-header">{{ item.label }}</div>
          <div class="bt-metric-rows" style="border:none">
            <div class="bt-metric-row">
              <div>
                <div class="bt-metric-k">覆盖样本</div>
                <div class="bt-metric-note">可执行 {{ metricScope(item, 'tradable')?.eligible ?? 0 }} 笔，已覆盖 {{ metricScope(item, 'tradable')?.covered ?? 0 }} 笔</div>
              </div>
              <div class="bt-metric-v">{{ metricScope(item, "tradable")?.coverage ?? 0 }}%</div>
            </div>
            <div class="bt-metric-row">
              <div>
                <div class="bt-metric-k">胜率</div>
                <div class="bt-metric-note">上涨 {{ metricScope(item, 'tradable')?.win_count ?? 0 }} ｜ 平 {{ metricScope(item, 'tradable')?.flat_count ?? 0 }} ｜ 下跌 {{ metricScope(item, 'tradable')?.loss_count ?? 0 }}</div>
              </div>
              <div class="bt-metric-v">{{ metricScope(item, "tradable")?.win_rate ?? 0 }}%</div>
            </div>
            <div class="bt-metric-row">
              <div>
                <div class="bt-metric-k">平均收益</div>
                <div class="bt-metric-note">平均盈利 {{ metricScope(item, 'tradable')?.avg_win_return ?? 0 }}% ｜ 平均回撤 {{ metricScope(item, 'tradable')?.avg_loss_return ?? 0 }}%</div>
              </div>
              <div class="bt-metric-v" :class="signedClass(metricScope(item, 'tradable')?.avg_return)">{{ formatSigned(metricScope(item, "tradable")?.avg_return, 2) }}%</div>
            </div>
          </div>

          <div class="bt-split-row" style="border:none;background:none;padding:0">
            <div style="font-size:11px;color:var(--text-muted);padding:4px 8px">
              超预期均值 <span class="red-text">{{ formatSigned(metricScope(item, 'tradable')?.by_open_status?.super?.avg_return, 2) }}%</span>
              ｜ 超预期胜率 {{ metricScope(item, 'tradable')?.by_open_status?.super?.win_rate ?? 0 }}%
            </div>
          </div>
        </div>
      </div>
    </div>


    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">历史样本明细</div>
          <div class="bt-subtitle">这里按所选推荐日回看“推荐理由 -> 开盘判断 -> 收益表现”的完整链路；高开谨慎规则已同步纳入口径。</div>
        </div>
      </div>

      <div class="summary-box" v-if="!historicalRecords.length">
        <div class="summary-text">当前还没有历史样本明细。只要累计多个推荐交易日，这里会自动展示跨日回测结果。</div>
      </div>

      <div class="bt-table-wrap" v-else>
        <table class="ladder-table">
          <thead>
            <tr>
              <th>推荐日</th>
              <th>排名</th>
              <th>标的</th>
              <th>开盘判断</th>
              <th>涨幅</th>
              <th>T+1</th>
              <th>T+2</th>
              <th>T+3</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in historicalRecords" :key="'record-' + row.date10 + '-' + row.code">
              <td class="bt-date-col">{{ formatMonthDay(row.date10) }}</td>
              <td>{{ row.daily_rank || "-" }}</td>
              <td class="bt-name-cell">
                <div class="bt-name-line">
                  <a v-if="row.code" class="stock-link" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
                  <span v-else>{{ row.name || "-" }}</span>
                </div>
                <div class="bt-name-sub">{{ row.code || "-" }} ｜ {{ row.score ?? "-" }} ｜ {{ row.score_sub_label || row.style_tag || row.bucket_label || "-" }}</div>
              </td>
              <td class="bt-left-cell">
                <span class="bt-pill" :class="openStatusClass(row.performance?.open_check?.status)">{{ openStatusLabel(row.performance?.open_check?.status, row.performance?.open_check?.label) }}</span>
                <div class="bt-cell-sub">{{ row.performance?.open_check?.note || "-" }}</div>
              </td>
              <td :class="signedClass(row.performance?.open_check?.gap_pct)">{{ formatSigned(row.performance?.open_check?.gap_pct, 2) }}%</td>
              <td :class="strategyReturnClass(row.performance, 'next_day')">
                {{ strategyReturnText(row.performance, "next_day") }}
                <div class="bt-cell-sub">{{ strategyReturnNote(row.performance, "next_day") }}</div>
              </td>
              <td :class="strategyReturnClass(row.performance, 'hold_2d')">
                {{ strategyReturnText(row.performance, "hold_2d") }}
                <div class="bt-cell-sub">{{ strategyReturnNote(row.performance, "hold_2d") }}</div>
              </td>
              <td :class="strategyReturnClass(row.performance, 'hold_3d')">
                {{ strategyReturnText(row.performance, "hold_3d") }}
                <div class="bt-cell-sub">{{ strategyReturnNote(row.performance, "hold_3d") }}</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    </template>

    <ShortReminderFooter />
  </div>
</template>

<style scoped src="./BacktestPage.css"></style>
