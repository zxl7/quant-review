export type AccountCurveInputRecord = {
  date?: string
  dailyPct?: number | string
}

export type AccountCurvePayload = {
  base?: number | string
  records?: AccountCurveInputRecord[]
}

export type AccountNavLedgerRecord = {
  trade_date?: string
  recommendation_date?: string
  strategy?: string
  stock_count?: number | string
  avg_return_pct?: number | string
  nav?: number | string
  codes?: string[]
  names?: string[]
}

export type AccountCurvePoint = {
  date: string
  dailyPct: number
  value: number
  cumPct: number
  drawdownPct: number
  stockCount: number
  codes: string[]
  names: string[]
}

export type AccountCurveSummary = {
  base: number
  latestValue: number
  totalReturnPct: number
  maxDrawdownPct: number
  bestDailyPct: number
  worstDailyPct: number
  tradeDays: number
}

export type AccountCurveComputed = {
  points: AccountCurvePoint[]
  summary: AccountCurveSummary
}

function toNumber(value: unknown, fallback = 0) {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

export function computeAccountCurve(raw: AccountCurvePayload | null | undefined): AccountCurveComputed {
  const base = toNumber(raw?.base, 1) > 0 ? toNumber(raw?.base, 1) : 1
  const rows = Array.isArray(raw?.records) ? raw?.records : []
  const ordered = [...rows]
    .map((item) => ({
      date: String(item?.date || "").trim(),
      dailyPct: toNumber(item?.dailyPct, 0),
    }))
    .filter((item) => item.date)
    .sort((a, b) => a.date.localeCompare(b.date))

  let value = base
  let peak = base
  let bestDailyPct = Number.NEGATIVE_INFINITY
  let worstDailyPct = Number.POSITIVE_INFINITY

  const points: AccountCurvePoint[] = ordered.map((item) => {
    value = value * (1 + item.dailyPct / 100)
    peak = Math.max(peak, value)
    const drawdownPct = peak > 0 ? ((value - peak) / peak) * 100 : 0
    bestDailyPct = Math.max(bestDailyPct, item.dailyPct)
    worstDailyPct = Math.min(worstDailyPct, item.dailyPct)
    return {
      date: item.date,
      dailyPct: item.dailyPct,
      value,
      cumPct: base > 0 ? ((value / base) - 1) * 100 : 0,
      drawdownPct,
      stockCount: 0,
      codes: [],
      names: [],
    }
  })

  const latestValue = points.length ? points[points.length - 1].value : base
  const totalReturnPct = base > 0 ? ((latestValue / base) - 1) * 100 : 0
  const maxDrawdownPct = points.reduce((worst, item) => Math.min(worst, item.drawdownPct), 0)

  return {
    points,
    summary: {
      base,
      latestValue,
      totalReturnPct,
      maxDrawdownPct,
      bestDailyPct: points.length ? bestDailyPct : 0,
      worstDailyPct: points.length ? worstDailyPct : 0,
      tradeDays: points.length,
    },
  }
}

export function computeAccountCurveFromBacktest(rows: any[], baseValue?: number | string): AccountCurveComputed {
  const grouped = new Map<
    string,
    {
      returns: number[]
      codes: string[]
      names: string[]
    }
  >()

  for (const row of Array.isArray(rows) ? rows : []) {
    const performance = row?.performance && typeof row.performance === "object" ? row.performance : {}
    const openCheck = performance?.open_check && typeof performance.open_check === "object" ? performance.open_check : {}
    const nextDay = performance?.next_day && typeof performance.next_day === "object" ? performance.next_day : {}
    if (!openCheck?.can_enter) continue
    if (String(nextDay?.status || "") !== "covered") continue
    const tradeDate = String(nextDay?.entry_date || nextDay?.exit_date || "").trim()
    if (!tradeDate) continue
    const returnPct = toNumber(nextDay?.return_pct, Number.NaN)
    if (!Number.isFinite(returnPct)) continue

    const item = grouped.get(tradeDate) || { returns: [], codes: [], names: [] }
    item.returns.push(returnPct)
    const code = String(row?.code || "").trim()
    const name = String(row?.name || "").trim()
    if (code) item.codes.push(code)
    if (name) item.names.push(name)
    grouped.set(tradeDate, item)
  }

  const base = toNumber(baseValue, 1) > 0 ? toNumber(baseValue, 1) : 1
  const ordered = Array.from(grouped.entries())
    .map(([date, item]) => ({
      date,
      dailyPct: item.returns.length ? item.returns.reduce((sum, value) => sum + value, 0) / item.returns.length : 0,
      stockCount: item.returns.length,
      codes: item.codes,
      names: item.names,
    }))
    .sort((a, b) => a.date.localeCompare(b.date))

  let value = base
  let peak = base
  let bestDailyPct = Number.NEGATIVE_INFINITY
  let worstDailyPct = Number.POSITIVE_INFINITY

  const points: AccountCurvePoint[] = ordered.map((item) => {
    value = value * (1 + item.dailyPct / 100)
    peak = Math.max(peak, value)
    const drawdownPct = peak > 0 ? ((value - peak) / peak) * 100 : 0
    bestDailyPct = Math.max(bestDailyPct, item.dailyPct)
    worstDailyPct = Math.min(worstDailyPct, item.dailyPct)
    return {
      date: item.date,
      dailyPct: item.dailyPct,
      value,
      cumPct: base > 0 ? ((value / base) - 1) * 100 : 0,
      drawdownPct,
      stockCount: item.stockCount,
      codes: item.codes,
      names: item.names,
    }
  })

  const latestValue = points.length ? points[points.length - 1].value : base
  const totalReturnPct = base > 0 ? ((latestValue / base) - 1) * 100 : 0
  const maxDrawdownPct = points.reduce((worst, item) => Math.min(worst, item.drawdownPct), 0)

  return {
    points,
    summary: {
      base,
      latestValue,
      totalReturnPct,
      maxDrawdownPct,
      bestDailyPct: points.length ? bestDailyPct : 0,
      worstDailyPct: points.length ? worstDailyPct : 0,
      tradeDays: points.length,
    },
  }
}

export function computeAccountCurveFromLedger(rows: AccountNavLedgerRecord[] | null | undefined, baseValue?: number | string): AccountCurveComputed {
  const base = toNumber(baseValue, 1) > 0 ? toNumber(baseValue, 1) : 1
  const ordered = (Array.isArray(rows) ? rows : [])
    .map((item) => ({
      date: String(item?.trade_date || "").trim(),
      dailyPct: toNumber(item?.avg_return_pct, 0),
      value: toNumber(item?.nav, Number.NaN),
      stockCount: Math.max(0, Math.round(toNumber(item?.stock_count, 0))),
      codes: Array.isArray(item?.codes) ? item.codes.map((x) => String(x || "").trim()).filter(Boolean) : [],
      names: Array.isArray(item?.names) ? item.names.map((x) => String(x || "").trim()).filter(Boolean) : [],
    }))
    .filter((item) => item.date)
    .sort((a, b) => a.date.localeCompare(b.date))

  let peak = base
  let bestDailyPct = Number.NEGATIVE_INFINITY
  let worstDailyPct = Number.POSITIVE_INFINITY

  const points: AccountCurvePoint[] = ordered.map((item, index) => {
    const value = Number.isFinite(item.value)
      ? item.value
      : (index === 0 ? base : ordered[index - 1].value) * (1 + item.dailyPct / 100)
    peak = Math.max(peak, value)
    const drawdownPct = peak > 0 ? ((value - peak) / peak) * 100 : 0
    bestDailyPct = Math.max(bestDailyPct, item.dailyPct)
    worstDailyPct = Math.min(worstDailyPct, item.dailyPct)
    item.value = value
    return {
      date: item.date,
      dailyPct: item.dailyPct,
      value,
      cumPct: base > 0 ? ((value / base) - 1) * 100 : 0,
      drawdownPct,
      stockCount: item.stockCount,
      codes: item.codes,
      names: item.names,
    }
  })

  const latestValue = points.length ? points[points.length - 1].value : base
  const totalReturnPct = base > 0 ? ((latestValue / base) - 1) * 100 : 0
  const maxDrawdownPct = points.reduce((worst, item) => Math.min(worst, item.drawdownPct), 0)

  return {
    points,
    summary: {
      base,
      latestValue,
      totalReturnPct,
      maxDrawdownPct,
      bestDailyPct: points.length ? bestDailyPct : 0,
      worstDailyPct: points.length ? worstDailyPct : 0,
      tradeDays: points.length,
    },
  }
}
