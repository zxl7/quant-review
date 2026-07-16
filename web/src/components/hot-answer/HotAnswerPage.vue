<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { DatePicker } from 'ant-design-vue';
import dayjs, { type Dayjs } from 'dayjs';
import ShortReminderFooter from '../common/ShortReminderFooter.vue';
import { useMarketData } from '../../composables/useMarketData';
import { useIntradayRuntime } from '../../composables/useIntradayRuntime';
import { useThemeHotStore, type TomorrowThemeLite, type TomorrowThemeStockLite } from '../../composables/useThemeHotStore';

const {
  setXgbPlates,
  setXgbStocksForPlate,
  tmrThemes,
  tmrStocksByThemeCode,
  ensureTomorrowLoaded,
  ensureTomorrowThemeStocksLoaded,
  setSelectedTomorrowThemeCode,
} = useThemeHotStore();
const { marketData } = useMarketData();
const { latest: intradayLatest, live: intradayLive, isStale: intradayRuntimeStale, error: intradayRuntimeError } = useIntradayRuntime();

type HotPlate = {
  id: string;
  name: string;
  description: string;
  leaderStockCount: number;
  leaderLimitCount: number;
  topLeaderNames: string[];
  eventHitCount: number;
  eventThemes: string[];
  displayTags: string[];
};

type HotStock = {
  code: string;
  name: string;
  changePct: number;
  price?: number;
  limitUpDays?: number;
  reason: string;
  label: string;
  relatedDesc: string;
  relatedThemes: string[];
  eventStrength: number;
};

type PlateRef = {
  id: string;
  name: string;
};

type PlateEventSummary = {
  eventHitCount: number;
  eventThemes: string[];
};

type StockEventSummary = {
  eventStrength: number;
  relatedThemes: string[];
};

type HotDecisionTone = 'buy' | 'watch' | 'avoid' | 'history';

type HotDecisionGate = {
  tone: HotDecisionTone;
  label: string;
  summary: string;
  modeLabel: string;
  signals: string[];
  vetoReasons: string[];
};

type HotPlateDecision = {
  tone: Exclude<HotDecisionTone, 'history'>;
  score: number;
  label: string;
  summary: string;
  confirmSignals: string[];
  vetoReasons: string[];
};

type HotStockAction = HotStock & {
  actionTone: Exclude<HotDecisionTone, 'history'>;
  actionScore: number;
  roleLabel: string;
  entryStyle: string;
  confirmSignals: string[];
  vetoReasons: string[];
  isActionable: boolean;
  matchedTomorrowThemeNames: string[];
  tomorrowReasonSnippets: string[];
  tomorrowLabels: string[];
  tomorrowIndustries: string[];
  isTomorrowThemeHit: boolean;
};

type MatchedTomorrowTheme = TomorrowThemeLite & {
  matchScore: number;
  matchLevel: 'exact' | 'fuzzy';
  matchReason: string;
};

type MatchedTomorrowThemeStock = TomorrowThemeStockLite & {
  themeCode: string;
  themeName: string;
  reasonSnippet: string;
  source: 'full' | 'preview';
};

type MatchedTomorrowThemePanel = MatchedTomorrowTheme & {
  stocks: MatchedTomorrowThemeStock[];
  hasFullStocks: boolean;
};

type HotStockTomorrowEvidence = {
  matchedTomorrowThemeNames: string[];
  tomorrowReasonSnippets: string[];
  tomorrowLabels: string[];
  tomorrowIndustries: string[];
  isTomorrowThemeHit: boolean;
};

const todayText = () => {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
};

const hotDate = ref(todayText());
const hotPlates = ref<HotPlate[]>([]);
const hotSelectedPlateId = ref('');
const hotSelectedPlateName = ref('');
const hotMode = ref<'leader' | 'all'>('leader');
const hotStocks = ref<HotStock[]>([]);
const hotLoading = ref(false);
const hotStockLoading = ref(false);
const hotError = ref('');
const hotLastUpdated = ref('');
const hotExpandedCodes = ref<string[]>([]);
const hotLeaderStocksByPlateId = ref<Record<string, HotStock[]>>({});
const hotAllStocksByPlateId = ref<Record<string, HotStock[]>>({});
const hotPlateEventById = ref<Record<string, PlateEventSummary>>({});
const hotStockEventByCode = ref<Record<string, StockEventSummary>>({});
const hotLeaderLoadedForDate = ref('');

const hotDateParam = computed(() => hotDate.value.replace(/-/g, ''));
const hotDateValue = computed<Dayjs | undefined>({
  get: () => (hotDate.value ? dayjs(hotDate.value, 'YYYY-MM-DD') : undefined),
  set: (value) => {
    hotDate.value = value ? value.format('YYYY-MM-DD') : todayText();
  },
});
const isToday = computed(() => hotDate.value === todayText());
const selectedPlate = computed(() => hotPlates.value.find((x) => x.id === hotSelectedPlateId.value));
const sortedStocks = computed(() => [...hotStocks.value].sort((a, b) => Number(b.changePct || 0) - Number(a.changePct || 0)));
const hotStats = computed(() => ({
  plates: hotPlates.value.length,
}));
const selectedLeaderStocks = computed(() => {
  const rows = hotLeaderStocksByPlateId.value[hotSelectedPlateId.value] || [];
  return [...rows].sort((a, b) => {
    const limitDiff = Number(b.limitUpDays || 0) - Number(a.limitUpDays || 0);
    if (limitDiff !== 0) return limitDiff;
    const eventDiff = Number(b.eventStrength || 0) - Number(a.eventStrength || 0);
    if (eventDiff !== 0) return eventDiff;
    return Number(b.changePct || 0) - Number(a.changePct || 0);
  });
});
const representativeStocks = computed(() => selectedLeaderStocks.value.slice(0, 3));
const selectedLeaderText = computed(() => {
  const names = representativeStocks.value.length
    ? representativeStocks.value.map((stock) => stock.name)
    : sortedStocks.value.slice(0, 3).map((stock) => stock.name);
  return names.filter(Boolean).slice(0, 3).join(' / ');
});
const matchedTomorrowThemes = computed<MatchedTomorrowTheme[]>(() => {
  if (!selectedPlate.value || !tmrThemes.value.length) return [];
  return tmrThemes.value
    .map((theme) => {
      const matched = scoreTomorrowThemeMatch(selectedPlate.value as HotPlate, theme);
      if (!matched) return null;
      return {
        ...theme,
        matchScore: matched.score,
        matchLevel: matched.matchLevel,
        matchReason: matched.matchReason,
      };
    })
    .filter(Boolean)
    .sort((a, b) => (
      Number(b!.matchScore || 0) - Number(a!.matchScore || 0)
      || Number(b!.isHot) - Number(a!.isHot)
      || Number(b!.ztCount || 0) - Number(a!.ztCount || 0)
      || Number(b!.gain || 0) - Number(a!.gain || 0)
      || Number(b!.cumulateGain || 0) - Number(a!.cumulateGain || 0)
    ))
    .slice(0, 3) as MatchedTomorrowTheme[];
});
const matchedTomorrowThemePanels = computed<MatchedTomorrowThemePanel[]>(() => matchedTomorrowThemes.value.map((theme) => {
  const fullStocks = tmrStocksByThemeCode.value[theme.themeCode] || [];
  const stocks = fullStocks.length
    ? fullStocks.slice(0, 5).map((stock) => ({
      ...stock,
      themeCode: theme.themeCode,
      themeName: theme.themeName,
      reasonSnippet: firstReasonLine(stock.reason),
      source: 'full' as const,
    }))
    : (theme.previewStocks || []).slice(0, 5).map((stock) => ({
      code: normalizeCode(stock.code),
      name: String(stock.name || '').trim(),
      gain: toNum(stock.gain, 0),
      price: 0,
      marketCap: 0,
      industry: '',
      label: '',
      reason: '',
      reasonSnippet: '',
      themeCode: theme.themeCode,
      themeName: theme.themeName,
      source: 'preview' as const,
    }));
  return {
    ...theme,
    stocks,
    hasFullStocks: fullStocks.length > 0,
  };
}));
const selectedStockCount = computed(() => (
  hotMode.value === 'leader'
    ? Number(selectedPlate.value?.leaderStockCount || 0)
    : hotStocks.value.length
));
const selectedLimitCount = computed(() => (
  hotMode.value === 'leader'
    ? Number(selectedPlate.value?.leaderLimitCount || 0)
    : hotStocks.value.filter((stock) => Number(stock.limitUpDays || 0) > 0).length
));
const actionAdvisor = computed<any>(() => (
  marketData.value?.actionAdvisor && typeof marketData.value.actionAdvisor === 'object'
    ? marketData.value.actionAdvisor
    : {}
));
const shortlineDecision = computed<any>(() => (
  marketData.value?.shortlineDecision && typeof marketData.value.shortlineDecision === 'object'
    ? marketData.value.shortlineDecision
    : {}
));
const tradePlan = computed<any>(() => (
  shortlineDecision.value?.tradePlan && typeof shortlineDecision.value.tradePlan === 'object'
    ? shortlineDecision.value.tradePlan
    : {}
));
const ztRelayRows = computed<any[]>(() => (Array.isArray(marketData.value?.ztAnalysis?.relay) ? marketData.value.ztAnalysis.relay : []));
const ztWatchRows = computed<any[]>(() => (Array.isArray(marketData.value?.ztAnalysis?.watch) ? marketData.value.ztAnalysis.watch : []));
const ladderRows = computed<any[]>(() => (Array.isArray(marketData.value?.ladder) ? marketData.value.ladder : []));
const top10Rows = computed<any[]>(() => (Array.isArray(marketData.value?.top10) ? marketData.value.top10 : []));

