import { computed, reactive } from 'vue';

export interface XgbHotPlate {
  id: string;
  name: string;
  description: string;
}

export interface XgbHotStock {
  code: string;
  name: string;
  changePct: number;
  limitUpDays?: number;
  reason: string;
  label: string;
  plateId?: string;
}

export interface TomorrowThemeLite {
  id: string;
  themeCode: string;
  themeName: string;
  title: string;
  summary: string;
  ztCount: number;
  gain: number;
  cumulateGain: number;
  isHot: boolean;
  previewStocks: Array<{ code: string; name: string; gain: number }>;
}

export interface TomorrowThemeStockLite {
  code: string;
  name: string;
  gain: number;
  price: number;
  marketCap: number;
  industry: string;
  label: string;
  reason: string;
}

interface ThemeHotState {
  xgbPlates: XgbHotPlate[];
  xgbStocksByPlateId: Record<string, XgbHotStock[]>;
  xgbUpdatedAt: number;
  tmrThemes: TomorrowThemeLite[];
  tmrStocksByThemeCode: Record<string, TomorrowThemeStockLite[]>;
  tmrUpdatedAt: number;
  selectedTomorrowThemeCode: string;
}

const state = reactive<ThemeHotState>({
  xgbPlates: [],
  xgbStocksByPlateId: {},
  xgbUpdatedAt: 0,
  tmrThemes: [],
  tmrStocksByThemeCode: {},
  tmrUpdatedAt: 0,
  selectedTomorrowThemeCode: '',
});

const normalizeName = (raw: unknown) => String(raw || '').trim().replace(/\s+/g, '');
const normalizeCode = (raw: unknown) => String(raw || '').trim().replace(/\.(SH|SZ|SS)$/i, '');
const isStockCode = (code: string) => /^(00|30|60|68)\d{4}$/.test(normalizeCode(code));
const toXgbSymbol = (code: string) => {
  const raw = normalizeCode(code);
  if (!raw) return '';
  return `${raw}.${raw.startsWith('6') ? 'SS' : 'SZ'}`;
};

let xgbBootInflight: Promise<void> | null = null;
let tmrBootInflight: Promise<void> | null = null;
const tmrStocksInflight = new Map<string, Promise<TomorrowThemeStockLite[]>>();

function makeEastmoneyHeaders(): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
  };
}

function makeEastmoneyAuth() {
  const ts = String(Date.now());
  const rc = ts + Date.now() + Math.random().toString(36).substring(2, 10);
  return { timestamp: ts, randomCode: rc };
}

const sanitizeTomorrowThemeStocks = (stocks: TomorrowThemeStockLite[]) => (
  Array.isArray(stocks)
    ? stocks.map((stock) => ({
      code: normalizeCode(stock?.code),
      name: String(stock?.name || '').trim(),
      gain: Number(stock?.gain) || 0,
      price: Number(stock?.price) || 0,
      marketCap: Number(stock?.marketCap) || 0,
      industry: String(stock?.industry || '').trim(),
      label: String(stock?.label || '').trim(),
      reason: String(stock?.reason || '').trim(),
    })).filter((stock) => stock.code || stock.name)
    : []
);

const writeTomorrowThemeStocks = (themeCode: string, stocks: TomorrowThemeStockLite[]) => {
  const code = String(themeCode || '').trim();
  if (!code) return [];
  const nextStocks = sanitizeTomorrowThemeStocks(stocks);
  state.tmrStocksByThemeCode = { ...state.tmrStocksByThemeCode, [code]: nextStocks };
  state.tmrUpdatedAt = Date.now();
  return nextStocks;
};

