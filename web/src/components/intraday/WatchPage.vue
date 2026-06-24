<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useMarketData } from "../../composables/useMarketData"
import { useIntradayAlertPool } from "../../composables/useIntradayAlertPool"
import { useIntradayRuntime } from "../../composables/useIntradayRuntime"
import ShortReminderFooter from "../common/ShortReminderFooter.vue"

const { marketData } = useMarketData()
const intradayAlertPool = useIntradayAlertPool()
const intradayRuntime = useIntradayRuntime()

const toNum = (v: unknown, d = 0) => {
  try {
    if (v === undefined || v === null || v === "") return d
    if (typeof v === "string") return Number(String(v).replace("%", "").replace("亿", "").trim()) || d
    const n = Number(v)
    return Number.isFinite(n) ? n : d
  } catch {
    return d
  }
}

const clamp100 = (v: unknown) => {
  const n = Number(v)
  if (!Number.isFinite(n)) return 0
  return Math.max(0, Math.min(100, n))
}

const lerpColor = (hexA: string, hexB: string, t: number) => {
  const toRgb = (hex: string) => {
    const h = String(hex || "")
      .replace("#", "")
      .trim()
    const s =
      h.length === 3
        ? h
            .split("")
            .map((x) => x + x)
            .join("")
        : h
    const n = parseInt(s || "000000", 16)
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  }
  const tt = Math.max(0, Math.min(1, Number(t)))
  const [r1, g1, b1] = toRgb(hexA)
  const [r2, g2, b2] = toRgb(hexB)
  const r = Math.round(r1 + (r2 - r1) * tt)
  const g = Math.round(g1 + (g2 - g1) * tt)
  const b = Math.round(b1 + (b2 - b1) * tt)
  return `rgb(${r},${g},${b})`
}

const heatColor = (v: unknown) => {
  const p = clamp100(v)
  if (p <= 45) return lerpColor("#f59e0b", "#ff4d4f", p / 45)
  return lerpColor("#ff4d4f", "#e60012", (p - 45) / 55)
}

const riskColor = (v: unknown) => {
  const p = clamp100(v)
  if (p <= 45) return lerpColor("#16a34a", "#00a63e", p / 45)
  if (p <= 75) return lerpColor("#00a63e", "#65a30d", (p - 45) / 30)
  return lerpColor("#65a30d", "#f59e0b", (p - 75) / 25)
}

const trendColorHtml = (text: string, sep: string, inverse = false) => {
  if (!text) return ""
  const parts = text
    .split(sep)
    .map((s) => s.trim())
    .filter(Boolean)
  if (parts.length < 2) return `<span class="trend-v">${text}</span>`
  const nums = parts.map((s) => parseFloat(s.replace(/[^0-9.\-]/g, "")))
  let html = ""
  for (let i = 0; i < parts.length; i++) {
    if (i > 0) html += `<span class="trend-sep">${sep}</span>`
    let cls = "trend-v flat"
    if (i > 0 && Number.isFinite(nums[i]) && Number.isFinite(nums[i - 1])) {
      const diff = nums[i] - nums[i - 1]
      const up = inverse ? diff < 0 : diff > 0
      const dn = inverse ? diff > 0 : diff < 0
      cls = `trend-v ${up ? "up" : dn ? "down" : "flat"}`
    }
    html += `<span class="${cls}">${parts[i]}</span>`
  }
  return html
}

const linePath = (series: unknown[], w = 860, h = 220, pad = 16) => {
  const vals = (Array.isArray(series) ? series : []).map((v) => Number(v)).filter((v) => Number.isFinite(v))
  if (!vals.length) return { line: "", area: "" }
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const span = max - min || 1
  const points = vals.map((v, i) => {
    const x = pad + (i / Math.max(vals.length - 1, 1)) * (w - pad * 2)
    const y = h - pad - ((v - min) / span) * (h - pad * 2)
    return { x, y }
  })
  const line = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(" ")
  const area = `${line} L ${points[points.length - 1].x.toFixed(2)} ${(h - pad).toFixed(2)} L ${points[0].x.toFixed(2)} ${(h - pad).toFixed(2)} Z`
  return { line, area }
}

const linePoints = (series: unknown[], w = 860, h = 220, pad = 16) => {
  const vals = (Array.isArray(series) ? series : []).map((v) => Number(v)).filter((v) => Number.isFinite(v))
  const n = vals.length
  if (!n) return []
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const span = max - min || 1
  const xStep = n > 1 ? (w - pad * 2) / (n - 1) : 0
  return vals.map((v, i) => ({
    x: +(pad + i * xStep).toFixed(2),
    y: +(h - pad - ((v - min) / span) * (h - pad * 2)).toFixed(2),
    value: v,
    index: i,
  }))
}

