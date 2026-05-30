<script setup lang="ts">
import { computed, ref, onMounted } from "vue"
import { useMarketData } from "../../composables/useMarketData"
import { useThemeHotStore } from "../../composables/useThemeHotStore"
import { normalizeThemeName } from "../../utils/themeUtils"

const { marketData } = useMarketData()
const { xgbUpdatedAt, tmrUpdatedAt, xgbPlates, tmrThemes, xgbStocksByPlateId } = useThemeHotStore()

const xqUrl = (code?: string | null) => {
  const raw = String(code || "").trim()
  if (!raw) return "https://xueqiu.com"
  const upper = raw.toUpperCase()
  if (upper.includes(".")) {
    const [num, suffix] = upper.split(".")
    const market = suffix === "SH" ? "SH" : suffix === "SZ" ? "SZ" : ""
    return market ? `https://xueqiu.com/S/${market}${num}` : `https://xueqiu.com/S/${upper}`
  }
  const market = raw.startsWith("6") ? "SH" : "SZ"
  return `https://xueqiu.com/S/${market}${raw}`
}

const formatPosition = (v: unknown) => {
  if (v === undefined || v === null || v === "") return "-"
  if (typeof v === "number") return `${Math.round(v * 100)}%`
  return String(v)
}

const planGuide = computed(() => marketData.value?.planGuide || null)
const planGuidePills = computed(() => {
  const g = planGuide.value
  if (!g) return []
  return [
    { text: `右侧：${g.rightsideText || "-"}`, primary: true },
    ...(g.mainline ? [{ text: `主线：${g.mainline}`, primary: false }] : []),
    ...(g.nature ? [{ text: `性质：${g.nature}`, primary: false }] : []),
    ...(g.resonance ? [{ text: `共振：${g.resonance}`, primary: false }] : []),
  ]
})
const planGuideWarnings = computed(() => (Array.isArray(planGuide.value?.warnings) ? planGuide.value?.warnings : []))

const positionAdvice = computed(() => {
  const finalPosition = formatPosition(marketData.value?.planGuide?.position)
  if (finalPosition && finalPosition !== "-") {
    const rightside = String(marketData.value?.planGuide?.rightsideText || "")
    const stance = rightside === "禁止" ? "防守" : rightside === "允许" ? "进攻" : "均衡"
    const cls = stance === "进攻" ? "pos-attack" : stance === "防守" ? "pos-def" : "pos-balance"
    const pillCls = stance === "进攻" ? "attack" : stance === "防守" ? "def" : "balance"
    return { stance, range: finalPosition, note: "", cls, pillCls }
  }
  const heat = Number(marketData.value?.mood?.heat ?? 0)
  const risk = Number(marketData.value?.mood?.risk ?? 0)
  const stage = String(marketData.value?.moodStage?.type || "")
  let stance = "均衡"
  let range = "35–50%"
  let note = "围绕主线核心，低位试错为主；不追高位一致。"
  if (stage === "fire") {
    stance = "防守"
    range = "15–30%"
    note = "退潮/冰点：只做低位试错，回避高位接力；优先看修复信号。"
  } else if (risk >= heat + 10) {
    stance = "防守"
    range = "20–35%"
    note = "风险压过热度：轻仓、分散、快进快出；等确定性再加仓。"
  } else if (heat >= risk + 10) {
    stance = "进攻"
    range = "50–70%"
    note = "热度占优：围绕主线核心与确认节点加仓；不做无辨识度扩散。"
  }
  const cls = stance === "进攻" ? "pos-attack" : stance === "防守" ? "pos-def" : "pos-balance"
  const pillCls = stance === "进攻" ? "attack" : stance === "防守" ? "def" : "balance"
  return { stance, range, note, cls, pillCls }
})

const ztRelaySorted = computed(() => (marketData.value?.ztAnalysis?.relay || []).slice())
const ztWatchSorted = computed(() => (marketData.value?.ztAnalysis?.watch || []).slice())
const ztAnalysisExpanded = ref(false)
const ztDebugExpanded = ref(false)
const ztDebugPlacement = ref<"all" | "relay" | "watch" | "excluded">("all")
const isLocalDebug = computed(() => {
  if (typeof window === "undefined") return false
  return ["localhost", "127.0.0.1"].includes(window.location.hostname) || window.location.protocol === "file:"
})
const ztDebugRows = computed(() => (Array.isArray(marketData.value?.ztAnalysis?.meta?.debug?.rows) ? marketData.value.ztAnalysis.meta.debug.rows : []))
const ztDebugFiltered = computed(() => {
  if (ztDebugPlacement.value === "all") return ztDebugRows.value
  return ztDebugRows.value.filter((row: any) => String(row?.placement || "") === ztDebugPlacement.value)
})
const ztDebugSummary = computed(() => {
  const rows = ztDebugRows.value
  return {
    relay: rows.filter((x: any) => x?.placement === "relay").length,
    watch: rows.filter((x: any) => x?.placement === "watch").length,
    excluded: rows.filter((x: any) => x?.placement === "excluded").length,
  }
})
const ztDebugScoreClass = (score: number) => {
  if (score >= 80) return "score-strong"
  if (score >= 65) return "score-mid"
  return "score-weak"
}
const ztDebugPlacementClass = (placement: string) => {
  if (placement === "relay") return "debug-place-relay"
  if (placement === "watch") return "debug-place-watch"
  return "debug-place-excluded"
}

const ztTagRows = (row: any) => (Array.isArray(row?.tagRows) ? row.tagRows : [])

// 推荐线：来自 watchlist.picks_advisor，合并展示在板块·梯队推票内。
type PickStock = {
  code: string
  name: string
  action: string
  score: number
  main_line: string
  primary_sector: string
  primary_confidence: number
  reasons: string[]
  cautions: string[]
  lbc: number
  cje_yi: number
  seal_fund_yi: number
  turnover: number
  breakdown?: Record<string, number>
  bonus?: number
  relay_power_score?: number
  style_tag?: string
  style_confidence?: number
  tide_status?: string
  tide_adjust?: number
}

type MainLinePicks = {
  main_line: string
  confidence: number
  is_chain: boolean
  constituents: string[]
  buy: PickStock[]
  watch: PickStock[]
  summary: string
  diagnostics?: { member_count: number; avg_score: number; tide_status?: string; tide_adjust?: number; tide_hint?: string }
}

type TideTheme = {
  name: string
  status: "traverse_candidate" | "confirmed_mainline" | "micro_traverse" | "rebound_warning" | "volume_rebound" | "weak" | "neutral"
  today_zt: number
  prev_zt: number | null
  pre_prev_zt: number | null
  resilience: number | null
  strength: number | null
  strength_rank: number | null
  strength_score: number | null
  tide_score: number
  confidence: "low" | "medium" | "high"
  warning_level: "none" | "watch" | "risk" | "danger"
  action_hint: string
}

type TideSignal = {
  date: string
  market?: { is_ebb_day?: boolean; trigger_count?: number; triggers?: string[] }
  themes?: TideTheme[]
  summary?: { action_hint?: string }
}

const picksAdvisor = computed(() => {
  const pa = (marketData.value as any)?.picks_advisor
  if (!pa || typeof pa !== "object") return null
  const picks = Array.isArray(pa.main_line_picks) ? (pa.main_line_picks as MainLinePicks[]) : []
  if (!picks.length) return null

  return {
    main_line_picks: picks,
    diagnostics: pa.diagnostics || {},
    generated_at_bj: (marketData.value as any)?.watchlist?.generated_at_bj || "",
  }
})

const tideSignal = computed<TideSignal | null>(() => {
  const md = marketData.value as any
  const fromWatchlist = md?.watchlist?.tide_signal
  if (fromWatchlist && typeof fromWatchlist === "object") return fromWatchlist as TideSignal
  const fromMarket = md?.tideSignal
  if (fromMarket && typeof fromMarket === "object") return fromMarket as TideSignal
  return null
})

const tideThemeRows = computed(() => (Array.isArray(tideSignal.value?.themes) ? tideSignal.value!.themes! : []))