async function hydrateTomorrowThemeStocksWithQuote(stocks: TomorrowThemeStockLite[]): Promise<TomorrowThemeStockLite[]> {
  const codes = Array.from(new Set(stocks.map((stock) => normalizeCode(stock.code)).filter(isStockCode)));
  if (!codes.length) return sanitizeTomorrowThemeStocks(stocks);
  const symbols = codes.map(toXgbSymbol).filter(Boolean);
  const url = `https://flash-api.xuangubao.cn/api/stock/data?fields=symbol,stock_chi_name,change_percent,price&strict=true&symbols=${symbols.join(',')}`;
  try {
    const res = await fetch(`${url}&_ts=${Date.now()}`, {
      cache: 'no-store',
      headers: {
        'Accept': 'application/json, text/plain, */*',
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
      },
    });
    if (!res.ok) return sanitizeTomorrowThemeStocks(stocks);
    const json = await res.json();
    const quoteData = json?.data || {};
    return sanitizeTomorrowThemeStocks(stocks.map((stock) => {
      const code = normalizeCode(stock.code);
      const symbol = toXgbSymbol(code);
      const quote = quoteData[symbol] || quoteData[code] || {};
      return {
        ...stock,
        code,
        name: String(quote.stock_chi_name || stock.name || code).trim(),
        gain: quote.change_percent === undefined || quote.change_percent === null ? Number(stock.gain) || 0 : Number(quote.change_percent) * 100,
        price: quote.price === undefined || quote.price === null ? Number(stock.price) || 0 : Number(quote.price),
      };
    }));
  } catch {
    return sanitizeTomorrowThemeStocks(stocks);
  }
}

async function tryLoadEastmoneyScript(src: string) {
  return await new Promise<boolean>((resolve) => {
    if (typeof document === 'undefined') {
      resolve(false);
      return;
    }
    const existed = document.querySelector(`script[data-eastmoney-data="${src}"]`) as HTMLScriptElement | null;
    if (existed) {
      existed.addEventListener('load', () => resolve(true), { once: true });
      existed.addEventListener('error', () => resolve(false), { once: true });
      resolve(Boolean((window as any).__EASTMONEY_TOMORROW_DATA__));
      return;
    }

    const script = document.createElement('script');
    script.src = src;
    script.async = true;
    script.dataset.eastmoneyData = src;
    script.onload = () => resolve(Boolean((window as any).__EASTMONEY_TOMORROW_DATA__));
    script.onerror = () => resolve(false);
    document.head.appendChild(script);
  });
}

async function getInjectedTomorrowData(): Promise<{ themes: TomorrowThemeLite[]; stocksByTheme: Record<string, TomorrowThemeStockLite[]> } | null> {
  try {
    let injected = (window as any).__EASTMONEY_TOMORROW_DATA__;
    if (!injected || !injected.themes || !injected.themes.length) {
      const scriptUrls = ['./eastmoney_tomorrow.js', 'eastmoney_tomorrow.js', '/eastmoney_tomorrow.js'];
      for (const src of scriptUrls) {
        try {
          const ok = await tryLoadEastmoneyScript(src);
          if (ok) {
            injected = (window as any).__EASTMONEY_TOMORROW_DATA__;
            if (injected?.themes?.length) break;
          }
        } catch {
          // ignore
        }
      }
    }

    if (!injected || !injected.themes || !injected.themes.length) {
      const jsonUrls = ['./eastmoney_tomorrow.json', 'eastmoney_tomorrow.json', '/eastmoney_tomorrow.json'];
      for (const url of jsonUrls) {
        try {
          const resp = await fetch(url);
          if (resp.ok) {
            injected = await resp.json();
            if (injected?.themes?.length) break;
          }
        } catch {
          // ignore
        }
      }
    }

    if (!injected || !injected.themes || !injected.themes.length) return null;

    const themes = Array.isArray(injected.themes)
      ? injected.themes.map((theme: any) => ({
        id: String(theme?.id || theme?.eid || theme?.sortNum || ''),
        themeCode: String(theme?.themeCode || ''),
        themeName: String(theme?.themeName || '').trim(),
        title: String(theme?.title || ''),
        summary: String(theme?.summary || ''),
        ztCount: Number(theme?.ztCount || theme?.fex3) || 0,
        gain: Number(theme?.gain || theme?.f3) || 0,
        cumulateGain: Number(theme?.cumulateGain || theme?.cumulateF3) || 0,
        isHot: Boolean(theme?.isHot),
        previewStocks: Array.isArray(theme?.previewStocks)
          ? theme.previewStocks.map((stock: any) => ({
            code: normalizeCode(stock?.code || stock?.securityCode || ''),
            name: String(stock?.name || stock?.securityName || '').trim(),
            gain: Number(stock?.gain || stock?.f3) || 0,
          })).filter((stock: { code: string; name: string; gain: number }) => stock.code || stock.name)
          : [],
      })).filter((theme: TomorrowThemeLite) => theme.themeName)
      : [];

    const stocksByTheme: Record<string, TomorrowThemeStockLite[]> = {};
    if (injected.stocksByTheme && typeof injected.stocksByTheme === 'object') {
      Object.entries(injected.stocksByTheme).forEach(([themeCode, items]) => {
        stocksByTheme[String(themeCode || '').trim()] = sanitizeTomorrowThemeStocks(items as TomorrowThemeStockLite[]);
      });
    }
    return { themes, stocksByTheme };
  } catch {
    return null;
  }
}