const normalizeCode = (value: unknown) => String(value || '').trim().replace(/\.(SZ|SS|SH)$/i, '');
const normalizeLooseText = (value: unknown) => String(value || '').trim().replace(/\s+/g, '');
const toXgbSymbol = (code: string) => {
  const raw = normalizeCode(code);
  if (!raw) return '';
  return `${raw}.${raw.startsWith('6') ? 'SS' : 'SZ'}`;
};
const isStockCode = (code: string) => /^(00|30|60|68)\d{4}$/.test(normalizeCode(code));
const toNum = (value: unknown, fallback = 0) => {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
};
const formatPct = (value: unknown) => {
  const n = toNum(value, 0);
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
};
const formatSignedPct = (value: unknown) => {
  const n = toNum(value, 0);
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
};
const formatMarketCap = (value: unknown) => {
  const n = toNum(value, 0);
  if (!n) return '';
  if (n >= 100000000) return `${(n / 100000000).toFixed(n >= 1000000000 ? 0 : 1)}亿市值`;
  if (n >= 10000) return `${(n / 10000).toFixed(0)}万市值`;
  return `${n.toFixed(0)}市值`;
};
const themeChipToneClass = (theme: string) => {
  const text = String(theme || '').trim();
  if (!text) return '';
  if (/连阳|底背离|利好/.test(text)) return 'is-hot';
  if (/减持|利空/.test(text)) return 'is-cool';
  return '';
};
const uniqueTexts = (items: unknown[], limit = 999) => {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const item of items) {
    const text = String(item || '').trim();
    const key = normalizeLooseText(text);
    if (!text || !key || seen.has(key)) continue;
    seen.add(key);
    out.push(text);
    if (out.length >= limit) break;
  }
  return out;
};
const splitLabelThemes = (text: string | undefined) => uniqueTexts(
  String(text || '')
    .split(/[，,、/|]/)
    .map((item) => item.trim())
    .filter(Boolean),
  8,
);
const splitTomorrowLabels = (text: string | undefined) => uniqueTexts(
  String(text || '')
    .split(/[，,、/|；;]/)
    .map((item) => item.trim())
    .filter((item) => item.length >= 2),
  6,
);
const splitThemeMatchTokens = (text: string | undefined) => {
  const raw = String(text || '').trim();
  if (!raw) return [];
  return uniqueTexts(
    raw
      .replace(/板块|概念|题材|方向|主线|赛道/g, ' ')
      .split(/[\s，,、/|+（）()\-]/)
      .map((item) => item.trim())
      .filter((item) => item.length >= 2),
    8,
  );
};
const scoreTomorrowThemeMatch = (plate: HotPlate, theme: TomorrowThemeLite) => {
  const plateName = String(plate.name || '').trim();
  const themeName = String(theme.themeName || '').trim();
  if (!plateName || !themeName) return null;
  const plateKey = normalizeLooseText(plateName);
  const themeKey = normalizeLooseText(themeName);
  if (!plateKey || !themeKey) return null;

  if (plateKey === themeKey) {
    return { score: 120, matchLevel: 'exact' as const, matchReason: '板块名与东财题材精确命中' };
  }

  if (plateKey.includes(themeKey) || themeKey.includes(plateKey)) {
    return { score: 88, matchLevel: 'fuzzy' as const, matchReason: '板块名与东财题材存在直接包含关系' };
  }

  const plateTokens = splitThemeMatchTokens(`${plateName} ${plate.description || ''}`);
  const themeTokens = splitThemeMatchTokens(`${themeName} ${theme.title || ''} ${theme.summary || ''}`);
  const overlap = plateTokens.filter((token) => themeTokens.some((item) => {
    const tokenKey = normalizeLooseText(token);
    const itemKey = normalizeLooseText(item);
    return tokenKey === itemKey || tokenKey.includes(itemKey) || itemKey.includes(tokenKey);
  }));

  if (overlap.length) {
    return {
      score: 60 + overlap.length * 8,
      matchLevel: 'fuzzy' as const,
      matchReason: `命中题材关键词 ${uniqueTexts(overlap, 2).join(' / ')}`,
    };
  }

  return null;
};
const makePlate = (plate: Partial<HotPlate>): HotPlate => ({
  id: String(plate.id || '').trim(),
  name: String(plate.name || '').trim(),
  description: String(plate.description || '').trim(),
  leaderStockCount: Number(plate.leaderStockCount || 0),
  leaderLimitCount: Number(plate.leaderLimitCount || 0),
  topLeaderNames: Array.isArray(plate.topLeaderNames) ? uniqueTexts(plate.topLeaderNames, 3) : [],
  eventHitCount: Number(plate.eventHitCount || 0),
  eventThemes: Array.isArray(plate.eventThemes) ? uniqueTexts(plate.eventThemes, 4) : [],
  displayTags: Array.isArray(plate.displayTags) ? uniqueTexts(plate.displayTags, 4) : [],
});
const makeStock = (stock: Partial<HotStock>): HotStock => ({
  code: normalizeCode(stock.code),
  name: String(stock.name || '').trim(),
  changePct: toNum(stock.changePct, 0),
  price: stock.price === undefined ? undefined : toNum(stock.price, 0),
  limitUpDays: stock.limitUpDays === undefined ? undefined : toNum(stock.limitUpDays, 0),
  reason: String(stock.reason || '').trim(),
  label: String(stock.label || '').trim(),
  relatedDesc: String(stock.relatedDesc || '').trim(),
  relatedThemes: Array.isArray(stock.relatedThemes) ? uniqueTexts(stock.relatedThemes, 6) : [],
  eventStrength: Number(stock.eventStrength || 0),
});
const resetHotDerivedState = () => {
  hotLeaderStocksByPlateId.value = {};
  hotAllStocksByPlateId.value = {};
  hotPlateEventById.value = {};
  hotStockEventByCode.value = {};
  hotLeaderLoadedForDate.value = '';
};

/**
 * 将包含换行符的文本分割为行数组，并移除常见的序号前缀（如 1、 1. 等）
 * 符合函数式编程：无副作用，纯函数处理字符串
 * @param text 待处理的文本内容
 */
const splitLines = (text: string | undefined): string[] => {
  if (!text) return [];
  
  // 1. 处理字面量 "\n" 字符（有些接口返回的是字符串形式的 \n 而不是真实换行符）
  let processed = String(text).replace(/\\n/g, '\n');
  
  // 2. 兼容性切割：如果文本中没有换行符，但存在类似 "；2、" 或 "。2、" 的结构，强制补齐换行
  // 这能处理那些把多条信息挤在同一行且只用序号分隔的情况
  if (!processed.includes('\n')) {
    processed = processed.replace(/([;；。!！?？])\s*(\d+[、.．])/g, '$1\n$2');
  }

  return processed
    .split(/\n+/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => line.replace(/^\d+[、.．]\s*/, ''));
};
const firstReasonLine = (text: string | undefined) => splitLines(text)[0] || String(text || '').trim();

const takeTexts = (items: unknown[], limit = 4) => uniqueTexts(items, limit);
const collectRowTags = (row: any) => {
  if (Array.isArray(row?.tagRows) && row.tagRows.length) {
    return row.tagRows
      .flatMap((item: any) => (Array.isArray(item?.tags) ? item.tags : []))
      .map((item: any) => String(item?.text || '').trim())
      .filter(Boolean);
  }
  return Array.isArray(row?.tags)
    ? row.tags.map((item: any) => String(item?.text || item || '').trim()).filter(Boolean)
    : [];
};
const hotShiftLabelTone = (text: unknown): Exclude<HotDecisionTone, 'history'> => {
  const raw = String(text || '').trim();
  if (/走强|修复|回暖|增强/.test(raw)) return 'buy';
  if (/走弱|退潮|跳水|分歧加剧/.test(raw)) return 'avoid';
  return 'watch';
};
const matchesPlateName = (plateName: string, values: unknown[]) => {
  const plateKey = normalizeLooseText(plateName);
  if (!plateKey) return false;
  return values.some((value) => {
    const textKey = normalizeLooseText(value);
    return Boolean(textKey) && (textKey.includes(plateKey) || plateKey.includes(textKey));
  });
};
const decisionToneRank = (tone: Exclude<HotDecisionTone, 'history'>) => {
  if (tone === 'buy') return 0;
  if (tone === 'watch') return 1;
  return 2;
};
const tradePlanPrimaryRows = computed<any[]>(() => (Array.isArray(tradePlan.value?.primaryCandidates) ? tradePlan.value.primaryCandidates : []));
const tradePlanWatchRows = computed<any[]>(() => (Array.isArray(tradePlan.value?.watchCandidates) ? tradePlan.value.watchCandidates : []));
const tradePlanByCode = computed(() => {
  const map = new Map<string, any>();
  [...tradePlanPrimaryRows.value, ...tradePlanWatchRows.value].forEach((row) => {
    const code = normalizeCode(row?.code);
    if (code && !map.has(code)) map.set(code, row);
  });
  return map;
});
const ztRelayByCode = computed(() => {
  const map = new Map<string, any>();
  ztRelayRows.value.forEach((row) => {
    const code = normalizeCode(row?.code);
    if (code) map.set(code, row);
  });
  return map;
});
const ztWatchByCode = computed(() => {
  const map = new Map<string, any>();
  ztWatchRows.value.forEach((row) => {
    const code = normalizeCode(row?.code);
    if (code) map.set(code, row);
  });
  return map;
});
const ladderByCode = computed(() => {
  const map = new Map<string, any>();
  ladderRows.value.forEach((row) => {
    const code = normalizeCode(row?.code || row?.dm);
    if (code) map.set(code, row);
  });
  return map;
});
const top10CapacitySet = computed(() => new Set(
  top10Rows.value.slice(0, 5).map((row) => normalizeCode(row?.code)).filter(Boolean),
));
const jumpToTomorrowTheme = (themeCode: string) => {
  const nextCode = String(themeCode || '').trim();
  if (!nextCode) return;
  setSelectedTomorrowThemeCode(nextCode);
  if (typeof document === 'undefined') return;
  const buttons = Array.from(document.querySelectorAll<HTMLButtonElement>('.tab-btn'));
  const target = buttons.find((button) => button.textContent?.trim() === '今日题材' && button.offsetParent !== null)
    || buttons.find((button) => button.textContent?.trim() === '今日题材');
  target?.click();
};
const buildTomorrowEvidenceByCode = () => {
  const map = new Map<string, HotStockTomorrowEvidence>();
  matchedTomorrowThemePanels.value.forEach((theme) => {
    theme.stocks.forEach((stock) => {
      const code = normalizeCode(stock.code);
      if (!code) return;
      const prev = map.get(code) || {
        matchedTomorrowThemeNames: [],
        tomorrowReasonSnippets: [],
        tomorrowLabels: [],
        tomorrowIndustries: [],
        isTomorrowThemeHit: false,
      };
      map.set(code, {
        matchedTomorrowThemeNames: uniqueTexts([...prev.matchedTomorrowThemeNames, theme.themeName], 3),
        tomorrowReasonSnippets: uniqueTexts([...prev.tomorrowReasonSnippets, firstReasonLine(stock.reason)], 2),
        tomorrowLabels: uniqueTexts([...prev.tomorrowLabels, ...splitTomorrowLabels(stock.label)], 3),
        tomorrowIndustries: uniqueTexts([...prev.tomorrowIndustries, stock.industry], 2),
        isTomorrowThemeHit: true,
      });
    });
  });
  return map;
};
const tomorrowEvidenceByCode = computed(() => buildTomorrowEvidenceByCode());