const seriesIsFlat = (series: unknown[], eps = 0.05) => {
  const vals = (Array.isArray(series) ? series : []).map((v) => Number(v)).filter((v) => Number.isFinite(v))
  if (vals.length <= 1) return true
  const first = vals[0]
  return vals.every((v) => Math.abs(v - first) <= eps)
}

const compressFlatSeries = (series: unknown[], eps = 0.05) => {
  const vals = (Array.isArray(series) ? series : []).map((v, index) => ({ value: Number(v), index })).filter((x) => Number.isFinite(x.value))
  if (vals.length <= 1) return vals
  const out: Array<{ value: number; index: number }> = []
  for (const item of vals) {
    const prev = out[out.length - 1]
    if (!prev || Math.abs(item.value - prev.value) > eps) out.push(item)
    else out[out.length - 1] = item
  }
  return out
}

const watchSnapshots = computed(() => intradayRuntime.snapshots.value || [])
const watchCurrentSnap = computed(() => {
  const rows = watchSnapshots.value
  return rows.length ? rows[rows.length - 1] : null
})
const watchPrevSnap = computed(() => {
  const rows = watchSnapshots.value
  return rows.length > 1 ? rows[rows.length - 2] : null
})

const watchCurrentShift = computed(() => {
  const curr = watchCurrentSnap.value || {}
  const label = curr.shift_label || curr.headline || "稳定"
  const tone = /走强|修复/.test(label) ? "bull" : /走弱|退潮/.test(label) ? "bear" : "mixed"
  return {
    score: curr.shift_score ?? "-",
    label,
    note: curr.note || "暂无情绪播报",
    tone,
  }
})

const watchMarket = computed(() => {
  const snap = watchCurrentSnap.value || {}
  const live = intradayRuntime.live.value?.market || marketData.value?.live?.market || {}
  const zt = snap.zt ?? live.zt ?? marketData.value?.panorama?.limitUp ?? "-"
  const zab = snap.zab ?? live.zab ?? "-"
  const dt = snap.dt ?? live.dt ?? marketData.value?.panorama?.limitDown ?? "-"
  const lianban = snap.lianban ?? live.lianban ?? "-"
  const max_lianban = snap.max_lb ?? live.max_lianban ?? "-"
  const zab_rate = snap.zb ?? live.zab_rate ?? "-"
  const amount = snap.amount ?? live.amount ?? marketData.value?.volume?.total ?? "-"
  return { zt, zab, dt, lianban, max_lianban, zab_rate, amount }
})

const watchIndices = computed(() => {
  const runtimeRows = Array.isArray((intradayRuntime.intradayRuntime.value as any)?.indices)
    ? (intradayRuntime.intradayRuntime.value as any).indices
    : []
  const fallbackRows = Array.isArray(marketData.value?.indices) ? marketData.value.indices : []
  const rows = (runtimeRows.length ? runtimeRows : fallbackRows).slice(0, 3)
  return rows.map((row: any) => ({
    code: String(row?.code || "").trim(),
    name: String(row?.name || "").trim(),
    val: String(row?.val || row?.price || "-").trim(),
    chg: String(row?.chg || "").trim(),
  }))
})

const watchIndicesAsOf = computed(() => {
  const runtimeAsOf = String((intradayRuntime.intradayRuntime.value as any)?.asOf?.indices || "").trim()
  if (runtimeAsOf) return runtimeAsOf
  return String(marketData.value?.meta?.asOf?.indices || "").trim()
})

const watchTempCards = computed(() => {
  const rows = watchSnapshots.value || []
  const curr = watchCurrentSnap.value || {}
  const prev = watchPrevSnap.value || {}
  const cfgs = [
    { key: "max_lb", label: "高度", unit: "板", inverse: false, hi: 4, mid: 3, max: 8 },
    { key: "zt", label: "涨停", unit: "", inverse: false, hi: 60, mid: 35, max: 100 },
    { key: "dt", label: "跌停", unit: "", inverse: true, hi: 10, mid: 22, max: 60 },
    { key: "jj", label: "晋级率", unit: "%", inverse: false, hi: 30, mid: 18, max: 60 },
    { key: "fb", label: "封板率", unit: "%", inverse: false, hi: 80, mid: 65, max: 100 },
    { key: "lianban", label: "连板", unit: "", inverse: false, hi: 15, mid: 8, max: 30 },
  ]
  return cfgs.map((cfg) => {
    const c = toNum((curr as any)?.[cfg.key], 0)
    const p = toNum((prev as any)?.[cfg.key], c)
    const delta = c - p
    const values = rows.map((x: any) => toNum(x?.[cfg.key], Number.NaN)).filter((v: number) => Number.isFinite(v))
    const isFlat = seriesIsFlat(values)
    const level = cfg.inverse ? (c <= cfg.hi ? "低位" : c <= cfg.mid ? "中位" : "高位") : c >= cfg.hi ? "高位" : c >= cfg.mid ? "中位" : "低位"
    const levelCls = level === "高位" ? "high" : level === "中位" ? "mid" : "low"
    const deltaWord = Math.abs(delta) < 0.05 ? "持平" : delta > 0 ? "上升" : "下降"
    const deltaVal = Math.abs(delta) < 0.05 ? "0" : `${delta > 0 ? "+" : "-"}${Number.isInteger(Math.abs(delta)) ? Math.abs(delta) : Math.abs(delta).toFixed(1)}${cfg.unit}`
    const valueText = `${Number.isInteger(c) ? c : c.toFixed(1)}${cfg.unit}`
    const compressedValues = compressFlatSeries(values).map((x) => x.value)
    const trend = isFlat ? "" : compressedValues.map((v) => (Number.isInteger(v) ? String(v) : v.toFixed(1)) + cfg.unit).join("→")
    return {
      key: cfg.key,
      label: cfg.label,
      level,
      levelCls,
      deltaWord,
      deltaVal,
      valueText,
      kind: cfg.inverse ? "risk" : "heat",
      barPct: clamp100((c / Math.max(cfg.max, 1)) * 100),
      isFlat,
      stableText: `数据未变化：${valueText}`,
      trendHtml: isFlat ? "" : trendColorHtml(trend, "→", cfg.inverse),
    }
  })
})

