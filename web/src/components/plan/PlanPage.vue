<script setup lang="ts">
import { computed, ref, onMounted } from "vue"
import { useMarketData } from "../../composables/useMarketData"
import { useThemeHotStore } from "../../composables/useThemeHotStore"
import { normalizeThemeName } from "../../utils/themeUtils"
import ShortReminderFooter from "../common/ShortReminderFooter.vue"

const { marketData } = useMarketData()
const { xgbUpdatedAt, tmrUpdatedAt, xgbPlates, tmrThemes, xgbStocksByPlateId } = useThemeHotStore()
const preserveResearchView = computed(() => {
  const md = marketData.value as any
  return md?.meta?.mode === "intraday" && md?.preservedResearch?.marketData && typeof md.preservedResearch.marketData === "object"
})
const planSource = computed<any>(() => {
  const md = marketData.value as any
  return preserveResearchView.value ? md.preservedResearch.marketData : (md || {})
})

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

const planGuide = computed(() => planSource.value?.planGuide || null)
const planDecision = computed(() => {
  const value = planSource.value?.planDecision
  return value && typeof value === "object" ? value : null
})
const planGuidePills = computed(() => (Array.isArray(planDecision.value?.guidePills) ? planDecision.value.guidePills : []))
const planGuideWarnings = computed(() => (Array.isArray(planDecision.value?.guideWarnings) ? planDecision.value.guideWarnings : []))
const positionAdvice = computed(() => {
  const value = planDecision.value?.positionAdvice
  if (value && typeof value === "object") {
    return {
      stance: String(value.stance || "均衡"),
      range: String(value.range || "-"),
      cls: String(value.cls || "pos-balance"),
      pillCls: String(value.pillCls || "balance"),
    }
  }
  const finalPosition = formatPosition(planSource.value?.planGuide?.position)
  return {
    stance: "均衡",
    range: finalPosition && finalPosition !== "-" ? finalPosition : "-",
    cls: "pos-balance",
    pillCls: "balance",
  }
})

const ztRelaySorted = computed(() => (planSource.value?.ztAnalysis?.relay || []).slice())
const ztWatchSorted = computed(() => (planSource.value?.ztAnalysis?.watch || []).slice())
const ztAnalysisExpanded = ref(false)
const ztDebugExpanded = ref(false)
const ztDebugPlacement = ref<"all" | "relay" | "watch" | "excluded">("all")
const isLocalDebug = computed(() => {
  if (typeof window === "undefined") return false
  return ["localhost", "127.0.0.1"].includes(window.location.hostname) || window.location.protocol === "file:"
})
const ztDebugRows = computed(() => (Array.isArray(planSource.value?.ztAnalysis?.meta?.debug?.rows) ? planSource.value.ztAnalysis.meta.debug.rows : []))
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

// 推荐线：来自 watchlist.picks_advisor，合并展示在板块·梯队 内。
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
  status:
    | "core_mainline"
    | "resonance_traverse"
    | "observe_candidate"
    | "neutral_wait"
    | "avoid_weak"
    | "afterglow_risk"
    | "shrinking_rebound"
    | "traverse_candidate"
    | "confirmed_mainline"
    | "micro_traverse"
    | "rebound_warning"
    | "volume_rebound"
    | "weak"
    | "neutral"
  base_tide_status?: string
  action?: "confirm" | "watch" | "avoid" | "no_new_position"
  tide_zone?: "rising" | "neutral" | "ebbing"
  tide_phase?: "rising" | "neutral" | "ebbing"
  core_score?: number
  ebb_score?: number
  today_zt?: number
  prev_zt?: number | null
  pre_prev_zt?: number | null
  resilience?: number | null
  strength: number | null
  strength_rank: number | null
  strength_score: number | null
  tide_score?: number
  news_score?: number
  market_score?: number
  confidence: "low" | "medium" | "high"
  warning_level?: "none" | "watch" | "risk" | "danger"
  action_hint: string
  children?: string[]
}

const picksAdvisor = computed(() => {
  const pa = planSource.value?.picks_advisor
  if (!pa || typeof pa !== "object") return null
  const picks = Array.isArray(pa.main_line_picks) ? (pa.main_line_picks as MainLinePicks[]) : []
  if (!picks.length) return null

  return {
    main_line_picks: picks,
    diagnostics: pa.diagnostics || {},
    generated_at_bj: planSource.value?.watchlist?.generated_at_bj || "",
  }
})

