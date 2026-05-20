<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue';
import HeroSection from './components/layout/HeroSection.vue';
import TabBar from './components/layout/TabBar.vue';
import SentimentPage from './components/sentiment/SentimentPage.vue';
import ThemesPage from './components/themes/ThemesPage.vue';
import LadderPage from './components/ladder/LadderPage.vue';
import PlanPage from './components/plan/PlanPage.vue';
import WatchPage from './components/intraday/WatchPage.vue';
import AbnormalPage from './components/intraday/AbnormalPage.vue';
import FlashPage from './components/intraday/FlashPage.vue';
import { useMarketData } from './composables/useMarketData';

const { marketData, marketToneClass } = useMarketData();
const marketThemeTone = computed(() => {
  const mood = marketData.value?.mood || {};
  const pan = marketData.value?.panorama || {};
  const score = Number(mood?.score ?? 0);
  const heat = Number(mood?.heat ?? 0);
  const risk = Number(mood?.risk ?? 0);
  const dt = Number(pan?.limitDown ?? 0);
  if (risk >= 55 || dt >= 8 || score <= 45) return 'bear';
  if (score >= 68 && heat >= 60 && risk <= 35) return 'bull';
  return 'mixed';
});

const defaultMode = marketData.value?.meta?.mode === 'intraday' ? 'intraday' : 'review';
const modeView = ref<'review' | 'intraday'>(defaultMode);
const reviewTabs = [
  { id: 'sentiment', name: '情绪' },
  { id: 'themes', name: '题材' },
  { id: 'ladder', name: '连板' },
  { id: 'plan', name: '预测' },
] as const;
const intradayTabs = [
  { id: 'watch', name: '实时' },
  { id: 'abnormal', name: '异动' },
  { id: 'flash', name: '快讯' },
] as const;
type TabId = (typeof reviewTabs)[number]['id'] | (typeof intradayTabs)[number]['id'];
const defaultPage = String(marketData.value?.meta?.default_page || '').trim();
const isReviewTab = reviewTabs.some((tab) => tab.id === defaultPage);
const isIntradayTab = intradayTabs.some((tab) => tab.id === defaultPage);
if (isIntradayTab) modeView.value = 'intraday';
if (isReviewTab) modeView.value = 'review';
const currentTab = ref<TabId>((isReviewTab || isIntradayTab ? defaultPage : modeView.value === 'intraday' ? 'watch' : 'sentiment') as TabId);
const visibleTabs = computed(() => (modeView.value === 'intraday' ? intradayTabs : reviewTabs));

const setModeView = (mode: 'review' | 'intraday') => {
  modeView.value = mode;
  const next = visibleTabs.value[0]?.id;
  if (next && !visibleTabs.value.some((tab) => tab.id === currentTab.value)) currentTab.value = next;
};

const heroCycleText = computed(() => '风中一刀的屠龙术丨');
const heroDateText = computed(() => {
  const raw = String(marketData.value.date || marketData.value.meta?.generatedAt?.slice(0, 10) || '').trim();
  if (!raw) return '收盘简报';
  const [year = '', month = '', day = ''] = raw.split('-');
  return `${year}年${month}月${day}日收盘简报`;
});
const heroUpdatedAt = computed(() => marketData.value.meta?.rendered_at_bj || marketData.value.meta?.generatedAt || '-');
const badgeIcon = computed(() => (marketToneClass.value === 'good' ? '🔥' : marketToneClass.value === 'warn' ? '⚠' : '🧊'));

const clamp100 = (v: unknown) => {
  const n = Number(v);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
};

