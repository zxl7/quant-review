<script setup lang="ts">
import { computed } from "vue"
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
  currentPoolRecords: [],
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
  if (!raw.realtimeBuy || typeof raw.realtimeBuy !== "object") return false
  if (!Array.isArray(raw.currentPoolRecords)) return false
  if (!Array.isArray(raw.records)) return false
  return true
}

const payload = computed<any>(() => {
  const raw = backtestSource.value?.stockResearchBacktest
  return isCompleteBacktestPayload(raw) ? raw : emptyPayload
})

const meta = computed(() => payload.value?.meta || emptyPayload.meta)
const summary = computed(() => payload.value?.summary || emptyPayload.summary)
const assumptions = computed<string[]>(() => (Array.isArray(payload.value?.assumptions) ? payload.value.assumptions : []))
const mainlineBreakdown = computed<any[]>(() => (Array.isArray(payload.value?.breakdowns?.by_mainline) ? payload.value.breakdowns.by_mainline.slice(0, 8) : []))
const statusBreakdown = computed<any[]>(() => (Array.isArray(payload.value?.breakdowns?.by_open_status) ? payload.value.breakdowns.by_open_status : []))
const missingPriceCodes = computed<string[]>(() => (Array.isArray(summary.value?.missing_price_codes) ? summary.value.missing_price_codes : []))

const realtimeBuy = computed<any>(() => {
  const raw = payload.value?.realtimeBuy
  return raw && typeof raw === "object" ? raw : emptyPayload.realtimeBuy
})
const hasValidPayload = computed(() => isCompleteBacktestPayload(backtestSource.value?.stockResearchBacktest))
const activeTradeDate = computed(() => String(meta.value?.active_trade_date || realtimeBuy.value?.trade_date || "").trim())
const realtimeTitleDate = computed(() => String(activeTradeDate.value || realtimeBuy.value?.reference_date || latestRecommendationDate.value || "").trim())
const realtimeCardTitle = computed(() => (realtimeTitleDate.value ? `竞价结果 — ${realtimeTitleDate.value} 9:25` : "竞价结果"))
const backtestUpdatedAt = computed(() => meta.value?.generated_at_bj || backtestSource.value?.meta?.generatedAt || (marketData.value as any)?.meta?.generatedAt || "-")
const quoteUpdatedAt = computed(() => realtimeBuy.value?.quote_time || "-")
const allCandidates = computed<any[]>(() => {
  const buy = Array.isArray(realtimeBuy.value?.buy_list) ? realtimeBuy.value.buy_list : []
  const rejected = Array.isArray(realtimeBuy.value?.rejected_list) ? realtimeBuy.value.rejected_list : []
  const pending = Array.isArray(realtimeBuy.value?.pending_list) ? realtimeBuy.value.pending_list : []
  const unavailable = Array.isArray(realtimeBuy.value?.unavailable_list) ? realtimeBuy.value.unavailable_list : []
  const all = [...buy, ...pending, ...rejected, ...unavailable]
  const rank: Record<string, number> = { super: 0, expected: 1, pending: 2, reject: 3, unavailable: 4 }
  all.sort((a, b) => {
    const ra = rank[String(a?.signal_status || "")] ?? 9
    const rb = rank[String(b?.signal_status || "")] ?? 9
    if (ra !== rb) return ra - rb
    return (b?.score ?? 0) - (a?.score ?? 0)
  })
  return all
})

const metrics = computed(() => {
  const data = payload.value?.metrics || {}
  return [
    { key: "next_day", label: "隔日收益", data: data.next_day || {} },
    { key: "hold_3d", label: "3日收益", data: data.hold_3d || {} },
    { key: "hold_5d", label: "5日收益", data: data.hold_5d || {} },
  ]
})

const currentPoolRecords = computed<any[]>(() => {
  const rows = Array.isArray(payload.value?.currentPoolRecords) ? [...payload.value.currentPoolRecords] : []
  rows.sort((a, b) => {
    const scoreDiff = toNum(b?.score, 0) - toNum(a?.score, 0)
    if (scoreDiff) return scoreDiff
    return String(a?.code || "").localeCompare(String(b?.code || ""))
  })
  return rows
})

