import { ref } from 'vue';
import { useThemeHotStore } from '../../composables/useThemeHotStore';

export interface TomorrowStock {
  code: string
  name: string
  gain: number
  price: number
  marketCap: number
  industry: string
  label: string
  reason: string
}

export interface TomorrowTheme {
  id: string
  rank: number
  title: string
  summary: string
  tradeDate: string
  themeCode: string
  themeName: string
  ztCount: number
  gain: number
  cumulateGain: number
  isHot: boolean
  previewStocks: Array<{ code: string; name: string; gain: number }>
}

function makeHeaders(): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
  };
}

function makeAuth() {
  const ts = String(Date.now());
  const rc = ts + Date.now() + Math.random().toString(36).substring(2, 10);
  return { timestamp: ts, randomCode: rc };
}

const API_BASE = 'https://emcfgdata.eastmoney.com/api/themeInvest';
const PAGE_SIZE = 15;

const isStockCode = (code: string) => /^(00|30|60|68)\d{4}$/.test(code);
const toXgbSymbol = (code: string) => {
  if (!code) return '';
  return `${code}.${code.startsWith('6') ? 'SS' : 'SZ'}`;
};

async function hydrateStocksWithQuote(stocks: TomorrowStock[]): Promise<TomorrowStock[]> {
  const codes = Array.from(new Set(stocks.map((x) => x.code).filter(isStockCode)));
  if (!codes.length) return stocks;
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
    if (!res.ok) return stocks;
    const json = await res.json();
    const quoteData = json?.data || {};
    
    return stocks.map((stock) => {
      const symbol = toXgbSymbol(stock.code);
      const quote = quoteData[symbol] || quoteData[stock.code] || {};
      return {
        ...stock,
        name: String(quote.stock_chi_name || stock.name).trim(),
        gain: quote.change_percent === undefined || quote.change_percent === null ? stock.gain : Number(quote.change_percent) * 100,
        price: quote.price === undefined || quote.price === null ? stock.price : Number(quote.price),
      };
    });
  } catch {
    return stocks;
  }
}

