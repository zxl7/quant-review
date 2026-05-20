import { computed, ref } from 'vue';
import reportTemplateHtml from '../../../templates/report_template.html?raw';
import latestReviewHtml from '../../../html/复盘日记-20260520-tab-v1.html?raw';

type MarketData = Record<string, any>;

function injectTemplateStyle(html: string) {
  if (typeof document === 'undefined') return;
  if (document.getElementById('report-template-style')) return;
  const match = html.match(/<style>([\s\S]*?)<\/style>/);
  if (!match?.[1]) return;
  const style = document.createElement('style');
  style.id = 'report-template-style';
  style.textContent = match[1];
  document.head.appendChild(style);
}

function tryParseInjectedData(html: string): MarketData | null {
  const match = html.match(/const __INJECTED_MARKET_DATA__ = (\{[\s\S]*?\});?\s*(?:\/\/|const __injectedMarketData__)/);
  if (!match?.[1]) return null;
  try {
    return Function(`return (${match[1]})`)();
  } catch {
    return null;
  }
}

const marketDataState = ref<MarketData>({});
const marketDataReady = ref(false);

export async function initMarketData() {
  if (marketDataReady.value) return;

  injectTemplateStyle(reportTemplateHtml);

  const cached = (window as any).__MARKET_DATA__;
  if (cached && typeof cached === 'object') {
    marketDataState.value = cached;
    marketDataReady.value = true;
    return;
  }

  const parsed = tryParseInjectedData(latestReviewHtml) || tryParseInjectedData(reportTemplateHtml) || {};
  marketDataState.value = parsed;
  (window as any).__MARKET_DATA__ = parsed;
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
