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
  const fallbackSnapshots = computed<any[]>(() =>
    Array.isArray(marketData.value?.intradaySnapshots?.snapshots) ? marketData.value.intradaySnapshots.snapshots : [],
  )
  const fallbackLive = computed<any>(() => (marketData.value?.live && typeof marketData.value.live === 'object' ? marketData.value.live : null))

  const snapshots = computed<any[]>(() => {
    const rows = runtimeState.value?.snapshots
    return Array.isArray(rows) && rows.length ? rows : fallbackSnapshots.value
  })
  const latest = computed<any>(() => {
    const row = runtimeState.value?.latest
    if (row && typeof row === 'object') return row
    const rows = snapshots.value
    return rows.length ? rows[rows.length - 1] : null
  })
  const live = computed<any>(() => {
    const row = runtimeState.value?.live
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