const tideThemeMatches = (tide: TideTheme, names: string[]) => {
  const key = normalizeThemeName(tide.name || "")
  if (!key) return false
  return names.some((raw) => {
    const name = normalizeThemeName(raw)
    return !!name && (name === key || name.includes(key) || key.includes(name))
  })
}

const tideThemeForBucket = (theme: string, matched: string[] = [], advisor?: MainLinePicks | null) => {
  const names = [theme, ...matched, advisor?.main_line || "", ...(advisor?.constituents || [])].filter(Boolean)
  return tideThemeRows.value.find((row) => tideThemeMatches(row, names)) || null
}

const tideStatusLabel = (status?: string) => {
  const labels: Record<string, string> = {
    confirmed_mainline: "确认主线",
    traverse_candidate: "退潮穿越",
    micro_traverse: "微型穿越",
    rebound_warning: "回光返照",
    volume_rebound: "缩量反弹",
    weak: "潮汐退潮",
    neutral: "中性观察",
  }
  return labels[String(status || "")] || ""
}

const tideHintClass = (level?: string) => {
  if (level === "danger" || level === "risk") return "stp-tide-hint is-risk"
  if (level === "watch") return "stp-tide-hint is-watch"
  return "stp-tide-hint"
}

const formatResilience = (v: number | null | undefined) => {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return ""
  const n = Number(v)
  return `${n >= 0 ? "+" : ""}${n.toFixed(1)}`
}

const tideCornerClass = (status?: string) => {
  if (status === "confirmed_mainline") return "is-main"
  if (status === "traverse_candidate" || status === "micro_traverse") return "is-watch"
  if (status === "rebound_warning" || status === "volume_rebound") return "is-risk"
  if (status === "weak") return "is-weak"
  return "is-neutral"
}

const tideCornerText = (tide?: TideTheme | null) => {
  if (!tide) return "潮汐不足"
  const label = tideStatusLabel(tide.status) || "潮汐中性"
  if (tide.status === "rebound_warning" || tide.status === "volume_rebound") {
    return `${label} · 不开新仓`
  }
  if (tide.status === "confirmed_mainline" && tide.strength_score !== null && tide.strength_score !== undefined) {
    return `${label} · 强${Math.round(Number(tide.strength_score))}`
  }
  const resilience = formatResilience(tide.resilience)
  return resilience ? `${label} · ${resilience}` : label
}

const tideCornerTitle = (tide?: TideTheme | null) => {
  if (!tide) return "潮汐数据不足，按原系统判断"
  const parts = [tide.action_hint]
  // 这里只解释后端统一产出的字段；前端不重新计算潮汐状态。
  if (Number.isFinite(Number(tide.tide_score))) parts.push(`潮汐分 ${Math.round(Number(tide.tide_score))}`)
  if (formatResilience(tide.resilience)) parts.push(`韧性 ${formatResilience(tide.resilience)}`)
  if (tide.strength_rank) parts.push(`强度排名 ${tide.strength_rank}`)
  if (tide.strength_score !== null && tide.strength_score !== undefined) parts.push(`板块强度 ${Math.round(Number(tide.strength_score))}`)
  if (tide.confidence) parts.push(`置信度 ${tide.confidence}`)
  return parts.filter(Boolean).join("｜")
}

const confClass = (c: number) => {
  if (c >= 0.7) return "conf-strong"
  if (c >= 0.5) return "conf-mid"
  return "conf-weak"
}

const scoreClass = (s: number) => {
  if (s >= 70) return "score-strong"
  if (s >= 50) return "score-mid"
  return "score-weak"
}

const pickPrimaryTag = (s: PickStock) => {
  if (s.lbc >= 2) return `${s.lbc}板`
  if (s.style_tag) return s.style_tag
  if (s.lbc === 1) return "首板"
  if (s.cje_yi >= 100) return "容量"
  return ""
}

const pickReasonBrief = (s: PickStock) => (Array.isArray(s.reasons) ? s.reasons.slice(0, 2) : [])
const pickCautionBrief = (s: PickStock) => (Array.isArray(s.cautions) ? s.cautions.slice(0, 1) : [])
const advisorMatchesTheme = (ml: MainLinePicks, theme: string, matched: string[] = []) => {
  const names = [theme, ...matched].map((x) => normalizeThemeName(x)).filter(Boolean)
  const main = normalizeThemeName(ml.main_line)
  const constituents = (ml.constituents || []).map((x) => normalizeThemeName(x)).filter(Boolean)
  return names.some((name) => {
    if (!name) return false
    if (main && (name === main || name.includes(main) || main.includes(name))) return true
    return constituents.some((c) => c === name || name.includes(c) || c.includes(name))
  })
}
const advisorForBucket = (theme: string, matched: string[] = []) => {
  const rows = picksAdvisor.value?.main_line_picks || []
  return rows.find((ml) => advisorMatchesTheme(ml, theme, matched)) || null
}
const advisorStockToZtPick = (s: PickStock): ZtStockPick => ({
  code: String(s.code || "").trim(),
  name: String(s.name || s.code || "").trim(),
  lbc: Number(s.lbc || 0),
  cjeYi: Number(s.cje_yi || 0),
  zjYi: Number(s.seal_fund_yi || 0),
  zbc: 0,
  source: "local",
  score: Number(s.score || 0),
})

// watchlist 反向索引：code → { primary_sector, primary_confidence, main_line, main_line_confidence }
// 数据来自 inject_data.py 的 _build_watchlist_stock_index（M3/M4 多源融合结果）。
const mainLineOf = (code: unknown) => {
  const k = String(code || "").trim()
  if (!k) return null
  const idx = (marketData.value as any)?.watchlist_stock_index
  if (!idx || typeof idx !== "object") return null
  const info = idx[k]
  if (!info) return null
  return {
    primary_sector: String(info.primary_sector || ""),
    primary_confidence: Number(info.primary_confidence || 0),
    main_line: String(info.main_line || ""),
    main_line_confidence: Number(info.main_line_confidence || 0),
  }
}

type ZtStockPick = {
  code: string
  name: string
  lbc: number
  cjeYi: number
  zjYi: number
  zbc: number
  source?: "xgb" | "local"
  changePct?: number
  limitUpDays?: number
  score?: number
  tags?: Array<{ text: string; cls: string }>
}

type SectorBucket = {
  theme: string
  source: "realtime" | "fallback" | "advisor"
  sources: string[]
  description: string
  count: number
  maxLbc: number
  highTier: ZtStockPick[]
  midTier: ZtStockPick[]
  baseTier: ZtStockPick[]
  plateStrength?: number
  plateLead?: string
  matchedLocalThemes: string[]
  resonanceScore: number
  themeScore: number
  themeTags: Array<{ text: string; cls: string }>
  advisor?: MainLinePicks | null
  tide?: TideTheme | null
}

const themePanelRows = computed(() => (Array.isArray(marketData.value?.themePanels?.strengthRows) ? marketData.value.themePanels.strengthRows : []))

const leaderByTheme = computed(() => {
  const map = new Map<string, { name: string; code: string; score: number }>()
  ;(Array.isArray(marketData.value?.leaders) ? marketData.value.leaders : []).forEach((row: any) => {
    const key = normalizeThemeName(String(row?.theme || ""))
    if (!key) return
    const next = {
      name: String(row?.name || "").replace(/^👑\s*/, "").trim(),
      code: String(row?.code || "").trim(),
      score: Number(row?.score || 0),
    }
    const prev = map.get(key)
    if (!prev || next.score > prev.score) map.set(key, next)
  })
  return map
})

const plateStrengthByName = computed(() => {
  const map = new Map<string, { strength: number; lead: string }>()
  ;(marketData.value?.plateRankTop10 || []).forEach((p: any) => {
    const name = normalizeThemeName(p?.name || "")
    if (!name) return
    map.set(name, { strength: Number(p?.strength || 0), lead: String(p?.lead || "").trim() })
  })
  return map
})