watch(
  () => matchedTomorrowThemes.value.map((theme) => theme.themeCode).join('|'),
  (themeCodes) => {
    if (!themeCodes) return;
    matchedTomorrowThemes.value.forEach((theme) => {
      void ensureTomorrowThemeStocksLoaded(theme.themeCode);
    });
  },
  { immediate: true },
);
const hotMarketSnapshot = computed(() => {
  const latest = intradayLatest.value && typeof intradayLatest.value === 'object' ? intradayLatest.value : {};
  const liveMarket = intradayLive.value?.market && typeof intradayLive.value.market === 'object'
    ? intradayLive.value.market
    : (marketData.value?.live?.market && typeof marketData.value.live.market === 'object' ? marketData.value.live.market : {});
  const moodInputs = marketData.value?.features?.mood_inputs && typeof marketData.value.features.mood_inputs === 'object'
    ? marketData.value.features.mood_inputs
    : {};
  const panorama = marketData.value?.panorama && typeof marketData.value.panorama === 'object'
    ? marketData.value.panorama
    : {};
  return {
    shiftLabel: String(latest.shift_label || latest.headline || '').trim(),
    shiftScore: latest.shift_score === undefined || latest.shift_score === null ? undefined : toNum(latest.shift_score, 0),
    note: String(latest.note || '').trim(),
    zt: toNum(latest.zt ?? liveMarket.zt ?? moodInputs.zt_count ?? panorama.limitUp, 0),
    zab: toNum(latest.zab ?? liveMarket.zab ?? moodInputs.zb_count, 0),
    zabRate: toNum(latest.zab_rate ?? latest.zb ?? liveMarket.zab_rate ?? moodInputs.zb_rate, 0),
    lianban: toNum(latest.lianban ?? liveMarket.lianban ?? moodInputs.lianban_count, 0),
    maxLianban: toNum(latest.max_lb ?? latest.max_lianban ?? liveMarket.max_lianban ?? moodInputs.max_lb, 0),
    jjRate: toNum(latest.jj ?? liveMarket.jj ?? moodInputs.jj_rate_adj ?? moodInputs.jj_rate, 0),
    fbRate: toNum(latest.fb ?? liveMarket.fb ?? moodInputs.fb_rate ?? panorama.ratio, 0),
    amount: String(latest.amount ?? liveMarket.amount ?? marketData.value?.volume?.total ?? '').trim(),
  };
});
const hasIntradayDecision = computed(() => {
  if (!isToday.value) return false;
  // 盘中链路拒绝本次采集时，只保留最后有效值供观察，不能继续当作下单确认。
  if (intradayRuntimeStale.value) return false;
  const latest = intradayLatest.value && typeof intradayLatest.value === 'object' ? intradayLatest.value : {};
  const liveMarket = intradayLive.value?.market && typeof intradayLive.value.market === 'object'
    ? intradayLive.value.market
    : (marketData.value?.live?.market && typeof marketData.value.live.market === 'object' ? marketData.value.live.market : {});
  const latestHas = ['shift_label', 'shift_score', 'zt', 'zab', 'fb', 'jj', 'max_lb', 'lianban'].some((key) => latest[key] !== undefined && latest[key] !== null && latest[key] !== '');
  const liveHas = ['zt', 'zab', 'zab_rate', 'lianban', 'max_lianban', 'amount'].some((key) => liveMarket[key] !== undefined && liveMarket[key] !== null && liveMarket[key] !== '');
  return latestHas || liveHas;
});

const collectObjects = (value: unknown, guard: (row: Record<string, any>) => boolean, limit = 800) => {
  const out: Record<string, any>[] = [];
  const seen = new Set<unknown>();
  const walk = (node: unknown) => {
    if (out.length >= limit || node === null || node === undefined || seen.has(node)) return;
    if (typeof node !== 'object') return;
    seen.add(node);
    if (Array.isArray(node)) {
      node.forEach(walk);
      return;
    }
    const row = node as Record<string, any>;
    if (guard(row)) out.push(row);
    Object.values(row).forEach(walk);
  };
  walk(value);
  return out;
};

const makeXgbHeaders = () => {
  return {
    'Accept': 'application/json, text/plain, */*',
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
  };
};