const parseXgbPlatesFromJson = (json: any): XgbHotPlate[] => {
  const out: XgbHotPlate[] = [];
  const seen = new Set<string>();
  const walk = (node: any) => {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    const id = node.id !== undefined ? String(node.id).trim() : '';
    const name = node.name !== undefined ? String(node.name).trim() : '';
    if (id && name && id !== '-1' && !seen.has(id)) {
      seen.add(id);
      out.push({ id, name, description: String(node.description || node.desc || '').trim() });
    }
    Object.values(node).forEach(walk);
  };
  walk(json);
  return out;
};

async function ensureXgbPlatesLoaded(force = false): Promise<void> {
  if (!force && state.xgbPlates.length) return;
  if (xgbBootInflight) return xgbBootInflight;
  xgbBootInflight = (async () => {
    try {
      const res = await fetch(`https://flash-api.xuangubao.cn/api/surge_stock/plates?_ts=${Date.now()}`, {
        cache: 'no-store',
        headers: {
          'Accept': 'application/json, text/plain, */*',
          'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
        },
      });
      if (!res.ok) return;
      const json = await res.json();
      const plates = parseXgbPlatesFromJson(json);
      if (plates.length) {
        state.xgbPlates = plates;
        state.xgbUpdatedAt = Date.now();
      }
    } catch { /* swallow */ } finally {
      xgbBootInflight = null;
    }
  })();
  return xgbBootInflight;
}

async function ensureTomorrowLoaded(force = false): Promise<void> {
  if (!force && state.tmrThemes.length) return;
  if (tmrBootInflight) return tmrBootInflight;
  tmrBootInflight = (async () => {
    try {
      const injected = await getInjectedTomorrowData();
      if (injected?.themes?.length) {
        state.tmrThemes = injected.themes;
        state.tmrUpdatedAt = Date.now();
        Object.entries(injected.stocksByTheme).forEach(([themeCode, stocks]) => {
          writeTomorrowThemeStocks(themeCode, stocks);
        });
        return;
      }

      const ts = String(Date.now());
      const rc = (ts + Date.now() + Math.random().toString(36).substring(2, 10)).substring(0, 32);
      const res = await fetch('https://emcfgdata.eastmoney.com/api/themeInvest/getFryTomorrowList', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
        },
        body: JSON.stringify({
          args: { pageSize: 15, lastTradeDate: '' },
          client: 'wap', clientType: 'cfw', clientVersion: '9001',
          randomCode: rc, timestamp: ts,
        }),
        signal: AbortSignal.timeout(10000),
      });
      if (!res.ok) return;
      const json = await res.json();
      if (json?.code !== 0) return;
      const data = json.data || {};
      const items: TomorrowThemeLite[] = [];
      Object.keys(data).filter((k) => /^\d+$/.test(k)).sort((a, b) => Number(a) - Number(b)).forEach((k) => {
        const it = data[k]; if (!it) return;
        items.push({
          id: String(it.eid || it.sortNum || ''),
          themeCode: String(it.themeCode || ''),
          themeName: String(it.themeName || '').trim(),
          title: String(it.title || ''),
          summary: String(it.summary || ''),
          ztCount: Number(it.fex3) || 0,
          gain: Number(it.f3) || 0,
          cumulateGain: Number(it.cumulateF3) || 0,
          isHot: it.isHot === 1 || it.isHot === '1',
          previewStocks: Array.isArray(it.stockList)
            ? it.stockList.map((stock: any) => ({
              code: String(stock?.code || stock?.securityCode || '').replace(/\.(SH|SZ)$/i, ''),
              name: String(stock?.name || stock?.securityName || '').trim(),
              gain: Number(stock?.f3) || 0,
            })).filter((stock: { code: string; name: string; gain: number }) => stock.code || stock.name)
            : [],
        });
      });
      if (items.length) {
        state.tmrThemes = items.filter((t) => t.themeName);
        state.tmrUpdatedAt = Date.now();
      }
    } catch { /* swallow */ } finally {
      tmrBootInflight = null;
    }
  })();
  return tmrBootInflight;
}

