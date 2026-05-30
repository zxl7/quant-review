<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import ShortReminderFooter from '../common/ShortReminderFooter.vue'

type FlashStock = {
  name: string
  symbol: string
}

type FlashBkJInfo = {
  id: number
  name: string
}

type FlashExplainInfo = {
  title: string
  content: string
}

type FlashItem = {
  id: string
  title: string
  subTitle: string
  summary: string
  hasSummary: boolean
  timeText: string
  timeShort: string
  timeValue: number
  isWarn: boolean
  tone: 'up' | 'down' | 'neutral'
  stocks: FlashStock[]
  allStocks: FlashStock[]
  bkjInfos: FlashBkJInfo[]
  explainInfos: FlashExplainInfo[]
  subjNames: string[]
  impact: number
  isPremium: boolean
  flashMessageType: string
}

const SUBJECT_MAP: Record<number, string> = {
  9: '要闻',
  10: '风险警示',
  23: '期货',
  35: '快讯',
  146: '航运物流',
  156: '基建',
  168: '半导体',
  203: '题材',
  223: '港口',
  283: 'AI算力',
  347: '轮胎化工',
  443: '定增',
  469: '公告',
  573: '港股',
  723: '个股',
  821: '宏观经济',
  927: '化工',
  1444: '区块链',
  1891: '氢能源',
}

const flashFilter = ref<'all' | 'warn' | 'up' | 'down'>('all')
const flashItems = ref<FlashItem[]>([])
const flashLastUpdated = ref('')
const flashLoading = ref(false)
const flashError = ref('')

let flashTimer: number | null = null
let flashReqInFlight = false

const flashCounts = computed(() => ({
  all: flashItems.value.length,
  warn: flashItems.value.filter((x) => x.isWarn).length,
  up: flashItems.value.filter((x) => x.tone === 'up').length,
  down: flashItems.value.filter((x) => x.tone === 'down').length,
}))

const filteredFlashItems = computed(() => {
  const f = flashFilter.value
  if (f === 'warn') return flashItems.value.filter((x) => x.isWarn)
  if (f === 'up') return flashItems.value.filter((x) => x.tone === 'up')
  if (f === 'down') return flashItems.value.filter((x) => x.tone === 'down')
  return flashItems.value
})

const setFlashFilter = (mode: 'all' | 'warn' | 'up' | 'down') => {
  flashFilter.value = mode
}

const inferFlashTone = (title: string, summary: string): 'up' | 'down' | 'neutral' => {
  const text = `${title || ''} ${summary || ''}`
  if (/跳水|跌停|走弱|风险|回落|分歧/.test(text)) return 'down'
  if (/涨停|拉升|走强|回封|新高|修复|反弹/.test(text)) return 'up'
  return 'neutral'
}

const toDate = (value: unknown): Date | null => {
  let date: Date | null = null
  if (typeof value === 'number' && Number.isFinite(value)) date = new Date(value * 1000)
  else if (typeof value === 'string' && value.trim()) date = new Date(value)
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return null
  return date
}

const fmtTime = (date: Date): string => {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  const ss = String(date.getSeconds()).padStart(2, '0')
  return `${y}-${m}-${d} ${hh}:${mm}:${ss}`
}