async function tryLoadEastmoneyScript(src: string) {
  return await new Promise<boolean>((resolve) => {
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

/** 读取注入的东方财富明日主题数据 */
async function getInjectedData(): Promise<{ themes: TomorrowTheme[]; stocksByTheme: Record<string, TomorrowStock[]> } | null> {
  try {
    // 首先尝试直接从 window 读取已注入的数据
    let injected = (window as any).__EASTMONEY_TOMORROW_DATA__;
    if (!injected || !injected.themes || !injected.themes.length) {
      // 尝试通过 script 加载
      const scriptUrls = [
        './eastmoney_tomorrow.js',
        'eastmoney_tomorrow.js',
        '/eastmoney_tomorrow.js',
      ];
      for (const src of scriptUrls) {
        try {
          const ok = await tryLoadEastmoneyScript(src);
          if (ok) {
            injected = (window as any).__EASTMONEY_TOMORROW_DATA__;
            if (injected && injected.themes && injected.themes.length) {
              break;
            }
          }
        } catch {
          // 继续尝试下一个
        }
      }
    }

    // 如果还是没有，尝试直接 fetch 读取 json 文件
    if (!injected || !injected.themes || !injected.themes.length) {
      const jsonUrls = [
        './eastmoney_tomorrow.json',
        'eastmoney_tomorrow.json',
        '/eastmoney_tomorrow.json',
      ];
      for (const url of jsonUrls) {
        try {
          const resp = await fetch(url);
          if (resp.ok) {
            injected = await resp.json();
            if (injected && injected.themes && injected.themes.length) {
              break;
            }
          }
        } catch {
          // 继续尝试下一个
        }
      }
    }

    if (!injected || !injected.themes || !injected.themes.length) return null;
    
    // 校验基础字段完整性
    const themes: TomorrowTheme[] = injected.themes.map((t: any) => ({
      id: t.id || '',
      rank: t.rank || 0,
      title: t.title || '',
      summary: t.summary || '',
      tradeDate: t.tradeDate || '',
      themeCode: t.themeCode || '',
      themeName: t.themeName || '',
      ztCount: t.ztCount || 0,
      gain: t.gain || 0,
      cumulateGain: t.cumulateGain || 0,
      isHot: !!t.isHot,
      previewStocks: (t.previewStocks || []).map((s: any) => ({
        code: s.code || '',
        name: s.name || '',
        gain: s.gain || 0,
      })),
    }));
    const stocksByTheme: Record<string, TomorrowStock[]> = {};
    if (injected.stocksByTheme) {
      for (const [themeCode, items] of Object.entries(injected.stocksByTheme)) {
        const list = (items as any[]).map((s: any) => ({
          code: s.code || '',
          name: s.name || '',
          gain: s.gain || 0,
          price: s.price || 0,
          marketCap: s.marketCap || 0,
          industry: s.industry || '',
          label: s.label || '',
          reason: s.reason || '',
        }));
        stocksByTheme[themeCode] = list;
      }
    }
    return { themes, stocksByTheme };
  } catch {
    return null;
  }
}

export function useTomorrowPicks() {
  const { setTomorrowThemes } = useThemeHotStore();
  const themes = ref<TomorrowTheme[]>([]);
  const loading = ref(false);
  const error = ref('');
  const selectedThemeCode = ref('');
  const stocks = ref<TomorrowStock[]>([]);
  const stocksLoading = ref(false);
  const isUsingInjected = ref(false); // 标记当前用的是预注入还是实时数据
  const injectedThemesDate = ref('');

  async function fetchThemes(force = false) {
    if (themes.value.length && !force) return;
    loading.value = true;
    error.value = '';
    isUsingInjected.value = false;

    // Tier 1: 预注入数据（17:00全量fetch下载好，最可靠）
    const injected = await getInjectedData();
    if (injected && injected.themes.length) {
      themes.value = injected.themes;
      isUsingInjected.value = true;
      injectedThemesDate.value = injected.themes[0].tradeDate || '';
      setTomorrowThemes(injected.themes);
      if (injected.themes.length) {
        if (!selectedThemeCode.value || !injected.themes.some(x => x.themeCode === selectedThemeCode.value)) {
          selectedThemeCode.value = injected.themes[0].themeCode;
          // 预注入数据可能已有该主题的成份股
          const preloaded = injected.stocksByTheme[injected.themes[0].themeCode];
          if (preloaded && preloaded.length) {
            stocks.value = preloaded;
            stocksLoading.value = false;
          } else {
            fetchStockList(injected.themes[0].themeCode);
          }
        }
      }
      loading.value = false;
      return;
    }

    // Tier 2: 运行时 API 调用（兜底）
    try {
      const { timestamp, randomCode } = makeAuth();
      const resp = await fetch(`${API_BASE}/getFryTomorrowList`, {
        method: 'POST',
        headers: makeHeaders(),
        body: JSON.stringify({
          args: { pageSize: PAGE_SIZE, lastTradeDate: '' },
          client: 'wap',
          clientType: 'cfw',
          clientVersion: '9001',
          randomCode: randomCode.substring(0, 32),
          timestamp,
        }),
        signal: AbortSignal.timeout(10000),
      });

      const json = await resp.json();
      if (json.code !== 0) {
        error.value = json.message || '请求失败';
        return;
      }

      const items: TomorrowTheme[] = [];
      const data = json.data || {};
      for (const key of Object.keys(data).filter((k) => /^\d+$/.test(k)).sort((a, b) => Number(a) - Number(b))) {
        const item = data[key];
        if (!item) continue;
        items.push({
          id: item.eid || String(item.sortNum),
          rank: item.sortNum || 0,
          title: item.title || '',
          summary: item.summary || '',
          tradeDate: item.tradeDate || '',
          themeCode: item.themeCode || '',
          themeName: item.themeName || '',
          ztCount: item.fex3 || 0,
          gain: item.f3 || 0,
          cumulateGain: item.cumulateF3 || 0,
          isHot: item.isHot === 1 || item.isHot === '1',
          previewStocks: (item.stockList || []).map((s: any) => ({
            code: (s.code || '').replace(/\.(SH|SZ)$/, ''),
            name: s.name || '',
            gain: s.f3 || 0,
          })),
        });
      }
      themes.value = items;
      setTomorrowThemes(items);
      if (items.length) {
        if (!selectedThemeCode.value || !items.some(x => x.themeCode === selectedThemeCode.value)) {
          selectedThemeCode.value = items[0].themeCode;
          fetchStockList(items[0].themeCode);
        } else if (force) {
          fetchStockList(selectedThemeCode.value);
        }
      }
    } catch (e: any) {
      error.value = e.message || '实时请求失败';
    } finally {
      loading.value = false;
    }
  }

  async function fetchStockList(themeCode: string) {
    stocksLoading.value = true;
    selectedThemeCode.value = themeCode;

    // Tier 1: 先查预注入数据
    if (isUsingInjected.value) {
      const injected = await getInjectedData();
      if (injected && injected.stocksByTheme[themeCode]) {
        stocks.value = await hydrateStocksWithQuote(injected.stocksByTheme[themeCode]);
        stocksLoading.value = false;
        return;
      }
    }

    // Tier 2: 运行时 API 调用
    try {
      const { timestamp, randomCode } = makeAuth();
      const resp = await fetch(`${API_BASE}/getStockList`, {
        method: 'POST',
        headers: makeHeaders(),
        body: JSON.stringify({
          args: { themeCode, pageSize: 200, pageNum: 1, sort: -1, sortField: 'f3' },
          client: 'web',
          clientType: 'cfw',
          clientVersion: '8.3',
          randomCode: randomCode.substring(0, 20),
          timestamp,
        }),
        signal: AbortSignal.timeout(10000),
      });

      const json = await resp.json();
      if (json.code !== 0) return;

      const list = json.data?.stockList || [];
      const rawStocks = list.map((s: any) => {
        const reasons = (s.keywordList || [])
          .filter((k: any) => k.keyword === '入选理由')
          .map((k: any) => k.introduction || '');
        return {
          code: (s.securityCode || '').replace(/\.(SH|SZ)$/, ''),
          name: s.securityName || '',
          gain: s.f3 || 0,
          price: s.f2 || 0,
          marketCap: s.f20 || 0,
          industry: s.f100 || '',
          label: s.label || '',
          reason: reasons.join('；') || '涨停',
        };
      });
      stocks.value = await hydrateStocksWithQuote(rawStocks);
    } catch {
      // ignore
    } finally {
      stocksLoading.value = false;
    }
  }

  async function selectTheme(themeCode: string) {
    selectedThemeCode.value = themeCode;

    // 预注入数据中查找
    if (isUsingInjected.value) {
      const injected = await getInjectedData();
      if (injected && injected.stocksByTheme[themeCode]) {
        stocks.value = await hydrateStocksWithQuote(injected.stocksByTheme[themeCode]);
        return;
      }
    }
    // 未命中缓存，走 API
    await fetchStockList(themeCode);
  }

  return { themes, loading, error, selectedThemeCode, stocks, stocksLoading, isUsingInjected, injectedThemesDate, fetchThemes, selectTheme };
}