const fetchText = async (url: string) => {
  const res = await fetch(`${url}${url.includes('?') ? '&' : '?'}_ts=${Date.now()}`, {
    cache: 'no-store',
    headers: makeXgbHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.text();
};

const fetchJson = async (url: string) => {
  const text = await fetchText(url);
  return JSON.parse(text);
};

const sourceUpdatedAt = (payload: any) => String(
  payload?.updated_at_bj || payload?.updatedAt || payload?.updated_at || payload?.generatedAt || '',
).trim();

const fetchHotEvents = async () => fetchJson('https://flash-api.xuangubao.cn/api/event/history?count=120');

const hydrateStocksWithQuote = async (stocks: HotStock[]) => {
  const codes = Array.from(new Set(stocks.map((x) => normalizeCode(x.code)).filter(isStockCode)));
  if (!codes.length) return stocks;
  const symbols = codes.map(toXgbSymbol).filter(Boolean);
  const quoteUrl = `https://flash-api.xuangubao.cn/api/stock/data?fields=symbol,stock_chi_name,change_percent,price,limit_up_days&strict=true&symbols=${symbols.join(',')}`;
  const labelUrl = `https://flash-api.xuangubao.cn/api/stock_label/labels?symbols=${symbols.join(',')}`;
  const [json, labelJson] = await Promise.all([
    fetchJson(quoteUrl),
    fetchJson(labelUrl).catch(() => ({ data: {} })),
  ]);
  const quoteData = json?.data || {};
  const labelData = labelJson?.data || {};
  return stocks.map((stock) => {
    const code = normalizeCode(stock.code);
    const symbol = toXgbSymbol(code);
    const quote = quoteData[symbol] || quoteData[code] || {};
    const labelRows = Array.isArray(labelData[symbol] || labelData[code]) ? (labelData[symbol] || labelData[code]) : [];
    const labelThemes = uniqueTexts(labelRows.map((item: any) => item?.label_name), 6);
    return makeStock({
      ...stock,
      code,
      name: String(quote.stock_chi_name || stock.name || code).trim(),
      changePct: quote.change_percent === undefined || quote.change_percent === null ? stock.changePct : toNum(quote.change_percent, 0) * 100,
      price: quote.price === undefined || quote.price === null ? stock.price : toNum(quote.price, 0),
      limitUpDays: quote.limit_up_days === undefined || quote.limit_up_days === null ? stock.limitUpDays : toNum(quote.limit_up_days, 0),
      label: labelThemes.join('、') || stock.label,
      relatedThemes: labelThemes,
    });
  });
};

const parseHotPlates = (json: any): HotPlate[] => {
  const rows = collectObjects(json, (row) => row.id !== undefined && row.name !== undefined);
  const map = new Map<string, HotPlate>();
  rows.forEach((row) => {
    const id = String(row.id ?? '').trim();
    const name = String(row.name ?? '').trim();
    if (!id || !name || id === '-1') return;
    if (!map.has(id)) {
      map.set(id, makePlate({
        id,
        name,
        description: String(row.description || row.desc || '').trim(),
      }));
    }
  });
  return Array.from(map.values());
};

const parsePlateRefsFromRow = (row: string): PlateRef[] => {
  const refs: PlateRef[] = [];
  const seen = new Set<string>();
  for (const match of row.matchAll(/"id":"?(-?\d+)"?,"name":"([^"]+)"/g)) {
    const id = String(match[1] || '').trim();
    const name = String(match[2] || '').trim();
    if (!id || !name || id === '-1' || seen.has(id)) continue;
    seen.add(id);
    refs.push({ id, name });
  }
  return refs;
};

const parseLeaderRowSegment = (segment: string, first = false) => {
  const matched = first ? segment.match(/\[\[([\s\S]*)/) : segment.match(/\],\[([\s\S]*)/);
  const row = matched?.[1] || segment.replace(/^\[\[/, '').replace(/^\],\[/, '');
  const plateRefs = parsePlateRefsFromRow(row);
  const stockPart = row.replace(/\[\{[\s\S]*$/, '');
  const cells = (stockPart.match(/"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?/g) || []).map((item) => item.replace(/^"|"$/g, ''));
  const codeIdx = cells.findIndex((cell) => isStockCode(cell));
  if (codeIdx === -1 || !plateRefs.length) return null;
  const code = normalizeCode(cells[codeIdx]);
  const nameIdx = cells.findIndex((cell, idx) => idx !== codeIdx && cell.length >= 2 && cell.length <= 10 && !isStockCode(cell));
  const name = nameIdx !== -1 ? cells[nameIdx].trim() : '';
  const strings = cells
    .map((val, idx) => ({ val, idx }))
    .filter((item) => item.idx !== codeIdx && item.idx !== nameIdx);
  const descItem = strings.sort((a, b) => b.val.length - a.val.length)[0];
  const desc = descItem && descItem.val.length > 10 ? descItem.val.trim() : '';
  const rawPct = cells.map((item) => Number(item)).find((item) => Number.isFinite(item) && Math.abs(item) <= 100);
  const label = cells.find((item) => /板|涨停|连板|首板|开板|炸板/.test(item) && item.length < 20) || '';
  if (!code || !name) return null;
  return {
    plateRefs,
    stock: makeStock({
      code,
      name,
      changePct: Math.abs(Number(rawPct)) <= 1 ? toNum(rawPct, 0) * 100 : toNum(rawPct, 0),
      limitUpDays: /首板/.test(label) ? 1 : Number((label.match(/(\d+)连板/) || [])[1] || 0),
      reason: desc,
      label,
      relatedDesc: desc,
      relatedThemes: splitLabelThemes(label),
    }),
  };
};

const parseLeaderStocksByPlateFromText = (text: string): Record<string, HotStock[]> => {
  const raw = String(text || '')
    .replace(/ /g, '')
    .replace(/(.SZ")|(.SS")|(.SH")/g, '"')
    .replace(/"id":-1,"name":"其他"/g, '"id":-2,"name":"其他"');
  const byPlateId: Record<string, HotStock[]> = {};
  const seenByPlate = new Map<string, Set<string>>();
  const pushParsed = (parsed: ReturnType<typeof parseLeaderRowSegment> | null) => {
    if (!parsed) return;
    for (const plate of parsed.plateRefs) {
      if (!plate.id) continue;
      const seen = seenByPlate.get(plate.id) || new Set<string>();
      if (seen.has(parsed.stock.code)) continue;
      seen.add(parsed.stock.code);
      seenByPlate.set(plate.id, seen);
      const list = byPlateId[plate.id] || [];
      list.push(makeStock(parsed.stock));
      byPlateId[plate.id] = list;
    }
  };

  (raw.match(/(\[\[).*?(?=\],\[)/g) || []).forEach((segment) => pushParsed(parseLeaderRowSegment(segment, true)));
  (raw.match(/(\],\[).*?((?=\],\[)|(?=\]\]))/g) || []).forEach((segment) => pushParsed(parseLeaderRowSegment(segment, false)));
  if (!Object.keys(byPlateId).length && raw.includes('[[')) pushParsed(parseLeaderRowSegment(raw.split(']]')[0], true));

  return byPlateId;
};

const parseLeaderStocksFromText = (text: string, plateId: string): HotStock[] => {
  return parseLeaderStocksByPlateFromText(text)[plateId] || [];
};

const parseLeaderStocks = (json: any, plateId: string): HotStock[] => {
  const arrayRows: any[][] = [];
  const seenArrays = new Set<unknown>();
  const walkArrays = (node: unknown) => {
    if (!node || typeof node !== 'object' || seenArrays.has(node)) return;
    seenArrays.add(node);
    if (Array.isArray(node)) {
      // 检查板块ID是否存在于数组的某个位置（通常是索引0或索引8）
      const hasPlate = node.some((cell) => {
        if (Array.isArray(cell)) {
          return cell.some((x: any) => String(x?.id ?? x?.plate_id ?? '') === plateId);
        }
        return false;
      });

      if (
        hasPlate &&
        node.some((cell) => typeof cell === 'string' && isStockCode(cell))
      ) {
        arrayRows.push(node);
      }
      node.forEach(walkArrays);
      return;
    }
    Object.values(node).forEach(walkArrays);
  };
  walkArrays(json);

  if (arrayRows.length) {
    const seen = new Set<string>();
    return arrayRows
      .map((row) => {
        // 自动识别字段索引
        // 1. 查找代码 (符合 6位数字 或 带 .SS/.SZ)
        const codeIdx = row.findIndex((cell) => typeof cell === 'string' && isStockCode(cell));
        if (codeIdx === -1) return null;
        const code = normalizeCode(row[codeIdx]);

        // 2. 查找名称 (通常在代码后面)
        const nameIdx = row.findIndex((cell, idx) => idx !== codeIdx && typeof cell === 'string' && cell.length >= 2 && cell.length <= 10 && !isStockCode(cell));
        const name = nameIdx !== -1 ? String(row[nameIdx]).trim() : '';

        // 3. 查找描述 (最长的字符串，且不是代码或名称)
        const strings = row
          .map((cell, idx) => ({ val: cell, idx }))
          .filter((item) => typeof item.val === 'string' && item.idx !== codeIdx && item.idx !== nameIdx);
        const descItem = strings.sort((a, b) => String(b.val).length - String(a.val).length)[0];
        const desc = descItem && String(descItem.val).length > 10 ? String(descItem.val).trim() : '';

        // 4. 查找标签 (包含"板"等关键字的短字符串)
        const labelItem = strings.find((item) => /板|涨停|连板|首板|开板|炸板/.test(String(item.val)) && String(item.val).length < 20);
        const label = labelItem ? String(labelItem.val).trim() : '';

        // 5. 查找涨幅
        const changeRaw = row.find((cell) => typeof cell === 'number' && Math.abs(cell) <= 100);
        const changePct = Math.abs(Number(changeRaw)) <= 1 ? Number(changeRaw) * 100 : Number(changeRaw);

        if (!code || !name || seen.has(code)) return null;
        seen.add(code);

        return {
          code,
          name,
          changePct: toNum(changePct, 0),
          limitUpDays: /首板/.test(label) ? 1 : Number((label.match(/(\d+)连板/) || [])[1] || 0),
          reason: desc,
          label,
          relatedDesc: desc,
          relatedThemes: splitLabelThemes(label),
          eventStrength: 0,
        };
      })
      .filter(Boolean) as HotStock[];
  }

  const rows = collectObjects(json, (row) => {
    const code = row.code ?? row.symbol;
    const name = row.prod_name ?? row.stock_chi_name ?? row.name;
    return code !== undefined && name !== undefined;
  });
  const out: HotStock[] = [];
  const seen = new Set<string>();
  rows.forEach((row) => {
    const related = collectObjects(row, (x) => String(x.id ?? '') === plateId || String(x.plate_id ?? '') === plateId, 20);
    if (plateId && related.length === 0 && JSON.stringify(row).indexOf(`"id":${plateId}`) === -1 && JSON.stringify(row).indexOf(`"id":"${plateId}"`) === -1) return;
    const code = normalizeCode(row.code ?? row.symbol);
    const name = String(row.prod_name ?? row.stock_chi_name ?? row.name ?? '').trim();
    if (!code || !name || seen.has(code)) return;
    seen.add(code);
    const rawPct = row.zf ?? row.change_percent ?? 0;
    const changePct = Math.abs(Number(rawPct)) <= 1 ? Number(rawPct) * 100 : Number(rawPct);
    out.push({
      code,
      name,
      changePct: toNum(changePct, 0),
      limitUpDays: toNum(row.limit_up_days, 0),
      reason: String(row.xq || row.desc || row.description || '').trim(),
      label: String(row.label || row.lb || '').trim(),
      relatedDesc: String(row.xq || row.desc || '').trim(),
      relatedThemes: splitLabelThemes(String(row.label || row.lb || '').trim()),
      eventStrength: 0,
    });
  });
  return out.map((stock) => makeStock(stock));
};

const parsePlateStocks = async (json: any): Promise<HotStock[]> => {
  const stockRows = collectObjects(json, (row) => row.symbol !== undefined || row.code !== undefined, 1000);
  const symbols = Array.from(new Set(stockRows.map((row) => normalizeCode(row.symbol ?? row.code)).filter(isStockCode))).slice(0, 80);
  if (!symbols.length) return [];

  const descByCode = new Map<string, string>();
  stockRows.forEach((row) => {
    const code = normalizeCode(row.symbol ?? row.code);
    const desc = String(row.desc || row.description || '').trim();
    if (code && desc && !descByCode.has(code)) descByCode.set(code, desc);
  });

  const quoteSymbols = symbols.map(toXgbSymbol).filter(Boolean);
  const quoteUrl = `https://flash-api.xuangubao.cn/api/stock/data?fields=symbol,stock_chi_name,change_percent,price,limit_up_days&strict=true&symbols=${quoteSymbols.join(',')}`;
  const labelUrl = `https://flash-api.xuangubao.cn/api/stock_label/labels?symbols=${quoteSymbols.join(',')}`;
  const [quoteJson, labelJson] = await Promise.all([fetchJson(quoteUrl), fetchJson(labelUrl).catch(() => ({ data: {} }))]);
  const quoteData = quoteJson?.data || {};
  const labelData = labelJson?.data || {};

  return symbols.map((code) => {
    const symbol = toXgbSymbol(code);
    const row = quoteData[symbol] || quoteData[code] || {};
    const labelRows = labelData[symbol] || labelData[code] || [];
    const labelThemes = Array.isArray(labelRows)
      ? uniqueTexts(labelRows.map((x: any) => String(x?.label_name || '').trim()), 6)
      : [];
    return makeStock({
      code,
      name: String(row.stock_chi_name || row.name || code).trim(),
      changePct: toNum(row.change_percent, 0) * 100,
      limitUpDays: toNum(row.limit_up_days, 0),
      reason: descByCode.get(code) || '',
      label: labelThemes.join('、'),
      relatedDesc: descByCode.get(code) || '',
      relatedThemes: labelThemes,
    });
  });
};

const parseHotEventSummaries = (json: any, plates: HotPlate[]) => {
  const rows = Array.isArray(json?.data) ? json.data : [];
  const plateIdByName = new Map<string, string>();
  const plateNameById = new Map<string, string>();
  plates.forEach((plate) => {
    plateIdByName.set(normalizeLooseText(plate.name), plate.id);
    plateNameById.set(plate.id, plate.name);
  });

  const plateHits = new Map<string, number>();
  const plateThemeCounts = new Map<string, Map<string, number>>();
  const stockSummaries = new Map<string, { eventStrength: number; themeCounts: Map<string, number> }>();

  const resolvePlateId = (rawId: unknown, rawName: unknown) => {
    const id = String(rawId || '').trim();
    if (id && plateNameById.has(id)) return id;
    const nameKey = normalizeLooseText(rawName);
    return plateIdByName.get(nameKey) || '';
  };
  const addPlateHit = (plateId: string) => {
    if (!plateId) return;
    plateHits.set(plateId, Number(plateHits.get(plateId) || 0) + 1);
  };
  const addPlateTheme = (plateId: string, themeName: unknown) => {
    const name = String(themeName || '').trim();
    if (!plateId || !name) return;
    const own = normalizeLooseText(plateNameById.get(plateId));
    const key = normalizeLooseText(name);
    if (!key || key === own) return;
    const bucket = plateThemeCounts.get(plateId) || new Map<string, number>();
    bucket.set(name, Number(bucket.get(name) || 0) + 1);
    plateThemeCounts.set(plateId, bucket);
  };
  const addStockTheme = (code: string, themeName: unknown) => {
    const name = String(themeName || '').trim();
    if (!code || !name) return;
    const summary = stockSummaries.get(code) || { eventStrength: 0, themeCounts: new Map<string, number>() };
    summary.themeCounts.set(name, Number(summary.themeCounts.get(name) || 0) + 1);
    stockSummaries.set(code, summary);
  };
  const addStockHit = (code: string) => {
    if (!code) return;
    const summary = stockSummaries.get(code) || { eventStrength: 0, themeCounts: new Map<string, number>() };
    summary.eventStrength += 1;
    stockSummaries.set(code, summary);
  };

  rows.forEach((row: any) => {
    const stock = (row && typeof row === 'object') ? (row.stock_abnormal_event_data || {}) : {};
    const relatedPlates = Array.isArray(stock.related_plates) ? stock.related_plates : [];
    const resolvedRefs = relatedPlates
      .map((plate: any): PlateRef => ({
        id: resolvePlateId(plate?.plate_id ?? plate?.id, plate?.plate_name ?? plate?.name),
        name: String(plate?.plate_name ?? plate?.name ?? '').trim(),
      }))
      .filter((plate: PlateRef) => plate.id);
    const code = normalizeCode(stock.symbol || row?.target);
    if (code && resolvedRefs.length) {
      addStockHit(code);
      resolvedRefs.forEach((ref: PlateRef) => addStockTheme(code, ref.name));
    }
    resolvedRefs.forEach((ref: PlateRef) => {
      addPlateHit(ref.id);
      resolvedRefs.forEach((other: PlateRef) => {
        if (other.id !== ref.id) addPlateTheme(ref.id, other.name);
      });
    });

    const plate = (row && typeof row === 'object') ? (row.plate_abnormal_event_data || {}) : {};
    const directPlateId = resolvePlateId(plate.plate_id ?? plate.id, plate.plate_name ?? plate.name);
    if (directPlateId) {
      addPlateHit(directPlateId);
      const relatedStocks = Array.isArray(plate.related_stocks) ? plate.related_stocks : [];
      relatedStocks.forEach((item: any) => {
        const relatedCode = normalizeCode(item?.symbol || item?.code);
        if (!relatedCode) return;
        addStockHit(relatedCode);
        addStockTheme(relatedCode, plateNameById.get(directPlateId) || plate?.plate_name || plate?.name);
      });
    }
  });

  const plateById: Record<string, PlateEventSummary> = {};
  plateNameById.forEach((_name, plateId) => {
    const themes = Array.from((plateThemeCounts.get(plateId) || new Map<string, number>()).entries())
      .sort((a, b) => b[1] - a[1])
      .map(([theme]) => theme);
    plateById[plateId] = {
      eventHitCount: Number(plateHits.get(plateId) || 0),
      eventThemes: uniqueTexts(themes, 4),
    };
  });

  const stockByCode: Record<string, StockEventSummary> = {};
  stockSummaries.forEach((summary, code) => {
    stockByCode[code] = {
      eventStrength: summary.eventStrength,
      relatedThemes: uniqueTexts(
        Array.from(summary.themeCounts.entries())
          .sort((a, b) => b[1] - a[1])
          .map(([theme]) => theme),
        4,
      ),
    };
  });

  return { plateById, stockByCode };
};

const applyStockEventEnhancements = (stocks: HotStock[]) => stocks.map((stock) => {
  const code = normalizeCode(stock.code);
  const eventMeta = hotStockEventByCode.value[code];
  const relatedThemes = uniqueTexts([
    ...(stock.relatedThemes || []),
    ...(eventMeta?.relatedThemes || []),
  ], 4);
  return makeStock({
    ...stock,
    code,
    relatedThemes,
    eventStrength: Number(eventMeta?.eventStrength || stock.eventStrength || 0),
  });
});

const mergePlateEnhancements = (plates: HotPlate[]) => plates.map((plate) => {
  const leaderStocks = hotLeaderStocksByPlateId.value[plate.id] || [];
  const leaderLimitCount = leaderStocks.filter((stock) => Number(stock.limitUpDays || 0) > 0).length;
  const topLeaderNames = uniqueTexts(
    [...leaderStocks]
      .sort((a, b) => {
        const limitDiff = Number(b.limitUpDays || 0) - Number(a.limitUpDays || 0);
        if (limitDiff !== 0) return limitDiff;
        return Number(b.changePct || 0) - Number(a.changePct || 0);
      })
      .map((stock) => stock.name),
    3,
  );
  const plateNameKey = normalizeLooseText(plate.name);
  const labelCounts = new Map<string, number>();
  leaderStocks.forEach((stock) => {
    (stock.relatedThemes || []).forEach((theme) => {
      const key = normalizeLooseText(theme);
      if (!key || key === plateNameKey || key.includes(plateNameKey) || plateNameKey.includes(key)) return;
      labelCounts.set(theme, Number(labelCounts.get(theme) || 0) + 1);
    });
  });
  const labelThemes = Array.from(labelCounts.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([theme]) => theme);
  const eventMeta = hotPlateEventById.value[plate.id] || { eventHitCount: 0, eventThemes: [] };

  return makePlate({
    ...plate,
    leaderStockCount: leaderStocks.length,
    leaderLimitCount,
    topLeaderNames,
    eventHitCount: Number(eventMeta.eventHitCount || 0),
    eventThemes: eventMeta.eventThemes || [],
    displayTags: uniqueTexts([...(labelThemes || []), ...(eventMeta.eventThemes || [])], 4),
  });
});

const loadHotPlates = async (keepSelection = false) => {
  hotLoading.value = true;
  hotError.value = '';
  const previousPlates = hotPlates.value;
  resetHotDerivedState();
  try {
    const url = isToday.value
      ? 'https://flash-api.xuangubao.cn/api/surge_stock/plates'
      : `https://flash-api.xuangubao.cn/api/surge_stock/plates?date=${Math.round(new Date(hotDate.value).getTime() / 1000)}`;
    const [json, eventJson] = await Promise.all([
      fetchJson(url),
      isToday.value ? fetchHotEvents().catch(() => null) : Promise.resolve(null),
    ]);
    let nextPlates = parseHotPlates(json);
    if (eventJson) {
      const eventSummaries = parseHotEventSummaries(eventJson, nextPlates);
      hotPlateEventById.value = eventSummaries.plateById;
      hotStockEventByCode.value = eventSummaries.stockByCode;
      nextPlates = mergePlateEnhancements(nextPlates);
    }
    hotPlates.value = nextPlates;
    if (isToday.value) setXgbPlates(hotPlates.value);
    if (!keepSelection || !hotPlates.value.some((x) => x.id === hotSelectedPlateId.value)) {
      const first = hotPlates.value[0];
      hotSelectedPlateId.value = first?.id || '';
      hotSelectedPlateName.value = first?.name || '';
    }
    // 只显示来源提供的时间，不能把浏览器请求完成时间伪装成数据更新时间。
    hotLastUpdated.value = sourceUpdatedAt(json);
    if (hotSelectedPlateId.value) await loadHotStocks(hotMode.value);
  } catch (e: any) {
    if (previousPlates.length) hotPlates.value = previousPlates;
    hotError.value = `热点解答获取失败：${String(e?.message || e)}`;
  } finally {
    hotLoading.value = false;
  }
};

const loadHotStocks = async (mode = hotMode.value, force = false) => {
  if (!hotSelectedPlateId.value) return;
  hotMode.value = mode;
  hotStockLoading.value = true;
  hotError.value = '';
  hotExpandedCodes.value = [];
  try {
    if (mode === 'leader') {
      if (!force && hotLeaderLoadedForDate.value === hotDate.value && Object.keys(hotLeaderStocksByPlateId.value).length) {
        hotStocks.value = hotLeaderStocksByPlateId.value[hotSelectedPlateId.value] || [];
        if (isToday.value) setXgbStocksForPlate(hotSelectedPlateId.value, hotStocks.value);
        return;
      }
      const url = isToday.value
        ? 'https://flash-api.xuangubao.cn/api/surge_stock/stocks?normal=true&uplimit=true'
        : `https://flash-api.xuangubao.cn/api/surge_stock/stocks?date=${hotDateParam.value}&normal=true&uplimit=true`;
      const text = await fetchText(url);
      let stocksByPlateId = parseLeaderStocksByPlateFromText(text);
      if (!Object.keys(stocksByPlateId).length) {
        const json = JSON.parse(text);
        stocksByPlateId = {};
        hotPlates.value.forEach((plate) => {
          const rows = parseLeaderStocks(json, plate.id);
          if (rows.length) stocksByPlateId[plate.id] = rows;
        });
      }
      const allStocks = uniqueTexts(
        Object.values(stocksByPlateId).flatMap((stocks) => stocks.map((stock) => stock.code)),
      ).map((code) => Object.values(stocksByPlateId).flat().find((stock) => normalizeCode(stock.code) === code)).filter(Boolean) as HotStock[];
      const hydratedStocks = applyStockEventEnhancements(await hydrateStocksWithQuote(allStocks));
      const stockIndex = new Map(hydratedStocks.map((stock) => [normalizeCode(stock.code), stock]));
      const nextLeaderStocksByPlateId: Record<string, HotStock[]> = {};
      Object.entries(stocksByPlateId).forEach(([plateId, stocks]) => {
        nextLeaderStocksByPlateId[plateId] = applyStockEventEnhancements(
          stocks.map((stock) => stockIndex.get(normalizeCode(stock.code)) || stock),
        );
      });
      hotLeaderStocksByPlateId.value = nextLeaderStocksByPlateId;
      hotLeaderLoadedForDate.value = hotDate.value;
      hotPlates.value = mergePlateEnhancements(hotPlates.value);
      hotStocks.value = nextLeaderStocksByPlateId[hotSelectedPlateId.value] || [];
    } else {
      if (!force && hotAllStocksByPlateId.value[hotSelectedPlateId.value]) {
        hotStocks.value = hotAllStocksByPlateId.value[hotSelectedPlateId.value];
        return;
      }
      const json = await fetchJson(`https://flash-api.xuangubao.cn/api/plate/plate_set?id=${hotSelectedPlateId.value}`);
      const parsed = await parsePlateStocks(json);
      hotStocks.value = applyStockEventEnhancements(parsed);
      hotAllStocksByPlateId.value = { ...hotAllStocksByPlateId.value, [hotSelectedPlateId.value]: hotStocks.value };
    }
    if (isToday.value) setXgbStocksForPlate(hotSelectedPlateId.value, hotStocks.value);
  } catch (e: any) {
    hotError.value = `股票明细获取失败：${String(e?.message || e)}`;
  } finally {
    hotStockLoading.value = false;
  }
};

const selectHotPlate = async (plate: HotPlate) => {
  hotSelectedPlateId.value = plate.id;
  hotSelectedPlateName.value = plate.name;
  await loadHotStocks(hotMode.value);
};

const toggleHotDetail = (code: string) => {
  const next = normalizeCode(code);
  hotExpandedCodes.value = hotExpandedCodes.value.includes(next)
    ? hotExpandedCodes.value.filter((x) => x !== next)
    : [...hotExpandedCodes.value, next];
};

const xueqiuUrl = (code: string) => `https://xueqiu.com/S/${code.startsWith('6') ? 'SH' : 'SZ'}${code}`;

const hotDecisionGate = computed<HotDecisionGate>(() => {
  if (!isToday.value) {
    return {
      tone: 'history',
      label: '仅供复盘',
      summary: '历史日期只保留热点浏览和题材复盘，不给盘中下单判断。',
      modeLabel: hotMode.value === 'leader' ? '领涨复盘' : '全部复盘',
      signals: takeTexts([
        selectedPlate.value?.name ? `${selectedPlate.value.name} 复盘口径` : '',
        `板块 ${hotStats.value.plates}`,
        `个股 ${selectedStockCount.value}`,
      ], 3),
      vetoReasons: [],
    };
  }

  if (!hasIntradayDecision.value) {
    return {
      tone: 'history',
      label: '等待盘中确认',
      summary: '盘中运行时还不够完整，先看热点与前排，不把这里当成直接下单信号。',
      modeLabel: hotMode.value === 'leader' ? '盘中待确认' : '暂看全景',
      signals: takeTexts([
        String(tradePlan.value?.marketGate || '').trim(),
        String(tradePlan.value?.tideGate || '').trim(),
        String(actionAdvisor.value?.posture || '').trim(),
        intradayRuntimeError.value || '',
        intradayRuntimeStale.value ? '盘中数据已过期' : '',
      ], 3),
      vetoReasons: takeTexts([
        '缺少有效盘中快照',
        '先等情绪与承接同步确认',
      ], 2),
    };
  }

  const snapshot = hotMarketSnapshot.value;
  const posture = String(actionAdvisor.value?.posture || '').trim();
  const marketGate = String(tradePlan.value?.marketGate || '').trim();
  const tideGate = String(tradePlan.value?.tideGate || '').trim();
  const strictGate = Boolean(tradePlan.value?.strictGate) || /休息|防守/.test(marketGate) || /防守|谨慎/.test(posture);
  const shiftTone = hotShiftLabelTone(snapshot.shiftLabel);
  const signals = takeTexts([
    snapshot.shiftLabel ? `情绪 ${snapshot.shiftLabel}${snapshot.shiftScore !== undefined ? ` ${snapshot.shiftScore}` : ''}` : '',
    snapshot.fbRate ? `封板 ${snapshot.fbRate.toFixed(0)}%` : '',
    snapshot.zabRate ? `炸板 ${snapshot.zabRate.toFixed(0)}%` : '',
    snapshot.maxLianban ? `高度 ${snapshot.maxLianban} 板` : '',
    marketGate ? `闸门 ${marketGate}` : '',
    tideGate ? `潮汐 ${tideGate}` : '',
    posture ? `姿态 ${posture}` : '',
  ], 5);
  const vetoReasons = takeTexts([
    strictGate ? `${marketGate || '市场闸门'}偏防守` : '',
    snapshot.zabRate >= 35 ? `炸板率 ${snapshot.zabRate.toFixed(1)}%，分歧偏强` : '',
    snapshot.maxLianban >= 6 && snapshot.zabRate >= 25 ? `高度 ${snapshot.maxLianban} 板且分歧不低，高位兑现风险在放大` : '',
    /走弱|退潮|跳水/.test(snapshot.shiftLabel) ? `盘中情绪 ${snapshot.shiftLabel}` : '',
  ], 4);

  let tone: Exclude<HotDecisionTone, 'history'> = 'watch';
  if (
    strictGate ||
    shiftTone === 'avoid' ||
    snapshot.zabRate >= 35 ||
    (snapshot.maxLianban >= 6 && snapshot.zabRate >= 25)
  ) {
    tone = 'avoid';
  } else if (
    shiftTone === 'buy' ||
    /进攻|试错|修复|回暖/.test(posture) ||
    (snapshot.fbRate >= 70 && snapshot.zabRate <= 22 && snapshot.zt >= 40)
  ) {
    tone = 'buy';
  }

  const label = tone === 'buy' ? '可试错' : tone === 'watch' ? '只观察不下单' : '今日回避';
  const summary = tone === 'buy'
    ? '情绪与承接允许试错，但仍只做前排回封确认，不做一致性追高。'
    : tone === 'watch'
      ? '环境没有差到必须空仓，但更适合等分歧转一致和回封确认。'
      : '当前市场闸门偏弱，先看风险释放，不把热点直接当成买点。';

  return {
    tone,
    label,
    summary,
    modeLabel: hotMode.value === 'leader' ? '盘中确认' : '全景过滤',
    signals,
    vetoReasons,
  };
});

const buildHotStockAction = (stock: HotStock, index: number): HotStockAction => {
  const code = normalizeCode(stock.code);
  const tomorrowEvidence = tomorrowEvidenceByCode.value.get(code) || {
    matchedTomorrowThemeNames: [],
    tomorrowReasonSnippets: [],
    tomorrowLabels: [],
    tomorrowIndustries: [],
    isTomorrowThemeHit: false,
  };
  const candidate = tradePlanByCode.value.get(code) || null;
  const relayRow = ztRelayByCode.value.get(code) || null;
  const watchRow = ztWatchByCode.value.get(code) || null;
  const ladderRow = ladderByCode.value.get(code) || null;
  const ladderTags = collectRowTags(ladderRow);
  const badge = toNum(ladderRow?.badge, 0);
  const marketTone = hotDecisionGate.value.tone;
  const isLimit = toNum(stock.limitUpDays, 0) > 0;
  const candidateTone = String(candidate?.tone || '').trim();
  const isPrimaryCandidate = candidateTone === 'attack' || String(candidate?.bucket || '').includes('优先');
  const isWatchCandidate = candidateTone === 'watch' || String(candidate?.bucket || '').includes('观察');
  const isCapacity = ladderTags.some((tag: string) => /高换手|换手|容量/.test(tag)) || top10CapacitySet.value.has(code);
  const relayScore = toNum(relayRow?.score, 0);
  const watchScore = toNum(watchRow?.score, 0);
  const candidateScore = toNum(candidate?.score, 0);
  const ztScore = relayScore || watchScore || candidateScore;

  let score = 18;
  score += Math.min(Math.max(toNum(stock.changePct, 0), 0), 20);
  score += Math.min(toNum(stock.eventStrength, 0) * 5, 18);
  if (isLimit) score += 24 + Math.min(toNum(stock.limitUpDays, 0) * 8, 20);
  if (isPrimaryCandidate) score += 24;
  else if (isWatchCandidate) score += 10;
  if (relayRow) score += 18;
  else if (watchRow) score += 8;
  if (badge >= 5) score += 16;
  else if (badge >= 3) score += 9;
  if (isCapacity) score += 4;
  score += Math.min(ztScore * 0.2, 18);
  if (!isLimit && !relayRow && !candidate) score -= 14;
  if (marketTone === 'avoid') score -= 28;
  if (badge >= 6 && hotMarketSnapshot.value.zabRate >= 25) score -= 10;
  if (index >= 3 && !relayRow && !candidate) score -= 8;

  let roleLabel = '跟风';
  if (badge >= 5) roleLabel = '情绪龙';
  else if (/龙/.test(String(relayRow?.leaderRole || ''))) roleLabel = '龙头';
  else if (relayRow) roleLabel = '前排';
  else if (badge >= 3) roleLabel = '高标';
  else if (isCapacity) roleLabel = '容量';
  else if (watchRow || isWatchCandidate) roleLabel = '观察';

  if (!hasIntradayDecision.value) {
    return {
      ...stock,
      actionTone: 'watch',
      actionScore: Math.round(score),
      roleLabel,
      entryStyle: isToday.value ? '等待盘中快照，不给直接下单判断' : '历史复盘样本，只看题材与前排表现',
      confirmSignals: takeTexts([
        isLimit ? `${toNum(stock.limitUpDays, 0) > 1 ? `${toNum(stock.limitUpDays, 0)}连板` : '首板'}表现` : '',
        toNum(stock.eventStrength, 0) >= 2 ? `异动命中 ${toNum(stock.eventStrength, 0)} 次` : '',
        candidate?.line ? `命中 ${candidate.line}` : '',
        tomorrowEvidence.isTomorrowThemeHit ? `命中东财题材 ${tomorrowEvidence.matchedTomorrowThemeNames[0] || ''}` : '',
      ], 3),
      vetoReasons: takeTexts([
        isToday.value ? '暂无有效盘中确认' : '历史日期默认不做盘中买入判断',
      ], 1),
      isActionable: false,
      matchedTomorrowThemeNames: tomorrowEvidence.matchedTomorrowThemeNames,
      tomorrowReasonSnippets: tomorrowEvidence.tomorrowReasonSnippets,
      tomorrowLabels: tomorrowEvidence.tomorrowLabels,
      tomorrowIndustries: tomorrowEvidence.tomorrowIndustries,
      isTomorrowThemeHit: tomorrowEvidence.isTomorrowThemeHit,
    };
  }

  let actionTone: Exclude<HotDecisionTone, 'history'> = 'watch';
  if (marketTone === 'avoid') {
    actionTone = score >= 68 && (relayRow || isPrimaryCandidate) ? 'watch' : 'avoid';
  } else if (score >= 72 && isLimit && (relayRow || isPrimaryCandidate || badge >= 3)) {
    actionTone = 'buy';
  } else if (score >= 48) {
    actionTone = 'watch';
  } else {
    actionTone = 'avoid';
  }

  const entryStyle = String(relayRow?.nextStep || watchRow?.nextStep || '').trim()
    || (actionTone === 'buy'
      ? (toNum(stock.limitUpDays, 0) >= 2 ? '只做回封确认，不追一致性' : '分歧转一致 / 回封确认')
      : actionTone === 'watch'
        ? '只看承接，不做追高'
        : '先别下单，等待更强确认');

  const confirmSignals = takeTexts([
    ...(Array.isArray(relayRow?.hitRules) ? relayRow.hitRules : []),
    ...(Array.isArray(watchRow?.hitRules) ? watchRow.hitRules : []),
    isLimit ? `${toNum(stock.limitUpDays, 0) > 1 ? `${toNum(stock.limitUpDays, 0)}连板` : '首板'}仍在前排` : '',
    toNum(stock.eventStrength, 0) >= 2 ? `异动命中 ${toNum(stock.eventStrength, 0)} 次` : '',
    selectedPlate.value?.eventHitCount ? `板块异动 ${selectedPlate.value.eventHitCount} 次` : '',
    hotDecisionGate.value.tone === 'buy' && hotMarketSnapshot.value.shiftLabel ? `情绪 ${hotMarketSnapshot.value.shiftLabel}` : '',
    candidate?.line ? `命中 ${candidate.line}` : '',
    tomorrowEvidence.isTomorrowThemeHit ? `命中东财 ${tomorrowEvidence.matchedTomorrowThemeNames[0] || '题材池'}` : '',
  ], 3);

  const vetoReasons = takeTexts([
    ...(Array.isArray(relayRow?.blockReasons) ? relayRow.blockReasons : []),
    ...(Array.isArray(watchRow?.blockReasons) ? watchRow.blockReasons : []),
    hotDecisionGate.value.tone === 'avoid' ? '市场闸门偏弱，先别硬接力' : '',
    !candidate && !relayRow && !watchRow ? '未进接力/观察池' : '',
    !isLimit ? '当前不是涨停/连板确认态' : '',
    !relayRow && !isPrimaryCandidate && index >= 3 ? '更像跟风，不做首选' : '',
    !isLimit && toNum(stock.changePct, 0) >= 8 ? '冲高过热，先等回封' : '',
  ], 3);

  return {
    ...stock,
    actionTone,
    actionScore: Math.round(score),
    roleLabel,
    entryStyle,
    confirmSignals,
    vetoReasons,
    isActionable: hasIntradayDecision.value && hotDecisionGate.value.tone !== 'avoid' && actionTone === 'buy',
    matchedTomorrowThemeNames: tomorrowEvidence.matchedTomorrowThemeNames,
    tomorrowReasonSnippets: tomorrowEvidence.tomorrowReasonSnippets,
    tomorrowLabels: tomorrowEvidence.tomorrowLabels,
    tomorrowIndustries: tomorrowEvidence.tomorrowIndustries,
    isTomorrowThemeHit: tomorrowEvidence.isTomorrowThemeHit,
  };
};

const stockActions = computed<HotStockAction[]>(() => (
  sortedStocks.value
    .map((stock, index) => buildHotStockAction(stock, index))
    .sort((a, b) => (
      decisionToneRank(a.actionTone) - decisionToneRank(b.actionTone)
      || b.actionScore - a.actionScore
      || Number(b.limitUpDays || 0) - Number(a.limitUpDays || 0)
      || Number(b.changePct || 0) - Number(a.changePct || 0)
    ))
));
const stockActionByCode = computed(() => {
  const map = new Map<string, HotStockAction>();
  stockActions.value.forEach((stock) => {
    map.set(normalizeCode(stock.code), stock);
  });
  return map;
});
const representativeStockActions = computed<HotStockAction[]>(() => representativeStocks.value
  .map((stock) => stockActionByCode.value.get(normalizeCode(stock.code)) || buildHotStockAction(stock, 0))
  .slice(0, 3));
const actionableStocks = computed<HotStockAction[]>(() => stockActions.value.filter((stock) => stock.isActionable).slice(0, 3));

const hotPlateDecision = computed<HotPlateDecision | null>(() => {
  if (!selectedPlate.value || !hasIntradayDecision.value) return null;
  const gateTone = hotDecisionGate.value.tone;
  let score = 34;
  const confirmSignals: string[] = [];
  const vetoReasons: string[] = [];
  const plateName = selectedPlate.value.name;
  const plateMatchedCandidates = stockActions.value.filter((stock) => (
    matchesPlateName(plateName, [stock.roleLabel, ...(stock.relatedThemes || [])])
    || matchesPlateName(plateName, [tradePlanByCode.value.get(normalizeCode(stock.code))?.line, tradePlanByCode.value.get(normalizeCode(stock.code))?.primarySector])
  ));

  if (selectedPlate.value.eventHitCount >= 3) {
    score += 16;
    confirmSignals.push(`盘中异动 ${selectedPlate.value.eventHitCount} 次`);
  }
  if (selectedLimitCount.value >= 3) {
    score += 18;
    confirmSignals.push(`前排涨停 ${selectedLimitCount.value} 只`);
  }
  if (representativeStockActions.value.some((stock) => toNum(stock.limitUpDays, 0) >= 2)) {
    score += 12;
    confirmSignals.push('有连板前排持续带动');
  }
  if (actionableStocks.value.length) {
    score += 18;
    confirmSignals.push(`通过过滤 ${actionableStocks.value.length} 只`);
  }
  if (plateMatchedCandidates.length >= 2) {
    score += 10;
    confirmSignals.push(`命中研究候选 ${plateMatchedCandidates.length} 只`);
  }

  if (gateTone === 'avoid') vetoReasons.push('市场闸门偏弱，题材也先按防守处理');
  if (!selectedLimitCount.value) vetoReasons.push('当前缺少涨停/连板承接');
  if (!selectedPlate.value.eventHitCount) vetoReasons.push('盘中异动证据不够连续');
  if (!actionableStocks.value.length) vetoReasons.push('还没有通过严格过滤的出手点');
  if ((selectedPlate.value.leaderStockCount || 0) <= 1) vetoReasons.push('联动个股偏少，更像单点脉冲');

  let tone: Exclude<HotDecisionTone, 'history'> = 'watch';
  if (gateTone === 'avoid' || score < 44) tone = 'avoid';
  else if (score >= 72 && actionableStocks.value.length) tone = 'buy';

  const label = tone === 'buy' ? '这个板块可做' : tone === 'watch' ? '这个板块先观察' : '这个板块先回避';
  const summary = tone === 'buy'
    ? '有前排承接和板块异动共振，但仍只盯最强 1 到 3 只确认点。'
    : tone === 'watch'
      ? '有热点，但更像等待二次确认，不适合看到题材就直接下单。'
      : '热点不等于买点，当前更缺前排承接或市场环境配合。';

  return {
    tone,
    score: Math.round(score),
    label,
    summary,
    confirmSignals: takeTexts(confirmSignals, 4),
    vetoReasons: takeTexts(vetoReasons, 4),
  };
});

const rankedStocks = computed<HotStockAction[]>(() => stockActions.value);

const refreshHotAnswer = () => loadHotPlates(true);

onMounted(() => {
  void ensureTomorrowLoaded();
  void loadHotPlates(false);
});
</script>

<template>
  <div class="hot-page">
    <div class="card hot-card" data-page="hotAnswer" id="sec-hot-answer">
      <div class="card-header">
        <div>
          <div class="card-title">热点解答</div>
        </div>
      </div>

      <div class="hot-toolbar">
        <div class="hot-toolbar-left">
          <label class="hot-date">
            <span>日期</span>
            <DatePicker
              v-model:value="hotDateValue"
              class="hot-date-picker"
              format="YYYY-MM-DD"
              :allow-clear="false"
              :input-read-only="true"
              @change="loadHotPlates(false)"
            />
          </label>
          <button class="hot-btn" type="button" @click="refreshHotAnswer()">刷新</button>
          <button class="hot-btn" :class="{ active: hotMode === 'leader' }" type="button" @click="loadHotStocks('leader')">领涨</button>
          <button class="hot-btn" :class="{ active: hotMode === 'all' }" type="button" @click="loadHotStocks('all')">全部</button>
        </div>
        <div class="hot-toolbar-right">
          <span>板块 <b class="hot-stat-num">{{ hotStats.plates }}</b></span>
          <span v-if="hotLastUpdated">更新 <b class="hot-stat-num">{{ hotLastUpdated }}</b></span>
        </div>
      </div>

      <div v-if="hotError" class="hot-error">{{ hotError }}</div>

      <div class="hot-layout">
        <aside class="hot-plates">
          <!-- Plate Loading Skeleton -->
          <div v-if="hotLoading && !hotPlates.length" class="hot-skeleton-list">
            <div v-for="i in 6" :key="'hsk-p-'+i" class="hot-skeleton-plate">
              <div class="hot-sk-title"></div>
              <div class="hot-sk-line"></div>
            </div>
          </div>

          <template v-else>
            <button
              v-for="plate in hotPlates"
              :key="plate.id"
              class="hot-plate"
              :class="{ active: plate.id === hotSelectedPlateId }"
              type="button"
              @click="selectHotPlate(plate)">
              <span class="hot-plate-name">{{ plate.name }}</span>
              <span v-if="plate.description" class="hot-plate-desc">{{ plate.description }}</span>
              <div v-if="hotMode === 'leader'" class="hot-plate-stats">
                <span class="hot-plate-stat">个股 {{ plate.leaderStockCount }}</span>
                <span class="hot-plate-stat hot">涨停 {{ plate.leaderLimitCount }}</span>
              </div>
            </button>
          </template>
        </aside>

        <section class="hot-detail">
          <div v-if="selectedPlate || hotSelectedPlateName" class="hot-detail-content">
            <div class="hot-detail-head">
              <div>
                <div class="hot-detail-title">{{ selectedPlate?.name || hotSelectedPlateName }}</div>
                <div class="hot-detail-desc">
                  <template v-if="splitLines(selectedPlate?.description).length > 1">
                    <ul class="hot-desc-list">
                      <li v-for="(line, i) in splitLines(selectedPlate?.description)" :key="i">{{ line }}</li>
                    </ul>
                  </template>
                  <template v-else>
                    {{ selectedPlate?.description }}
                  </template>
                </div>
                <div class="hot-detail-metrics">
                  <span class="hot-detail-metric">个股 {{ selectedStockCount }}</span>
                  <span class="hot-detail-metric hot">涨停 {{ selectedLimitCount }}</span>
                  <span v-if="selectedPlate?.eventHitCount" class="hot-detail-metric">异动 {{ selectedPlate?.eventHitCount }}</span>
                </div>
              </div>
              <div class="hot-mode">{{ hotMode === 'leader' ? '领涨' : '全部' }}</div>
            </div>

            <div v-if="selectedLeaderText" class="hot-detail-summary">
              <div v-if="selectedLeaderText" class="hot-summary-row">
                <span class="hot-summary-k">代表股</span>
                <span class="hot-summary-v">{{ selectedLeaderText }}</span>
              </div>
            </div>

            <div class="hot-decision-panel" :class="`tone-${hotDecisionGate.tone}`">
              <div class="hot-decision-kicker">市场能不能买</div>
              <div class="hot-decision-head">
                <div>
                  <div class="hot-decision-title">{{ hotDecisionGate.label }}</div>
                  <div class="hot-decision-copy">{{ hotDecisionGate.summary }}</div>
                </div>
                <span class="hot-decision-mode">{{ hotDecisionGate.modeLabel }}</span>
              </div>
              <div v-if="hotDecisionGate.signals.length" class="hot-decision-tags">
                <span v-for="signal in hotDecisionGate.signals" :key="`gate-${signal}`" class="hot-decision-chip">
                  {{ signal }}
                </span>
              </div>
              <div v-if="hotDecisionGate.vetoReasons.length" class="hot-decision-notes">
                <div class="hot-decision-note-title">先别急着下单</div>
                <ul class="hot-decision-note-list">
                  <li v-for="reason in hotDecisionGate.vetoReasons" :key="`gate-veto-${reason}`">{{ reason }}</li>
                </ul>
              </div>
            </div>

            <div v-if="hotPlateDecision" class="hot-decision-panel is-plate" :class="`tone-${hotPlateDecision.tone}`">
              <div class="hot-decision-kicker">这个板块值不值得买</div>
              <div class="hot-decision-head">
                <div>
                  <div class="hot-decision-title">{{ hotPlateDecision.label }}</div>
                  <div class="hot-decision-copy">{{ hotPlateDecision.summary }}</div>
                </div>
                <span class="hot-decision-score">判断 {{ hotPlateDecision.score }}</span>
              </div>
              <div v-if="hotPlateDecision.confirmSignals.length" class="hot-decision-tags">
                <span v-for="signal in hotPlateDecision.confirmSignals" :key="`plate-signal-${signal}`" class="hot-decision-chip">
                  {{ signal }}
                </span>
              </div>
              <div v-if="hotPlateDecision.vetoReasons.length" class="hot-decision-notes">
                <div class="hot-decision-note-title">当前缺什么</div>
                <ul class="hot-decision-note-list">
                  <li v-for="reason in hotPlateDecision.vetoReasons" :key="`plate-veto-${reason}`">{{ reason }}</li>
                </ul>
              </div>
            </div>

            <div class="hot-theme-evidence">
              <div class="hot-leader-title">题材跟踪证据</div>
              <div v-if="matchedTomorrowThemePanels.length" class="hot-theme-evidence-card">
                <ol class="hot-theme-evidence-list">
                  <li
                  v-for="theme in matchedTomorrowThemePanels"
                  :key="`theme-evidence-${theme.themeCode}`"
                  class="hot-theme-evidence-item">
                    <div class="hot-theme-card-head">
                      <div class="hot-theme-card-title-wrap">
                        <div class="hot-theme-card-title-row">
                          <span class="hot-theme-card-name">{{ theme.themeName }}</span>
                          <span v-if="theme.isHot" class="hot-theme-flag hot">HOT</span>
                        </div>
                        <div v-if="theme.title" class="hot-theme-card-title">{{ theme.title }}</div>
                      </div>
                      <button class="hot-theme-jump" type="button" @click="jumpToTomorrowTheme(theme.themeCode)">
                        去今日题材
                      </button>
                    </div>
                    <div v-if="theme.summary" class="hot-theme-card-summary">{{ theme.summary }}</div>
                    <div v-if="theme.stocks?.length" class="hot-theme-preview">
                      <div class="hot-summary-row hot-summary-row-tags">
                        <span class="hot-summary-k">代表股</span>
                        <span class="hot-summary-v">
                          {{ theme.stocks.slice(0, 4).map((stock) => stock.name || stock.code).filter(Boolean).join(' / ') }}
                        </span>
                      </div>
                      <div
                        v-if="theme.stocks[0] && (theme.stocks[0].reasonSnippet || theme.stocks[0].industry || theme.stocks[0].marketCap)"
                        class="hot-theme-preview-brief">
                        <span v-if="theme.stocks[0].reasonSnippet">入选理由：{{ theme.stocks[0].reasonSnippet }}</span>
                        <span v-else-if="theme.stocks[0].industry || theme.stocks[0].marketCap">
                          {{ [theme.stocks[0].industry, theme.stocks[0].marketCap ? formatMarketCap(theme.stocks[0].marketCap) : ''].filter(Boolean).join(' / ') }}
                        </span>
                      </div>
                    </div>
                  </li>
                </ol>
              </div>
              <div v-else-if="tmrThemes.length" class="hot-theme-empty">
                暂无东财题材映射
              </div>
              <div v-else class="hot-theme-empty">
                暂无题材数据
              </div>
            </div>

            <div v-if="hasIntradayDecision" class="hot-action-section">
              <div class="hot-leader-title">当前只盯哪几只</div>
              <div v-if="actionableStocks.length" class="hot-action-list">
                <article
                  v-for="stock in actionableStocks"
                  :key="`action-${stock.code}`"
                  class="hot-action-card"
                  :class="`tone-${stock.actionTone}`">
                  <div class="hot-action-head">
                    <div class="hot-action-title-row">
                      <a
                        :class="['hot-stock-name', { 'is-limit-up': stock.limitUpDays }]"
                        :href="xueqiuUrl(stock.code)"
                        target="_blank"
                        rel="noopener noreferrer">
                        {{ stock.name }}
                      </a>
                      <span class="hot-action-role">{{ stock.roleLabel }}</span>
                      <span class="hot-action-tone">{{ stock.actionTone === 'buy' ? '可执行' : '先观察' }}</span>
                    </div>
                    <span class="hot-decision-score">评分 {{ stock.actionScore }}</span>
                  </div>
                  <div class="hot-leader-metrics">
                    <span v-if="stock.price" class="hot-price">{{ stock.price.toFixed(2) }}</span>
                    <span :class="['hot-pct', stock.changePct >= 0 ? 'up' : 'down']">{{ formatPct(stock.changePct) }}</span>
                    <span
                      v-for="theme in stock.relatedThemes"
                      :key="`action-${stock.code}-${theme}`"
                      :class="['hot-theme-chip', themeChipToneClass(theme)]">
                      {{ theme }}
                    </span>
                    <span
                      v-for="label in stock.tomorrowLabels.slice(0, 2)"
                      :key="`action-tmr-${stock.code}-${label}`"
                      class="hot-theme-chip">
                      {{ label }}
                    </span>
                    <span v-if="stock.limitUpDays" class="hot-limit">{{ stock.limitUpDays === 1 ? '首板' : stock.limitUpDays + '连板' }}</span>
                    <span v-if="stock.isTomorrowThemeHit" class="hot-signal-chip">题材命中</span>
                  </div>
                  <div class="hot-action-entry">{{ stock.entryStyle }}</div>
                  <div v-if="stock.confirmSignals.length" class="hot-action-tags">
                    <span v-for="signal in stock.confirmSignals" :key="`action-confirm-${stock.code}-${signal}`" class="hot-action-chip">
                      {{ signal }}
                    </span>
                  </div>
                  <div v-if="stock.isTomorrowThemeHit && (stock.matchedTomorrowThemeNames.length || stock.tomorrowReasonSnippets.length)" class="hot-tomorrow-evidence">
                    <div class="hot-tomorrow-title">
                      东财题材：{{ stock.matchedTomorrowThemeNames.join(' / ') || '已命中题材池' }}
                      <span v-if="stock.tomorrowIndustries.length" class="hot-tomorrow-meta">· {{ stock.tomorrowIndustries.join(' / ') }}</span>
                    </div>
                    <div
                      v-for="reason in stock.tomorrowReasonSnippets.slice(0, 2)"
                      :key="`action-tmr-reason-${stock.code}-${reason}`"
                      class="hot-tomorrow-reason">
                      {{ reason }}
                    </div>
                  </div>
                  <div v-if="stock.vetoReasons.length" class="hot-action-risk">
                    先别乱追：{{ stock.vetoReasons.join(' / ') }}
                  </div>
                </article>
              </div>
              <div v-else class="hot-empty">
                当前没有通过严格过滤的买点，先观察承接和回封，不把所有强势股都当成可买。
              </div>
            </div>

            <div v-if="representativeStockActions.length" class="hot-leader-section">
              <div class="hot-leader-title">代表股详情</div>
              <div class="hot-leader-list">
                <article v-for="stock in representativeStockActions" :key="`leader-${stock.code}`" class="hot-leader-card" :class="`tone-${stock.actionTone}`">
                  <div class="hot-leader-head">
                    <div class="hot-action-title-wrap">
                      <a
                        :class="['hot-stock-name', { 'is-limit-up': stock.limitUpDays }]"
                        :href="xueqiuUrl(stock.code)"
                        target="_blank"
                        rel="noopener noreferrer">
                        {{ stock.name }}
                      </a>
                      <div class="hot-action-mini-row">
                        <span class="hot-action-role">{{ stock.roleLabel }}</span>
                        <span class="hot-action-tone is-inline">{{ stock.actionTone === 'buy' ? '可执行' : stock.actionTone === 'watch' ? '观察' : '回避' }}</span>
                      </div>
                    </div>
                    <div class="hot-leader-metrics">
                      <span v-if="stock.price" class="hot-price">{{ stock.price.toFixed(2) }}</span>
                      <span :class="['hot-pct', stock.changePct >= 0 ? 'up' : 'down']">{{ formatPct(stock.changePct) }}</span>
                      <span
                        v-for="theme in stock.relatedThemes"
                        :key="`leader-${stock.code}-${theme}`"
                        :class="['hot-theme-chip', themeChipToneClass(theme)]">
                        {{ theme }}
                      </span>
                      <span
                        v-for="label in stock.tomorrowLabels.slice(0, 2)"
                        :key="`leader-tmr-${stock.code}-${label}`"
                        class="hot-theme-chip">
                        {{ label }}
                      </span>
                      <span v-if="stock.limitUpDays" class="hot-limit">{{ stock.limitUpDays === 1 ? '首板' : stock.limitUpDays + '连板' }}</span>
                      <span v-if="stock.isTomorrowThemeHit" class="hot-signal-chip">题材命中</span>
                    </div>
                  </div>
                  <div class="hot-action-entry">{{ stock.entryStyle }}</div>
                  <div v-if="stock.confirmSignals.length" class="hot-action-tags">
                    <span v-for="signal in stock.confirmSignals" :key="`leader-confirm-${stock.code}-${signal}`" class="hot-action-chip">
                      {{ signal }}
                    </span>
                  </div>
                  <div v-if="stock.isTomorrowThemeHit && (stock.matchedTomorrowThemeNames.length || stock.tomorrowReasonSnippets.length)" class="hot-tomorrow-evidence">
                    <div class="hot-tomorrow-title">
                      东财题材：{{ stock.matchedTomorrowThemeNames.join(' / ') || '已命中题材池' }}
                      <span v-if="stock.tomorrowIndustries.length" class="hot-tomorrow-meta">· {{ stock.tomorrowIndustries.join(' / ') }}</span>
                    </div>
                    <div
                      v-for="reason in stock.tomorrowReasonSnippets.slice(0, 2)"
                      :key="`leader-tmr-reason-${stock.code}-${reason}`"
                      class="hot-tomorrow-reason">
                      {{ reason }}
                    </div>
                  </div>
                  <div v-if="stock.vetoReasons.length" class="hot-action-risk">
                    先别急：{{ stock.vetoReasons.join(' / ') }}
                  </div>
                  <div v-if="stock.reason || stock.relatedDesc" class="hot-leader-desc">
                    {{ splitLines(stock.reason || stock.relatedDesc)[0] || (stock.reason || stock.relatedDesc) }}
                  </div>
                </article>
              </div>
            </div>

            <!-- Stock Loading Skeleton -->
            <div v-if="hotStockLoading" class="hot-skeleton-list small">
              <div v-for="i in 4" :key="'hsk-s-'+i" class="hot-skeleton-stock">
                <div class="hot-sk-row">
                  <div class="hot-sk-name"></div>
                  <div class="hot-sk-pct"></div>
                </div>
                <div class="hot-sk-line"></div>
              </div>
            </div>

            <div v-else-if="!rankedStocks.length" class="hot-empty">暂无个股明细</div>
            
            <div v-else class="hot-stock-list">
              <article v-for="stock in rankedStocks" :key="stock.code" class="hot-stock" :class="`tone-${stock.actionTone}`">
                <div class="hot-stock-main">
                  <div class="hot-stock-title">
                    <a
                      :class="['hot-stock-name', { 'is-limit-up': stock.limitUpDays }]"
                      :href="xueqiuUrl(stock.code)"
                      target="_blank"
                      rel="noopener noreferrer">
                      {{ stock.name }}
                    </a>
                    <span v-if="stock.price" class="hot-price">{{ stock.price.toFixed(2) }}</span>
                    <span :class="['hot-pct', stock.changePct >= 0 ? 'up' : 'down']">{{ formatPct(stock.changePct) }}</span>
                    <span
                      v-for="theme in stock.relatedThemes"
                      :key="`${stock.code}-${theme}`"
                      :class="['hot-theme-chip', themeChipToneClass(theme)]">
                      {{ theme }}
                    </span>
                    <span
                      v-for="label in stock.tomorrowLabels.slice(0, 2)"
                      :key="`list-tmr-${stock.code}-${label}`"
                      class="hot-theme-chip">
                      {{ label }}
                    </span>
                    <span v-if="stock.limitUpDays" class="hot-limit">{{ stock.limitUpDays === 1 ? '首板' : stock.limitUpDays + '连板' }}</span>
                    <span v-if="stock.eventStrength" class="hot-signal-chip">异动 {{ stock.eventStrength }}</span>
                    <span v-if="stock.isTomorrowThemeHit" class="hot-signal-chip">题材命中</span>
                    <span class="hot-action-tone is-inline" :class="`tone-${stock.actionTone}`">
                      {{ stock.actionTone === 'buy' ? '可执行' : stock.actionTone === 'watch' ? '观察' : '回避' }}
                    </span>
                    <span class="hot-action-role is-inline">{{ stock.roleLabel }}</span>
                  </div>
                  <button v-if="hotMode === 'all' && (stock.reason || stock.relatedDesc)" class="hot-detail-toggle" type="button" @click="toggleHotDetail(stock.code)">
                    {{ hotExpandedCodes.includes(stock.code) ? '收起' : '详情' }}
                  </button>
                </div>
                <div class="hot-stock-exec">{{ stock.entryStyle }}</div>
                <div v-if="stock.confirmSignals.length" class="hot-action-tags compact">
                  <span v-for="signal in stock.confirmSignals" :key="`${stock.code}-confirm-${signal}`" class="hot-action-chip">
                    {{ signal }}
                  </span>
                </div>
                <div v-if="stock.vetoReasons.length" class="hot-action-risk compact">
                  先别急：{{ stock.vetoReasons.join(' / ') }}
                </div>
                <div v-if="stock.isTomorrowThemeHit && (stock.matchedTomorrowThemeNames.length || stock.tomorrowReasonSnippets.length)" class="hot-tomorrow-evidence compact">
                  <div class="hot-tomorrow-title">
                    东财题材：{{ stock.matchedTomorrowThemeNames.join(' / ') || '已命中题材池' }}
                    <span v-if="stock.tomorrowIndustries.length" class="hot-tomorrow-meta">· {{ stock.tomorrowIndustries.join(' / ') }}</span>
                  </div>
                  <div
                    v-for="reason in stock.tomorrowReasonSnippets.slice(0, 2)"
                    :key="`list-tmr-reason-${stock.code}-${reason}`"
                    class="hot-tomorrow-reason">
                    {{ reason }}
                  </div>
                </div>
                <div v-if="(stock.reason || stock.relatedDesc) && (hotMode === 'leader' || hotExpandedCodes.includes(stock.code))" class="hot-reason">
                  <ol v-if="splitLines(stock.reason || stock.relatedDesc).length > 1" class="hot-reason-list">
                    <li v-for="(line, index) in splitLines(stock.reason || stock.relatedDesc)" :key="index">
                      {{ line }}
                    </li>
                  </ol>
                  <template v-else>
                    {{ splitLines(stock.reason || stock.relatedDesc)[0] || (stock.reason || stock.relatedDesc) }}
                  </template>
                </div>
              </article>
            </div>
          </div>
          <div v-else class="hot-empty-state">
            <div class="hot-empty-icon">👈</div>
            <div class="hot-empty-text">请在左侧选择感兴趣的热点板块</div>
          </div>
        </section>
      </div>
    </div>

    <ShortReminderFooter />
  </div>
</template>

<style scoped src="./HotAnswerPage.css"></style>