const records = computed<any[]>(() => {
  const rows = Array.isArray(payload.value?.records) ? [...payload.value.records] : []
  rows.sort((a, b) => {
    const dateDiff = String(b?.date10 || "").localeCompare(String(a?.date10 || ""))
    if (dateDiff) return dateDiff
    const scoreDiff = toNum(b?.score, 0) - toNum(a?.score, 0)
    if (scoreDiff) return scoreDiff
    return String(a?.code || "").localeCompare(String(b?.code || ""))
  })
  return rows
})
const latestRecommendationDate = computed(() => String(meta.value?.latest_recommendation_date || realtimeBuy.value?.reference_date || "").trim())
const currentRecords = computed<any[]>(() => currentPoolRecords.value)
const currentEligibleCount = computed(() => currentRecords.value.filter((row) => !!row?.performance?.open_check?.can_enter).length)
const historicalRecords = computed<any[]>(() => records.value)
const hasCurrentPlan = computed(() => hasValidPayload.value && currentRecords.value.length > 0)
const hasHistoricalRecords = computed(() => historicalRecords.value.length > 0)
const hasRealtimeSnapshot = computed(() => {
  if (!hasValidPayload.value) return false
  if (!realtimeBuy.value?.reference_date) return false
  if (!isEntryWindowTime(realtimeBuy.value?.quote_time)) return false
  return allCandidates.value.length > 0
})
const hasAnyRenderableSection = computed(() => hasCurrentPlan.value || hasHistoricalRecords.value || hasRealtimeSnapshot.value)
const currentPlanTitleDate = computed(() => String(activeTradeDate.value || latestRecommendationDate.value || "").trim())
const currentPlanCardTitle = computed(() => (currentPlanTitleDate.value ? `待验证池 — ${currentPlanTitleDate.value}` : "待验证池"))
const emptyStateText = computed(() => {
  if (!hasValidPayload.value) return "当前暂无有效回测数据，明天 09:25-09:30 落地后会自动显示对应内容。"
  if (hasCurrentPlan.value) return "收盘后推送的个股研究样本已经落进回测 JSON，当前先展示明天待验证池；到明天 09:25-09:30 再补真实竞价命中结果。"
  if (!realtimeBuy.value?.reference_date) return "当前推荐还没到次日 09:25-09:30，明天窗口内会落地实时行情。"
  if (!isEntryWindowTime(realtimeBuy.value?.quote_time)) return "当前暂无有效竞价快照，等明天 09:25-09:30 落地后再显示命中结果。"
  return "当前没有可展示的回测结果。"
})
const realtimeEmptyText = computed(() => {
  if (!hasValidPayload.value) return "当前暂无有效回测数据。"
  if (!hasCurrentPlan.value) return "当前还没有待验证池数据，先执行一次复盘脚本生成个股回测 JSON。"
  if (!realtimeBuy.value?.reference_date) return "当前是收盘后待验证阶段，明天 09:25-09:30 会补充实时量价和命中结果。"
  if (!isEntryWindowTime(realtimeBuy.value?.quote_time)) return "当前还没到有效竞价快照时间，明天 09:25-09:30 会自动显示真实命中结果。"
  return "当前没有命中结果。"
})

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

function openStatusLabel(status?: string, label?: string) {
  if (label) return label
  const key = String(status || "")
  if (key === "super") return "超预期"
  if (key === "expected") return "符合预期"
  if (key === "pending") return "待确认"
  if (key === "wait_reseal") return "待确认"
  if (key === "reject") return "低预期"
  return "暂无判断"
}

