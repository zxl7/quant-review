<script setup lang="ts">
import { computed, ref, watchEffect } from "vue"
import { useMarketData } from "../../composables/useMarketData"
import { useECharts } from "../../composables/useECharts"
import ShortReminderFooter from "../common/ShortReminderFooter.vue"
import { computeAccountCurveFromBacktest, computeAccountCurveFromLedger } from "./accountCurve"
const { marketData } = useMarketData()
const backtestSource = computed<any>(() => {
  const md = marketData.value as any
  return md || {}
})
const accountCurveChartRef = ref<HTMLElement | null>(null)

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
    latest_closed_trade_date: "",
    latest_closed_recommendation_date: "",
    default_display_trade_date: "",
    default_display_recommendation_date: "",
    has_pending_next_trade_day: false,
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
    latest_closed_trade_date: "",
    latest_closed_recommendation_date: "",
    default_display_trade_date: "",
    default_display_recommendation_date: "",
    has_pending_next_trade_day: false,
    default_display_note: "",
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

const marketSessionDate = computed(() => String((marketData.value as any)?.date || backtestSource.value?.date || "").trim())
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
const realtimeReferenceDate = computed(() => String(realtimeBuy.value?.reference_date || latestRecommendationDate.value || "").trim())
const realtimeTitleDate = computed(() => {
  return String(realtimeBuy.value?.trade_date || activeTradeDate.value || recommendationTradeDateMap.value[realtimeReferenceDate.value] || marketSessionDate.value || realtimeReferenceDate.value || "").trim()
})
const realtimeCardTitle = computed(() => (realtimeTitleDate.value ? `竞价结果 — ${realtimeTitleDate.value} 9:25` : "竞价结果"))
const backtestUpdatedAt = computed(() => meta.value?.generated_at_bj || backtestSource.value?.meta?.generatedAt || (marketData.value as any)?.meta?.generatedAt || "-")
const quoteUpdatedAt = computed(() => realtimeBuy.value?.quote_time || "-")
const isForcedQuerySnapshot = computed(() => !!realtimeBuy.value?.diagnostics?.forced_query)
const watchGroupRank: Record<string, number> = {
  "高标/题材核心": 0,
  "高位分歧": 1,
  "容量核心": 2,
  "风险观察": 3,
  "补充观察": 4,
}
const snapshotSignalRank: Record<string, number> = { super: 0, expected: 1, pending: 2, reject: 3, unavailable: 4 }

function compareSelectionRows(a: any, b: any) {
  const aBucket = String(a?.bucket || "")
  const bBucket = String(b?.bucket || "")
  if (aBucket !== bBucket) {
    if (aBucket === "relay") return -1
    if (bBucket === "relay") return 1
    if (aBucket === "watch") return -1
    if (bBucket === "watch") return 1
    return aBucket.localeCompare(bBucket)
  }
  const aRelayRank = toNum(a?.relay_rank, 0)
  const bRelayRank = toNum(b?.relay_rank, 0)
  if (aRelayRank || bRelayRank) {
    const diff = (aRelayRank || 999) - (bRelayRank || 999)
    if (diff) return diff
  }
  const aWatchRank = toNum(a?.watch_rank, 0)
  const bWatchRank = toNum(b?.watch_rank, 0)
  if (aWatchRank || bWatchRank) {
    const diff = (aWatchRank || 999) - (bWatchRank || 999)
    if (diff) return diff
  }
  const aWatchGroup = watchGroupRank[String(a?.watch_group || "")] ?? 9
  const bWatchGroup = watchGroupRank[String(b?.watch_group || "")] ?? 9
  if (aWatchGroup !== bWatchGroup) return aWatchGroup - bWatchGroup
  const scoreDiff = toNum(b?.score, 0) - toNum(a?.score, 0)
  if (scoreDiff) return scoreDiff
  return String(a?.code || "").localeCompare(String(b?.code || ""))
}

function compareSnapshotRows(a: any, b: any) {
  const ra = snapshotSignalRank[String(a?.signal_status || "")] ?? 9
  const rb = snapshotSignalRank[String(b?.signal_status || "")] ?? 9
  if (ra !== rb) return ra - rb
  return compareSelectionRows(a, b)
}

function sortSelectionRows(rows: any[]) {
  rows.sort(compareSelectionRows)
  return rows
}

