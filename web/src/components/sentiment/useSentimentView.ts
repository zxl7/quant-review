import { computed } from 'vue';
import { useMarketData } from '../../composables/useMarketData';

type MoodGroup = 'carry' | 'cons' | 'risk';

const CARRY_LABELS = new Set(['连板晋级率', '2进3成功率', '3进4成功率', '连板断板率']);
const CONS_LABELS = new Set(['早盘封板占比', '平均封板资金', '涨停换手(中位)', '涨停炸板次数(均)']);

const toNum = (v: unknown, d = 0) => {
  if (v === undefined || v === null || v === '') return d;
  if (typeof v === 'string') return Number(v.replace('%', '').replace('亿', '').trim()) || d;
  const n = Number(v);
  return Number.isFinite(n) ? n : d;
};

const resolveMoodGroup = (label: string): MoodGroup => {
  if (CARRY_LABELS.has(label)) return 'carry';
  if (CONS_LABELS.has(label)) return 'cons';
  return 'risk';
};

export const heatColor = (v: number) => {
  const n = Number(v || 0);
  if (n <= 45) return '#f59e0b';
  if (n <= 70) return '#ff4d4f';
  return '#e60012';
};

export const riskColor = (v: number) => {
  const n = Number(v || 0);
  if (n <= 45) return '#16a34a';
  if (n <= 75) return '#0db110ff';
  return '#f59e0b';
};

export function useSentimentView() {
  const { marketData, marketToneClass } = useMarketData();

  const moodCards = computed<any[]>(() => (Array.isArray(marketData.value?.moodCards) ? marketData.value.moodCards : []));
  const moodCardsBy = (group: MoodGroup) => moodCards.value.filter((card: any) => resolveMoodGroup(String(card?.label || '')) === group);

  const moodCardValueClass = (group: MoodGroup, card: any) => {
    const v = toNum(String(card?.value || '').replace('分', '').replace('%', '').replace('亿', ''), Number.NaN);
    if (group === 'carry') {
      if (!Number.isFinite(v)) return card?.valueClass || '';
      if (v >= 60) return 'red-text';
      if (v >= 30) return 'orange-text';
      return 'green-text';
    }
    if (group === 'cons') {
      if (!Number.isFinite(v)) return card?.valueClass || '';
      if (v >= 50) return 'orange-text';
      if (v >= 20) return 'green-text';
      return 'red-text';
    }
    if (!Number.isFinite(v)) return card?.valueClass || '';
    if (v >= 60) return 'red-text';
    if (v >= 25) return 'orange-text';
    return 'green-text';
  };

  const topZtTheme = computed<any>(() => (marketData.value?.themePanels?.ztTop || [])[0] || null);
  const topPlate = computed<any>(() => (marketData.value?.plateRankTop10 || [])[0] || null);
  const rotationInfo = computed<any>(() => marketData.value?.rotation || null);

  const ztTotalCount = computed(() => {
    const fromMood = Number(marketData.value?.features?.mood_inputs?.zt_count);
    if (Number.isFinite(fromMood) && fromMood > 0) return fromMood;
    return (marketData.value?.themePanels?.ztTop || []).reduce((sum: number, item: any) => sum + Number(item?.count || 0), 0);
  });

  const topZtConcRatio = computed(() => {
    const count = Number(topZtTheme.value?.count || 0);
    const total = ztTotalCount.value;
    if (!count || !total) return 0;
    return Math.round((count / total) * 1000) / 10;
  });

  const concRatioCls = computed(() => {
    const ratio = topZtConcRatio.value;
    if (ratio >= 35) return 'red-text';
    if (ratio >= 20) return 'orange-text';
    return 'green-text';
  });

  const concRatioLabel = computed(() => {
    const ratio = topZtConcRatio.value;
    if (ratio >= 35) return '高度抱团';
    if (ratio >= 20) return '主线明确';
    if (ratio > 0) return '资金分散';
    return '-';
  });

  const concRatioBadgeClass = computed(() => {
    if (concRatioCls.value === 'red-text') return 'high';
    if (concRatioCls.value === 'orange-text') return 'mid';
    return 'low';
  });

  const sentimentDecision = computed<any>(() => marketData.value?.sentimentDecision || {});
  const resonanceVerdict = computed(() => {
    const value = sentimentDecision.value?.resonanceVerdict;
    return value && typeof value === 'object' ? value : { text: '-', cls: '' };
  });
  const narrativeOverview = computed(() => {
    const value = sentimentDecision.value?.narrativeOverview;
    return value && typeof value === 'object' ? value : null;
  });
  const narrativeCoverage = computed(() => {
    const value = sentimentDecision.value?.narrativeCoverage;
    return value && typeof value === 'object' ? value : null;
  });
  const narrativeHitNames = computed(() => String(narrativeCoverage.value?.hitNames || ''));

  return {
    marketData,
    marketToneClass,
    moodCardsBy,
    moodCardValueClass,
    topZtTheme,
    topPlate,
    rotationInfo,
    topZtConcRatio,
    concRatioLabel,
    concRatioBadgeClass,
    resonanceVerdict,
    narrativeOverview,
    narrativeCoverage,
    narrativeHitNames,
  };
}
