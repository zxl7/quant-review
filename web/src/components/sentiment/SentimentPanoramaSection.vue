<script setup lang="ts">
import { computed, ref } from 'vue';
import { echarts } from '../../echarts-setup';
import { useECharts } from '../../composables/useECharts';
import { useSentimentView } from './useSentimentView';

const { marketData, marketToneClass, moodCardsBy, moodCardValueClass } = useSentimentView();

const moodPanels = [
  { group: 'carry', title: '承接', pill: '晋级/断板', accent: 'rgba(239, 68, 68, 0.9)' },
  { group: 'cons', title: '一致性', pill: '早封/资金', accent: 'rgba(245, 158, 11, 0.92)' },
  { group: 'risk', title: '风险', pill: '高度/拥挤', accent: 'rgba(16, 185, 129, 0.9)' },
] as const;

const volumeChartRef = ref<HTMLElement | null>(null);
const volumeOptions = computed<any>(() => {
  const data = marketData.value.volume;
  if (!data?.dates?.length || data.dates.length < 2) return null;

  const vals = data.values.map((v: unknown) => Number(v));
  const maxV = Math.max(...vals.filter((v: number) => Number.isFinite(v)));
  const yMax = Number.isFinite(maxV) ? Math.ceil(maxV / 5000) * 5000 + 2000 : 40000;
  const trendColor = marketToneClass.value === 'good' ? '#ef4444' : marketToneClass.value === 'fire' ? '#0ea5e9' : '#f59e0b';
  const isUp = (index: number) => index === 0 || vals[index] >= vals[index - 1];

  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { top: '12%', left: '3%', right: '3%', bottom: '12%', containLabel: true },
    xAxis: {
      type: 'category',
      data: data.dates,
      axisLine: { lineStyle: { color: 'var(--text-muted)' } },
      axisLabel: { color: 'var(--text-muted)', fontWeight: 800, fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      max: yMax,
      splitLine: { lineStyle: { type: 'dashed', color: 'var(--border)' } },
      axisLabel: {
        color: 'var(--text-muted)',
        fontWeight: 700,
        fontSize: 10,
        formatter: (v: number) => (Number(v) >= 10000 ? Math.round(v) : Number(v).toFixed(0)),
      },
    },
    series: [
      {
        name: '两市成交额',
        type: 'bar',
        label: {
          show: true,
          position: 'top',
          distance: 6,
          fontSize: 10,
          fontWeight: 900,
          color: 'var(--text-muted)',
          formatter: (p: any) => {
            const v = Number(p.value?.value ?? p.value ?? 0);
            if (!Number.isFinite(v) || v <= 0) return '';
            if (v >= 10000) return `${(v / 10000).toFixed(2)}万亿`;
            return `${v.toFixed(0)}亿`;
          },
        },
        data: vals.map((v: number, index: number) => ({
          value: v,
          itemStyle: {
            color: isUp(index) ? 'rgba(239,68,68,0.75)' : 'rgba(16,185,129,0.75)',
            borderRadius: [5, 5, 0, 0],
          },
        })),
        barWidth: '42%',
      },
      {
        name: '成交趋势',
        type: 'line',
        data: vals,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 3, color: trendColor },
        markLine: {
          symbol: 'none',
          label: { color: 'var(--text-muted)', fontWeight: 800, fontSize: 10 },
          lineStyle: { color: 'rgba(148,163,184,0.55)', type: 'dashed' },
          data: [{ type: 'average', name: '均值' }],
        },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: echarts.color.modifyAlpha(trendColor, 0.22) },
            { offset: 1, color: echarts.color.modifyAlpha(trendColor, 0.02) },
          ]),
        },
      },
    ],
  };
});

useECharts(volumeChartRef, volumeOptions);
</script>

<template>
  <div class="card" data-page="sentiment" id="sec-volume">
    <div class="card-header"><div class="card-title">市场全景 · 7日对比</div></div>

    <div class="section-header">量能趋势</div>
    <div class="inset">
      <div class="inset-head">
        <div class="h">两市成交额</div>
        <div class="s">近 7 日 · 量能回流强弱</div>
      </div>
      <div ref="volumeChartRef" class="chart-container" style="margin-bottom: 0"></div>

      <div class="mc-panels">
        <div v-for="panel in moodPanels" :key="panel.group" class="mc-panel" :style="{ '--mc-accent': panel.accent }">
          <div class="mc-head">
            <div class="mc-title"><span class="dot"></span>{{ panel.title }}</div>
            <div class="mc-pill">{{ panel.pill }}</div>
          </div>
          <div class="mc-items">
            <div class="mc-item" v-for="(card, idx) in moodCardsBy(panel.group)" :key="`mood-${panel.group}-${idx}`">
              <div class="mc-left">
                <div class="mc-k">{{ card.label }}</div>
                <div class="mc-note">{{ card.note }}</div>
              </div>
              <div class="mc-v" :class="moodCardValueClass(panel.group, card)">{{ card.value }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