async function ensureTomorrowThemeStocksLoaded(themeCode: string, force = false): Promise<TomorrowThemeStockLite[]> {
  const code = String(themeCode || '').trim();
  if (!code) return [];
  if (!force && state.tmrStocksByThemeCode[code]?.length) return state.tmrStocksByThemeCode[code];
  if (tmrStocksInflight.has(code)) return tmrStocksInflight.get(code)!;

  const inflight = (async () => {
    try {
      const injected = await getInjectedTomorrowData();
      const injectedStocks = injected?.stocksByTheme?.[code];
      if (Array.isArray(injectedStocks) && injectedStocks.length) {
        return writeTomorrowThemeStocks(code, await hydrateTomorrowThemeStocksWithQuote(injectedStocks));
      }

      const { timestamp, randomCode } = makeEastmoneyAuth();
      const resp = await fetch('https://emcfgdata.eastmoney.com/api/themeInvest/getStockList', {
        method: 'POST',
        headers: makeEastmoneyHeaders(),
        body: JSON.stringify({
          args: { themeCode: code, pageSize: 200, pageNum: 1, sort: -1, sortField: 'f3' },
          client: 'web',
          clientType: 'cfw',
          clientVersion: '8.3',
          randomCode: randomCode.substring(0, 20),
          timestamp,
        }),
        signal: AbortSignal.timeout(10000),
      });
      if (!resp.ok) return state.tmrStocksByThemeCode[code] || [];
      const json = await resp.json();
      if (json?.code !== 0) return state.tmrStocksByThemeCode[code] || [];

      const rawStocks = Array.isArray(json?.data?.stockList)
        ? json.data.stockList.map((stock: any) => {
          const reasons = Array.isArray(stock?.keywordList)
            ? stock.keywordList
              .filter((item: any) => item?.keyword === '入选理由')
              .map((item: any) => String(item?.introduction || '').trim())
              .filter(Boolean)
            : [];
          return {
            code: normalizeCode(stock?.securityCode || stock?.code || ''),
            name: String(stock?.securityName || stock?.name || '').trim(),
            gain: Number(stock?.f3) || 0,
            price: Number(stock?.f2) || 0,
            marketCap: Number(stock?.f20) || 0,
            industry: String(stock?.f100 || stock?.industry || '').trim(),
            label: String(stock?.label || '').trim(),
            reason: reasons.join('；') || '涨停',
          };
        })
        : [];

      return writeTomorrowThemeStocks(code, await hydrateTomorrowThemeStocksWithQuote(rawStocks));
    } catch {
      return state.tmrStocksByThemeCode[code] || [];
    } finally {
      tmrStocksInflight.delete(code);
    }
  })();

  tmrStocksInflight.set(code, inflight);
  return inflight;
}