const watchSeriesValues = (key: string) => watchSnapshots.value.map((x: any) => toNum(x?.[key], Number.NaN)).filter((v: number) => Number.isFinite(v))
const watchSinglePoint = (series: unknown[], w = 860, h = 220, pad = 16) => {
  const vals = (Array.isArray(series) ? series : []).map((v) => Number(v)).filter((v) => Number.isFinite(v))
  if (!vals.length) return []
  const value = vals[vals.length - 1]
  const y = h - pad - (clamp100(value) / 100) * (h - pad * 2)
  return [{ x: +(w / 2).toFixed(2), y: +y.toFixed(2), value, index: vals.length - 1 }]
}
const watchLinePoints = (key: string) => {
  const vals = watchSeriesValues(key)
  if (seriesIsFlat(vals)) return watchSinglePoint(vals)
  const compressed = compressFlatSeries(vals)
  const pts = linePoints(
    compressed.map((x) => x.value),
    860,
    220,
    16,
  )
  return pts.map((p, i) => ({ ...p, index: compressed[i]?.index ?? p.index }))
}
const watchLinePath = (key: string) => {
  const vals = watchSeriesValues(key)
  if (seriesIsFlat(vals)) return { line: "", area: "" }
  return linePath(
    compressFlatSeries(vals).map((x) => x.value),
    860,
    220,
    16,
  )
}
const watchScorePoints = computed(() => watchLinePoints("shift_score"))
const watchHeatPoints = computed(() => watchLinePoints("heat"))
const watchRiskPoints = computed(() => watchLinePoints("risk"))
const watchScoreLine = computed(() => watchLinePath("shift_score"))
const watchHeatLine = computed(() => watchLinePath("heat"))
const watchRiskLine = computed(() => watchLinePath("risk"))
const watchCompressedSnapshots = computed(() => {
  const rows = watchSnapshots.value || []
  if (rows.length <= 1) return rows.map((x: any, index: number) => ({ ...x, _index: index }))
  const keys = ["shift_score", "heat", "risk"]
  const out: any[] = []
  const sameCore = (a: any, b: any) => keys.every((key) => Math.abs(toNum(a?.[key], Number.NaN) - toNum(b?.[key], Number.NaN)) <= 0.05)
  for (let i = 0; i < rows.length; i++) {
    const item = { ...(rows[i] || {}), _index: i }
    const prev = out[out.length - 1]
    if (!prev || !sameCore(item, prev)) out.push(item)
    else out[out.length - 1] = item
  }
  return out
})
const watchCurrentIndex = computed(() => {
  const rows = watchSnapshots.value || []
  return rows.length ? rows.length - 1 : -1
})
const watchTimePoints = computed(() => watchCompressedSnapshots.value.map((x: any) => ({ time: x?.time || "--", index: x?._index ?? 0 })))
const watchRecentRows = computed(() => {
  const rows = watchSnapshots.value || []
  const n = watchSnapshots.value.length > 12 ? 12 : 8
  return rows.slice(-n).reverse()
})
const watchTrajectoryFlat = computed(() => ["shift_score", "heat", "risk"].every((key) => seriesIsFlat(watchSeriesValues(key))))

