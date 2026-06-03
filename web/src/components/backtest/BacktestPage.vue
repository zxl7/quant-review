<script setup lang="ts">
import { computed } from "vue"
import { useMarketData } from "../../composables/useMarketData"

const { marketData } = useMarketData()

const emptyPayload = {
  meta: {
    title: "个股回测",
    subtitle: "",
    entry_window: "09:25-09:30",
    source_module: "ztAnalysis.relay/watch",
    generated_at_bj: "",
    generated_from: [],
  },
  summary: {
    total_samples: 0,
    eligible_samples: 0,
    expected_count: 0,
    super_count: 0,
    wait_reseal_count: 0,
    rejected_count: 0,
    unique_codes: 0,
    trade_days: 0,
    priced_codes: 0,
    missing_price_codes: [],
  },
  assumptions: [],
  breakdowns: {
    by_mainline: [],
    by_open_status: [],
  },
  metrics: {},
  records: [],
  spotlight: {},
  diagnostics: {},
}

const payload = computed<any>(() => {
  const raw = (marketData.value as any)?.stockResearchBacktest
  return raw && typeof raw === "object" ? raw : emptyPayload
})

const meta = computed(() => payload.value?.meta || emptyPayload.meta)
const summary = computed(() => payload.value?.summary || emptyPayload.summary)
const assumptions = computed<string[]>(() => (Array.isArray(payload.value?.assumptions) ? payload.value.assumptions : []))
const mainlineBreakdown = computed<any[]>(() => (Array.isArray(payload.value?.breakdowns?.by_mainline) ? payload.value.breakdowns.by_mainline.slice(0, 8) : []))
const statusBreakdown = computed<any[]>(() => (Array.isArray(payload.value?.breakdowns?.by_open_status) ? payload.value.breakdowns.by_open_status : []))
const sourceFiles = computed<string[]>(() => (Array.isArray(meta.value?.generated_from) ? meta.value.generated_from : []))
const missingPriceCodes = computed<string[]>(() => (Array.isArray(summary.value?.missing_price_codes) ? summary.value.missing_price_codes : []))

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
  if (key === "wait_reseal") return "is-wait"
  if (key === "reject") return "is-reject"
  return "is-neutral"
}

function openStatusLabel(status?: string, label?: string) {
  if (label) return label
  const key = String(status || "")
  if (key === "super") return "超预期开盘"
  if (key === "expected") return "符合预期"
  if (key === "wait_reseal") return "待回封确认"
  if (key === "reject") return "低预期/未确认"
  return "暂无判断"
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
            {{ meta.subtitle || "同源读取个股研究推荐，只在次日 09:25-09:30 满足符合预期或超预期开口径时，按开盘价记为入场。" }}
          </div>
        </div>
        <div class="bt-badge">{{ meta.entry_window || "09:25-09:30" }}</div>
      </div>

      <div class="summary-box">
        <div class="summary-text">
          这里只统计次日开盘窗口能直接执行的样本。若推荐文案要求
          <span class="red-text">“超预期但需回封确认”</span>，
          当前会保守记为
          <span class="blue-text">wait_reseal</span>，
          不在开盘 9:25-9:30 直接算买入。
        </div>
      </div>

      <div class="bt-kpi-grid">
        <div class="bt-kpi-card">
          <div class="bt-kpi-label">总样本</div>
          <div class="bt-kpi-value">{{ summary.total_samples ?? 0 }}</div>
          <div class="bt-kpi-note">覆盖 {{ summary.trade_days ?? 0 }} 个推荐交易日</div>
        </div>
        <div class="bt-kpi-card">
          <div class="bt-kpi-label">可执行样本</div>
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
          <div class="bt-kpi-label">已覆盖标的</div>
          <div class="bt-kpi-value">{{ summary.priced_codes ?? 0 }}/{{ summary.unique_codes ?? 0 }}</div>
          <div class="bt-kpi-note">缺失价格 {{ missingPriceCodes.length }} 只</div>
        </div>
      </div>

      <div class="bt-pill-row" v-if="statusBreakdown.length">
        <span v-for="item in statusBreakdown" :key="'status-' + item.name" class="bt-pill" :class="openStatusClass(item.name)">
          {{ openStatusLabel(item.name) }} {{ item.count ?? 0 }}
        </span>
      </div>

      <div class="bt-pill-row" v-if="mainlineBreakdown.length">
        <span v-for="item in mainlineBreakdown" :key="'ml-' + item.name" class="bt-pill is-neutral">
          {{ item.name }} {{ item.count ?? 0 }}
        </span>
      </div>

      <div class="bt-meta" v-if="sourceFiles.length || missingPriceCodes.length">
        <div v-if="sourceFiles.length">样本来源文件：{{ sourceFiles.join("、") }}</div>
        <div v-if="missingPriceCodes.length">缺失价格代码：{{ missingPriceCodes.join("、") }}</div>
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
          <div class="card-title">逐笔复盘明细</div>
          <div class="bt-subtitle">按推荐日倒序展示，方便直接回看“推荐理由 -> 开盘判断 -> 收益表现”的完整链路。</div>
        </div>
      </div>

      <div class="summary-box" v-if="!records.length">
        <div class="summary-text">当前还没有回测明细。只要 `marketData.stockResearchBacktest` 注入完成，这里会自动展示系统内回测结果。</div>
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
            <tr v-for="row in records" :key="'record-' + row.date10 + '-' + row.code">
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