function sortSnapshotRows(rows: any[]) {
  rows.sort(compareSnapshotRows)
  return rows
}
const realtimeCandidates = computed<any[]>(() => {
  const buy = Array.isArray(realtimeBuy.value?.buy_list) ? realtimeBuy.value.buy_list : []
  const rejected = Array.isArray(realtimeBuy.value?.rejected_list) ? realtimeBuy.value.rejected_list : []
  const pending = Array.isArray(realtimeBuy.value?.pending_list) ? realtimeBuy.value.pending_list : []
  const unavailable = Array.isArray(realtimeBuy.value?.unavailable_list) ? realtimeBuy.value.unavailable_list : []
  return sortSnapshotRows([...buy, ...pending, ...rejected, ...unavailable])
})
const hasAnyRealtimeSnapshot = computed(() => {
  if (!hasValidPayload.value) return false
  if (!realtimeBuy.value?.reference_date) return false
  if (!isForcedQuerySnapshot.value && !isEntryWindowTime(realtimeBuy.value?.quote_time)) return false
  return realtimeCandidates.value.length > 0
})

function metricScope(item: any, scope: "all" | "tradable") {
  const scopes = item?.data?.scopes
  if (scopes && typeof scopes === "object" && scopes[scope] && typeof scopes[scope] === "object") return scopes[scope]
  return item?.data || {}
}

