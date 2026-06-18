import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useMarketData } from './useMarketData'

type IntradayRuntime = {
  schema?: string
  date?: string
  updated_at?: string
  source?: string
  latest?: Record<string, any> | null
  snapshots?: Record<string, any>[]
  live?: Record<string, any> | null
}

const runtimeState = ref<IntradayRuntime>({})
const runtimeLoading = ref(false)
const runtimeError = ref('')

let runtimeTimer: number | null = null
let runtimeReqInFlight = false

function latestSnapshotTs(source: unknown): string {
  if (!source || typeof source !== 'object') return ''
  const latest = (source as any).latest
  if (latest && typeof latest === 'object') {
    const ts = String((latest as any).ts_bj || (latest as any).updated_at || '').trim()
    if (ts) return ts
  }
  const rows = Array.isArray((source as any).snapshots) ? (source as any).snapshots : []
  const last = rows.length ? rows[rows.length - 1] : null
  if (last && typeof last === 'object') {
    return String((last as any).ts_bj || (last as any).updated_at || '').trim()
  }
  return String((source as any).updated_at || '').trim()
}

function isRuntimePayloadFresh(runtime: IntradayRuntime, fallback: Record<string, any> | null, marketDate: string) {
  const runtimeDate = String(runtime?.date || '').trim()
  if (runtimeDate && marketDate && runtimeDate < marketDate) return false
  const runtimeTs = latestSnapshotTs(runtime)
  if (!runtimeTs) return false
  const fallbackTs = latestSnapshotTs(fallback)
  if (!fallbackTs) return true
  return runtimeTs >= fallbackTs
}

async function fetchIntradayRuntime() {
  try {
    if (runtimeReqInFlight) return
    runtimeReqInFlight = true
    runtimeLoading.value = true
    runtimeError.value = ''
    const urls = [
      './intraday_runtime.json',
      'intraday_runtime.json',
      '/intraday_runtime.json',
    ]
    let loaded = false
    for (const url of urls) {
      try {
        const res = await fetch(`${url}?_ts=${Date.now()}`, { cache: 'no-store' })
        if (!res.ok) continue
        const data = await res.json()
        if (data && typeof data === 'object') {
          runtimeState.value = data
          loaded = true
          break
        }
      } catch {
        // try next
      }
    }
    if (!loaded) {
      runtimeError.value = '盘中运行时文件未就绪'
    }
  } catch (e: any) {
    runtimeError.value = `盘中运行时读取失败：${String(e?.message || e)}`
  } finally {
    runtimeLoading.value = false
    runtimeReqInFlight = false
  }
}

function startIntradayRuntimePolling(intervalMs = 15000) {
  if (runtimeTimer) return
  void fetchIntradayRuntime()
  runtimeTimer = window.setInterval(() => {
    void fetchIntradayRuntime()
  }, intervalMs)
}

function stopIntradayRuntimePolling() {
  if (runtimeTimer) {
    window.clearInterval(runtimeTimer)
    runtimeTimer = null
  }
}

export function useIntradayRuntime() {
  const { marketData } = useMarketData()
  const marketDate = computed(() => String(marketData.value?.date || '').trim())
  const fallbackRuntime = computed<Record<string, any> | null>(() => {
    const raw = marketData.value?.intradaySnapshots
    return raw && typeof raw === 'object' ? raw : null
  })
  const fallbackSnapshots = computed<any[]>(() =>
    Array.isArray(fallbackRuntime.value?.snapshots) ? fallbackRuntime.value.snapshots : [],
  )
  const fallbackLive = computed<any>(() => (marketData.value?.live && typeof marketData.value.live === 'object' ? marketData.value.live : null))
  const runtimeFresh = computed(() => isRuntimePayloadFresh(runtimeState.value || {}, fallbackRuntime.value, marketDate.value))
  const effectiveRuntime = computed<IntradayRuntime>(() => (runtimeFresh.value ? runtimeState.value || {} : {}))

  const snapshots = computed<any[]>(() => {
    const rows = effectiveRuntime.value?.snapshots
    return Array.isArray(rows) && rows.length ? rows : fallbackSnapshots.value
  })
  const latest = computed<any>(() => {
    const row = effectiveRuntime.value?.latest
    if (row && typeof row === 'object') return row
    const rows = snapshots.value
    return rows.length ? rows[rows.length - 1] : null
  })
  const live = computed<any>(() => {
    const row = effectiveRuntime.value?.live
    if (row && typeof row === 'object') return row
    return fallbackLive.value
  })

  onMounted(() => {
    startIntradayRuntimePolling()
  })

  onBeforeUnmount(() => {
    stopIntradayRuntimePolling()
  })

  return {
    intradayRuntime: computed(() => runtimeState.value || {}),
    snapshots,
    latest,
    live,
    loading: runtimeLoading,
    error: runtimeError,
    refresh: fetchIntradayRuntime,
    start: startIntradayRuntimePolling,
    stop: stopIntradayRuntimePolling,
  }
}
