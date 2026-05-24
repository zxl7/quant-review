import { ref } from 'vue';

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
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)',
    Referer: 'https://wap.eastmoney.com/',
  };
}

function makeAuth() {
  const ts = String(Date.now());
  const rc = ts + Date.now() + Math.random().toString(36).substring(2, 10);
  return { timestamp: ts, randomCode: rc };
}

const API_BASE = 'https://emcfgdata.eastmoney.com/api/themeInvest';
const PAGE_SIZE = 15;

export function useTomorrowPicks() {
  const themes = ref<TomorrowTheme[]>([]);
  const loading = ref(false);
  const error = ref('');
  const selectedThemeCode = ref('');
  const stocks = ref<TomorrowStock[]>([]);
  const stocksLoading = ref(false);

  async function fetchThemes() {
    if (themes.value.length) return;
    loading.value = true;
    error.value = '';

    // 1) 优先从注入数据读取（CI 预取，无 CORS 问题）
    const injected = (window as any).__TOMORROW_PICKS__;
    if (injected && Array.isArray(injected.themes) && injected.themes.length) {
      themes.value = injected.themes;
      loading.value = false;
      if (injected.themes[0]) {
        selectedThemeCode.value = injected.themes[0].themeCode;
        if (injected.themes[0].stocks?.length) {
          stocks.value = injected.themes[0].stocks;
        } else {
          fetchStockList(injected.themes[0].themeCode);
        }
      }
      return;
    }

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
      if (items.length && !selectedThemeCode.value) {
        selectedThemeCode.value = items[0].themeCode;
        fetchStockList(items[0].themeCode);
      }
    } catch (e: any) {
      // API 失败 → 兜底本地 JSON 文件
      try {
        const resp = await fetch('./tomorrow_picks.json');
        if (resp.ok) {
          const data = await resp.json();
          const list = Array.isArray(data?.themes) ? data.themes : [];
          if (list.length) {
            themes.value = list;
            selectedThemeCode.value = list[0].themeCode;
            if (list[0].stocks?.length) stocks.value = list[0].stocks;
            loading.value = false;
            return;
          }
        }
      } catch {}
      error.value = e.message || '网络错误';
    } finally {
      loading.value = false;
    }
  }

  async function fetchStockList(themeCode: string) {
    stocksLoading.value = true;
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
      stocks.value = list.map((s: any) => {
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
    } catch {
      // ignore
    } finally {
      stocksLoading.value = false;
    }
  }

  function selectTheme(themeCode: string) {
    selectedThemeCode.value = themeCode;
    fetchStockList(themeCode);
  }

  return { themes, loading, error, selectedThemeCode, stocks, stocksLoading, fetchThemes, selectTheme };
}
