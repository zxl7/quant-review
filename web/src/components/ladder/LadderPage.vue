<script setup lang="ts">
import { computed, ref } from 'vue';
import { useMarketData } from '../../composables/useMarketData';
import { useECharts } from '../../composables/useECharts';

const { marketData } = useMarketData();

const xqUrl = (code?: string | null) => {
  const raw = String(code || '').trim();
  if (!raw) return 'https://xueqiu.com';
  const upper = raw.toUpperCase();
  if (upper.includes('.')) {
    const [num, suffix] = upper.split('.');
    const market = suffix === 'SH' ? 'SH' : suffix === 'SZ' ? 'SZ' : '';
    return market ? `https://xueqiu.com/S/${market}${num}` : `https://xueqiu.com/S/${upper}`;
  }
  const market = raw.startsWith('6') ? 'SH' : 'SZ';
  return `https://xueqiu.com/S/${market}${raw}`;
};

const groupedLadder = computed(() => {
  const rows = Array.isArray(marketData.value?.ladder) ? [...marketData.value.ladder] : [];
  const groups = new Map<number, any[]>();
  rows.forEach((row) => {
    const badge = Number(row?.badge || 0);
    if (!badge) return;
    if (!groups.has(badge)) groups.set(badge, []);
    groups.get(badge)?.push(row);
  });
  return Array.from(groups.entries())
    .sort((a, b) => b[0] - a[0])
    .map(([badge, rows], idx) => ({
      badge,
      rows,
      count: rows.length,
      stepOffset: `${idx * 28}px`,
      badgeClass: `badge-${Math.min(Math.max(badge, 1), 7)}`,
    }));
});

const brokenListText = computed(() => {
  const items = Array.isArray(marketData.value?.brokenList) ? marketData.value.brokenList : [];
  if (!items.length) return '';
  return items.map((x: any) => `${x.name || '-'}(${x.lb || '-'}板)`).join(' / ');
});

const firstBoards = computed(() => Array.isArray(marketData.value?.firstBoards) ? marketData.value.firstBoards : []);

const heightChartRef = ref<HTMLElement | null>(null);
const heightOptions = computed<any>(() => {
  const data = marketData.value?.heightTrend;
  const dates = Array.isArray(data?.dates) ? data.dates : [];
  if (dates.length < 2) return null;
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { top: 0, textStyle: { color: '#64748b', fontSize: 11, fontWeight: 700 } },
    grid: { top: 34, left: '3%', right: '3%', bottom: '8%', containLabel: true },
    xAxis: { type: 'category', data: dates, axisLabel: { color: '#64748b', fontWeight: 700, fontSize: 10 } },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#64748b', fontWeight: 700, fontSize: 10 } },
    series: [
      { name: '主板高度', type: 'line', smooth: true, data: data?.main || [], showSymbol: true, symbolSize: 7, lineStyle: { width: 3, color: '#ef4444' }, itemStyle: { color: '#ef4444' } },
      { name: '次高', type: 'line', smooth: true, data: data?.sub || [], showSymbol: true, symbolSize: 6, lineStyle: { width: 2.5, color: '#f59e0b' }, itemStyle: { color: '#f59e0b' } },
      { name: '创业板', type: 'line', smooth: true, data: data?.gem || [], showSymbol: true, symbolSize: 6, lineStyle: { width: 2.5, color: '#94a3b8' }, itemStyle: { color: '#94a3b8' } },
    ],
  };
});
useECharts(heightChartRef, heightOptions);
</script>

<template>
  <div class="ladder-page">
    <div class="card" data-page="ladder" id="sec-height">
      <div class="card-header">
        <div class="card-title">近7日高度趋势</div>
        <div class="card-badge">7D</div>
      </div>
      <div class="height-trend-wrap">
        <div class="chart-container" style="height: 260px; margin-bottom: 0">
          <div ref="heightChartRef" style="width: 100%; height: 100%"></div>
        </div>
      </div>
    </div>

    <div class="card" data-page="ladder" id="sec-ladder">
      <div class="card-header">
        <div class="card-title">连板天梯</div>
        <div class="card-badge">非ST</div>
      </div>
      <div class="ladder-summary" id="ladderSummary"></div>
      <div class="ladder-rows" id="ladderBody">
        <div class="ladder-step" v-for="group in groupedLadder" :key="'ladder-'+group.badge" :style="{ '--step-offset': group.stepOffset }">
          <div class="ladder-step-header">
            <span class="ladder-badge" :class="group.badgeClass">{{ group.badge }}板</span>
            <span class="ladder-step-count">{{ group.count }}只</span>
          </div>
          <div class="ladder-stock-list">
            <div class="ladder-stock-card" v-for="row in group.rows" :key="`${row.code || row.name}-${group.badge}`">
              <div class="ladder-stock-name">
                <a v-if="row.code" class="stock-link" :href="xqUrl(row.code || row.dm || '')" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
                <template v-else>{{ row.name }}</template>
              </div>
              <div class="ladder-stock-meta">
                <span class="ladder-chip" :class="row.status === '晋级' ? 'red-text' : 'orange-text'">{{ row.status || '-' }}</span>
                <span class="ladder-chip" v-for="(t, i) in (row.qualityTags || [])" :key="`${row.code || row.name}-tag-${i}`" :class="t.cls">{{ t.text }}</span>
              </div>
              <div class="ladder-chip-note" v-if="row.note">{{ row.note }}</div>
            </div>
          </div>
        </div>
      </div>
      <div
        v-if="brokenListText"
        style="margin-top: 12px; padding: 10px 14px; background: rgba(239, 68, 68, 0.08); border-radius: var(--radius-sm); font-size: 12px; color: var(--danger); font-weight: 600"
        id="brokenList">
        ❌ 昨日断板：{{ brokenListText }}
      </div>
      <details id="firstBoardDetails" style="margin-top: 12px" v-if="firstBoards.length">
        <summary style="cursor: pointer; color: var(--text-secondary); font-weight: 900; font-size: 12px">首板（{{ firstBoards.length }}）</summary>
        <div class="ladder-stock-list" style="margin-top: 10px">
          <div class="ladder-stock-card" v-for="row in firstBoards" :key="`first-${row.code || row.name}`">
            <div class="ladder-stock-name">
              <a v-if="row.code" class="stock-link" :href="xqUrl(row.code || row.dm || '')" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
              <template v-else>{{ row.name }}</template>
            </div>
            <div class="ladder-stock-meta">
              <span class="ladder-chip orange-text">首板</span>
            </div>
          </div>
        </div>
      </details>
    </div>
  </div>
</template>