const themeToZtStocks = computed(() => {
  const out = new Map<string, ZtStockPick[]>()
  const ztgc = Array.isArray(marketData.value?.ztgc) ? marketData.value.ztgc : []
  const themesMap = (marketData.value?.zt_code_themes || {}) as Record<string, string[]>
  ztgc.forEach((s: any) => {
    const code = String(s?.dm || s?.code || "").trim()
    if (!code) return
    const themes = (themesMap[code] && themesMap[code].length ? themesMap[code] : s?.hy ? [String(s.hy)] : []).filter(Boolean)
    if (!themes.length) return
    const pick: ZtStockPick = {
      code,
      name: String(s?.mc || s?.name || code),
      lbc: Number(s?.lbc || 0),
      cjeYi: Number(s?.cje || 0) / 1e8,
      zjYi: Number(s?.zj || 0) / 1e8,
      zbc: Number(s?.zbc || 0),
    }
    themes.forEach((t) => {
      const k = String(t).trim()
      if (!k) return
      if (!out.has(k)) out.set(k, [])
      const list = out.get(k)!
      if (!list.some((x) => x.code === pick.code)) list.push(pick)
    })
  })
  return out
})

const findMatchingLocalThemes = (hotName: string): string[] => {
  const key = normalizeThemeName(hotName)
  if (!key) return []
  const matches: string[] = []
  themeToZtStocks.value.forEach((_v, k) => {
    const kk = normalizeThemeName(k)
    if (!kk) return
    if (kk === key) {
      matches.unshift(k)
      return
    }
    if (kk.includes(key) || (key.length >= 3 && key.includes(kk))) matches.push(k)
  })
  return matches
}

const aggregateStocksForTheme = (hotName: string): { stocks: ZtStockPick[]; matched: string[] } => {
  const matched = findMatchingLocalThemes(hotName)
  const dedup = new Map<string, ZtStockPick>()
  matched.forEach((t) => {
    ;(themeToZtStocks.value.get(t) || []).forEach((s) => {
      if (!dedup.has(s.code)) dedup.set(s.code, s)
    })
  })
  const stocks = Array.from(dedup.values())
  stocks.sort((a, b) => b.lbc - a.lbc || b.zjYi - a.zjYi || b.cjeYi - a.cjeYi)
  return { stocks, matched }
}

const scoreClassByValue = (s: number) => {
  if (s >= 70) return "score-strong"
  if (s >= 50) return "score-mid"
  return "score-weak"
}

const buildStockTags = (stock: ZtStockPick, plateName?: string): Array<{ text: string; cls: string }> => {
  const tags: Array<{ text: string; cls: string }> = []
  if (stock.source === "xgb") tags.push({ text: "实时", cls: "stp-chip stp-chip-hot" })
  if ((stock.limitUpDays || 0) >= 2 || stock.lbc >= 2) tags.push({ text: `${Math.max(stock.limitUpDays || 0, stock.lbc)}板`, cls: "stp-chip stp-chip-red" })
  else tags.push({ text: "首板", cls: "stp-chip stp-chip-amber" })
  if ((stock.changePct || 0) >= 8) tags.push({ text: `涨幅+${(stock.changePct || 0).toFixed(1)}%`, cls: "stp-chip stp-chip-red" })
  else if ((stock.changePct || 0) >= 3) tags.push({ text: `涨幅+${(stock.changePct || 0).toFixed(1)}%`, cls: "stp-chip stp-chip-amber" })
  if (stock.zjYi >= 1.5) tags.push({ text: `封${stock.zjYi.toFixed(1)}亿`, cls: "stp-chip stp-chip-blue" })
  else if (stock.cjeYi >= 20) tags.push({ text: `${stock.cjeYi.toFixed(0)}亿`, cls: "stp-chip stp-chip-blue" })
  if (plateName) tags.push({ text: plateName, cls: "stp-chip stp-chip-slate" })
  return tags.slice(0, 4)
}

const calculateStockScore = (stock: ZtStockPick, plateStrength = 0, isRealtimePlate = false) => {
  let score = 24
  score += Math.min(stock.lbc * 15, 45)
  score += Math.min(stock.zjYi * 6, 16)
  score += Math.min(stock.cjeYi * 0.5, 12)
  score += Math.min((stock.changePct || 0) * 1.4, 12)
  score += Math.min(plateStrength / 5, 10)
  if (isRealtimePlate) score += 6
  if (stock.source === "xgb") score += 8
  if ((stock.limitUpDays || 0) >= 2) score += 6
  if (stock.zbc >= 3) score -= 8
  else if (stock.zbc >= 1) score -= 3
  return Math.max(0, Math.min(100, Math.round(score)))
}

const calculateThemeScore = (bucket: { sources: string[]; stocks: ZtStockPick[]; plateStrength?: number; resonanceScore: number }) => {
  let score = 22
  score += Math.min(bucket.resonanceScore * 0.42, 42)
  score += Math.min((bucket.plateStrength || 0) / 4, 16)
  score += Math.min(bucket.stocks.length * 4, 16)
  score += Math.min((bucket.stocks[0]?.lbc || 0) * 6, 18)
  if (bucket.sources.some((x) => x.includes("选股宝"))) score += 6
  if (bucket.sources.some((x) => x.includes("热门"))) score += 5
  return Math.max(0, Math.min(100, Math.round(score)))
}

const buildThemeTags = (theme: string, stocks: ZtStockPick[], sources: string[], plateStrength?: number) => {
  const tags: Array<{ text: string; cls: string }> = []
  if (sources.some((x) => x.includes("选股宝"))) tags.push({ text: "实时热点", cls: "stp-chip stp-chip-hot" })
  if (sources.some((x) => x.includes("热门"))) tags.push({ text: "明日热门", cls: "stp-chip stp-chip-red" })
  if ((stocks[0]?.lbc || 0) >= 3) tags.push({ text: `${stocks[0].lbc}板龙头`, cls: "stp-chip stp-chip-red" })
  else if ((stocks[0]?.lbc || 0) === 2) tags.push({ text: "2板承接", cls: "stp-chip stp-chip-amber" })
  if ((plateStrength || 0) >= 70) tags.push({ text: "板块强", cls: "stp-chip stp-chip-blue" })
  else if ((plateStrength || 0) >= 45) tags.push({ text: "板块活跃", cls: "stp-chip stp-chip-blue" })
  if (stocks.length >= 4) tags.push({ text: `${stocks.length}股联动`, cls: "stp-chip stp-chip-slate" })
  return tags.slice(0, 4)
}

const getRealtimeStocksForPlate = (plateId: string, _plateName: string): ZtStockPick[] => {
  const pid = String(plateId || "").trim()
  const rows = pid ? xgbStocksByPlateId.value?.[pid] || [] : []
  return rows
    .map(
      (s: any): ZtStockPick => ({
        code: String(s?.code || "").trim(),
        name: String(s?.name || "").trim(),
        lbc: Number(s?.limitUpDays || 0),
        cjeYi: 0,
        zjYi: 0,
        zbc: 0,
        source: "xgb" as const,
        changePct: Number(s?.changePct || 0),
        limitUpDays: Number(s?.limitUpDays || 0),
        tags: [],
      }),
    )
    .filter((s: ZtStockPick) => s.code)
}

const calculateResonanceScore = (sources: string[], stocks: ZtStockPick[], plateStrength?: number) => {
  let score = sources.length * 15 // 每个来源 15 分
  score += Math.min(stocks.length * 5, 30) // 涨停个股加分，封顶 30

  const maxLbc = stocks[0]?.lbc || 0
  score += maxLbc * 8 // 连板高度加分

  if (plateStrength) {
    score += Math.min(plateStrength / 4, 30) // 板块强度加分，封顶 30
  }

  if (sources.some((s) => s.includes("热门"))) score += 10 // 热门题材额外加分

  return Math.min(Math.round(score), 100)
}

