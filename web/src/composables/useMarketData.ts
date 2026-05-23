import { computed, ref } from 'vue';

type MarketData = Record<string, any>;

function _setDocTitle(data: MarketData) {
  const d = data?.date || '';
  document.title = d ? `${d} A股简报` : 'A股简报';
}

const marketDataState = ref<MarketData>({});
const marketDataReady = ref(false);

async function tryLoadMarketDataScript(src: string) {
  return await new Promise<boolean>((resolve) => {
    const existed = document.querySelector(`script[data-market-data="${src}"]`) as HTMLScriptElement | null;
    if (existed) {
      existed.addEventListener('load', () => resolve(true), { once: true });
      existed.addEventListener('error', () => resolve(false), { once: true });
      resolve(Boolean((window as any).__MARKET_DATA__));
      return;
    }

    const script = document.createElement('script');
    script.src = src;
    script.async = true;
    script.dataset.marketData = src;
    script.onload = () => resolve(Boolean((window as any).__MARKET_DATA__));
    script.onerror = () => resolve(false);
    document.head.appendChild(script);
  });
}

export async function initMarketData() {
  if (marketDataReady.value) return;

  // 生产环境：window.__MARKET_DATA__ 由 inject_data.py 设置
  const cached = (window as any).__MARKET_DATA__;
  if (cached && typeof cached === 'object' && Object.keys(cached).length > 1) {
    marketDataState.value = cached;
    marketDataReady.value = true;
    _setDocTitle(cached);
    return;
  }

  const scriptUrls = [
    './market_data.js',
    'market_data.js',
    '/market_data.js',
  ];

  for (const src of scriptUrls) {
    try {
      const ok = await tryLoadMarketDataScript(src);
      const injected = (window as any).__MARKET_DATA__;
      if (ok && injected && typeof injected === 'object' && Object.keys(injected).length > 1) {
        marketDataState.value = injected;
        marketDataReady.value = true;
        _setDocTitle(injected);
        return;
      }
    } catch {
      // 继续尝试下一个路径
    }
  }

  // 开发 / 本地打包预览：尝试读取同目录数据文件
  const fallbackUrls = [
    './market_data.json',
    'market_data.json',
    '/market_data.json',
  ];

  for (const url of fallbackUrls) {
    try {
      const resp = await fetch(url);
      if (resp.ok) {
        const data = await resp.json();
        marketDataState.value = data;
        marketDataReady.value = true;
        _setDocTitle(data);
        return;
      }
    } catch {
      // 继续尝试下一个路径
    }
  }

  marketDataReady.value = true;
}

export function useMarketData() {
  const marketData = computed(() => marketDataState.value || {});
  const marketToneClass = computed(() => {
    const mood = marketData.value?.mood || {};
    const heat = Number(mood?.heat ?? 0);
    const risk = Number(mood?.risk ?? 0);
    const score = Number(mood?.score ?? 0);
    if (risk >= 55 || score <= 45) return 'fire';
    if (score >= 68 && heat >= 60 && risk <= 35) return 'good';
    return 'warn';
  });

  return {
    marketData,
    marketToneClass,
    marketDataReady,
  };
}