const planUpdatedAt = computed(() => {
  const md = planSource.value as any
  return picksAdvisor.value?.generated_at_bj || md?.watchlist?.generated_at_bj || md?.meta?.generatedAt || "-"
})

const planThemeResolver = computed<any>(() => {
  const value = planSource.value?.planThemeResolver
  return value && typeof value === "object" ? value : null
})
const resolverContexts = computed<Record<string, any>>(() => {
  const value = planThemeResolver.value?.contexts
  return value && typeof value === "object" ? value : {}
})
const resolverAliasToTheme = computed<Record<string, string>>(() => {
  const value = planThemeResolver.value?.aliasToTheme
  return value && typeof value === "object" ? value : {}
})
const themeResolverToken = (value: unknown) => String(value || "").trim().replace(/\s+/g, "").toLowerCase()
const resolveThemeContext = (names: Array<string | null | undefined>) => {
  const aliasToTheme = resolverAliasToTheme.value
  const contexts = resolverContexts.value
  for (const rawValue of names) {
    const raw = String(rawValue || "").trim()
    if (!raw) continue
    const candidates = [raw, normalizeThemeName(raw)].filter(Boolean)
    for (const candidate of candidates) {
      const canonical = aliasToTheme[themeResolverToken(candidate)]
      if (canonical && contexts[canonical]) return contexts[canonical]
    }
  }
  const nameTokens = names
    .map((value) => [String(value || "").trim(), normalizeThemeName(String(value || "").trim())])
    .flat()
    .map((value) => themeResolverToken(value))
    .filter(Boolean)
  for (const context of Object.values(contexts)) {
    const aliases = Array.isArray((context as any)?.aliases) ? (context as any).aliases : []
    const aliasTokens: string[] = aliases.map((alias: string) => themeResolverToken(alias)).filter(Boolean)
    const hit = nameTokens.some((token) => aliasTokens.some((aliasToken: string) => aliasToken === token || aliasToken.includes(token) || token.includes(aliasToken)))
    if (hit) return context
  }
  return null
}
const tideThemeForBucket = (theme: string, matched: string[] = [], advisor?: MainLinePicks | null) => {
  const context = resolveThemeContext([theme, ...matched, advisor?.main_line || "", ...(advisor?.constituents || [])])
  return context?.tide || null
}