const makeBucket = (plateId: string, theme: string, source: "realtime" | "fallback" | "advisor", sources: string[], description: string, stocks: ZtStockPick[], matched: string[]): SectorBucket => {
  const realtimeStocks = source === "realtime" ? getRealtimeStocksForPlate(plateId, theme) : []
  const mergedMap = new Map<string, ZtStockPick>()
  ;[...realtimeStocks, ...stocks].forEach((s) => {
    if (!s.code) return
    if (!mergedMap.has(s.code)) mergedMap.set(s.code, s)
    else {
      const prev = mergedMap.get(s.code)!
      mergedMap.set(s.code, {
        ...prev,
        ...s,
        source: prev.source === "xgb" || s.source === "xgb" ? "xgb" : s.source || prev.source,
        changePct: s.changePct ?? prev.changePct,
        limitUpDays: s.limitUpDays ?? prev.limitUpDays,
      })
    }
  })
  const mergedStocks = Array.from(mergedMap.values())
  const maxLbc = mergedStocks[0]?.lbc || 0
  const plateInfo = plateStrengthByName.value.get(theme) || (matched.length ? plateStrengthByName.value.get(matched[0]) : undefined)
  const advisor = advisorForBucket(theme, matched)
  const tide = tideThemeForBucket(theme, matched, advisor)
  const resonanceScore = calculateResonanceScore(sources, mergedStocks, plateInfo?.strength)
  const scoredStocks = mergedStocks
    .map((stock) => {
      const score = calculateStockScore(stock, plateInfo?.strength || 0, source === "realtime")
      return {
        ...stock,
        score,
        tags: buildStockTags(stock, theme),
      }
    })
    .sort((a, b) => Number(b.score || 0) - Number(a.score || 0) || b.lbc - a.lbc || (b.changePct || 0) - (a.changePct || 0) || b.zjYi - a.zjYi || b.cjeYi - a.cjeYi)
  const themeScore = calculateThemeScore({ sources, stocks: scoredStocks, plateStrength: plateInfo?.strength, resonanceScore })
  const themeTags = buildThemeTags(theme, scoredStocks, sources, plateInfo?.strength)

  return {
    theme,
    source,
    sources,
    description,
    count: scoredStocks.length,
    maxLbc,
    highTier: scoredStocks.filter((s) => s.lbc >= 3).slice(0, 3),
    midTier: scoredStocks.filter((s) => s.lbc === 2).slice(0, 3),
    baseTier: scoredStocks.filter((s) => s.lbc <= 1).slice(0, 3),
    plateStrength: plateInfo?.strength,
    plateLead: plateInfo?.lead,
    matchedLocalThemes: matched,
    resonanceScore,
    themeScore,
    themeTags,
    advisor,
    tide,
  }
}

const buildThemePanelFallbackBuckets = (): SectorBucket[] => {
  return themePanelRows.value
    .map((row: any) => {
      const theme = String(row?.name || "").trim()
      if (!theme) return null
      const { stocks, matched } = aggregateStocksForTheme(theme)
      const leader = leaderByTheme.value.get(normalizeThemeName(theme))
      const zt = Number(row?.zt || 0)
      const zb = Number(row?.zb || 0)
      const dt = Number(row?.dt || 0)
      const net = Number(row?.net || 0)
      const risk = Number(row?.risk || 0)
      const descBits = [
        `${zt}涨停`,
        zb > 0 ? `${zb}炸板` : "",
        dt > 0 ? `${dt}跌停` : "",
        Number.isFinite(net) ? `净强${net.toFixed(1)}` : "",
        Number.isFinite(risk) ? `风险${risk.toFixed(1)}` : "",
        leader?.name ? `龙头${leader.name}` : "",
      ].filter(Boolean)
      const bucket = makeBucket("", theme, "fallback", ["本地板块推测"], descBits.join(" · "), stocks, matched)
      bucket.plateStrength = Math.max(0, Math.min(100, Math.round(50 + zt * 5 - zb * 4 - dt * 6 + net * 4 - risk * 3)))
      bucket.plateLead = bucket.plateLead || leader?.name || ""

      if (!bucket.count && leader?.code && leader?.name) {
        bucket.count = 1
        bucket.baseTier = [
          {
            code: leader.code,
            name: leader.name,
            lbc: 0,
            cjeYi: 0,
            zjYi: 0,
            zbc: 0,
            source: "local",
            score: Math.max(55, Math.round(leader.score || 0)),
            tags: [{ text: "题材龙头", cls: "stp-chip stp-chip-red" }],
          },
        ]
      }

      bucket.themeTags = [
        ...bucket.themeTags,
        ...(risk >= 4.5 || zb >= 3 || dt >= 3
          ? [{ text: "高分歧", cls: "stp-chip stp-chip-amber" }]
          : [{ text: "本地推测", cls: "stp-chip stp-chip-slate" }]),
      ].slice(0, 4)
      return bucket
    })
    .filter((x: SectorBucket | null): x is SectorBucket => !!x)
}

const getEchelonFormation = (bucket: SectorBucket) => {
  const counts = new Map<number, number>()
  ;[...bucket.highTier, ...bucket.midTier, ...bucket.baseTier].forEach((s) => {
    counts.set(s.lbc, (counts.get(s.lbc) || 0) + 1)
  })
  const tiers = Array.from(counts.keys()).sort((a, b) => b - a)
  if (!tiers.length) return ""
  return tiers.map((lbc) => `${lbc}板(${counts.get(lbc)})`).join(" → ")
}

const sectorTierPicks = computed<SectorBucket[]>(() => {
  void xgbUpdatedAt.value
  void tmrUpdatedAt.value

  const ztgcLen = Array.isArray(marketData.value?.ztgc) ? marketData.value.ztgc.length : 0
  if (!ztgcLen) return []

  const xgb = xgbPlates.value
  const tmr = tmrThemes.value

  // 实时优先:用选股宝热点板块 / 东财明日题材驱动
  const realtimeBuckets = new Map<string, SectorBucket>()
  xgb.forEach((p) => {
    const name = String(p.name || "").trim()
    if (!name || realtimeBuckets.has(name)) return
    const { stocks, matched } = aggregateStocksForTheme(name)
    realtimeBuckets.set(name, makeBucket(p.id, name, "realtime", ["选股宝热点"], p.description || "", stocks, matched))
  })
  tmr.forEach((t) => {
    const name = String(t.themeName || "").trim()
    if (!name) return
    if (realtimeBuckets.has(name)) {
      const exist = realtimeBuckets.get(name)!
      if (!exist.sources.includes(t.isHot ? "明日热门" : "明日")) {
        exist.sources.push(t.isHot ? "明日热门" : "明日")
      }
      if (!exist.description && t.summary) exist.description = t.summary
      return
    }
    // 只让明日热门进入(非热门跳过避免噪音)
    if (!t.isHot) return
    const { stocks, matched } = aggregateStocksForTheme(name)
    realtimeBuckets.set(name, makeBucket("", name, "realtime", ["明日热门"], t.summary || "", stocks, matched))
  })

  let buckets = Array.from(realtimeBuckets.values())

  // 实时数据完全为空 → 本地兜底:按 ztgc theme 命中数最高的前 N 个 theme
  if (!xgb.length && !tmr.length) {
    const themeCount = new Map<string, number>()
    const themesMap = (marketData.value?.zt_code_themes || {}) as Record<string, string[]>
    Object.values(themesMap).forEach((arr: any) => {
      ;(Array.isArray(arr) ? arr : []).forEach((t: any) => {
        const k = String(t || "").trim()
        if (!k) return
        themeCount.set(k, (themeCount.get(k) || 0) + 1)
      })
    })
    const sortedThemes = Array.from(themeCount.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([t]) => t)
      .slice(0, 8)
    sortedThemes.forEach((t) => {
      const { stocks, matched } = aggregateStocksForTheme(t)
      buckets.push(makeBucket("", t, "fallback", ["本地涨停归集"], "", stocks, matched))
    })
  } else {
    // 实时有数据,但有些 hot plate 在涨停池里完全没匹配到 → 仍然展示(空梯队),提示"narrative热但价格未跟"
    // (已经包含在 realtimeBuckets,无需额外动作)
  }

  ;(picksAdvisor.value?.main_line_picks || []).forEach((ml) => {
    const exists = buckets.some((bucket) => advisorMatchesTheme(ml, bucket.theme, bucket.matchedLocalThemes))
    if (exists) return
    const { stocks, matched } = aggregateStocksForTheme(ml.main_line)
    const advisorStocks = [...(ml.buy || []), ...(ml.watch || [])].map(advisorStockToZtPick).filter((s) => s.code)
    const merged = new Map<string, ZtStockPick>()
    ;[...advisorStocks, ...stocks].forEach((s) => {
      if (!s.code || merged.has(s.code)) return
      merged.set(s.code, s)
    })
    buckets.push(makeBucket("", ml.main_line, "advisor", ["推荐线"], ml.summary || "", Array.from(merged.values()), matched))
  })

  if (!buckets.length) {
    buckets = buildThemePanelFallbackBuckets()
  }

  // 排序:共振评分优先 → 有涨停股的在前 → maxLbc
  buckets.sort((a, b) => {
    if (b.resonanceScore !== a.resonanceScore) return b.resonanceScore - a.resonanceScore
    const aHas = a.count > 0 ? 1 : 0
    const bHas = b.count > 0 ? 1 : 0
    if (aHas !== bHas) return bHas - aHas
    return b.maxLbc - a.maxLbc
  })

  return buckets.slice(0, 6)
})