const fmtTimeShort = (date: Date): string => {
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

const normalizeFlashStocks = (stocks: unknown): FlashStock[] => {
  if (!Array.isArray(stocks)) return []
  const seen = new Set<string>()
  const out: FlashStock[] = []
  for (const raw of stocks) {
    if (!raw || typeof raw !== 'object') continue
    const row = raw as Record<string, any>
    const name = String(row.name || '').trim()
    const symbol = String(row.symbol || row.code || '').trim()
    const key = `${name}-${symbol}`
    if (!name || key === '-' || seen.has(key)) continue
    seen.add(key)
    out.push({ name, symbol })
    if (out.length >= 6) break
  }
  return out
}

const resolveSubjNames = (subjIds: number[]): string[] =>
  subjIds.map((id) => SUBJECT_MAP[id] || `主题${id}`).filter(Boolean)

const normalizeExplainInfos = (infos: unknown): FlashExplainInfo[] => {
  if (!Array.isArray(infos)) return []
  return infos
    .filter((x): x is Record<string, any> => Boolean(x) && typeof x === 'object')
    .map((x) => ({
      title: String(x.title || '').trim(),
      content: String(x.content || '').trim(),
    }))
    .filter((x) => x.title || x.content)
}

const normalizeFlashItems = (messages: unknown) => {
  const rows = Array.isArray(messages) ? messages : []
  const mapped = rows
    .filter((x): x is Record<string, any> => Boolean(x) && typeof x === 'object')
    .map((x, index) => {
      const subjIds = Array.isArray(x.subj_ids) ? x.subj_ids.map((v: unknown) => Number(v)) : []
      const title = String(x.title || '').trim()
      const summary = String(x.summary || '').trim()
      const date = toDate(x.created_at)
      return {
        id: String(x.id || x.msg_id || x.created_at || index),
        title,
        subTitle: String(x.sub_title || '').trim(),
        summary,
        hasSummary: Boolean(x.has_summary) || summary.length > 0,
        timeText: date ? fmtTime(date) : '--',
        timeShort: date ? fmtTimeShort(date) : '--',
        timeValue: date ? date.getTime() : 0,
        isWarn: subjIds.includes(10),
        tone: inferFlashTone(title, summary),
        stocks: normalizeFlashStocks(x.stocks),
        allStocks: normalizeFlashStocks(x.all_stocks),
        bkjInfos: Array.isArray(x.bkj_infos)
          ? x.bkj_infos
              .filter((b: unknown): b is Record<string, any> => Boolean(b) && typeof b === 'object')
              .map((b: Record<string, any>) => ({ id: Number(b.id || 0), name: String(b.name || '').trim() }))
              .filter((b: FlashBkJInfo) => b.name)
          : [],
        explainInfos: normalizeExplainInfos(x.explain_infos),
        subjNames: resolveSubjNames(subjIds),
        impact: Number(x.impact || 0),
        isPremium: Boolean(x.is_premium),
        flashMessageType: String(x.flash_message_type || 'default'),
      }
    })
    .filter((x) => x.title)

  const deduped = new Map<string, FlashItem>()
  mapped.forEach((item) => {
    const key = `${item.title}__${item.summary}`
    const prev = deduped.get(key)
    if (!prev || item.timeValue > prev.timeValue) deduped.set(key, item)
  })

  return Array.from(deduped.values()).sort((a, b) => b.timeValue - a.timeValue)
}

const sortedFlashItems = computed(() =>
  [...filteredFlashItems.value].sort((a, b) => b.timeValue - a.timeValue),
)

const refreshFlash = async () => {
  try {
    if (flashReqInFlight) return
    flashReqInFlight = true
    flashLoading.value = true
    flashError.value = ''
    const url = 'https://baoer-api.xuangubao.cn/api/v6/message/newsflash?subj_ids=9,10,723,35,469,821&platform=pcweb'
    const res = await fetch(`${url}&_ts=${Date.now()}`, { cache: 'no-store' })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const json = await res.json()
    flashItems.value = normalizeFlashItems(json?.data?.messages)
    flashLastUpdated.value = fmtTime(new Date())
  } catch (e: any) {
    flashError.value = `快讯获取失败：${String(e?.message || e)}`
  } finally {
    flashLoading.value = false
    flashReqInFlight = false
  }
}

const startFlashPolling = (forceRestart = false) => {
  if (flashTimer && !forceRestart) return
  if (flashTimer && forceRestart) {
    window.clearInterval(flashTimer)
    flashTimer = null
  }
  refreshFlash()
  flashTimer = window.setInterval(() => {
    void refreshFlash()
  }, 15000)
}

const stopFlashPolling = () => {
  if (flashTimer) {
    window.clearInterval(flashTimer)
    flashTimer = null
  }
}

const flashStockUrl = (symbol?: string | null) => {
  const raw = String(symbol || '').trim()
  if (!raw) return 'https://xueqiu.com'
  const upper = raw.toUpperCase()
  if (upper.includes('.')) {
    const [num, suffix] = upper.split('.')
    const market = suffix === 'SH' ? 'SH' : suffix === 'SZ' ? 'SZ' : ''
    return market ? `https://xueqiu.com/S/${market}${num}` : `https://xueqiu.com/S/${upper}`
  }
  const market = raw.startsWith('6') ? 'SH' : 'SZ'
  return `https://xueqiu.com/S/${market}${raw}`
}

const formatImpact = (impact: number): string => {
  if (impact >= 3) return '重大'
  if (impact >= 1) return '重要'
  return ''
}

onMounted(() => {
  startFlashPolling(true)
})

onBeforeUnmount(() => {
  stopFlashPolling()
})
</script>

<template>
  <div class="flash-page">
    <div class="card" data-page="flash" id="sec-flash">
      <div class="card-header">
        <div class="card-title">股通快讯</div>
        <div class="card-badge">15s</div>
      </div>

      <div class="flash-toolbar">
        <div class="flash-toolbar-left">
          <button class="flash-btn" :class="{ active: flashFilter === 'all' }" type="button" @click="setFlashFilter('all')">全部 {{ flashCounts.all }}</button>
          <button class="flash-btn up" :class="{ active: flashFilter === 'up' }" type="button" @click="setFlashFilter('up')">利多 {{ flashCounts.up }}</button>
          <button class="flash-btn down" :class="{ active: flashFilter === 'down' }" type="button" @click="setFlashFilter('down')">利空 {{ flashCounts.down }}</button>
          <button class="flash-btn warn" :class="{ active: flashFilter === 'warn' }" type="button" @click="setFlashFilter('warn')">警示 {{ flashCounts.warn }}</button>
          <button class="flash-btn" type="button" @click="refreshFlash()">刷新</button>
        </div>
        <div class="flash-toolbar-right">
          <span class="flash-stat up">利多 {{ flashCounts.up }}</span>
          <span class="flash-stat down">利空 {{ flashCounts.down }}</span>
          <span v-if="flashLastUpdated">{{ flashLastUpdated }}</span>
          <span v-else>等待首次拉取</span>
          <span>共 {{ filteredFlashItems.length }} 条</span>
        </div>
      </div>

      <div v-if="flashLoading && !sortedFlashItems.length" class="flash-loading">正在拉取快讯...</div>
      <div v-else-if="flashError" class="flash-error">{{ flashError }}</div>
      <div v-else-if="!sortedFlashItems.length" class="flash-empty">暂无符合条件的快讯</div>
      <div v-else class="flash-list">
        <article
          class="flash-item"
          :class="[item.tone, { warn: item.isWarn }]"
          v-for="item in sortedFlashItems"
          :key="item.id">

          <div class="flash-row">
            <span class="flash-time">{{ item.timeShort }}：</span>
            <span class="flash-title">{{ item.title }}</span>
            <span v-if="item.isWarn" class="flash-flag warn">警示</span>
            <span v-else-if="item.tone === 'up'" class="flash-flag up">利多</span>
            <span v-else-if="item.tone === 'down'" class="flash-flag down">利空</span>
          </div>

          <div class="flash-subtitle" v-if="item.subTitle">{{ item.subTitle }}</div>

          <div class="flash-summary" v-if="item.summary">{{ item.summary }}</div>

          <div class="flash-meta" v-if="item.impact > 0 || item.isPremium">
            <span class="flash-impact" :class="impact >= 3 ? 'high' : 'mid'" v-for="impact in [item.impact].filter(Boolean)" :key="'imp'">
              影响：{{ formatImpact(item.impact) }}
            </span>
            <span class="flash-badge" v-if="item.isPremium">付费</span>
          </div>

          <div class="flash-tags" v-if="item.subjNames.length">
            <span class="flash-tag" v-for="(name, i) in item.subjNames" :key="'subj-'+i">{{ name }}</span>
          </div>

          <div class="flash-bkjs" v-if="item.bkjInfos.length">
            <span class="flash-bkj" v-for="bk in item.bkjInfos" :key="'bk-'+bk.id">{{ bk.name }}</span>
          </div>

          <div class="flash-stocks" v-if="item.stocks.length">
            <a
              class="flash-stock"
              v-for="stock in item.stocks"
              :key="item.id + '-' + stock.symbol"
              :href="flashStockUrl(stock.symbol)"
              target="_blank"
              rel="noopener noreferrer">{{ stock.name }}</a>
            <span class="flash-more-stocks" v-if="item.allStocks.length > item.stocks.length"
              :title="item.allStocks.map(s => s.name).join('、')">+{{ item.allStocks.length - item.stocks.length }}</span>
          </div>

          <div class="flash-explains" v-if="item.explainInfos.length">
            <div class="flash-explain" v-for="(ex, i) in item.explainInfos" :key="'ex-'+i">
              <span class="flash-explain-title" v-if="ex.title">{{ ex.title }}</span>
              <span class="flash-explain-content" v-if="ex.content">{{ ex.content }}</span>
            </div>
          </div>

        </article>
      </div>
    </div>

    <ShortReminderFooter />
  </div>
</template>

<style scoped src="./FlashPage.css"></style>
