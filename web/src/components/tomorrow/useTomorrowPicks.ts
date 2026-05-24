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

export function useTomorrowPicks() {
  const themes = ref<TomorrowTheme[]>([]);
  const loading = ref(false);
  const error = ref('');
  const selectedThemeCode = ref('');
  const stocks = ref<TomorrowStock[]>([]);
  const stocksLoading = ref(false);

  async function fetchThemes(force = false) {
    if (themes.value.length && !force) return;
    loading.value = true;
    error.value = '';

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
      if (items.length) {
        // 如果是强制刷新，且当前选中的 code 在新列表中不存在，才切换到第一个
        if (!selectedThemeCode.value || !items.some(x => x.themeCode === selectedThemeCode.value)) {
          selectedThemeCode.value = items[0].themeCode;
          fetchStockList(items[0].themeCode);
        } else if (force) {
          // 强制刷新时，也刷新当前选中的成分股
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
