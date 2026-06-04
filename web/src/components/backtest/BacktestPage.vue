<script setup lang="ts">
import { computed } from "vue"
import { useMarketData } from "../../composables/useMarketData"

const { marketData } = useMarketData()
const backtestSource = computed<any>(() => {
  const md = marketData.value as any
  return md || {}
})

const emptyPayload = {
  meta: {
    title: "个股回测",
    subtitle: "",
    entry_window: "09:25-09:30",
    source_module: "ztAnalysis.relay/watch",
    generated_at_bj: "",
    generated_from: [],
    latest_recommendation_date: "",
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
  spotlight: {},
  diagnostics: {},
  realtimeBuy: {
    reference_date: "",
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

const payload = computed<any>(() => {
  const raw = backtestSource.value?.stockResearchBacktest
  return raw && typeof raw === "object" ? raw : emptyPayload
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
const backtestUpdatedAt = computed(() => meta.value?.generated_at_bj || backtestSource.value?.meta?.generatedAt || (marketData.value as any)?.meta?.generatedAt || "-")
const quoteUpdatedAt = computed(() => realtimeBuy.value?.quote_time || "-")
const realtimeBuyList = computed<any[]>(() => (Array.isArray(realtimeBuy.value?.buy_list) ? realtimeBuy.value.buy_list : []))
const realtimePendingList = computed<any[]>(() => (Array.isArray(realtimeBuy.value?.pending_list) ? realtimeBuy.value.pending_list : []))
const realtimeUnavailableList = computed<any[]>(() => (Array.isArray(realtimeBuy.value?.unavailable_list) ? realtimeBuy.value.unavailable_list : []))

const metrics = computed(() => {
  const data = payload.value?.metrics || {}
  return [
    { key: "next_day", label: "隔日收益", data: data.next_day || {} },
    { key: "hold_3d", label: "3日收益", data: data.hold_3d || {} },
    { key: "hold_5d", label: "5日收益", data: data.hold_5d || {} },
  ]
})

const spotlight = computed(() => {
  const data = payload.value?.spotlight || {}
  return {
    best: Array.isArray(data.best_t3_trades) ? data.best_t3_trades : [],
    worst: Array.isArray(data.worst_t3_trades) ? data.worst_t3_trades : [],
  }
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
  if (key === "super") return "超预期开盘"
  if (key === "expected") return "符合预期"
  if (key === "pending") return "待盘中确认"
  if (key === "wait_reseal") return "待回封确认"
  if (key === "reject") return "低预期/未确认"
  return "暂无判断"
}

function decisionLabel(status?: string, label?: string) {
  if (label) return label
  const key = String(status || "")
  if (key === "buy") return "直接买入"
  if (key === "pending") return "待盘中确认"
  if (key === "reject") return "未达买点"
  if (key === "unavailable") return "报价缺失"
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
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">{{ meta.title || "个股回测" }}</div>
          <div class="bt-subtitle">
            {{ meta.subtitle || "同源读取个股研究推荐。当前研究池只看最新推荐日，历史样本单独用于回测统计。" }}
          </div>
          <div class="bt-meta">
            <div>回测生成时间 {{ backtestUpdatedAt }}</div>
            <div>9:25 报价时间 {{ quoteUpdatedAt }}</div>
            <div>当前研究池 {{ latestRecommendationDate || "-" }}</div>
          </div>
        </div>
        <div class="bt-badge">{{ realtimeBuy.entry_window || meta.entry_window || "09:25-09:30" }}</div>
      </div>
      <div class="bt-kpi-grid">
        <div class="bt-kpi-card">
          <div class="bt-kpi-label">今日候选</div>
          <div class="bt-kpi-value">{{ realtimeBuy.candidate_count ?? 0 }}</div>
          <div class="bt-kpi-note">推荐日 {{ realtimeBuy.reference_date || "-" }}</div>
        </div>
        <div class="bt-kpi-card">
          <div class="bt-kpi-label">9:25 买入</div>
          <div class="bt-kpi-value red-text">{{ realtimeBuy.buy_count ?? 0 }}</div>
          <div class="bt-kpi-note">超预期 {{ realtimeBuy.direct_super_count ?? 0 }} ｜ 符合预期 {{ realtimeBuy.direct_expected_count ?? 0 }}</div>
        </div>
        <div class="bt-kpi-card">
          <div class="bt-kpi-label">待盘中确认</div>
          <div class="bt-kpi-value blue-text">{{ realtimeBuy.pending_count ?? 0 }}</div>
          <div class="bt-kpi-note">回封 / 封单 / 开板条件未在 9:25 直接确认</div>
        </div>
        <div class="bt-kpi-card">
          <div class="bt-kpi-label">报价覆盖</div>
          <div class="bt-kpi-value">{{ realtimeBuy.quoted_count ?? 0 }}/{{ realtimeBuy.candidate_count ?? 0 }}</div>
          <div class="bt-kpi-note">更新时间 {{ realtimeBuy.quote_time || "-" }}</div>
        </div>
        <div class="bt-kpi-card">
          <div class="bt-kpi-label">当前研究池</div>
          <div class="bt-kpi-value">{{ currentRecords.length }}</div>
          <div class="bt-kpi-note">和个股研究同源，推荐日 {{ latestRecommendationDate || "-" }}</div>
        </div>
        <div class="bt-kpi-card">
          <div class="bt-kpi-label">当前可执行</div>
          <div class="bt-kpi-value">{{ currentEligibleCount }}</div>
          <div class="bt-kpi-note">当前研究池里开盘可直接执行的样本</div>
        </div>
      </div>

      <div class="bt-pill-row" v-if="mainlineBreakdown.length">
        <span v-for="item in mainlineBreakdown" :key="'ml-' + item.name" class="bt-pill is-neutral">
          {{ item.name }} {{ item.count ?? 0 }}
        </span>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">9:25 买入列表</div>
          <div class="bt-subtitle">只有在开盘竞价价格和量能已经满足条件时，才会直接进入这张清单。</div>
        </div>
      </div>

      <div class="summary-box" v-if="!realtimeBuyList.length">
        <div class="summary-text">当前没有直接买入标的。可能是今天没有符合预期/超预期的开口，也可能是远端报价尚未返回。</div>
      </div>

      <div class="bt-live-grid" v-else>
        <div class="bt-live-card" v-for="row in realtimeBuyList" :key="'buy-' + row.code">
          <div class="bt-live-head">
            <div class="bt-live-main">
              <a class="stock-link" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
              <div class="bt-name-sub">代码 {{ row.code || "-" }} ｜ {{ row.bucket_label || row.bucket || "-" }} ｜ 分数 {{ row.score ?? "-" }}</div>
            </div>
            <div class="bt-live-badges">
              <span class="bt-pill" :class="openStatusClass(row.signal_status)">{{ openStatusLabel(row.signal_status, row.signal_label) }}</span>
              <span class="bt-pill is-neutral">{{ decisionLabel(row.decision_status, row.decision_label) }}</span>
            </div>
          </div>
          <div class="bt-live-stats">
            <div class="bt-live-stat">
              <span>竞价价</span>
              <strong>{{ formatPlain(row.auction_price, 2) }}</strong>
            </div>
            <div class="bt-live-stat">
              <span>缺口</span>
              <strong :class="signedClass(row.gap_pct)">{{ formatSigned(row.gap_pct, 2) }}%</strong>
            </div>
            <div class="bt-live-stat">
              <span>竞价成交额</span>
              <strong>{{ formatPlain(row.auction_amount_yi, 2) }}亿</strong>
            </div>
            <div class="bt-live-stat">
              <span>量能阈值</span>
              <strong>{{ formatPlain(row.auction_amount_need_yi, 2) }}亿</strong>
            </div>
          </div>
          <div class="bt-live-rule">{{ row.rule_text || row.expected_text || row.super_text || "-" }}</div>
          <div class="bt-cell-sub">{{ row.note || "-" }}</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">当前研究池</div>
          <div class="bt-subtitle">这一段只展示最新推荐日的样本，和“个股研究”页读取的是同一份 `ztAnalysis.relay/watch`。</div>
        </div>
      </div>

      <div class="summary-box" v-if="!currentRecords.length">
        <div class="summary-text">当前研究池还没有可展示的同源样本。</div>
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
              <th>缺口</th>
              <th>T+1</th>
              <th>T+3</th>
              <th>T+5</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in currentRecords" :key="'current-record-' + row.date10 + '-' + row.code">
              <td>{{ row.date10 || "-" }}</td>
              <td class="bt-name-cell">
                <div class="bt-name-line">
                  <a v-if="row.code" class="stock-link" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
                  <span v-else>{{ row.name || "-" }}</span>
                </div>
                <div class="bt-name-sub">代码 {{ row.code || "-" }} ｜ 分数 {{ row.score ?? "-" }} ｜ {{ row.score_sub_label || row.style_tag || row.bucket_label || "-" }}</div>
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

    <div class="bt-live-split">
      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">待盘中确认</div>
            <div class="bt-subtitle">这类标的竞价价格和量能可能已接近买点，但还需要盘中回封、封单或开板限制确认。</div>
          </div>
        </div>
        <div class="summary-box" v-if="!realtimePendingList.length">
          <div class="summary-text">当前没有待盘中确认的标的。</div>
        </div>
        <div class="bt-mini-list" v-else>
          <div class="bt-mini-item" v-for="row in realtimePendingList" :key="'pending-' + row.code">
            <div class="bt-mini-head">
              <a class="stock-link" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
              <span class="bt-pill is-wait">{{ decisionLabel(row.decision_status, row.decision_label) }}</span>
            </div>
            <div class="bt-cell-sub">
              {{ formatSigned(row.gap_pct, 2) }}% ｜ {{ formatPlain(row.auction_amount_yi, 2) }}亿
              <span v-if="Array.isArray(row.pending_reasons) && row.pending_reasons.length"> ｜ {{ row.pending_reasons.join(" / ") }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">报价缺失 / 待补齐</div>
            <div class="bt-subtitle">如果实时接口没有返回，先留在这里，不会误放进买入列表。</div>
          </div>
        </div>
        <div class="summary-box" v-if="!realtimeUnavailableList.length">
          <div class="summary-text">当前报价覆盖完整，没有缺失标的。</div>
        </div>
        <div class="bt-mini-list" v-else>
          <div class="bt-mini-item" v-for="row in realtimeUnavailableList" :key="'na-' + row.code">
            <div class="bt-mini-head">
              <a class="stock-link" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
              <span class="bt-pill is-neutral">{{ decisionLabel(row.decision_status, row.decision_label) }}</span>
            </div>
            <div class="bt-cell-sub">{{ row.note || "-" }}</div>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">历史回测概览</div>
          <div class="bt-subtitle">这一段是跨多个推荐交易日的历史统计，用来复盘“这套预期文案长期好不好用”。</div>
        </div>
      </div>

      <div class="bt-pill-row" v-if="statusBreakdown.length">
        <span v-for="item in statusBreakdown" :key="'status-' + item.name" class="bt-pill" :class="openStatusClass(item.name)">
          {{ openStatusLabel(item.name) }} {{ item.count ?? 0 }}
        </span>
      </div>

      <div class="bt-kpi-grid">
        <div class="bt-kpi-card">
          <div class="bt-kpi-label">历史总样本</div>
          <div class="bt-kpi-value">{{ summary.total_samples ?? 0 }}</div>
          <div class="bt-kpi-note">源样本 {{ summary.source_samples ?? summary.total_samples ?? 0 }} ｜ 清洗掉 {{ summary.filtered_non_backtest_samples ?? 0 }}</div>
        </div>
        <div class="bt-kpi-card">
          <div class="bt-kpi-label">历史可执行样本</div>
          <div class="bt-kpi-value">{{ summary.eligible_samples ?? 0 }}</div>
          <div class="bt-kpi-note">开盘入场率 {{ entryRate }}%</div>
        </div>
        <div class="bt-kpi-card">
          <div class="bt-kpi-label">超预期开盘</div>
          <div class="bt-kpi-value red-text">{{ summary.super_count ?? 0 }}</div>
          <div class="bt-kpi-note">强确认开口，单独观察收益质量</div>
        </div>
        <div class="bt-kpi-card">
          <div class="bt-kpi-label">符合预期开盘</div>
          <div class="bt-kpi-value orange-text">{{ summary.expected_count ?? 0 }}</div>
          <div class="bt-kpi-note">按预案正常开口的入场样本</div>
        </div>
        <div class="bt-kpi-card">
          <div class="bt-kpi-label">待回封确认</div>
          <div class="bt-kpi-value blue-text">{{ summary.wait_reseal_count ?? 0 }}</div>
          <div class="bt-kpi-note">超预期但需要盘中行为确认</div>
        </div>
        <div class="bt-kpi-card">
          <div class="bt-kpi-label">价格覆盖</div>
          <div class="bt-kpi-value">{{ summary.priced_codes ?? 0 }}/{{ summary.unique_codes ?? 0 }}</div>
          <div class="bt-kpi-note">缺失价格 {{ missingPriceCodes.length }} 只</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">策略表现</div>
          <div class="bt-subtitle">收益口径：次日开盘买入，分别统计 T+1 / T+3 / T+5 收盘卖出；不含手续费、滑点和一字板无法成交约束。</div>
        </div>
      </div>

      <div class="bt-metrics-grid">
        <div class="bt-metric-card" v-for="item in metrics" :key="item.key">
          <div class="section-header">{{ item.label }}</div>
          <div class="bt-metric-rows">
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

          <div class="bt-split-row">
            <div class="bt-split-box">
              <div class="bt-split-label red-text">超预期</div>
              <div class="bt-split-value">{{ item.data?.by_open_status?.super?.covered ?? 0 }} 笔</div>
              <div class="bt-split-note">均值 {{ formatSigned(item.data?.by_open_status?.super?.avg_return, 2) }}% ｜ 胜率 {{ item.data?.by_open_status?.super?.win_rate ?? 0 }}%</div>
            </div>
            <div class="bt-split-box">
              <div class="bt-split-label orange-text">符合预期</div>
              <div class="bt-split-value">{{ item.data?.by_open_status?.expected?.covered ?? 0 }} 笔</div>
              <div class="bt-split-note">均值 {{ formatSigned(item.data?.by_open_status?.expected?.avg_return, 2) }}% ｜ 胜率 {{ item.data?.by_open_status?.expected?.win_rate ?? 0 }}%</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="card" v-if="spotlight.best.length || spotlight.worst.length">
      <div class="card-header">
        <div>
          <div class="card-title">T+3 复盘聚焦</div>
          <div class="bt-subtitle">优先看最强兑现和最差反馈，帮助校正第二天开盘入场后的风险收益预期。</div>
        </div>
      </div>

      <div class="bt-spotlight-grid">
        <div class="bt-spotlight-card">
          <div class="section-header">T+3 最强样本</div>
          <div class="bt-spotlight-list">
            <div class="bt-spotlight-item" v-for="row in spotlight.best" :key="'best-' + row.date + '-' + row.code">
              <div class="bt-spotlight-main">
                <a class="stock-link" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
                <span class="bt-spotlight-sub">{{ row.date }} ｜ {{ row.bucket === "relay" ? "接力候选" : "观察池" }}</span>
              </div>
              <div class="bt-spotlight-v red-text">{{ formatSigned(row.return_pct, 2) }}%</div>
            </div>
          </div>
        </div>
        <div class="bt-spotlight-card">
          <div class="section-header">T+3 最差样本</div>
          <div class="bt-spotlight-list">
            <div class="bt-spotlight-item" v-for="row in spotlight.worst" :key="'worst-' + row.date + '-' + row.code">
              <div class="bt-spotlight-main">
                <a class="stock-link" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
                <span class="bt-spotlight-sub">{{ row.date }} ｜ {{ row.bucket === "relay" ? "接力候选" : "观察池" }}</span>
              </div>
              <div class="bt-spotlight-v green-text">{{ formatSigned(row.return_pct, 2) }}%</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">历史样本明细</div>
          <div class="bt-subtitle">这里保留跨多个推荐日的完整回测样本，方便回看“推荐理由 -> 开盘判断 -> 收益表现”的历史链路。</div>
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
              <th>缺口</th>
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
                <div class="bt-name-sub">代码 {{ row.code || "-" }} ｜ 分数 {{ row.score ?? "-" }} ｜ {{ row.score_sub_label || row.style_tag || row.bucket_label || "-" }}</div>
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

    <div class="card" v-if="assumptions.length">
      <div class="card-header">
        <div>
          <div class="card-title">回测口径说明</div>
          <div class="bt-subtitle">当前保持和“个股研究”同源，同时对无法复刻的竞价与回封细节做保守处理。</div>
        </div>
      </div>
      <ul class="bt-assumptions">
        <li v-for="(item, idx) in assumptions" :key="'assumption-' + idx">{{ item }}</li>
      </ul>
    </div>
  </div>
</template>

<style scoped src="./BacktestPage.css"></style>