const lerpColor = (hexA: string, hexB: string, t: number) => {
  const toRgb = (hex: string) => {
    const h = String(hex || '').replace('#', '').trim();
    const s = h.length === 3 ? h.split('').map((x) => x + x).join('') : h;
    const n = parseInt(s || '000000', 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  };
  const tt = Math.max(0, Math.min(1, Number(t)));
  const [r1, g1, b1] = toRgb(hexA);
  const [r2, g2, b2] = toRgb(hexB);
  const r = Math.round(r1 + (r2 - r1) * tt);
  const g = Math.round(g1 + (g2 - g1) * tt);
  const b = Math.round(b1 + (b2 - b1) * tt);
  return `rgb(${r},${g},${b})`;
};

const heatColor = (v: unknown) => {
  const p = clamp100(v);
  if (p <= 45) return lerpColor('#f59e0b', '#ff4d4f', p / 45);
  return lerpColor('#ff4d4f', '#e60012', (p - 45) / 55);
};

const riskColor = (v: unknown) => {
  const p = clamp100(v);
  if (p <= 45) return lerpColor('#16a34a', '#00a63e', p / 45);
  if (p <= 75) return lerpColor('#00a63e', '#65a30d', (p - 45) / 30);
  return lerpColor('#65a30d', '#f59e0b', (p - 75) / 25);
};

const ringStyle = (val: unknown, r: number, kind = 'heat') => {
  const rr = Number(r) || 18;
  const c = 2 * Math.PI * rr;
  const p = clamp100(val) / 100;
  const dashoffset = c * (1 - p);
  const stroke = kind === 'risk' ? riskColor(val) : heatColor(val);
  return {
    stroke,
    strokeDasharray: `${c.toFixed(2)} ${c.toFixed(2)}`,
    strokeDashoffset: `${dashoffset.toFixed(2)}`,
  };
};

const heatClass = (v: unknown) => {
  const n = Number(v);
  if (Number.isNaN(n)) return 'orange-text';
  if (n >= 70) return 'red-text';
  return 'orange-text';
};

const riskClass = (v: unknown) => {
  const n = Number(v);
  if (Number.isNaN(n)) return 'orange-text';
  if (n >= 55) return 'orange-text';
  return 'green-text';
};

const sparklinePoints = (arr: unknown[]) => {
  const xs = (Array.isArray(arr) ? arr : []).map((v) => Number(v)).filter((v) => Number.isFinite(v));
  const n = xs.length;
  if (n <= 1) return '';
  const minV = Math.min(...xs);
  const maxV = Math.max(...xs);
  const span = maxV - minV || 1;
  return xs
    .map((v, i) => {
      const x = (i / (n - 1)) * 100;
      const y = 26 - ((v - minV) / span) * 22;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');
};

const indexChgClass = (chg?: string) => {
  const v = Number(String(chg || '').replace('%', ''));
  if (v > 0) return 'up';
  if (v < 0) return 'down';
  return 'flat';
};

const indexChgIcon = (chg?: string) => {
  const v = Number(String(chg || '').replace('%', ''));
  if (v > 0) return '▲';
  if (v < 0) return '▼';
  return '';
};

const indexCardToneClass = (chg?: string) => {
  const v = Number(String(chg || '').replace('%', ''));
  if (v > 0) return 'idx-up';
  if (v < 0) return 'idx-down';
  return 'idx-flat';
};

watchEffect(() => {
  if (typeof document === 'undefined') return;
  document.body.setAttribute('data-market-tone', marketThemeTone.value);
  document.body.setAttribute('data-page', currentTab.value);
});
</script>

<template>
  <div class="shell" :data-market-tone="marketThemeTone">
    <div class="container">
      <HeroSection
        :market-data="marketData"
        :mode-view="modeView"
        :market-tone-class="marketToneClass"
        :badge-icon="badgeIcon"
        :hero-cycle-text="heroCycleText"
        :hero-date-text="heroDateText"
        :hero-updated-at="heroUpdatedAt"
        :heat-class="heatClass"
        :risk-class="riskClass"
        :ring-style="ringStyle"
        :sparkline-points="sparklinePoints"
        :index-chg-class="indexChgClass"
        :index-card-tone-class="indexCardToneClass"
        :index-chg-icon="indexChgIcon"
        @set-mode="setModeView"
      />
      <TabBar :tabs="visibleTabs" :current-tab="currentTab" @select="currentTab = $event as TabId" />

      <main class="page-main">
        <SentimentPage v-if="currentTab === 'sentiment'" />
        <ThemesPage v-else-if="currentTab === 'themes'" />
        <LadderPage v-else-if="currentTab === 'ladder'" />
        <PlanPage v-else-if="currentTab === 'plan'" />
        <WatchPage v-else-if="currentTab === 'watch'" />
        <AbnormalPage v-else-if="currentTab === 'abnormal'" />
        <FlashPage v-else-if="currentTab === 'flash'" />
      </main>
    </div>
  </div>
</template>