export function useThemeHotStore() {
  const xgbPlates = computed(() => state.xgbPlates);
  const xgbStocksByPlateId = computed(() => state.xgbStocksByPlateId);
  const tmrThemes = computed(() => state.tmrThemes);
  const tmrStocksByThemeCode = computed(() => state.tmrStocksByThemeCode);
  const xgbUpdatedAt = computed(() => state.xgbUpdatedAt);
  const tmrUpdatedAt = computed(() => state.tmrUpdatedAt);
  const selectedTomorrowThemeCode = computed(() => state.selectedTomorrowThemeCode);

  const xgbHotPlateNames = computed<Set<string>>(() => new Set(state.xgbPlates.map((p) => normalizeName(p.name)).filter(Boolean)));
  const tmrHotThemeNames = computed<Set<string>>(() => new Set(state.tmrThemes.filter((t) => t.isHot).map((t) => normalizeName(t.themeName)).filter(Boolean)));
  const tmrAllThemeNames = computed<Set<string>>(() => new Set(state.tmrThemes.map((t) => normalizeName(t.themeName)).filter(Boolean)));

  const xgbHotCodes = computed<Set<string>>(() => {
    const set = new Set<string>();
    Object.values(state.xgbStocksByPlateId).forEach((arr) => arr.forEach((s) => { if (s.code) set.add(String(s.code).trim()); }));
    return set;
  });

  const narrativeHitForTheme = (themeOrPlateName: unknown): { hit: boolean; sources: string[] } => {
    const key = normalizeName(themeOrPlateName);
    if (!key) return { hit: false, sources: [] };
    const sources: string[] = [];
    if (xgbHotPlateNames.value.has(key)) sources.push('选股宝热点');
    if (tmrHotThemeNames.value.has(key)) sources.push('东财明日热门');
    else if (tmrAllThemeNames.value.has(key)) sources.push('东财明日');
    if (!sources.length) {
      const partial = state.xgbPlates.some((p) => normalizeName(p.name).includes(key) || key.includes(normalizeName(p.name)));
      if (partial) sources.push('选股宝热点(模糊)');
    }
    return { hit: sources.length > 0, sources };
  };

  const narrativeHitForStock = (code: unknown): boolean => xgbHotCodes.value.has(String(code || '').trim());

  const setXgbPlates = (plates: XgbHotPlate[]) => {
    state.xgbPlates = Array.isArray(plates) ? plates.map((p) => ({
      id: String(p?.id || '').trim(),
      name: String(p?.name || '').trim(),
      description: String(p?.description || '').trim(),
    })).filter((p) => p.id && p.name) : [];
    state.xgbUpdatedAt = Date.now();
  };

  const setXgbStocksForPlate = (plateId: string, stocks: XgbHotStock[]) => {
    const pid = String(plateId || '').trim();
    if (!pid) return;
    const list = Array.isArray(stocks) ? stocks.map((s) => ({
      code: String(s?.code || '').trim(),
      name: String(s?.name || '').trim(),
      changePct: Number(s?.changePct) || 0,
      limitUpDays: Number(s?.limitUpDays) || 0,
      reason: String(s?.reason || '').trim(),
      label: String(s?.label || '').trim(),
      plateId: pid,
    })).filter((s) => s.code) : [];
    state.xgbStocksByPlateId = { ...state.xgbStocksByPlateId, [pid]: list };
  };

  const setTomorrowThemes = (themes: TomorrowThemeLite[]) => {
    state.tmrThemes = Array.isArray(themes) ? themes.map((t) => ({
      id: String(t?.id || ''),
      themeCode: String(t?.themeCode || ''),
      themeName: String(t?.themeName || '').trim(),
      title: String(t?.title || ''),
      summary: String(t?.summary || ''),
      ztCount: Number(t?.ztCount) || 0,
      gain: Number(t?.gain) || 0,
      cumulateGain: Number(t?.cumulateGain) || 0,
      isHot: Boolean(t?.isHot),
      previewStocks: Array.isArray(t?.previewStocks)
        ? t.previewStocks.map((stock) => ({
          code: String(stock?.code || '').replace(/\.(SH|SZ)$/i, ''),
          name: String(stock?.name || '').trim(),
          gain: Number(stock?.gain) || 0,
        })).filter((stock) => stock.code || stock.name)
        : [],
    })).filter((t) => t.themeName) : [];
    state.tmrUpdatedAt = Date.now();
  };

  const setTomorrowThemeStocks = (themeCode: string, stocks: TomorrowThemeStockLite[]) => {
    writeTomorrowThemeStocks(themeCode, stocks);
  };

  const setSelectedTomorrowThemeCode = (themeCode: string) => {
    state.selectedTomorrowThemeCode = String(themeCode || '').trim();
  };

  return {
    xgbPlates,
    xgbStocksByPlateId,
    xgbUpdatedAt,
    tmrThemes,
    tmrStocksByThemeCode,
    tmrUpdatedAt,
    selectedTomorrowThemeCode,
    xgbHotPlateNames,
    tmrHotThemeNames,
    tmrAllThemeNames,
    xgbHotCodes,
    narrativeHitForTheme,
    narrativeHitForStock,
    setXgbPlates,
    setXgbStocksForPlate,
    setTomorrowThemes,
    setTomorrowThemeStocks,
    setSelectedTomorrowThemeCode,
    ensureXgbPlatesLoaded,
    ensureTomorrowLoaded,
    ensureTomorrowThemeStocksLoaded,
  };
}