function decisionLabel(signalStatus?: string, decisionStatus?: string, fallbackLabel?: string) {
  const s = String(signalStatus || "")
  const d = String(decisionStatus || "")
  if (s === "super") return "买入"
  if (s === "expected") return "观察"
  if (s === "reject") return "低预期"
  if (d === "pending") return "待盘中确认"
  if (d === "unavailable") return "报价缺失"
  if (fallbackLabel) return fallbackLabel
  return "待判断"
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
  if (status === "covered") return `${item?.entry_date || "-"} 开盘买入 -> ${item?.exit_date || "-"} 收盘卖出`
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
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">{{ realtimeCardTitle }}</div>
          <div class="bt-subtitle">超预期 = 买入，符合预期 = 观察，低预期 = 不入场。</div>
        </div>
      </div>

      <div class="summary-box" v-if="!hasRealtimeSnapshot">
        <div class="summary-text">{{ realtimeEmptyText }}</div>
      </div>

      <div class="bt-table-wrap" v-else>
        <table class="ladder-table">
          <thead>
            <tr>
              <th>标的</th>
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
    </div>

    <div class="card" v-if="hasCurrentPlan">
      <div class="card-header">
        <div>
          <div class="card-title">{{ currentPlanCardTitle }}</div>
          <div class="bt-subtitle">这里展示收盘后由个股研究推送进回测 JSON 的样本，以及明天 09:25 需要命中的标准。</div>
        </div>
      </div>

      <div class="bt-table-wrap bt-table-wrap-plan">
        <table class="ladder-table bt-plan-table">
          <thead>
            <tr>
              <th>推荐日</th>
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
              <td>{{ row.date10 || "-" }}</td>
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
          <div class="bt-subtitle">收益口径：次日开盘买入，分别统计 T+1 / T+3 / T+5 收盘卖出；不含手续费、滑点和一字板无法成交约束。</div>
        </div>
      </div>

      <div class="bt-metrics-grid">
        <div class="bt-metric-card" v-for="item in metrics" :key="item.key">
          <div class="section-header">{{ item.label }}</div>
          <div class="bt-metric-rows" style="border:none">
            <div class="bt-metric-row">
              <div>
                <div class="bt-metric-k">覆盖样本</div>
                <div class="bt-metric-note">可执行 {{ item.data?.eligible ?? 0 }} 笔，已覆盖 {{ item.data?.covered ?? 0 }} 笔</div>
              </div>
              <div class="bt-metric-v">{{ item.data?.coverage ?? 0 }}%</div>
            </div>
            <div class="bt-metric-row">
              <div>
                <div class="bt-metric-k">胜率</div>
                <div class="bt-metric-note">上涨 {{ item.data?.win_count ?? 0 }} ｜ 平 {{ item.data?.flat_count ?? 0 }} ｜ 下跌 {{ item.data?.loss_count ?? 0 }}</div>
              </div>
              <div class="bt-metric-v">{{ item.data?.win_rate ?? 0 }}%</div>
            </div>
            <div class="bt-metric-row">
              <div>
                <div class="bt-metric-k">平均收益</div>
                <div class="bt-metric-note">平均盈利 {{ item.data?.avg_win_return ?? 0 }}% ｜ 平均回撤 {{ item.data?.avg_loss_return ?? 0 }}%</div>
              </div>
              <div class="bt-metric-v" :class="signedClass(item.data?.avg_return)">{{ formatSigned(item.data?.avg_return, 2) }}%</div>
            </div>
          </div>

          <div class="bt-split-row" style="border:none;background:none;padding:0">
            <div style="font-size:11px;color:var(--text-muted);padding:4px 8px">
              均值 <span class="red-text">{{ formatSigned(item.data?.by_open_status?.super?.avg_return, 2) }}%</span> ｜ 胜率 {{ item.data?.by_open_status?.super?.win_rate ?? 0 }}%
            </div>
          </div>
        </div>
      </div>
    </div>


    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">历史样本明细</div>
          <div class="bt-subtitle">这里保留跨多个推荐日的完整回测样本，方便回看"推荐理由 -> 开盘判断 -> 收益表现"的历史链路。</div>
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
              <th>标的</th>
              <th>池子</th>
              <th>主线</th>
              <th>开盘判断</th>
              <th>涨幅</th>
              <th>T+1</th>
              <th>T+3</th>
              <th>T+5</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in historicalRecords" :key="'record-' + row.date10 + '-' + row.code">
              <td>{{ row.date10 || "-" }}</td>
              <td class="bt-name-cell">
                <div class="bt-name-line">
                  <a v-if="row.code" class="stock-link" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
                  <span v-else>{{ row.name || "-" }}</span>
                </div>
                <div class="bt-name-sub">{{ row.code || "-" }} ｜ {{ row.score ?? "-" }} ｜ {{ row.score_sub_label || row.style_tag || row.bucket_label || "-" }}</div>
              </td>
              <td>{{ row.bucket_label || row.bucket || "-" }}</td>
              <td class="bt-left-cell">
                <div>{{ row.main_line || "-" }}</div>
                <div class="bt-cell-sub">{{ row.hy || row.plate_name || "-" }}</div>
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
              <td :class="strategyReturnClass(row.performance, 'hold_3d')">
                {{ strategyReturnText(row.performance, "hold_3d") }}
                <div class="bt-cell-sub">{{ strategyReturnNote(row.performance, "hold_3d") }}</div>
              </td>
              <td :class="strategyReturnClass(row.performance, 'hold_5d')">
                {{ strategyReturnText(row.performance, "hold_5d") }}
                <div class="bt-cell-sub">{{ strategyReturnNote(row.performance, "hold_5d") }}</div>
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