const sectorPicksMeta = computed(() => {
  void xgbUpdatedAt.value
  void tmrUpdatedAt.value
  const buckets = sectorTierPicks.value
  const realtimeCnt = buckets.filter((b) => b.source === "realtime").length
  const fallbackUsed = buckets.some((b) => b.source === "fallback")
  return {
    bucketTotal: buckets.length,
    realtimeCnt,
    fallbackUsed,
    advisorCnt: buckets.filter((b) => b.advisor).length,
    xgbCnt: xgbPlates.value.length,
    tmrCnt: tmrThemes.value.length,
    tmrHotCnt: tmrThemes.value.filter((t) => t.isHot).length,
  }
})
</script>

<template>
  <div class="plan-page">
    <div class="card" data-page="plan" id="sec-action">
      <div class="card-title">行动指南</div>
      <div class="plan-top-grid">
        <div class="plan-main-stack">
          <div class="v2-strategy" v-if="planGuide">
            <div class="row">
              <div class="head-main">
                <div class="tone">{{ planGuide.phase || "-" }}</div>
                <span class="plan-score-badge">
                  <strong>{{ planGuide.score ?? "-" }}</strong>
                </span>
              </div>
              <div>
                <span class="pos-k">仓位：</span>
                <span class="pos-v" :class="positionAdvice.cls">{{ positionAdvice.range }}</span>
              </div>

              <div class="pos-tags">
                <span class="pos-pill" :class="positionAdvice.pillCls">{{ positionAdvice.stance }}</span>
                <span class="pos-pill">热{{ marketData.mood?.heat ?? "-" }}/险{{ marketData.mood?.risk ?? "-" }}</span>
                <span class="pos-pill">{{ marketData.moodStage?.title || "-" }}</span>
              </div>
            </div>
            <div class="advice" :class="planGuide.rightsideText === '禁止' ? 'danger' : planGuide.rightsideText === '允许' ? '' : 'warn'" v-if="planGuide.advice">{{ planGuide.advice }}</div>
            <div class="kpis">
              <span v-for="(pill, idx) in planGuidePills" :key="'pg-pill-' + idx" class="pill" :class="{ primary: pill.primary }">{{ pill.text }}</span>
            </div>
            <ul class="rules">
              <li v-for="(r, i) in planGuideWarnings" :key="'c-w-' + i">{{ r }}</li>
            </ul>
          </div>

        </div>
      </div>
    </div>

    <div class="card" data-page="plan" id="sec-sector-tier-picks" v-if="sectorTierPicks.length">
      <div class="card-header">
        <div>
          <div class="card-title">板块·梯队推票</div>
          <div class="stp-subtitle">
            <span class="stp-dot-realtime"></span>
            实时驱动
            <strong>{{ sectorPicksMeta.realtimeCnt }}</strong>
            <span class="stp-sep">·</span>
            {{ sectorPicksMeta.xgbCnt }}
            <span class="stp-sep">·</span>
            {{ sectorPicksMeta.tmrHotCnt }}/{{ sectorPicksMeta.tmrCnt }}
            <template v-if="sectorPicksMeta.advisorCnt">
              <span class="stp-sep">·</span>
              推荐线
              <strong>{{ sectorPicksMeta.advisorCnt }}</strong>
            </template>
            <template v-if="sectorPicksMeta.fallbackUsed">
              <span class="stp-sep">·</span>
              <span class="orange-text" style="font-weight: 900" title="实时接口无数据,退回本地涨停归集">⚠ 本地兜底</span>
            </template>
          </div>
        </div>
        <div class="card-badge">narrative × 涨停 × 梯队</div>
      </div>
      <div class="sector-tier-grid">
        <div
          v-for="(bucket, i) in sectorTierPicks"
          :key="'stp-' + bucket.theme + '-' + i"
          class="sector-tier-card"
          :class="[bucket.source === 'realtime' ? 'is-realtime' : bucket.source === 'advisor' ? 'is-advisor' : 'is-fallback', !bucket.count ? 'is-empty' : '']">
          <div class="stp-head">
            <div class="stp-name">
              <span class="stp-rank">{{ i + 1 }}</span>
              <span class="stp-name-text">{{ bucket.theme }}</span>
              <span class="stp-theme-score" :class="scoreClass(bucket.themeScore)">主题 {{ bucket.themeScore }}</span>
              <span class="stp-resonance-badge" :class="scoreClass(bucket.resonanceScore)">共振 {{ bucket.resonanceScore }}</span>
            </div>
            <span class="stp-tide-corner" :class="tideCornerClass(bucket.tide?.status)" :title="tideCornerTitle(bucket.tide)">
              {{ tideCornerText(bucket.tide) }}
            </span>
          </div>
          <div class="stp-tag-row" v-if="bucket.themeTags?.length">
            <span v-for="(tag, ti) in bucket.themeTags" :key="'theme-tag-' + bucket.theme + '-' + ti" :class="tag.cls">{{ tag.text }}</span>
          </div>
          <div class="stp-meta">
            <span class="stp-kv">
              <strong :class="bucket.count >= 3 ? 'red-text' : 'orange-text'">{{ bucket.count }}</strong>
              只涨停
            </span>
            <span class="stp-sep" v-if="bucket.maxLbc >= 2">·</span>
            <span class="stp-kv" v-if="bucket.maxLbc >= 2">
              最高
              <strong class="red-text">{{ bucket.maxLbc }}</strong>
              板
            </span>
            <span class="stp-sep" v-if="bucket.plateStrength">·</span>
            <span class="stp-kv" v-if="bucket.plateStrength">
              强度
              <strong>{{ Math.round(bucket.plateStrength) }}</strong>
            </span>
            <span class="stp-sep" v-if="bucket.plateLead">·</span>
            <span class="stp-kv" v-if="bucket.plateLead">
              领涨
              <strong>{{ bucket.plateLead }}</strong>
            </span>
            <div class="stp-formation" v-if="getEchelonFormation(bucket)">
              梯队阵型：
              <strong>{{ getEchelonFormation(bucket) }}</strong>
            </div>
          </div>
          <div v-if="bucket.tide && bucket.tide.action_hint && bucket.tide.status !== 'neutral'" :class="tideHintClass(bucket.tide.warning_level)">
            {{ bucket.tide.action_hint }}
          </div>
          <div class="stp-desc" v-if="bucket.description" :title="bucket.description">{{ bucket.description }}</div>
          <div class="stp-advisor" v-if="bucket.advisor">
            <div class="stp-advisor-head">
              <span>推票明细</span>
              <span v-if="bucket.advisor.diagnostics?.member_count">{{ bucket.advisor.diagnostics.member_count }}只成员</span>
            </div>
            <div class="stp-advisor-section" v-if="bucket.advisor.buy?.length">
              <div class="stp-advisor-label buy">推荐</div>
              <a class="stp-advisor-row buy" v-for="s in bucket.advisor.buy" :key="'stp-buy-' + bucket.theme + '-' + s.code" :href="xqUrl(s.code)" target="_blank" rel="noopener noreferrer">
                <span class="stp-advisor-name">{{ s.name }}</span>
                <span class="stp-advisor-score" :class="scoreClass(s.score)">评 {{ s.score }}</span>
                <span class="stp-advisor-tag" v-if="pickPrimaryTag(s)">{{ pickPrimaryTag(s) }}</span>
                <span class="stp-advisor-reason" v-for="(r, ri) in pickReasonBrief(s)" :key="'stp-buy-r-' + s.code + '-' + ri">{{ r }}</span>
              </a>
            </div>
            <div class="stp-advisor-section" v-if="bucket.advisor.watch?.length">
              <div class="stp-advisor-label watch">观察</div>
              <div class="stp-advisor-watch">
                <a
                  class="stp-advisor-watch-item"
                  v-for="s in bucket.advisor.watch"
                  :key="'stp-watch-' + bucket.theme + '-' + s.code"
                  :href="xqUrl(s.code)"
                  target="_blank"
                  rel="noopener noreferrer"
                  :title="s.reasons.join(' · ')">
                  <span>{{ s.name }}</span>
                  <strong :class="scoreClass(s.score)">{{ s.score }}</strong>
                  <em v-if="pickPrimaryTag(s)">{{ pickPrimaryTag(s) }}</em>
                </a>
              </div>
            </div>
          </div>
          <div class="stp-empty" v-if="!bucket.count">narrative 热但涨停池暂未跟上 · 留意首板异动</div>
          <div class="stp-tiers" v-else>
            <div class="stp-tier-block" v-if="bucket.highTier.length">
              <div class="stp-tier-label tier-high">高位 ≥3连</div>
              <div class="stp-high-rows">
                <a v-for="s in bucket.highTier" :key="'h-' + bucket.theme + '-' + s.code" class="stp-high-row" :href="xqUrl(s.code)" target="_blank" rel="noopener noreferrer">
                  <span class="stp-star">★</span>
                  <span class="stp-high-name">{{ s.name }}</span>
                  <span class="stp-stock-score" :class="scoreClass(Number(s.score || 0))">{{ s.score }}</span>
                  <span class="stp-high-tag">{{ s.lbc }}板</span>
                  <span class="stp-high-fund" v-if="s.zjYi >= 1">封 {{ s.zjYi.toFixed(1) }}亿</span>
                  <span class="stp-high-fund" v-else-if="s.cjeYi >= 1">{{ s.cjeYi.toFixed(1) }}亿</span>
                </a>
              </div>
            </div>
            <div class="stp-tier-block" v-if="bucket.midTier.length">
              <div class="stp-tier-label tier-mid">中位 2连</div>
              <div class="stp-name-row">
                <a v-for="(s, mi) in bucket.midTier" :key="'m-' + bucket.theme + '-' + s.code" class="stp-name-link mid" :href="xqUrl(s.code)" target="_blank" rel="noopener noreferrer">
                  {{ s.name }}
                  <span class="stp-inline-score" :class="scoreClass(Number(s.score || 0))">{{ s.score }}</span>
                  <span v-if="mi < bucket.midTier.length - 1" class="stp-name-sep">·</span>
                </a>
              </div>
            </div>
            <div class="stp-tier-block" v-if="bucket.baseTier.length">
              <div class="stp-tier-label tier-base">
                首板
                <span class="stp-tier-count">({{ bucket.count - bucket.highTier.length - bucket.midTier.length }})</span>
              </div>
              <div class="stp-name-row">
                <a v-for="(s, bi) in bucket.baseTier" :key="'b-' + bucket.theme + '-' + s.code" class="stp-name-link base" :href="xqUrl(s.code)" target="_blank" rel="noopener noreferrer">
                  {{ s.name }}
                  <span class="stp-inline-score" :class="scoreClass(Number(s.score || 0))">{{ s.score }}</span>
                  <span v-if="bi < bucket.baseTier.length - 1" class="stp-name-sep">·</span>
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="card" data-page="plan" id="sec-zt-analysis">
      <div class="card-header">
        <div class="zt-header-left">
          <div class="card-title">
            <span>涨停数据分析</span>
            <span class="zt-header-sector" v-if="marketData.ztAnalysis?.meta?.tierThemeCount">
              梯队：{{ marketData.ztAnalysis?.meta?.tierThemeCount }}板块
              <template v-if="marketData.ztAnalysis?.meta?.tierThemeTop">（{{ marketData.ztAnalysis?.meta?.tierThemeTop }}）</template>
            </span>
            <div class="zt-header-meta-inline">
              <span class="sep">｜</span>
              涨停池
              <span class="orange-text">{{ marketData.ztgc?.length ?? 0 }}</span>
              <span class="sep">·</span>
              题材映射
              <span class="orange-text">{{ marketData.zt_code_themes ? Object.keys(marketData.zt_code_themes).length : 0 }}</span>
            </div>
          </div>
        </div>
        <div class="zt-header-actions">
          <div class="card-badge">封单 · 板块归属 · 量能 · 炸板 · 梯队</div>
          <button class="plan-toggle-btn" :class="{ expanded: ztAnalysisExpanded }" type="button" :aria-expanded="ztAnalysisExpanded" @click="ztAnalysisExpanded = !ztAnalysisExpanded">
            <span class="plan-toggle-btn__label">涨停数据分析</span>
            <span class="plan-toggle-btn__state">{{ ztAnalysisExpanded ? "收起" : "展开" }}</span>
          </button>
        </div>
      </div>
      <div v-if="ztAnalysisExpanded" class="zt-panel">
        <div class="zt-col">
          <div class="section-header">接力候选</div>
          <div class="zt-list">
            <div class="zt-item" v-for="(row, i) in ztRelaySorted" :key="'relay-' + i">
              <div class="zt-top">
                <div>
                  <div class="zt-name">
                    <a v-if="row.code" class="stock-link" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
                    <span v-else>{{ row.name }}</span>
                  </div>
                  <div class="zt-sub" v-html="row.reason"></div>
                </div>
                <div class="zt-score" :class="row.superLeaderTone || ''" :title="row.factorHint || ''">
                  <div class="v">{{ row.factorScore ?? row.score }}</div>
                  <div class="k">{{ row.scoreLabel || "接力优先" }}</div>
                  <div class="g" v-if="row.scoreSubLabel">{{ row.scoreSubLabel }}</div>
                </div>
              </div>
              <div class="zt-mainline-row" v-if="mainLineOf(row.code)">
                <span class="zt-ml-chip">🏷 {{ mainLineOf(row.code)?.primary_sector }}</span>
                <span class="zt-ml-line" v-if="mainLineOf(row.code)?.main_line">
                  · 主线
                  <strong>{{ mainLineOf(row.code)?.main_line }}</strong>
                </span>
              </div>
              <div class="zt-enrich-row" v-if="row.capacityLabel && row.capacityLabel !== '小盘'">
                <span class="zt-enrich-chip enrich-cap">{{ row.capacityLabel }}</span>
              </div>
              <div class="zt-tags">
                <div class="zt-tag-row" v-for="tagRow in ztTagRows(row)" :key="'relay-tag-row-' + i + '-' + tagRow.tone" :class="'zt-tag-row-' + tagRow.tone">
                  <span class="ladder-chip" v-for="(t, ti) in tagRow.tags" :key="'relay-tag-' + i + '-' + tagRow.tone + '-' + ti" :class="t.cls">{{ t.text }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="zt-col">
          <div class="section-header">观察池（大容量/前龙头，看情绪反馈）</div>
          <div class="zt-list">
            <div class="zt-item" v-for="(row, i) in ztWatchSorted" :key="'watch-' + i">
              <div class="zt-top">
                <div>
                  <div class="zt-name">
                    <a v-if="row.code" class="stock-link" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
                    <span v-else>{{ row.name }}</span>
                  </div>
                  <div class="zt-sub" v-html="row.reason"></div>
                </div>
                <div class="zt-score" :class="row.superLeaderTone || ''" :title="row.factorHint || ''">
                  <div class="v">{{ row.factorScore ?? row.score }}</div>
                  <div class="k">{{ row.scoreLabel || row.watchGroup || "观察参考" }}</div>
                  <div class="g" v-if="row.scoreSubLabel || row.watchGroup">{{ row.scoreSubLabel || row.watchGroup }}</div>
                </div>
              </div>
              <div class="zt-mainline-row" v-if="mainLineOf(row.code)">
                <span class="zt-ml-chip">🏷 {{ mainLineOf(row.code)?.primary_sector }}</span>
                <span class="zt-ml-line" v-if="mainLineOf(row.code)?.main_line">
                  · 主线
                  <strong>{{ mainLineOf(row.code)?.main_line }}</strong>
                </span>
              </div>
              <div class="zt-enrich-row" v-if="row.capacityLabel && row.capacityLabel !== '小盘'">
                <span class="zt-enrich-chip enrich-cap">{{ row.capacityLabel }}</span>
              </div>
              <div class="zt-tags">
                <div class="zt-tag-row" v-for="tagRow in ztTagRows(row)" :key="'watch-tag-row-' + i + '-' + tagRow.tone" :class="'zt-tag-row-' + tagRow.tone">
                  <span class="ladder-chip" v-for="(t, ti) in tagRow.tags" :key="'watch-tag-' + i + '-' + tagRow.tone + '-' + ti" :class="t.cls">{{ t.text }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="summary-box" v-if="!marketData.ztgc || !marketData.ztgc.length">
        <div class="summary-text">未注入当日涨停池明细（ztgc）。请用渲染脚本从 pools_cache.json 注入后再查看本模块。</div>
      </div>
      <div class="summary-box" v-else-if="!((marketData.ztAnalysis?.relay || []).length || (marketData.ztAnalysis?.watch || []).length)">
        <div class="summary-text">涨停分析暂未生成，请检查涨停池、题材映射或前端派生逻辑。</div>
      </div>
      <div v-else-if="!ztAnalysisExpanded" class="zt-collapsed-note">默认折叠，展开后查看接力候选、观察池以及每只票的封单、炸板、梯队和题材归属。</div>
    </div>

    <div class="card" data-page="plan" id="sec-zt-debug" v-if="isLocalDebug && ztDebugRows.length">
      <div class="card-header">
        <div>
          <div class="card-title">预测算法调试台</div>
          <div class="advisor-subtitle">
            接力
            <strong class="red-text">{{ ztDebugSummary.relay }}</strong>
            <span class="stp-sep">·</span>
            观察
            <strong class="orange-text">{{ ztDebugSummary.watch }}</strong>
            <span class="stp-sep">·</span>
            未入池
            <strong class="blue-text">{{ ztDebugSummary.excluded }}</strong>
          </div>
        </div>
        <button class="plan-toggle-btn plan-toggle-btn-debug" :class="{ expanded: ztDebugExpanded }" type="button" :aria-expanded="ztDebugExpanded" @click="ztDebugExpanded = !ztDebugExpanded">
          <span class="plan-toggle-btn__label">调试明细</span>
          <span class="plan-toggle-btn__state">{{ ztDebugExpanded ? "收起" : "展开" }}</span>
        </button>
      </div>
      <div v-if="ztDebugExpanded" class="zt-debug-panel">
        <div class="zt-debug-toolbar">
          <button class="abnormal-switch" :class="{ active: ztDebugPlacement === 'all' }" type="button" @click="ztDebugPlacement = 'all'">全部</button>
          <button class="abnormal-switch" :class="{ active: ztDebugPlacement === 'relay' }" type="button" @click="ztDebugPlacement = 'relay'">接力池</button>
          <button class="abnormal-switch" :class="{ active: ztDebugPlacement === 'watch' }" type="button" @click="ztDebugPlacement = 'watch'">观察池</button>
          <button class="abnormal-switch" :class="{ active: ztDebugPlacement === 'excluded' }" type="button" @click="ztDebugPlacement = 'excluded'">未入池</button>
        </div>
        <div class="zt-debug-list">
          <div class="zt-debug-item" v-for="row in ztDebugFiltered" :key="'dbg-' + row.code + '-' + row.name">
            <div class="zt-debug-top">
              <div class="zt-debug-main">
                <div class="zt-debug-title">
                  <a v-if="row.code" class="stock-link" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
                  <span v-else>{{ row.name }}</span>
                  <span class="zt-debug-place" :class="ztDebugPlacementClass(row.placement)">{{ row.placementLabel }}</span>
                  <span class="zt-debug-step">{{ row.nextStep || `${row.lbc}板` }}</span>
                  <span class="zt-debug-theme" v-if="row.predTheme">{{ row.predTheme }}</span>
                </div>
                <div class="zt-debug-sub">{{ row.factorHint }}</div>
              </div>
              <div class="zt-debug-score">
                <div class="advisor-score" :class="ztDebugScoreClass(Number(row.score || 0))">总 {{ row.score }}</div>
                <div class="zt-debug-score-line">
                  <span>龙 {{ row.leaderFactorScore }}</span>
                  <span>接 {{ row.relayFactorScore }}</span>
                  <span>容 {{ row.capacityFactorScore }}</span>
                  <span>险 {{ row.riskControlScore }}</span>
                </div>
              </div>
            </div>
            <div class="zt-debug-meta">
              <span>环境 {{ row.environmentScore }}</span>
              <span>哲学 {{ row.leaderPhilosophyScore }}</span>
              <span>承接 {{ row.stepContextScore }}</span>
              <span>断板风险 {{ row.breakRisk }}</span>
              <span>开板 {{ row.open }}</span>
              <span v-if="row.marketGateLabel">环境位 {{ row.marketGateLabel }}</span>
            </div>
            <div class="zt-debug-bits" v-if="row.hitRules?.length">
              <span class="zt-debug-bit hit" v-for="hit in row.hitRules" :key="'hit-' + row.code + '-' + hit">{{ hit }}</span>
            </div>
            <div class="zt-debug-bits" v-if="row.blockReasons?.length">
              <span class="zt-debug-bit block" v-for="reason in row.blockReasons" :key="'block-' + row.code + '-' + reason">{{ reason }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.zt-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.plan-toggle-btn {
  appearance: none;
  border: 1px solid color-mix(in oklab, var(--theme-accent) 18%, rgba(148, 163, 184, 0.28));
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.94), rgba(255, 247, 237, 0.9)), var(--bg-card);
  color: var(--text-primary);
  min-height: 38px;
  padding: 0 12px 0 14px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  gap: 9px;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.02em;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
  transition:
    transform 180ms ease,
    box-shadow 180ms ease,
    border-color 180ms ease,
    background 180ms ease;
}

.plan-toggle-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.1);
}