const watchResonanceMarkers = computed(() => {
  const alerts = (intradayAlertPool as any).items?.value || []
  const resEvents = alerts.filter((a: any) => a.eventType === 99999)
  if (!resEvents.length) return []

  const snaps = watchSnapshots.value
  if (!snaps.length) return []

  const pts = watchScorePoints.value
  if (!pts.length) return []

  return resEvents
    .map((event: any) => {
      const [h, m] = event.time.split(":").map(Number)
      const eventMin = h * 60 + m

      // 直接在压缩点集上找时间最近的快照（而非通过原始 index 匹配）
      let bestIdx = -1
      let minDiff = 99999

      snaps.forEach((s: any, idx: number) => {
        const [sh, sm] = (s.time || "00:00").split(":").map(Number)
        const sMin = sh * 60 + sm
        const diff = Math.abs(sMin - eventMin)
        if (diff < minDiff && diff < 10) {
          minDiff = diff
          bestIdx = idx
        }
      })

      if (bestIdx === -1) return null

      // 找压缩点集中 index 最接近 bestIdx 的点（允许 index <= bestIdx）
      let closestPt = pts[0]
      for (const p of pts) {
        if (p.index <= bestIdx) closestPt = p
        else break
      }
      return { ...closestPt, label: event.title.replace("🔥 板块共振：", "") }
    })
    .filter(Boolean)
})

const watchEvolutionSummary = computed(() => {
  const rows = watchSnapshots.value || []
  if (!rows.length) return "暂无盘中切片，无法生成演化总结。"
  const first: any = rows[0] || {}
  const last: any = rows[rows.length - 1] || {}
  if (watchTrajectoryFlat.value) {
    return `盘中核心数据未变化：情绪分 ${last.shift_score ?? "-"}，热度 ${last.heat ?? "-"}，风险 ${last.risk ?? "-"}。继续等待下一次有效变化。`
  }
  const scoreDiff = toNum(last?.shift_score, 0) - toNum(first?.shift_score, 0)
  const heatDiff = toNum(last?.heat, 0) - toNum(first?.heat, 0)
  const riskDiff = toNum(last?.risk, 0) - toNum(first?.risk, 0)
  const peak = rows.reduce((best: any, cur: any) => (toNum(cur?.shift_score, -1e9) > toNum(best?.shift_score, -1e9) ? cur : best), rows[0])
  const low = rows.reduce((best: any, cur: any) => (toNum(cur?.shift_score, 1e9) < toNum(best?.shift_score, 1e9) ? cur : best), rows[0])
  const dir = scoreDiff >= 5 ? "整体走强" : scoreDiff >= 1 ? "边际修复" : scoreDiff <= -5 ? "明显走弱" : scoreDiff <= -1 ? "略有回落" : "整体平稳"
  const hr = `热度${heatDiff > 0 ? "抬升" : heatDiff < 0 ? "回落" : "基本持平"}，风险${riskDiff > 0 ? "上行" : riskDiff < 0 ? "回落" : "持平"}`
  const peakText = peak && peak.time ? `盘中最强时点在 ${peak.time}（${peak.shift_label || "稳定"}，情绪分 ${peak.shift_score ?? "-"}）` : ""
  const lowText = low && low.time && low.time !== peak?.time ? `，最弱时点在 ${low.time}（${low.shift_label || "稳定"}，情绪分 ${low.shift_score ?? "-"}）` : ""
  return `从 ${first.time || "开盘"} 到 ${last.time || "当前"}，情绪 ${dir}；${hr}。${peakText}${lowText}。收在 ${last.shift_label || last.headline || "稳定"} 状态。`
})

const liveError = computed(() => intradayRuntime.error.value || "")

const enableIntradayAlert = () => {
  if (!intradayAlertPool.enabled.value) intradayAlertPool.setEnabled(true)
}

const historySearch = ref("")
const historyFilter = ref("all")

const filteredHistory = computed(() => {
  let list = (intradayAlertPool as any).allHistory?.value || []

  if (historyFilter.value === "resonance") {
    list = list.filter((x: any) => x.eventType === 99999)
  }

  if (historySearch.value) {
    const s = historySearch.value.toLowerCase()
    list = list.filter((x: any) => x.title.toLowerCase().includes(s) || x.subtitle.toLowerCase().includes(s))
  }

  list = [...list].sort((a: any, b: any) => b.eventTimestamp - a.eventTimestamp)
  return list
})

const muteIntradayAlert = () => {
  if (intradayAlertPool.enabled.value) intradayAlertPool.setEnabled(false)
}

const handleResonanceToastClick = (item: any) => {
  intradayAlertPool.dismissResonanceToast(item.id)
  historyFilter.value = "resonance"
  intradayAlertPool.toggleHistory()
}

const toastTimers = new Map<string, number>()

const scheduleToastDismiss = (id: string) => {
  const existing = toastTimers.get(id)
  if (existing) window.clearTimeout(existing)
  const timer = window.setTimeout(() => {
    intradayAlertPool.dismissResonanceToast(id)
    toastTimers.delete(id)
  }, 6000)
  toastTimers.set(id, timer)
}