const tideStatusLabel = (status?: string) => {
  const labels: Record<string, string> = {
    core_mainline: "核心确认",
    resonance_traverse: "核心穿越",
    observe_candidate: "核心观察",
    neutral_wait: "中性等待",
    avoid_weak: "潮汐退潮",
    afterglow_risk: "回光返照",
    shrinking_rebound: "缩量反弹",
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

const tideDisplayTitle = (theme: TideTheme) => {
  const parts = [tideCornerTitle(theme)]
  if (theme.children?.length) parts.push(`细分：${theme.children.join(" / ")}`)
  return parts.filter(Boolean).join("｜")
}

const tideRiskPanel = computed(() => {
  const value = planThemeResolver.value?.tideRiskPanel
  return value && typeof value === "object" ? value : null
})

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
  if (status === "core_mainline" || status === "resonance_traverse") return "is-main"
  if (status === "observe_candidate") return "is-watch"
  if (status === "afterglow_risk" || status === "shrinking_rebound") return "is-risk"
  if (status === "avoid_weak") return "is-weak"
  if (status === "confirmed_mainline") return "is-main"
  if (status === "traverse_candidate" || status === "micro_traverse") return "is-watch"
  if (status === "rebound_warning" || status === "volume_rebound") return "is-risk"
  if (status === "weak") return "is-weak"
  return "is-neutral"
}

const tideCornerText = (tide?: TideTheme | null) => {
  if (!tide) return "潮汐不足"
  const label = tideStatusLabel(tide.status) || "潮汐中性"
  if (tide.action === "no_new_position" || tide.status === "rebound_warning" || tide.status === "volume_rebound") {
    return `${label} · 不开新仓`
  }
  if (Number.isFinite(Number(tide.core_score))) {
    return `${label} · 核${Math.round(Number(tide.core_score))}`
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
  if (Number.isFinite(Number(tide.core_score))) parts.push(`核心分 ${Math.round(Number(tide.core_score))}`)
  if (Number.isFinite(Number(tide.tide_score))) parts.push(`潮汐分 ${Math.round(Number(tide.tide_score))}`)
  if (Number.isFinite(Number(tide.news_score))) parts.push(`消息 ${Math.round(Number(tide.news_score))}`)
  if (Number.isFinite(Number(tide.market_score))) parts.push(`市场 ${Math.round(Number(tide.market_score))}`)
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
  const context = resolveThemeContext([theme, ...matched, ml.main_line, ...(ml.constituents || [])])
  if (!context) return false
  const canonical = String(context.canonicalTheme || "")
  const mlNames = [ml.main_line, ...(ml.constituents || [])].map((x) => normalizeThemeName(String(x || ""))).filter(Boolean)
  return mlNames.some((name) => name === canonical)
}
const advisorForBucket = (theme: string, matched: string[] = []) => {
  const context = resolveThemeContext([theme, ...matched])
  return context?.advisor || null
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
// 数据来自 publish web bundle 的 _build_watchlist_stock_index（M3/M4 多源融合结果）。
const mainLineOf = (code: unknown) => {
  const k = String(code || "").trim()
  if (!k) return null
  const idx = planSource.value?.watchlist_stock_index
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
  descriptionUrl?: string
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
  ztEvidence?: ZtThemeEvidence | null
  evidenceSummary?: string
}

type ZtThemeEvidence = {
  relayCount: number
  watchCount: number
  maxRelayFactorScore: number
  maxRiskControlScore: number
  maxEnvironmentScore: number
  maxSectorTrendScore: number
  minBreakRisk: number | null
  watchGroups: string[]
  stockNames: string[]
}
const aggregateStocksForTheme = (hotName: string): { stocks: ZtStockPick[]; matched: string[] } => {
  const context = resolveThemeContext([hotName])
  const stocks = Array.isArray(context?.stocks) ? context.stocks : []
  const matched = Array.isArray(context?.matchedLocalThemes) ? context.matchedLocalThemes : []
  return { stocks, matched }
}
const fallbackThemeNames = computed<string[]>(() => {
  const rows = Array.isArray(planThemeResolver.value?.fallbackThemes) ? planThemeResolver.value.fallbackThemes : []
  return rows
    .map((row: any) => String(row?.theme || "").trim())
    .filter(Boolean)
})

const ztEvidenceWeight = (evidence?: ZtThemeEvidence | null) => {
  if (!evidence) return -1
  const breakRisk = Number.isFinite(Number(evidence.minBreakRisk)) ? Number(evidence.minBreakRisk) : 100
  return evidence.relayCount * 18 + evidence.watchCount * 8 + evidence.maxRelayFactorScore * 0.45 + evidence.maxSectorTrendScore * 0.2 + (100 - breakRisk) * 0.08
}

const ztEvidenceForBucket = (theme: string, matched: string[] = [], advisor?: MainLinePicks | null) => {
  const context = resolveThemeContext([theme, ...matched, advisor?.main_line || "", ...(advisor?.constituents || [])])
  return context?.ztEvidence || null
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

const calculateThemeScore = (bucket: { sources: string[]; stocks: ZtStockPick[]; plateStrength?: number; resonanceScore: number; ztEvidence?: ZtThemeEvidence | null }) => {
  let score = 22
  score += Math.min(bucket.resonanceScore * 0.42, 42)
  score += Math.min((bucket.plateStrength || 0) / 4, 16)
  score += Math.min(bucket.stocks.length * 4, 16)
  score += Math.min((bucket.stocks[0]?.lbc || 0) * 6, 18)
  if (bucket.sources.some((x) => x.includes("选股宝"))) score += 6
  if (bucket.sources.some((x) => x.includes("热门"))) score += 5
  if (bucket.ztEvidence) {
    // 接力/观察池是涨停分析已经算好的证据层，这里只做兼容消费，不再前端重算。
    score += Math.min(bucket.ztEvidence.relayCount * 6, 16)
    score += Math.min(bucket.ztEvidence.watchCount * 2, 6)
    score += Math.min(bucket.ztEvidence.maxRelayFactorScore * 0.08, 8)
    score += Math.min(bucket.ztEvidence.maxEnvironmentScore * 0.05, 5)
    score += Math.max(0, bucket.ztEvidence.maxRiskControlScore - 55) * 0.12
    score -= Math.max(0, 45 - bucket.ztEvidence.maxRiskControlScore) * 0.2
    if (Number.isFinite(Number(bucket.ztEvidence.minBreakRisk))) {
      score -= Math.max(0, Number(bucket.ztEvidence.minBreakRisk) - 68) * 0.18
    }
  }
  return Math.max(0, Math.min(100, Math.round(score)))
}

const buildThemeTags = (theme: string, stocks: ZtStockPick[], sources: string[], plateStrength?: number, resonanceScore = 0, ztEvidence?: ZtThemeEvidence | null) => {
  const tags: Array<{ text: string; cls: string }> = []
  if (sources.some((x) => x.includes("选股宝"))) tags.push({ text: "实时热点", cls: "stp-chip stp-chip-hot" })
  if (sources.some((x) => x.includes("热门"))) tags.push({ text: "明日热门", cls: "stp-chip stp-chip-red" })
  if ((stocks[0]?.lbc || 0) >= 3) tags.push({ text: `${stocks[0].lbc}板龙头`, cls: "stp-chip stp-chip-red" })
  else if ((stocks[0]?.lbc || 0) === 2) tags.push({ text: "2板承接", cls: "stp-chip stp-chip-amber" })
  if ((plateStrength || 0) >= 70) tags.push({ text: "板块强", cls: "stp-chip stp-chip-blue" })
  else if ((plateStrength || 0) >= 45) tags.push({ text: "板块活跃", cls: "stp-chip stp-chip-blue" })
  if (ztEvidence?.relayCount) tags.push({ text: `接力池${ztEvidence.relayCount}`, cls: "stp-chip stp-chip-red" })
  else if (ztEvidence?.watchCount) tags.push({ text: `观察池${ztEvidence.watchCount}`, cls: "stp-chip stp-chip-blue" })
  if (ztEvidence && (ztEvidence.maxRiskControlScore < 40 || Number(ztEvidence.minBreakRisk ?? 0) >= 70)) {
    tags.push({ text: "风险偏大", cls: "stp-chip stp-chip-amber" })
  }
  if (resonanceScore >= 85) tags.push({ text: "强共振", cls: "stp-chip stp-chip-red" })
  else if (resonanceScore >= 70) tags.push({ text: "有共振", cls: "stp-chip stp-chip-slate" })
  if (stocks.length >= 4) tags.push({ text: `${stocks.length}股联动`, cls: "stp-chip stp-chip-slate" })
  return tags.slice(0, 4)
}

const ztEvidenceSummary = (evidence?: ZtThemeEvidence | null) => {
  if (!evidence) return ""
  const bits = []
  if (evidence.relayCount) bits.push(`接力池${evidence.relayCount}`)
  if (evidence.watchCount) bits.push(`观察池${evidence.watchCount}`)
  if (Number.isFinite(Number(evidence.maxSectorTrendScore)) && evidence.maxSectorTrendScore > 0) bits.push(`板块势${Math.round(evidence.maxSectorTrendScore)}`)
  if (Number.isFinite(Number(evidence.maxRiskControlScore)) && evidence.maxRiskControlScore > 0) {
    bits.push(evidence.maxRiskControlScore >= 60 ? `风控稳${Math.round(evidence.maxRiskControlScore)}` : `风控弱${Math.round(evidence.maxRiskControlScore)}`)
  }
  if (evidence.stockNames.length) bits.push(`命中${evidence.stockNames.slice(0, 2).join(" / ")}`)
  return bits.join(" · ")
}

const extractFirstUrl = (text?: string | null) => {
  const raw = String(text || "").trim()
  if (!raw) return ""
  const m = raw.match(/https?:\/\/[^\s]+/i)
  return m?.[0] || ""
}

const baiduSearchUrl = (keyword: string) => `https://www.baidu.com/s?wd=${encodeURIComponent(keyword)}`

const bucketDescUrl = (bucket: SectorBucket) => {
  const explicit = String(bucket.descriptionUrl || "").trim()
  if (explicit) return explicit
  const embedded = extractFirstUrl(bucket.description)
  if (embedded) return embedded
  const keyword = [bucket.theme, bucket.description].filter(Boolean).join(" ")
  return baiduSearchUrl(keyword || bucket.theme || "A股 题材")
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

const makeBucket = (
  plateId: string,
  theme: string,
  source: "realtime" | "fallback" | "advisor",
  sources: string[],
  description: string,
  stocks: ZtStockPick[],
  matched: string[],
  descriptionUrl = "",
): SectorBucket => {
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
  const context = resolveThemeContext([theme, ...matched])
  const plateStrength = Number(context?.plateStrength || 0)
  const plateLead = String(context?.plateLead || "")
  const advisor = (context?.advisor as MainLinePicks | null) || advisorForBucket(theme, matched)
  const tide = (context?.tide as TideTheme | null) || tideThemeForBucket(theme, matched, advisor)
  const ztEvidence = (context?.ztEvidence as ZtThemeEvidence | null) || ztEvidenceForBucket(theme, matched, advisor)
  const baseResonanceScore = Number(context?.baseResonanceScore || 0)
  const baseThemeScore = Number(context?.baseThemeScore || 0)
  const baseThemeTags = Array.isArray(context?.baseThemeTags) ? context.baseThemeTags : []
  const evidenceSummary = String(context?.evidenceSummary || "").trim()
  const scoredStocks = mergedStocks
    .map((stock) => {
      const score = stock.source === "xgb" ? calculateStockScore(stock, plateStrength, source === "realtime") : Number(stock.score ?? calculateStockScore(stock, plateStrength, false))
      return {
        ...stock,
        score,
        tags: Array.isArray(stock.tags) && stock.source !== "xgb" ? stock.tags : buildStockTags(stock, theme),
      }
    })
    .sort((a, b) => Number(b.score || 0) - Number(a.score || 0) || b.lbc - a.lbc || (b.changePct || 0) - (a.changePct || 0) || b.zjYi - a.zjYi || b.cjeYi - a.cjeYi)
  const resonanceScore = source === "realtime" ? calculateResonanceScore(sources, scoredStocks, plateStrength) : baseResonanceScore || calculateResonanceScore(sources, scoredStocks, plateStrength)
  const themeScore = source === "realtime" ? calculateThemeScore({ sources, stocks: scoredStocks, plateStrength, resonanceScore, ztEvidence }) : baseThemeScore || calculateThemeScore({ sources, stocks: scoredStocks, plateStrength, resonanceScore, ztEvidence })
  const themeTags = source === "realtime" ? buildThemeTags(theme, scoredStocks, sources, plateStrength, resonanceScore, ztEvidence) : (baseThemeTags.length ? baseThemeTags : buildThemeTags(theme, scoredStocks, sources, plateStrength, resonanceScore, ztEvidence))

  return {
    theme,
    source,
    sources,
    description,
    descriptionUrl,
    count: scoredStocks.length,
    maxLbc,
    highTier: scoredStocks.filter((s) => s.lbc >= 3).slice(0, 3),
    midTier: scoredStocks.filter((s) => s.lbc === 2).slice(0, 3),
    baseTier: scoredStocks.filter((s) => s.lbc <= 1).slice(0, 3),
    plateStrength: plateStrength || undefined,
    plateLead,
    matchedLocalThemes: matched,
    resonanceScore,
    themeScore,
    themeTags,
    advisor,
    tide,
    ztEvidence,
    evidenceSummary,
  }
}

const buildThemePanelFallbackBuckets = (): SectorBucket[] => {
  const rows = Array.isArray(planSource.value?.themePanels?.strengthRows) ? planSource.value.themePanels.strengthRows : []
  return rows
    .map((row: any) => {
      const theme = String(row?.name || "").trim()
      if (!theme) return null
      const { stocks, matched } = aggregateStocksForTheme(theme)
      const context = resolveThemeContext([theme])
      const leader = context?.leader
      const fallbackPanel = context?.fallbackPanel && typeof context.fallbackPanel === "object" ? context.fallbackPanel : null
      const zt = Number(fallbackPanel?.zt ?? row?.zt ?? 0)
      const zb = Number(fallbackPanel?.zb ?? row?.zb ?? 0)
      const dt = Number(fallbackPanel?.dt ?? row?.dt ?? 0)
      const risk = Number(fallbackPanel?.risk ?? row?.risk ?? 0)
      const fallbackDesc = String(fallbackPanel?.desc || "").trim()
      const bucket = makeBucket("", theme, "fallback", ["本地板块推测"], fallbackDesc, stocks, matched)
      bucket.plateStrength = Number(fallbackPanel?.strengthScore ?? 0) || bucket.plateStrength
      bucket.plateLead = bucket.plateLead || String(leader?.name || "")

      if (!bucket.count && leader?.code && leader?.name) {
        bucket.count = 1
        bucket.baseTier = [
          {
            code: String(leader.code),
            name: String(leader.name),
            lbc: 0,
            cjeYi: 0,
            zjYi: 0,
            zbc: 0,
            source: "local",
            score: Math.max(55, Math.round(Number(leader.score || 0))),
            tags: [{ text: "题材龙头", cls: "stp-chip stp-chip-red" }],
          },
        ]
      }

      bucket.themeTags = [
        ...bucket.themeTags,
        ...(fallbackPanel?.tagText ? [{ text: String(fallbackPanel.tagText), cls: String(fallbackPanel.tagCls || "stp-chip stp-chip-slate") }] : []),
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

  const ztgcLen = Array.isArray(planSource.value?.ztgc) ? planSource.value.ztgc.length : 0
  if (!ztgcLen) return []

  const xgb = preserveResearchView.value ? [] : xgbPlates.value
  const tmr = preserveResearchView.value ? [] : tmrThemes.value

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
    fallbackThemeNames.value.forEach((t) => {
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

  // 先按综合势能，再参考涨停分析证据与共振，保证板块卡和涨停分析口径一致。
  buckets.sort((a, b) => {
    if (b.themeScore !== a.themeScore) return b.themeScore - a.themeScore
    if (ztEvidenceWeight(b.ztEvidence) !== ztEvidenceWeight(a.ztEvidence)) return ztEvidenceWeight(b.ztEvidence) - ztEvidenceWeight(a.ztEvidence)
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
  const xgbCount = preserveResearchView.value ? 0 : xgbPlates.value.length
  const tmrCount = preserveResearchView.value ? 0 : tmrThemes.value.length
  const tmrHotCount = preserveResearchView.value ? 0 : tmrThemes.value.filter((t) => t.isHot).length
  return {
    bucketTotal: buckets.length,
    realtimeCnt,
    fallbackUsed,
    advisorCnt: buckets.filter((b) => b.advisor).length,
    xgbCnt: xgbCount,
    tmrCnt: tmrCount,
    tmrHotCnt: tmrHotCount,
  }
})
</script>

<template>
  <div class="plan-page">
    <div class="card" data-page="plan" id="sec-action">
      <div class="zt-header-meta">研究数据更新时间 {{ planUpdatedAt }}</div>
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
                <span class="pos-pill">热{{ planSource.mood?.heat ?? marketData.mood?.heat ?? "-" }}/险{{ planSource.mood?.risk ?? marketData.mood?.risk ?? "-" }}</span>
                <span class="pos-pill">{{ planSource.moodStage?.title || marketData.moodStage?.title || "-" }}</span>
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
          <div class="card-title">板块·梯队 </div>
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
      <div class="stp-tide-risk-panel" v-if="tideRiskPanel">
        <div class="stp-tide-risk-main">
          <span class="stp-tide-risk-badge">{{ tideRiskPanel.status }}</span>
          <span v-if="tideRiskPanel.lossScore !== null">亏钱效应 {{ tideRiskPanel.lossScore }}</span>
          <span v-for="(reason, ri) in tideRiskPanel.reasons.slice(0, 3)" :key="'tide-risk-reason-' + ri">{{ reason }}</span>
        </div>
        <div class="stp-tide-zones">
          <div class="stp-tide-zone is-rise" v-if="tideRiskPanel.zones.rising.length">
            <span class="stp-tide-risk-label">涨潮</span>
            <span v-for="theme in tideRiskPanel.zones.rising" :key="'tide-rise-' + theme.name" class="stp-tide-risk-chip" :title="tideDisplayTitle(theme)">
              {{ theme.name }}<template v-if="Number.isFinite(Number(theme.core_score))"> {{ Math.round(Number(theme.core_score)) }}</template>
            </span>
          </div>
          <div class="stp-tide-zone is-neutral" v-if="tideRiskPanel.zones.neutral.length">
            <span class="stp-tide-risk-label">中性</span>
            <span v-for="theme in tideRiskPanel.zones.neutral" :key="'tide-neutral-' + theme.name" class="stp-tide-risk-chip" :title="tideDisplayTitle(theme)">
              {{ theme.name }}<template v-if="Number.isFinite(Number(theme.core_score))"> {{ Math.round(Number(theme.core_score)) }}</template>
            </span>
          </div>
          <div class="stp-tide-zone is-ebb" v-if="tideRiskPanel.zones.ebbing.length">
            <span class="stp-tide-risk-label">退潮</span>
            <span v-for="theme in tideRiskPanel.zones.ebbing" :key="'tide-ebb-' + theme.name" class="stp-tide-risk-chip" :title="tideDisplayTitle(theme)">
              {{ theme.name }}<template v-if="Number.isFinite(Number(theme.ebb_score))"> {{ Math.round(Number(theme.ebb_score)) }}</template>
            </span>
          </div>
        </div>
        <div class="stp-tide-risk-triggers" v-if="tideRiskPanel.triggers.length">
          {{ tideRiskPanel.triggers.slice(0, 4).join(" / ") }}
        </div>
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
              <span class="stp-theme-score" :class="scoreClass(bucket.themeScore)">势能 {{ bucket.themeScore }}</span>
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
          <div class="stp-evidence" v-if="bucket.ztEvidence">
            {{ ztEvidenceSummary(bucket.ztEvidence) }}
          </div>
          <a
            class="stp-desc stp-desc-link"
            v-if="bucket.description"
            :href="bucketDescUrl(bucket)"
            :title="bucket.description"
            target="_blank"
            rel="noopener noreferrer">
            {{ bucket.description }}
          </a>
          <div class="stp-advisor" v-if="bucket.advisor">
            <div class="stp-advisor-section" v-if="bucket.advisor.buy?.length">
              <div class="stp-advisor-label buy">核心推荐</div>
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
            <span class="zt-header-sector" v-if="planSource.ztAnalysis?.meta?.tierThemeCount">
              梯队：{{ planSource.ztAnalysis?.meta?.tierThemeCount }}板块
              <template v-if="planSource.ztAnalysis?.meta?.tierThemeTop">（{{ planSource.ztAnalysis?.meta?.tierThemeTop }}）</template>
            </span>
            <div class="zt-header-meta-inline">
              <span class="sep">｜</span>
              涨停池
              <span class="orange-text">{{ planSource.ztgc?.length ?? 0 }}</span>
              <span class="sep">·</span>
              题材映射
              <span class="orange-text">{{ planSource.zt_code_themes ? Object.keys(planSource.zt_code_themes).length : 0 }}</span>
            </div>
          </div>
        </div>
        <div class="zt-header-actions">
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
      <div class="summary-box" v-if="!planSource.ztgc || !planSource.ztgc.length">
        <div class="summary-text">未注入当日涨停池明细（ztgc）。请用渲染脚本从 pools_cache.json 注入后再查看本模块。</div>
      </div>
      <div class="summary-box" v-else-if="!((planSource.ztAnalysis?.relay || []).length || (planSource.ztAnalysis?.watch || []).length)">
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
          <button class="abnormal-switch zt-debug-switch" :class="{ active: ztDebugPlacement === 'all' }" type="button" @click="ztDebugPlacement = 'all'">全部</button>
          <button class="abnormal-switch zt-debug-switch" :class="{ active: ztDebugPlacement === 'relay' }" type="button" @click="ztDebugPlacement = 'relay'">接力池</button>
          <button class="abnormal-switch zt-debug-switch" :class="{ active: ztDebugPlacement === 'watch' }" type="button" @click="ztDebugPlacement = 'watch'">观察池</button>
          <button class="abnormal-switch zt-debug-switch" :class="{ active: ztDebugPlacement === 'excluded' }" type="button" @click="ztDebugPlacement = 'excluded'">未入池</button>
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

    <ShortReminderFooter />
  </div>
</template>

<style scoped src="./PlanPage.css"></style>