.plan-toggle-btn:active {
  transform: translateY(0);
}

.plan-toggle-btn__label {
  color: var(--text-secondary);
}

.plan-toggle-btn__state {
  color: #b45309;
}

.plan-toggle-btn.expanded {
  border-color: rgba(230, 0, 18, 0.22);
  background: linear-gradient(135deg, rgba(255, 243, 243, 0.96), rgba(255, 236, 230, 0.94)), var(--bg-card);
  box-shadow: 0 12px 28px rgba(230, 0, 18, 0.12);
}

.plan-toggle-btn.expanded .plan-toggle-btn__label,
.plan-toggle-btn.expanded .plan-toggle-btn__state {
  color: #b42318;
}

.plan-toggle-btn-debug {
  min-width: 126px;
  justify-content: center;
}

.zt-collapsed-note {
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px dashed rgba(245, 158, 11, 0.3);
  background: linear-gradient(135deg, rgba(255, 249, 235, 0.92), rgba(255, 255, 255, 0.88));
  color: var(--text-secondary);
  font-size: 11.5px;
  font-weight: 750;
  line-height: 1.6;
}

[data-theme="dark"] .plan-toggle-btn {
  background: linear-gradient(135deg, rgba(30, 41, 59, 0.92), rgba(15, 23, 42, 0.88)), var(--bg-card);
  border-color: rgba(148, 163, 184, 0.24);
  box-shadow: 0 10px 24px rgba(2, 6, 23, 0.28);
}