const currentPoolRecords = computed<any[]>(() => {
  const rows = Array.isArray(payload.value?.currentPoolRecords) ? [...payload.value.currentPoolRecords] : []
  return sortSelectionRows(rows)
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
    return compareSelectionRows(a, b)
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
    return compareSelectionRows(a, b)
  })
  return rows
})
const latestRecommendationDate = computed(() => String(meta.value?.latest_recommendation_date || realtimeBuy.value?.reference_date || "").trim())
const latestClosedTradeDate = computed(() => String(meta.value?.latest_closed_trade_date || lifecycle.value?.latest_closed_trade_date || "").trim())
const latestClosedRecommendationDateMeta = computed(() => String(meta.value?.latest_closed_recommendation_date || lifecycle.value?.latest_closed_recommendation_date || "").trim())
const defaultDisplayTradeDate = computed(() => String(meta.value?.default_display_trade_date || lifecycle.value?.default_display_trade_date || "").trim())
const defaultDisplayRecommendationDateMeta = computed(() => String(meta.value?.default_display_recommendation_date || lifecycle.value?.default_display_recommendation_date || "").trim())
const hasPendingNextTradeDay = computed(() => !!(meta.value?.has_pending_next_trade_day ?? lifecycle.value?.has_pending_next_trade_day))
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
const latestHistoricalRecommendationDate = computed(() => String(lifecycle.value?.latest_historical_recommendation_date || "").trim())
const recommendationTradeDateMap = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  for (const item of historicalSnapshots.value) {
    const referenceDate = String(item?.reference_date || "").trim()
    const tradeDate = String(item?.trade_date || item?.trade_date10 || "").trim()
    if (referenceDate && tradeDate) out[referenceDate] = tradeDate
  }
  const realtimeReference = String(realtimeBuy.value?.reference_date || latestRecommendationDate.value || "").trim()
  const realtimeTradeDate = String(realtimeBuy.value?.trade_date || activeTradeDate.value || "").trim()
  if (realtimeReference && realtimeTradeDate) out[realtimeReference] = realtimeTradeDate
  return out
})
const latestClosedRecommendationDate = computed(() => {
  if (defaultDisplayRecommendationDateMeta.value && availableRecommendationDates.value.includes(defaultDisplayRecommendationDateMeta.value)) {
    return defaultDisplayRecommendationDateMeta.value
  }
  if (latestClosedRecommendationDateMeta.value && availableRecommendationDates.value.includes(latestClosedRecommendationDateMeta.value)) {
    return latestClosedRecommendationDateMeta.value
  }
  if (latestHistoricalRecommendationDate.value && availableRecommendationDates.value.includes(latestHistoricalRecommendationDate.value)) {
    return latestHistoricalRecommendationDate.value
  }
  const historicalDates = new Set<string>()
  for (const item of historicalSnapshots.value) {
    const date10 = String(item?.reference_date || "").trim()
    if (date10 && availableRecommendationDates.value.includes(date10)) historicalDates.add(date10)
  }
  return Array.from(historicalDates).sort((a, b) => b.localeCompare(a))[0] || ""
})
const defaultRecommendationDate = computed(() => {
  if (defaultDisplayRecommendationDateMeta.value && availableRecommendationDates.value.includes(defaultDisplayRecommendationDateMeta.value)) {
    return defaultDisplayRecommendationDateMeta.value
  }
  if (latestClosedRecommendationDate.value) {
    return latestClosedRecommendationDate.value
  }
  if (hasAnyRealtimeSnapshot.value && realtimeReferenceDate.value && availableRecommendationDates.value.includes(realtimeReferenceDate.value)) {
    return realtimeReferenceDate.value
  }
  if (latestRecommendationDate.value && availableRecommendationDates.value.includes(latestRecommendationDate.value)) {
    return latestRecommendationDate.value
  }
  return availableRecommendationDates.value[0] || latestRecommendationDate.value || ""
})
const selectedRecommendationDate = computed(() => {
  const raw = String(selectedRecommendationDateInput.value || "").trim()
  if (raw && availableRecommendationDates.value.includes(raw)) return raw
  return defaultRecommendationDate.value
})
watchEffect(() => {
  const raw = String(selectedRecommendationDateInput.value || "").trim()
  const next = String(defaultRecommendationDate.value || "").trim()
  if (!next) return
  if (raw && availableRecommendationDates.value.includes(raw)) return
  if (raw === next) return
  selectedRecommendationDateInput.value = next
})
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
  return sortSelectionRows(rows)
})
const currentEligibleCount = computed(() => currentRecords.value.filter((row) => !!row?.performance?.open_check?.can_enter).length)
const hasCurrentPlan = computed(() => hasValidPayload.value && currentRecords.value.length > 0)
const hasHistoricalRecords = computed(() => selectedDayDisplayRecords.value.length > 0)
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
  if (selectedRecommendationDate.value && selectedRecommendationDate.value !== String(realtimeBuy.value?.reference_date || "").trim()) return false
  return hasAnyRealtimeSnapshot.value
})
const showingRealtimeSnapshot = computed(() => hasRealtimeSnapshot.value)
const showingPredictionTable = computed(() => !showingRealtimeSnapshot.value && isViewingCurrentRecommendation.value && hasCurrentPlan.value)
const hasSelectedSnapshot = computed(() => hasRealtimeSnapshot.value || showingPredictionTable.value || historicalCandidates.value.length > 0)
const allCandidates = computed<any[]>(() => {
  if (showingRealtimeSnapshot.value) return realtimeCandidates.value
  if (showingPredictionTable.value) return currentRecords.value
  return historicalCandidates.value
})
const hasAnyRenderableSection = computed(() => hasCurrentPlan.value || hasHistoricalRecords.value || hasSelectedSnapshot.value)
const selectedResultTradeDate = computed(() => {
  if (showingRealtimeSnapshot.value) return realtimeTitleDate.value
  if (showingPredictionTable.value) {
    return String(recommendationTradeDateMap.value[selectedRecommendationDate.value] || activeTradeDate.value || "").trim()
  }
  return String(
    selectedHistoricalSnapshot.value?.trade_date || recommendationTradeDateMap.value[selectedRecommendationDate.value] || defaultDisplayTradeDate.value || ""
  ).trim()
})
const isDefaultSelection = computed(() => selectedRecommendationDate.value === defaultRecommendationDate.value)
const isSkippedMissingClosedDay = computed(() => {
  if (!isDefaultSelection.value) return false
  if (showingRealtimeSnapshot.value || showingPredictionTable.value) return false
  if (!marketSessionDate.value || !selectedResultTradeDate.value) return false
  return selectedResultTradeDate.value !== marketSessionDate.value
})
const lifecycleStage = computed(() => String(lifecycle.value?.stage || "empty"))
const lifecycleStageLabel = computed(() => String(lifecycle.value?.stage_label || "暂无数据"))
const lifecycleStageNote = computed(() => String(lifecycle.value?.stage_note || "").trim())
const lifecycleQuoteLabel = computed(() => String(lifecycle.value?.quote_state_label || "等待推送"))
const lifecycleQuoteNote = computed(() => String(lifecycle.value?.quote_state_note || "").trim())
const currentPlanTitleDate = computed(() => String(selectedRecommendationDate.value || latestRecommendationDate.value || activeTradeDate.value || "").trim())
const currentRecommendationAnchorDate = computed(() => {
  if (showingRealtimeSnapshot.value && realtimeReferenceDate.value) return realtimeReferenceDate.value
  if (latestRecommendationDate.value) return latestRecommendationDate.value
  return realtimeReferenceDate.value
})
const isViewingCurrentRecommendation = computed(() => {
  const selected = String(selectedRecommendationDate.value || "").trim()
  const current = String(currentRecommendationAnchorDate.value || "").trim()
  if (!selected || !current) return false
  if (selected === current) return true
  return hasAnyRealtimeSnapshot.value && selected === realtimeReferenceDate.value
})
const snapshotTradeDate = computed(() => {
  if (showingRealtimeSnapshot.value) return realtimeTitleDate.value
  return String(selectedHistoricalSnapshot.value?.trade_date || selectedResultTradeDate.value || defaultDisplayTradeDate.value || "").trim()
})
const snapshotCardTitle = computed(() => {
  if (showingRealtimeSnapshot.value) {
    return realtimeTitleDate.value ? `闭环结果 — ${realtimeTitleDate.value}` : "闭环结果"
  }
  if (showingPredictionTable.value) return currentPlanTitleDate.value ? `待验证推荐 — ${currentPlanTitleDate.value}` : "待验证推荐"
  return snapshotTradeDate.value ? `闭环结果 — ${snapshotTradeDate.value}` : "闭环结果待补"
})
const realtimeSubtitle = computed(() => {
  if (showingPredictionTable.value) {
    return "当前财富密码样本直接来自上一交易日涨停分析的接力池/观察池，排序已按龙头接力优先、确定性优先重排；先看盘后条件，次日 09:25 再补竞价结果。"
  }
  if (!isViewingCurrentRecommendation.value) {
    if (selectedHistoricalSnapshot.value) {
      return `这里按同一套龙头接力优先顺位，恢复 ${effectiveHistoricalDate.value} 推荐在 ${selectedHistoricalSnapshot.value?.trade_date || "-"} 开盘的命中结果与当日收益；原始 9:25 快照缺失也会自动衔接。`
    }
    return `当前只保留最新推荐日 ${String(realtimeBuy.value?.reference_date || "-")} 的 9:25 竞价快照；所选推荐日请看下方开盘判断和收益表现。`
  }
  if (hasRealtimeSnapshot.value && quoteUpdatedAt.value && quoteUpdatedAt.value !== "-") {
    if (isForcedQuerySnapshot.value) {
      return `今日缺失的竞价快照已在 ${quoteUpdatedAt.value} 补齐，当前按正常闭环结果展示。`
    }
    return `竞价快照：${quoteUpdatedAt.value}｜高开超5%先观察，不直接追。`
  }
  if (selectedHistoricalSnapshot.value) {
    return `这里根据收盘后回测记录恢复 ${effectiveHistoricalDate.value} 推荐在 ${selectedHistoricalSnapshot.value?.trade_date || "-"} 开盘的命中结果与当日收益。`
  }
  if (hasCurrentPlan.value && latestRecommendationDate.value) {
    return `盘后样本已更新到 ${latestRecommendationDate.value}，明日 09:25-09:30 再补真实竞价命中结果。`
  }
  return "高开超5%先观察，不直接追。"
})
const strategySubtitle = computed(() => {
  const dateLabel = selectedResultTradeDate.value ? `结果口径 ${selectedResultTradeDate.value}｜` : ""
  const updatedAt = String(backtestUpdatedAt.value || "").trim()
  return updatedAt && updatedAt !== "-"
    ? `${dateLabel}收益口径：高开超5%样本先观察，不计入直接开盘买入，再统计 T+1 / T+2 / T+3 收盘卖出。最新刷新：${updatedAt}`
    : `${dateLabel}收益口径：高开超5%样本先观察，不计入直接开盘买入，再统计 T+1 / T+2 / T+3 收盘卖出。`
})
const summaryHeaderSubtitle = computed(() => {
  if (showingRealtimeSnapshot.value && realtimeReferenceDate.value) {
    const tradeDate = selectedResultTradeDate.value || realtimeTitleDate.value || "-"
    const nextLabel = hasPendingNextTradeDay.value && latestRecommendationDate.value && latestRecommendationDate.value !== realtimeReferenceDate.value
      ? `；切换到 ${latestRecommendationDate.value} 可查看下一交易日待验证推荐`
      : ""
    return `今天是 ${marketSessionDate.value || tradeDate}，页面当前展示 ${tradeDate} 的闭环结果（对应推荐日 ${realtimeReferenceDate.value}）${nextLabel}。`
  }
  if (!isViewingCurrentRecommendation.value && selectedRecommendationDate.value) {
    const latestLabel = hasPendingNextTradeDay.value && latestRecommendationDate.value ? `；切到 ${latestRecommendationDate.value} 可看下一交易日待验证推荐` : ""
    const tradeDate = selectedResultTradeDate.value || "-"
    if (isDefaultSelection.value && marketSessionDate.value) {
      if (isSkippedMissingClosedDay.value) {
        return `今天是 ${marketSessionDate.value}，当天闭环缺失时会自动跳过；当前展示最近一个有数据的闭环日 ${tradeDate}（对应推荐日 ${selectedRecommendationDate.value}）${latestLabel}。`
      }
      return `今天是 ${marketSessionDate.value}，页面默认展示当天闭环结果 ${tradeDate}（对应推荐日 ${selectedRecommendationDate.value}）${latestLabel}。`
    }
    return `当前展示 ${tradeDate} 的闭环结果（对应推荐日 ${selectedRecommendationDate.value}）${latestLabel}。`
  }
  return lifecycleStageNote.value || strategySubtitle.value
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
    key: "session_date",
    label: "页面日期",
    value: marketSessionDate.value || "-",
    note: selectedResultTradeDate.value
      ? (isSkippedMissingClosedDay.value
          ? `当天闭环缺失，已自动跳到最近有数据的 ${selectedResultTradeDate.value}`
          : `默认按今天进入页面，主结果展示 ${selectedResultTradeDate.value}`)
      : (activeTradeDate.value ? `待验证交易日 ${activeTradeDate.value}` : "当前暂无待验证交易日"),
  },
  {
    key: "history",
    label: showingRealtimeSnapshot.value ? "当前闭环" : (isViewingCurrentRecommendation.value ? "待验证批次" : "当前闭环"),
    value: selectedResultTradeDate.value || activeTradeDate.value || "-",
    note: selectedRecommendationDate.value
      ? `对应推荐日 ${selectedRecommendationDate.value}${availableRecommendationDates.value.length > 1 ? `｜可切换 ${availableRecommendationDates.value.length} 个批次` : ""}`
      : "当前还没有可切换批次",
  },
  {
    key: "pool",
    label: showingRealtimeSnapshot.value ? "当前结果样本" : (isViewingCurrentRecommendation.value ? "待验证样本" : "推荐池样本"),
    value: `${currentRecords.value.length}`,
    note: isViewingCurrentRecommendation.value
      ? (currentEligibleCount.value > 0 ? `可入场候选 ${currentEligibleCount.value} 条` : "当前以盘后样本展示为主")
      : (currentEligibleCount.value > 0 ? `当日可入场样本 ${currentEligibleCount.value} 条` : "当前以历史推荐样本展示为主"),
  },
  {
    key: "snapshot",
    label: showingRealtimeSnapshot.value ? "9:25 快照" : "闭环结果",
    value: hasSelectedSnapshot.value ? `${allCandidates.value.length}` : "-",
    note: showingRealtimeSnapshot.value
      ? (isForcedQuerySnapshot.value ? `补齐时间 ${quoteUpdatedAt.value}` : `快照时间 ${quoteUpdatedAt.value}`)
      : (showingPredictionTable.value ? "当前展示收盘后推送的待验证样本" : (selectedHistoricalSnapshot.value?.diagnostics?.note || "历史预测未恢复")),
  },
])
function recommendationOptionLabel(date10: string) {
  const recommendationDate = String(date10 || "").trim()
  if (!recommendationDate) return "-"
  const tradeDate = String(recommendationTradeDateMap.value[recommendationDate] || "").trim()
  if (recommendationDate === defaultDisplayRecommendationDateMeta.value) {
    return tradeDate ? `${tradeDate} 闭环（默认，推荐于 ${recommendationDate}）` : `${recommendationDate} · 闭环（默认）`
  }
  if (recommendationDate === latestRecommendationDate.value && hasPendingNextTradeDay.value) {
    return tradeDate ? `${tradeDate} 待验证（推荐于 ${recommendationDate}）` : `${recommendationDate} · 待验证`
  }
  return tradeDate ? `${tradeDate} 闭环（推荐于 ${recommendationDate}）` : recommendationDate
}
const emptyStateText = computed(() => {
  if (!hasValidPayload.value) return "当前暂无有效回测数据，明天 09:25-09:30 落地后会自动显示对应内容。"
  if (hasCurrentPlan.value) return "收盘后推送的个股研究样本已经落进回测 JSON，当前先展示待验证推荐；到下一交易日 09:25-09:30 再补真实竞价命中结果。"
  if (!realtimeBuy.value?.reference_date) return "当前推荐还没到次日 09:25-09:30，明天窗口内会落地实时行情。"
  if (isForcedQuerySnapshot.value) return "今日缺失的竞价快照正在补齐，补齐后会按正常闭环结果展示。"
  if (!isEntryWindowTime(realtimeBuy.value?.quote_time)) return "当前暂无有效竞价快照，等明天 09:25-09:30 落地后再显示命中结果。"
  return "当前没有可展示的回测结果。"
})
const realtimeEmptyText = computed(() => {
  if (!hasValidPayload.value) return "当前暂无有效回测数据。"
  if (!isViewingCurrentRecommendation.value) return "所选推荐日没有原始 9:25 快照，但如果历史回测已落地，会在这里恢复命中结果。"
  if (!hasCurrentPlan.value) return "当前还没有待验证推荐数据，先执行一次复盘脚本生成个股回测 JSON。"
  if (!realtimeBuy.value?.reference_date) return "当前是收盘后待验证阶段，明天 09:25-09:30 会补充实时量价和命中结果。"
  if (isForcedQuerySnapshot.value) return "今日缺失的竞价快照补齐仍未拿到可用实时行情。"
  if (!isEntryWindowTime(realtimeBuy.value?.quote_time)) return "当前还没到有效竞价快照时间，明天 09:25-09:30 会自动显示真实命中结果。"
  return "当前没有命中结果。"
})
const historicalSnapshotNotice = computed(() => {
  if (showingRealtimeSnapshot.value || showingPredictionTable.value) return ""
  return String(selectedHistoricalSnapshot.value?.diagnostics?.note || "").trim()
})
const accountStrategyMetricsPayload = computed<any>(() => {
  const md = marketData.value as any
  const raw = md?.accountStrategyMetrics
  return raw && typeof raw === "object" ? raw : { records: [] }
})
const accountStrategyMetricMap = computed<Record<string, any>>(() => {
  const out: Record<string, any> = {}
  const rows = Array.isArray(accountStrategyMetricsPayload.value?.records) ? accountStrategyMetricsPayload.value.records : []
  for (const item of rows) {
    const key = String(item?.recommendation_date || "").trim()
    if (key) out[key] = item
  }
  return out
})
const selectedStrategyMetricRecord = computed<any | null>(() => {
  const key = selectedRecommendationDate.value || effectiveHistoricalDate.value
  return key ? accountStrategyMetricMap.value[key] || null : null
})
const metrics = computed(() => {
  const record = selectedStrategyMetricRecord.value
  const defs = [
    { key: "next_day", label: "隔日收益" },
    { key: "hold_2d", label: "2日收益" },
    { key: "hold_3d", label: "3日收益" },
  ]
  if (record?.metrics && typeof record.metrics === "object") {
    return defs.map((item) => ({
      key: item.key,
      label: item.label,
      data: {
        scopes: {
          all: record.metrics?.[item.key]?.all || {},
          tradable: record.metrics?.[item.key]?.tradable || {},
        },
      },
    }))
  }
  return buildDateScopedMetrics(selectedDayRecordsAll.value)
})
const accountCurveBase = computed(() => {
  const md = marketData.value as any
  return md?.accountNavLedger?.base ?? md?.accountCurve?.base ?? 1
})
const accountNavLedgerRecords = computed<any[]>(() => {
  const md = marketData.value as any
  return Array.isArray(md?.accountNavLedger?.records) ? md.accountNavLedger.records : []
})
const accountCurve = computed(() => {
  if (accountNavLedgerRecords.value.length) {
    return computeAccountCurveFromLedger(accountNavLedgerRecords.value, accountCurveBase.value)
  }
  return computeAccountCurveFromBacktest(records.value, accountCurveBase.value)
})
const accountCurvePoints = computed(() => accountCurve.value.points)
const accountCurveSummary = computed(() => accountCurve.value.summary)
const accountCurveUpdatedAt = computed(() => {
  const points = accountCurvePoints.value
  return points.length ? points[points.length - 1].date : "-"
})
const accountCurveOption = computed(() => {
  const points = accountCurvePoints.value
  if (!points.length) return null
  const values = points.map((item) => Number(item.value.toFixed(4)))
  const minValue = Math.min(...values)
  const maxValue = Math.max(...values)
  const span = maxValue - minValue || 0.01
  const padding = span * 0.16
  return {
    animation: false,
    grid: { left: 18, right: 18, top: 26, bottom: 30, containLabel: true },
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(15, 23, 42, 0.92)",
      borderWidth: 0,
      textStyle: { color: "#f8fafc" },
        formatter: (items: any[]) => {
          const first = Array.isArray(items) ? items[0] : null
          const index = Number(first?.dataIndex ?? -1)
          const point = index >= 0 ? points[index] : null
          if (!point) return ""
        return [
          `<strong>${point.date}</strong>`,
          `净值：${formatPlain(point.value, 4)}`,
          `当日等权收益：${formatSigned(point.dailyPct, 2)}%`,
          `累计：${formatSigned(point.cumPct, 2)}%`,
          `回撤：${formatSigned(point.drawdownPct, 2)}%`,
          `买入个股：${point.stockCount} 只`,
          point.names.length ? `标的：${point.names.join(" / ")}` : "",
        ].join("<br/>")
      },
    },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: points.map((item) => item.date.slice(5)),
      axisLine: { lineStyle: { color: "rgba(148, 163, 184, 0.35)" } },
      axisLabel: { color: "#94a3b8", fontSize: 11 },
      axisTick: { show: false },
    },
    yAxis: {
      type: "value",
      min: Number((minValue - padding).toFixed(4)),
      max: Number((maxValue + padding).toFixed(4)),
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: "rgba(148, 163, 184, 0.14)" } },
      axisLabel: {
        color: "#94a3b8",
        fontSize: 11,
        formatter: (value: number) => formatPlain(value, 2),
      },
    },
    series: [
      {
        type: "line",
        smooth: true,
        symbol: "circle",
        symbolSize: 7,
        data: values,
        lineStyle: { width: 3, color: "#ef4444" },
        itemStyle: { color: "#ef4444", borderColor: "#ffffff", borderWidth: 2 },
        areaStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(239, 68, 68, 0.28)" },
              { offset: 1, color: "rgba(239, 68, 68, 0.02)" },
            ],
          },
        },
      },
    ],
  }
})
useECharts(accountCurveChartRef, accountCurveOption)

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