watch(
  () => intradayAlertPool.resonanceToasts.value.length,
  () => {
    intradayAlertPool.resonanceToasts.value.forEach((item) => {
      if (!toastTimers.has(item.id)) scheduleToastDismiss(item.id)
    })
  },
  { immediate: true, deep: true },
)

onMounted(() => {
  intradayAlertPool.start()
})

onBeforeUnmount(() => {
  intradayAlertPool.stop()
})
</script>

<template>
  <div class="card" data-page="watch" id="sec-watch">
    <div class="wb">
      <div class="wb-body">
        <div class="wb-grid">
          <div class="wb-span-4 wb-flat-section wb-shift-card" :class="'tone-' + watchCurrentShift.tone">
            <div class="evidence-group-title" :class="{ red: watchCurrentShift.tone === 'bull', green: watchCurrentShift.tone === 'bear' }">
              盘中情绪分
              <span v-if="watchCurrentShift.tone === 'bull'" style="font-size: 10px; opacity: 0.8; margin-left: 4px">拉升中</span>
              <span v-else-if="watchCurrentShift.tone === 'bear'" style="font-size: 10px; opacity: 0.8; margin-left: 4px">下跌中</span>
            </div>
            <div class="wb-flat-subtitle">和主情绪页同口径，按盘中快照动态计算</div>
            <div class="wb-shift">
              <div class="wb-shift-top">
                <div style="display: flex; align-items: baseline; gap: 6px">
                  <div class="wb-shift-score">{{ watchCurrentShift.score }}</div>
                  <div class="wb-shift-delta" v-if="watchPrevSnap?.shift_score != null && watchCurrentSnap?.shift_score != null && watchCurrentSnap.shift_score !== watchPrevSnap.shift_score">
                    <template v-if="watchCurrentSnap.shift_score > watchPrevSnap.shift_score">↑{{ watchCurrentSnap.shift_score - watchPrevSnap.shift_score }}</template>
                    <template v-else>↓{{ watchPrevSnap.shift_score - watchCurrentSnap.shift_score }}</template>
                  </div>
                </div>
                <div class="wb-shift-right">
                  <div class="wb-shift-label">{{ watchCurrentShift.label }}</div>
                </div>
              </div>
              <div class="wb-shift-bar">
                <div class="wb-shift-bar-fill" :style="{ width: Math.max(0, Math.min(100, Number(watchCurrentShift.score) || 0)) + '%' }"></div>
                <span class="wb-shift-bar-pct">{{ watchCurrentShift.score }}%</span>
              </div>
              <div class="wb-shift-note">{{ watchCurrentShift.note }}</div>

              <!-- 新增：关键里程碑时间轴 -->
              <div class="wb-milestones" v-if="(intradayAlertPool as any).items?.value?.length">
                <div class="milestone-header">
                  <div class="milestone-title" :class="{ red: watchCurrentShift.tone === 'bull', green: watchCurrentShift.tone === 'bear' }">今日关键异动回顾</div>
                  <button class="milestone-history-btn" type="button" @click="intradayAlertPool.toggleHistory()">全天回顾</button>
                </div>
                <div class="milestone-list">
                  <div v-for="item in [...((intradayAlertPool as any).items?.value || [])].reverse().slice(0, 15)" :key="item.id" class="milestone-item" :class="item.priorityLevel">
                    <span class="m-time">{{ item.time }}</span>
                    <span class="m-label" :class="item.tone">{{ item.eventTypeLabel }}</span>
                    <span class="m-text" :class="item.tone">{{ item.title }}</span>
                    <span class="m-val" :class="item.tone" v-if="item.valueText">{{ item.valueText }}</span>
                    <span class="m-moment" :class="item.tone" v-if="item.momentText">{{ item.momentText }}</span>
                  </div>
                </div>
              </div>

              <div class="wb-shift-drivers" v-if="watchTempCards.length">
                <span class="wb-driver" v-for="item in watchTempCards" :key="'drv-' + item.key">
                  {{ item.label }} {{ item.valueText }}
                  <i
                    v-if="item.deltaWord !== '持平' && item.deltaVal !== '0' && item.deltaVal !== '+0' && item.deltaVal !== '-0'"
                    :class="['dim-chip-inline', item.deltaWord === '上升' ? 'up' : 'down']">
                    {{ item.deltaVal }}
                  </i>
                </span>
              </div>
              <div class="wb-mini-kpis">
                <div class="wb-mini-kpi">
                  <div class="k">热 / 险</div>
                  <div class="wb-kpi-row">
                    <span class="v">热{{ watchCurrentSnap?.heat ?? "-" }}</span>
                    <span class="n">险 {{ watchCurrentSnap?.risk ?? "-" }}</span>
                  </div>
                </div>
                <div class="wb-mini-kpi">
                  <div class="k">涨停 / 跌停</div>
                  <div class="wb-kpi-row">
                    <span class="v">{{ watchMarket.zt ?? "-" }} / {{ watchMarket.dt ?? "-" }}</span>
                    <span class="n">炸板 {{ watchMarket.zab ?? "-" }}</span>
                  </div>
                </div>
                <div class="wb-mini-kpi">
                  <div class="k">连板 / 高度</div>
                  <div class="wb-kpi-row">
                    <span class="v">{{ watchMarket.lianban ?? "-" }} / {{ watchMarket.max_lianban ?? "-" }}</span>
                    <span class="n">炸板率 {{ watchMarket.zab_rate ?? "-" }}%</span>
                  </div>
                </div>
                <div class="wb-mini-kpi">
                  <div class="k">成交额</div>
                  <div class="v">{{ watchMarket.amount ?? "-" }}</div>
                </div>
              </div>
            </div>
            <div class="wb-alerts" v-if="((intradayRuntime.live.value?.alerts || marketData.live?.alerts) || []).length">
              <span class="wb-alert" v-for="(a, i) in (intradayRuntime.live.value?.alerts || marketData.live?.alerts || [])" :key="'wba-' + i" :class="a.level">{{ a.text }}</span>
            </div>
            <div class="wb-index-strip" v-if="watchIndices.length">
              <div class="wb-index-strip-head">
                <span>三大指数</span>
                <span v-if="watchIndicesAsOf">{{ watchIndicesAsOf }}</span>
              </div>
              <div class="wb-index-strip-list">
                <div class="wb-index-pill" v-for="idx in watchIndices" :key="idx.code || idx.name">
                  <span class="wb-index-pill-name">{{ idx.name }}</span>
                  <span class="wb-index-pill-val">{{ idx.val }}</span>
                  <span class="wb-index-pill-chg" :class="{ up: idx.chg.startsWith('+'), down: idx.chg.startsWith('-') }">{{ idx.chg || '--' }}</span>
                </div>
              </div>
            </div>
            <div class="wb-alerts" v-if="liveError">
              <span class="wb-alert error">{{ liveError }}</span>
            </div>
            <div v-if="!watchSnapshots.length && !intradayRuntime.live.value && !marketData.live" style="margin-top: 10px; font-size: 12px; color: var(--text-muted); font-weight: 850">暂无盯盘快照，执行一次 watch-slice 即可生成</div>
          </div>

          <div class="wb-span-12 wb-flat-section">
            <div class="evidence-group-title" :class="{ red: watchCurrentShift.tone === 'bull', green: watchCurrentShift.tone === 'bear' }">
              六维参考温度
              <span v-if="watchCurrentShift.tone === 'bull'" style="font-size: 10px; opacity: 0.8; margin-left: 4px">热度升温</span>
              <span v-else-if="watchCurrentShift.tone === 'bear'" style="font-size: 10px; opacity: 0.8; margin-left: 4px">风险抬升</span>
            </div>
            <div class="wb-flat-subtitle">参考情绪温度设计，按当前点位与半小时序列展示</div>
            <div class="dim-grid">
              <div class="dim-item" v-for="item in watchTempCards" :key="'wt-' + item.key">
                <div class="dim-top">
                  <span class="dim-k">
                    {{ item.label }}
                    <span class="lvl-badge" :class="item.levelCls">{{ item.level }}</span>
                  </span>
                  <span class="dim-v">{{ item.valueText }}</span>
                </div>
                <div class="dim-bar">
                  <div class="dim-fill" :style="{ width: item.barPct + '%', background: item.kind === 'risk' ? riskColor(item.barPct) : heatColor(item.barPct) }"></div>
                </div>
                <div class="dim-mini">
                  <span class="dim-chip" v-if="!item.isFlat">{{ item.deltaWord }} {{ item.deltaVal }}</span>
                  <code v-if="item.isFlat">{{ item.stableText }}</code>
                  <code v-if="item.trendHtml" v-html="'趋势：' + item.trendHtml"></code>
                </div>
              </div>
            </div>
          </div>

          <div class="wb-span-12 wb-flat-section">
            <div class="evidence-group-title" :class="{ red: watchCurrentShift.tone === 'bull', green: watchCurrentShift.tone === 'bear' }">
              盘中轨迹
              <span v-if="watchCurrentShift.tone === 'bull'" style="font-size: 10px; opacity: 0.8; margin-left: 4px">承接有力</span>
              <span v-else-if="watchCurrentShift.tone === 'bear'" style="font-size: 10px; opacity: 0.8; margin-left: 4px">分歧扩散</span>
            </div>
            <div class="wb-flat-subtitle">用同一口径看“承接/分歧/扩散”是否在变好</div>
            <div v-if="watchSnapshots.length">
              <div class="wb-trend-panel">
                <svg class="wb-trend-svg" viewBox="0 0 860 220" preserveAspectRatio="none" aria-label="盘中轨迹折线图">
                  <line class="wb-trend-gridline" x1="16" y1="32" x2="844" y2="32"></line>
                  <line class="wb-trend-gridline" x1="16" y1="110" x2="844" y2="110"></line>
                  <line class="wb-trend-gridline" x1="16" y1="204" x2="844" y2="204"></line>
                  <path v-if="watchScoreLine.area" class="wb-trend-score" :d="watchScoreLine.area"></path>
                  <path v-if="watchScoreLine.line" class="wb-trend-line-score" :d="watchScoreLine.line"></path>
                  <path v-if="watchHeatLine.line" class="wb-trend-line-heat" :d="watchHeatLine.line"></path>
                  <path v-if="watchRiskLine.line" class="wb-trend-line-risk" :d="watchRiskLine.line"></path>

                  <!-- 板块共振标记 -->
                  <g v-for="(m, i) in watchResonanceMarkers" :key="'wrm-' + i">
                    <line class="wb-trend-resonance-line" :x1="m.x" y1="32" :x2="m.x" y2="204"></line>
                    <rect class="wb-trend-resonance-bg" :x="m.x - 20" y="10" width="40" height="18" rx="4"></rect>
                    <text class="wb-trend-resonance-text" :x="m.x" y="23" text-anchor="middle">{{ m.label }}</text>
                  </g>

                  <circle
                    v-for="(p, i) in watchScorePoints"
                    :key="'wsp-' + i"
                    class="wb-trend-dot score"
                    :class="{ current: p.index === watchCurrentIndex }"
                    :cx="p.x"
                    :cy="p.y"
                    :r="p.index === watchCurrentIndex ? 5.5 : 3.6"></circle>
                  <circle
                    v-for="(p, i) in watchHeatPoints"
                    :key="'whp-' + i"
                    class="wb-trend-dot heat"
                    :class="{ current: p.index === watchCurrentIndex }"
                    :cx="p.x"
                    :cy="p.y"
                    :r="p.index === watchCurrentIndex ? 5.2 : 3.2"></circle>
                  <circle
                    v-for="(p, i) in watchRiskPoints"
                    :key="'wrp-' + i"
                    class="wb-trend-dot risk"
                    :class="{ current: p.index === watchCurrentIndex }"
                    :cx="p.x"
                    :cy="p.y"
                    :r="p.index === watchCurrentIndex ? 5.2 : 3.2"></circle>
                </svg>
                <div class="wb-trend-now" v-if="watchCurrentSnap?.time">
                  <span>当前高亮</span>
                  <strong>{{ watchCurrentSnap.time }}</strong>
                </div>

                <div class="wb-trend-legend">
                  <span>
                    <i class="score"></i>
                    盘中情绪分
                  </span>
                  <span>
                    <i class="heat"></i>
                    热度
                  </span>
                  <span>
                    <i class="risk"></i>
                    风险
                  </span>
                </div>
                <div class="wb-evo-summary">
                  <div class="k" :class="{ red: watchCurrentShift.tone === 'bull', green: watchCurrentShift.tone === 'bear' }">今日盘中情绪演化总结</div>
                  <div class="v">{{ watchEvolutionSummary }}</div>
                </div>
              </div>
              <div class="wb-trend-axis">
                <span v-for="p in watchTimePoints" :key="'wta-' + p.index" :class="{ active: p.index <= watchCurrentIndex, current: p.index === watchCurrentIndex }">{{ p.time }}</span>
              </div>
              <div class="wb-list" style="margin-top: 12px">
                <div class="wb-row" v-for="(x, i) in watchRecentRows" :key="'wbt-' + i">
                  <span class="name">{{ x.time }} {{ x.shift_label || x.headline || "—" }}</span>
                  <span class="meta">封{{ x.fb ?? "-" }}% | 晋{{ x.jj ?? "-" }}% | 炸{{ x.zb ?? "-" }}% | 跌{{ x.dt ?? "-" }} | 热{{ x.heat ?? "-" }} | 险{{ x.risk ?? "-" }}</span>
                </div>
              </div>
            </div>
            <div v-else style="font-size: 12px; color: var(--text-muted); font-weight: 850">暂无快照流数据（收盘重建后会自动生成模拟轨迹）</div>
          </div>
        </div>
        <div class="wb-alert-sidebar">
          <div class="wb-sidebar-head">
            <div class="wb-sidebar-title">盘中异动提醒</div>
            <div class="wb-sidebar-meta">{{ intradayAlertPool.statusText.value }}</div>
          </div>
          <div class="wb-sidebar-actions">
            <button class="wb-sidebar-btn" type="button" @click="intradayAlertPool.refresh()">刷新</button>
            <button class="wb-sidebar-btn" type="button" @click="intradayAlertPool.markAllRead()">已读</button>
            <button class="wb-sidebar-btn" :class="{ on: intradayAlertPool.enabled.value }" type="button" @click="enableIntradayAlert()">开启</button>
            <button class="wb-sidebar-btn" :class="{ on: !intradayAlertPool.enabled.value }" type="button" @click="muteIntradayAlert()">静默</button>
          </div>
          <div class="wb-sidebar-body">
            <div class="wb-sidebar-list" v-if="intradayAlertPool.railItems.value.length">
              <button
                v-for="item in intradayAlertPool.railItems.value"
                :key="item.id"
                class="wb-sidebar-item"
                :class="[item.tone, item.priorityLevel, { unread: item.unread }]"
                type="button"
                @click="intradayAlertPool.onItemClick(item)">
                <div class="wb-sidebar-top">
                  <span class="time">{{ item.time }}</span>
                  <span class="badge" :class="item.tone">{{ item.eventTypeLabel }}</span>
                </div>
                <div class="wb-sidebar-name" :class="item.tone">
                  {{ item.title }}
                  <span class="move" v-if="item.valueText">{{ item.valueText }}</span>
                  <span class="move-moment" v-if="item.momentText">{{ item.momentText }}</span>
                </div>
                <div class="wb-sidebar-sub">{{ item.subtitle }}</div>
              </button>
            </div>
            <div class="wb-sidebar-empty" v-else>{{ intradayAlertPool.error.value || "当前没有提醒级异动" }}</div>
          </div>
        </div>
      </div>
    </div>

    <ShortReminderFooter />
  </div>

  <!-- 全天异动回顾大弹窗 -->
  <Teleport to="body">
    <div v-if="intradayAlertPool.historyOpen.value" class="alert-history-overlay" @click.self="intradayAlertPool.toggleHistory()">
      <div class="alert-history-modal">
        <div class="ah-head">
          <div class="ah-title" :class="{ red: watchCurrentShift.tone === 'bull', green: watchCurrentShift.tone === 'bear' }">
            今日异动全纪实
            <span v-if="watchCurrentShift.tone === 'bull'" style="font-size: 11px; font-weight: 800; margin-left: 8px; color: var(--danger)">[ 市场拉升中 ]</span>
            <span v-else-if="watchCurrentShift.tone === 'bear'" style="font-size: 11px; font-weight: 800; margin-left: 8px; color: var(--success)">[ 市场下跌中 ]</span>
          </div>
          <div class="ah-close" @click="intradayAlertPool.toggleHistory()">✕</div>
        </div>

        <div class="ah-filters">
          <div class="ah-search-box">
            <input v-model="historySearch" placeholder="搜索个股/板块名称..." class="ah-input" />
          </div>
          <div class="ah-tabs">
            <button
              v-for="t in [
                { k: 'all', n: '全部' },
                { k: 'resonance', n: '共振' },
              ]"
              :key="t.k"
              @click="historyFilter = t.k"
              class="ah-tab"
              :class="{ active: historyFilter === t.k }">
              {{ t.n }}
            </button>
          </div>
        </div>

        <div class="ah-body">
          <div class="ah-columns">
            <div v-if="!filteredHistory.length" class="ah-empty">暂无符合条件的记录</div>
            <div v-for="item in filteredHistory" :key="item.id" class="ah-item" :class="[item.tone, item.priorityLevel]">
              <div class="ah-item-left">
                <span class="ah-time">{{ item.time }}</span>
                <span class="ah-badge" :class="item.tone">{{ item.eventTypeLabel }}</span>
              </div>
              <div class="ah-item-content">
                <div class="ah-item-title" :class="item.tone">
                  {{ item.title }}
                  <span class="ah-val" v-if="item.valueText">{{ item.valueText }}</span>
                  <span class="ah-moment" v-if="item.momentText">{{ item.momentText }}</span>
                </div>
                <div class="ah-item-sub">{{ item.subtitle }}</div>
              </div>
            </div>
          </div>
        </div>

        <div class="ah-footer">共 {{ filteredHistory.length }} 条记录 · 仅保存今日数据</div>
      </div>
    </div>
  </Teleport>

  <!-- 板块共振右侧弹窗 -->
  <Teleport to="body">
    <div class="resonance-toast-container">
      <button
        v-for="item in intradayAlertPool.resonanceToasts.value"
        :key="item.id"
        class="resonance-toast"
        :class="item.tone"
        type="button"
        @click="handleResonanceToastClick(item)">
        <div class="resonance-toast-head">
          <span class="resonance-toast-badge">🔥 共振</span>
          <span class="resonance-toast-time">{{ item.time }}</span>
        </div>
        <div class="resonance-toast-body">{{ item.title }}</div>
        <div class="resonance-toast-foot">{{ item.subtitle }}</div>
        <span class="resonance-toast-close" @click.stop="intradayAlertPool.dismissResonanceToast(item.id)">✕</span>
        <div class="resonance-toast-bar" :class="item.tone"></div>
      </button>
    </div>
  </Teleport>
</template>

<style scoped src="./WatchPage.css"></style>