[data-theme="dark"] .plan-toggle-btn__label {
  color: rgba(226, 232, 240, 0.88);
}

[data-theme="dark"] .plan-toggle-btn__state {
  color: #fdba74;
}

[data-theme="dark"] .plan-toggle-btn.expanded {
  border-color: rgba(248, 113, 113, 0.28);
  background: linear-gradient(135deg, rgba(69, 10, 10, 0.42), rgba(30, 41, 59, 0.92)), var(--bg-card);
  box-shadow: 0 14px 30px rgba(127, 29, 29, 0.24);
}

[data-theme="dark"] .zt-collapsed-note {
  background: linear-gradient(135deg, rgba(120, 53, 15, 0.22), rgba(30, 41, 59, 0.92));
  border-color: rgba(251, 191, 36, 0.26);
}

.zt-debug-panel {
  display: grid;
  gap: 10px;
}

.zt-debug-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.zt-debug-list {
  display: grid;
  gap: 10px;
}

.zt-debug-item {
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.72);
  padding: 10px 12px;
}

[data-theme="dark"] .zt-debug-item {
  background: rgba(15, 23, 42, 0.48);
  border-color: rgba(148, 163, 184, 0.2);
}

.zt-debug-top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.zt-debug-main {
  min-width: 0;
}

.zt-debug-title {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 13px;
  font-weight: 950;
  color: var(--text-primary);
}