function relaySelectionModeText(mode?: unknown) {
  const key = String(mode || "").trim()
  if (key === "strict") return "严格接力"
  if (key === "relaxed") return "宽松补位"
  if (key === "broad") return "宽题材兜底"
  if (key === "emergency") return "应急兜底"
  return ""
}

function rowPlacementText(row: any) {
  const label = String(row?.placement_label || row?.bucket_label || row?.bucket || "").trim() || "-"
  const relayRank = toNum(row?.relay_rank, 0)
  const watchRank = toNum(row?.watch_rank, 0)
  const watchGroup = String(row?.watch_group || "").trim()
  if (relayRank > 0) return `${label} #${relayRank}`
  if (watchRank > 0) return watchGroup ? `${label} #${watchRank} · ${watchGroup}` : `${label} #${watchRank}`
  if (watchGroup) return `${label} · ${watchGroup}`
  return label
}

function rowExplainText(row: any) {
  const parts: string[] = []
  const selectionMode = relaySelectionModeText(row?.relay_selection_mode)
  const ladderLabel = String(row?.theme_ladder_profile?.label || "").trim()
  const hitRules = Array.isArray(row?.hit_rules) ? row.hit_rules.filter(Boolean) : []
  const blockReasons = Array.isArray(row?.block_reasons) ? row.block_reasons.filter(Boolean) : []
  const factorHint = String(row?.factor_hint || "").trim()
  if (selectionMode) parts.push(`口径：${selectionMode}`)
  if (ladderLabel) parts.push(ladderLabel)
  if (hitRules.length) parts.push(`命中：${hitRules.join(" / ")}`)
  if (blockReasons.length) parts.push(`拦截：${blockReasons.join(" / ")}`)
  if (factorHint) parts.push(factorHint)
  return parts.join(" ｜ ") || "-"
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

function rowOpenPrice(row: any) {
  const direct = row?.open_price
  if (direct !== undefined && direct !== null && direct !== "") return direct
  return row?.auction_price
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
          <div class="bt-subtitle">{{ summaryHeaderSubtitle }}</div>
        </div>
        <div class="bt-filter-box" v-if="availableRecommendationDates.length">
          <label class="bt-filter-label" for="bt-recommendation-date">结果批次</label>
          <select id="bt-recommendation-date" class="bt-filter-select" v-model="selectedRecommendationDateInput">
            <option v-for="date10 in availableRecommendationDates" :key="date10" :value="date10">
              {{ recommendationOptionLabel(date10) }}
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

      <div class="bt-table-wrap" v-else-if="showingPredictionTable">
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
                <div class="bt-name-sub">{{ row.code || "-" }} ｜ {{ row.score_label || "综合分" }} {{ row.score ?? "-" }}</div>
              </td>
              <td>{{ row.relay_rank || row.watch_rank || row.daily_rank || "-" }}</td>
              <td>{{ rowPlacementText(row) }}</td>
              <td class="bt-left-cell">
                <div>{{ row.main_line || "-" }}</div>
              </td>
              <td>{{ showingPredictionTable ? "-" : `${formatPlain(row.prev_close, 2)}元` }}</td>
              <td :class="signedClass(row.gap_pct)">{{ showingPredictionTable ? "-" : `${formatPlain(row.auction_price, 2)}元` }}</td>
              <td :class="signedClass(row.gap_pct)">{{ showingPredictionTable ? "-" : `${formatSigned(row.gap_pct, 2)}%` }}</td>
              <td>{{ showingPredictionTable ? "-" : `${formatPlain(row.auction_amount_yi, 2)}亿` }}</td>
              <td>{{ showingPredictionTable ? "-" : `${formatPlain(row.auction_amount_need_yi, 2)}亿` }}</td>
              <td>
                <span v-if="!showingPredictionTable" class="bt-pill" :class="openStatusClass(row.signal_status)">{{ decisionLabel(row.signal_status, row.decision_status) }}</span>
                <span v-else>-</span>
              </td>
              <td class="bt-cond-cell">
                <template v-if="showingPredictionTable">
                  <div class="bt-cell-sub">{{ rowExplainText(row) }}</div>
                  <div class="bt-cell-sub"><strong>超预期：</strong>{{ row.expectation?.super_text || "-" }}</div>
                  <div class="bt-cell-sub"><strong>预期：</strong>{{ row.expectation?.expected_text || "-" }}</div>
                  <div class="bt-cell-sub"><strong>低预期：</strong>{{ row.expectation?.low_text || "-" }}</div>
                </template>
                <template v-else>
                  <span class="bt-pill" :class="openStatusClass(row.signal_status)" style="margin-right:4px">{{ row.signal_label || '-' }}</span>
                  <div class="bt-cell-sub">{{ row.rule_text || row.reason_text || "-" }}</div>
                  <div class="bt-cell-sub">{{ rowExplainText(row) }}</div>
                </template>
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
              <th>开盘价</th>
              <th>开盘涨幅</th>
              <th>收盘价</th>
              <th>收盘涨幅</th>
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
                <div class="bt-name-sub">{{ row.code || "-" }} ｜ {{ row.score_label || "综合分" }} {{ row.score ?? "-" }}</div>
              </td>
              <td>{{ row.relay_rank || row.watch_rank || row.daily_rank || "-" }}</td>
              <td>{{ rowPlacementText(row) }}</td>
              <td class="bt-left-cell">{{ row.main_line || "-" }}</td>
              <td>
                <span class="bt-pill" :class="openStatusClass(row.signal_status)">{{ decisionLabel(row.signal_status, row.decision_status, row.signal_label) }}</span>
              </td>
              <td>{{ formatPlain(rowOpenPrice(row), 2) }}元</td>
              <td :class="signedClass(row.gap_pct)">{{ formatSigned(row.gap_pct, 2) }}%</td>
              <td>{{ formatPlain(row.close_price, 2) }}元</td>
              <td :class="signedClass(row.close_pct)">{{ formatSigned(row.close_pct, 2) }}%</td>
              <td :class="snapshotReturnClass(row)">{{ snapshotReturnText(row) }}</td>
              <td class="bt-cond-cell">
                <div class="bt-cell-sub">{{ row.note || "-" }}</div>
                <div class="bt-cell-sub">{{ rowExplainText(row) }}</div>
              </td>
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
          <div class="card-title">账户净值走势</div>
          <p class="bt-subtitle">这里按历史回测中"符合买入条件"的个股做等权平均，默认满仓分配；如果某天有 4 只票，就按单只 25% 仓位折算成当天账户收益。</p>
          <p class="bt-subtitle">注：不考虑如何卖出，只考虑买入。</p>
        </div>
      </div>

      <div class="summary-box" v-if="!accountCurvePoints.length">
        <div class="summary-text">当前还没有可用于回放账户曲线的历史买入样本。只要历史回测里累计出可买入且已覆盖收益的个股，这里就会自动生成净值折线图。</div>
      </div>

      <template v-else>
        <div class="bt-kpi-grid bt-account-kpis">
          <div class="bt-kpi-card">
            <div class="bt-kpi-label">最新净值</div>
            <div class="bt-kpi-value">{{ formatPlain(accountCurveSummary.latestValue, 4) }}</div>
            <div class="bt-kpi-note">最新记录日期 {{ accountCurveUpdatedAt }}</div>
          </div>
          <div class="bt-kpi-card">
            <div class="bt-kpi-label">累计收益</div>
            <div class="bt-kpi-value" :class="signedClass(accountCurveSummary.totalReturnPct)">{{ formatSigned(accountCurveSummary.totalReturnPct, 2) }}%</div>
            <div class="bt-kpi-note">初始基准 {{ formatPlain(accountCurveSummary.base, 2) }}</div>
          </div>
          <div class="bt-kpi-card">
            <div class="bt-kpi-label">回放天数</div>
            <div class="bt-kpi-value">{{ accountCurveSummary.tradeDays }}</div>
            <div class="bt-kpi-note">按有买入样本的交易日统计</div>
          </div>
          <div class="bt-kpi-card">
            <div class="bt-kpi-label">最大回撤</div>
            <div class="bt-kpi-value green-text">{{ formatSigned(accountCurveSummary.maxDrawdownPct, 2) }}%</div>
            <div class="bt-kpi-note">按历史净值高点回撤计算</div>
          </div>
          <div class="bt-kpi-card">
            <div class="bt-kpi-label">单日波动</div>
            <div class="bt-kpi-value">
              <span class="red-text">{{ formatSigned(accountCurveSummary.bestDailyPct, 2) }}%</span>
              /
              <span class="green-text">{{ formatSigned(accountCurveSummary.worstDailyPct, 2) }}%</span>
            </div>
            <div class="bt-kpi-note">最好 / 最差单日等权收益</div>
          </div>
        </div>

        <div ref="accountCurveChartRef" class="bt-account-chart" aria-label="账户净值折线图"></div>
      </template>
    </div>
    </template>

    <ShortReminderFooter />
  </div>
</template>

<style scoped src="./BacktestPage.css"></style>