.zt-debug-sub {
  margin-top: 4px;
  font-size: 11px;
  font-weight: 800;
  color: var(--text-muted);
  line-height: 1.5;
}

.zt-debug-place,
.zt-debug-step,
.zt-debug-theme,
.zt-debug-bit {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 900;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(255, 255, 255, 0.72);
  color: var(--text-secondary);
}

.zt-debug-place.debug-place-relay {
  color: #e60012;
  border-color: rgba(230, 0, 18, 0.18);
  background: rgba(230, 0, 18, 0.08);
}

.zt-debug-place.debug-place-watch {
  color: #d97706;
  border-color: rgba(217, 119, 6, 0.2);
  background: rgba(245, 158, 11, 0.1);
}

.zt-debug-place.debug-place-excluded {
  color: #475569;
}

.zt-debug-score {
  flex: 0 0 auto;
  display: grid;
  justify-items: end;
  gap: 6px;
}

.zt-debug-score-line,
.zt-debug-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 11px;
  font-weight: 850;
  color: var(--text-secondary);
}

.zt-debug-meta {
  margin-top: 8px;
}

.zt-debug-bits {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.zt-debug-bit.hit {
  color: #e60012;
  border-color: rgba(230, 0, 18, 0.18);
  background: rgba(230, 0, 18, 0.08);
}

.zt-debug-bit.block {
  color: #0f766e;
  border-color: rgba(15, 118, 110, 0.16);
  background: rgba(20, 184, 166, 0.08);
}

:deep(.sector-tier-card.is-advisor) {
  border-color: rgba(230, 0, 18, 0.16);
  background: linear-gradient(135deg, rgba(255, 241, 242, 0.52), rgba(255, 255, 255, 0.72)), var(--bg-card);
}

.stp-advisor {
  margin-top: 10px;
  padding: 9px 10px;
  border-radius: 8px;
  border: 1px solid rgba(230, 0, 18, 0.12);
  background: linear-gradient(135deg, rgba(255, 247, 247, 0.84), rgba(255, 255, 255, 0.72));
}

.stp-advisor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 7px;
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 950;
}

.stp-advisor-head span:first-child {
  color: #b91c1c;
}

.stp-advisor-section + .stp-advisor-section {
  margin-top: 8px;
}

.stp-advisor-label {
  margin-bottom: 5px;
  font-size: 10.5px;
  font-weight: 950;
}

.stp-advisor-label.buy {
  color: var(--danger);
}

.stp-advisor-label.watch {
  color: var(--warning);
}

.stp-advisor-row {
  display: grid;
  grid-template-columns: minmax(66px, 1fr) auto auto;
  align-items: center;
  gap: 6px;
  padding: 6px 0;
  color: var(--text-primary);
  text-decoration: none;
  border-top: 1px dashed rgba(148, 163, 184, 0.18);
}

.stp-advisor-row:first-of-type {
  border-top: 0;
}

.stp-advisor-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 950;
}

.stp-advisor-score,
.stp-advisor-tag {
  white-space: nowrap;
  border-radius: 6px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  padding: 1px 6px;
  font-size: 10.5px;
  font-weight: 950;
  background: rgba(255, 255, 255, 0.72);
}

.stp-advisor-reason {
  grid-column: 1 / -1;
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 800;
}

.stp-advisor-watch {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.stp-advisor-watch-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  max-width: 100%;
  color: var(--text-secondary);
  text-decoration: none;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 7px;
  padding: 4px 7px;
  background: rgba(255, 255, 255, 0.68);
  font-size: 11.5px;
  font-weight: 850;
}

.stp-advisor-watch-item span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stp-advisor-watch-item strong {
  font-size: 10.5px;
}

.stp-advisor-watch-item em {
  color: var(--text-muted);
  font-style: normal;
  font-size: 10px;
}

.stp-tide-corner {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  max-width: 168px;
  min-height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(248, 250, 252, 0.82);
  color: var(--text-secondary);
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.06);
  font-size: 10.5px;
  font-weight: 950;
  line-height: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stp-tide-corner.is-main {
  color: #b91c1c;
  border-color: rgba(239, 68, 68, 0.24);
  background: rgba(254, 226, 226, 0.68);
}

.stp-tide-corner.is-watch {
  color: #b45309;
  border-color: rgba(245, 158, 11, 0.28);
  background: rgba(254, 243, 199, 0.72);
}

.stp-tide-corner.is-risk {
  color: #7f1d1d;
  border-color: rgba(185, 28, 28, 0.3);
  background: linear-gradient(135deg, rgba(254, 202, 202, 0.86), rgba(255, 247, 237, 0.7));
}

.stp-tide-corner.is-weak {
  color: #475569;
  border-color: rgba(100, 116, 139, 0.26);
  background: rgba(241, 245, 249, 0.82);
}

.stp-tide-corner.is-neutral {
  color: #64748b;
}

.stp-tide-hint {
  margin-top: 7px;
  padding: 7px 9px;
  border-radius: 8px;
  border: 1px dashed rgba(148, 163, 184, 0.22);
  background: rgba(248, 250, 252, 0.72);
  color: var(--text-secondary);
  font-size: 11.5px;
  font-weight: 850;
  line-height: 1.55;
}

.stp-tide-hint.is-watch {
  border-color: rgba(245, 158, 11, 0.28);
  background: rgba(255, 251, 235, 0.78);
  color: #92400e;
}

.stp-tide-hint.is-risk {
  border-color: rgba(239, 68, 68, 0.28);
  background: rgba(254, 242, 242, 0.78);
  color: #991b1b;
}

[data-theme="dark"] :deep(.sector-tier-card.is-advisor) {
  background: linear-gradient(135deg, rgba(69, 10, 10, 0.2), rgba(15, 23, 42, 0.62)), var(--bg-card);
}

[data-theme="dark"] .stp-advisor {
  background: linear-gradient(135deg, rgba(69, 10, 10, 0.28), rgba(15, 23, 42, 0.54));
  border-color: rgba(248, 113, 113, 0.18);
}

[data-theme="dark"] .stp-advisor-score,
[data-theme="dark"] .stp-advisor-tag,
[data-theme="dark"] .stp-advisor-watch-item {
  background: rgba(15, 23, 42, 0.58);
}

[data-theme="dark"] .stp-tide-corner,
[data-theme="dark"] .stp-tide-hint {
  background: rgba(15, 23, 42, 0.58);
  border-color: rgba(148, 163, 184, 0.22);
}

[data-theme="dark"] .stp-tide-corner.is-main,
[data-theme="dark"] .stp-tide-corner.is-risk,
[data-theme="dark"] .stp-tide-hint.is-risk {
  color: #fecaca;
  background: rgba(127, 29, 29, 0.28);
  border-color: rgba(248, 113, 113, 0.24);
}

[data-theme="dark"] .stp-tide-corner.is-watch,
[data-theme="dark"] .stp-tide-hint.is-watch {
  color: #fde68a;
  background: rgba(120, 53, 15, 0.24);
  border-color: rgba(251, 191, 36, 0.24);
}

@media (max-width: 760px) {
  .zt-header-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .plan-toggle-btn,
  .plan-toggle-btn-debug {
    width: 100%;
    justify-content: space-between;
  }

  .zt-debug-top {
    flex-direction: column;
  }

  .zt-debug-score {
    justify-items: start;
  }

  .stp-advisor-row {
    grid-template-columns: 1fr auto;
  }

  .stp-advisor-tag {
    grid-column: 1 / -1;
    justify-self: start;
  }
}
</style>
