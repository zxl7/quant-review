<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import * as echarts from 'echarts';
import { useMarketData } from '../../composables/useMarketData';
import { useECharts } from '../../composables/useECharts';
import ShortReminderFooter from '../common/ShortReminderFooter.vue';
import { normalizeThemeName } from '../../utils/themeUtils';

const { marketData } = useMarketData();

const brokenPremium = ref<{ avg: number; median: number; list: any[] }>({ avg: 0, median: 0, list: [] });
const brokenLoading = ref(false);

const fetchBrokenPremium = async () => {
  const items = Array.isArray(marketData.value?.brokenList) ? marketData.value.brokenList : [];
  if (!items.length) return;

  brokenLoading.value = true;
  const codes = items.map((x: any) => x.code).filter(Boolean);
  const symbols = codes.map((c: string) => `${c}.${c.startsWith('6') ? 'SS' : 'SZ'}`);
  
  try {
    const res = await fetch(`https://flash-api.xuangubao.cn/api/stock/data?fields=symbol,change_percent&symbols=${symbols.join(',')}`);
    const json = await res.json();
    const quotes = json?.data || {};
    
    const gains = items.map((item: any) => {
      const symbol = `${item.code}.${item.code.startsWith('6') ? 'SS' : 'SZ'}`;
      const g = quotes[symbol]?.change_percent !== undefined ? quotes[symbol].change_percent * 100 : 0;
      return { ...item, gain: g };
    });

    const gainValues = gains.map(x => x.gain);
    brokenPremium.value = {
      avg: gainValues.reduce((a, b) => a + b, 0) / gainValues.length,
      median: median(gainValues),
      list: gains,
    };
  } catch (e) {
    console.error('Failed to fetch broken premium', e);
  } finally {
    brokenLoading.value = false;
  }
};

onMounted(() => {
  fetchBrokenPremium();
});

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

const median = (arr: number[]) => {
  const a = (arr || []).filter((v) => Number.isFinite(v)).sort((x, y) => x - y);
  if (!a.length) return 0;
  const mid = Math.floor(a.length / 2);
  return a.length % 2 ? a[mid] : (a[mid - 1] + a[mid]) / 2;
};

const fmtYi = (v: number) => (Number.isFinite(Number(v)) && Number(v) > 0 ? `${Number(v).toFixed(Number(v) >= 10 ? 0 : 2)}亿` : '-');
const fmtHhmm = (fbt?: string | null) => {
  const s = String(fbt || '').trim();
  if (!s) return '';
  if (s.includes(':')) return s.slice(0, 5);
  if (s.length >= 4) return `${s.slice(0, 2)}:${s.slice(2, 4)}`;
  return s;
};
const timeClass = (hhmm?: string | null) => {
  const s = String(hhmm || '');
  if (!s.includes(':')) return 'blue-text';
  const [hh, mm] = s.split(':').map((x) => Number(x));
  const t = hh * 60 + mm;
  if (t <= 9 * 60 + 30) return 'red-text';
  if (t >= 14 * 60 + 30) return 'blue-text';
  return 'orange-text';
};

const ladderRows = computed(() => Array.isArray(marketData.value?.ladder) ? [...marketData.value.ladder] : []);

const mainTheme = computed(() => String(marketData.value?.themePanels?.ztTop?.[0]?.name || ''));

const themesFor = (code: unknown): string[] => {
  const key = String(code || '').trim();
  if (!key) return [];
  const map = marketData.value?.zt_code_themes || {};
  const arr = Array.isArray(map[key]) ? map[key] : [];
  return arr.slice(0, 4).map((x: unknown) => String(x || '').trim()).filter(Boolean);
};

const isMainThemeChip = (theme: string) => Boolean(mainTheme.value) && theme === mainTheme.value;

const groupedLadder = computed(() => {
  const groups = new Map<number, any[]>();
  ladderRows.value.forEach((row) => {
    const badge = Number(row?.badge || 0);
    if (!badge) return;
    if (!groups.has(badge)) groups.set(badge, []);
    groups.get(badge)?.push(row);
  });
  
  return Array.from(groups.entries())
    .sort((a, b) => b[0] - a[0])
    .map(([badge, rows]) => {
      // 1. 板块统计：找出该梯队的主流板块
      const sectorCounts = new Map<string, number>();
      rows.forEach(r => {
        const themes = themesFor(r.code);
        themes.forEach(t => {
          const normalized = normalizeThemeName(t);
          sectorCounts.set(normalized, (sectorCounts.get(normalized) || 0) + 1);
        });
      });
      const topSectors = Array.from(sectorCounts.entries())
        .sort((a, b) => b[1] - a[1])
        .slice(0, 2)
        .map(([name, count]) => ({ name, count }));

      // 2. 接力情绪分析
      const qCount = (label: string) => rows.filter((r) => String(r.qualityLabel || '') === label).length;
      const accel = qCount('加速确认');
      const relay = qCount('温和放量') + qCount('高换手承接');
      const weak = qCount('分歧烂板') + qCount('反复回封');
      
      let relaySentiment = '均衡';
      let relayCls = 'kpi-orange';
      if (accel > rows.length * 0.5) { relaySentiment = '加速'; relayCls = 'kpi-red'; }
      else if (relay > rows.length * 0.4) { relaySentiment = '接力'; relayCls = 'kpi-orange'; }
      else if (weak > rows.length * 0.3) { relaySentiment = '分歧'; relayCls = 'kpi-blue'; }

      const zbcArr = rows.map((r) => Number(r?.zbc ?? 0));
      const resealCnt = zbcArr.filter((v) => v >= 1).length;
      const multiOpenCnt = zbcArr.filter((v) => v >= 2).length;
      const resealRate = rows.length ? Math.round((resealCnt / rows.length) * 100) : 0;
      const multiOpenRate = rows.length ? Math.round((multiOpenCnt / rows.length) * 100) : 0;
      
      const sealYiArr = rows.map((r) => Number(r?.zj ?? 0) / 1e8).filter((v) => v > 0);
      const sealMed = median(sealYiArr);
      const sealMax = sealYiArr.length ? Math.max(...sealYiArr) : 0;

      return {
        badge,
        rows,
        count: rows.length,
        badgeClass: badge >= 6 ? 'badge-6' : badge === 5 ? 'badge-5' : `badge-${badge}`,
        resealRate,
        multiOpenRate,
        resealCls: resealRate >= 55 ? 'kpi-red' : resealRate >= 35 ? 'kpi-orange' : 'kpi-blue',
        multiCls: multiOpenRate >= 35 ? 'kpi-red' : multiOpenRate >= 18 ? 'kpi-orange' : 'kpi-blue',
        sealMed,
        sealMax,
        topSectors,
        relaySentiment,
        relayCls,
        resonanceScore: Math.min(topSectors.length * 20 + rows.length * 2 + badge * 5, 100), // 梯队共振分
      };
    });
});

const ladderSummary = computed(() => {
  const data = ladderRows.value;
  const mi = marketData.value?.features?.mood_inputs || {};
  const yest = Number(mi.yest_lb_count ?? 0);
  const promote = data.filter((r) => r.status === '晋级').length;
  const jj = mi.jj_rate !== undefined ? `${Number(mi.jj_rate).toFixed(1)}%` : '-';
  const zt = Number(marketData.value?.panorama?.limitUp ?? 0);
  const maxLb = Number(mi.max_lb ?? groupedLadder.value?.[0]?.badge ?? 0);
  const zbRate = mi.zb_rate !== undefined ? `${Number(mi.zb_rate).toFixed(1)}%` : '-';
  const total = data.length || 0;
  const cleanName = (name: string) => String(name || '').replace(/^[^\u4e00-\u9fa5A-Za-z0-9]+/, '').trim();
  const qCount = (label: string) => data.filter((r) => String(r.qualityLabel || '') === label).length;
  const accelCnt = qCount('加速确认');
  const warmCnt = qCount('温和放量');
  const rottenCnt = qCount('分歧烂板');
  const resealCnt = qCount('反复回封');
  const highTurnCnt = qCount('高换手承接');
  const topRows = [...data].sort((a, b) => Number(b.badge || 0) - Number(a.badge || 0) || Number(b.zj || 0) - Number(a.zj || 0));
  const topRow = topRows[0] || {};
  const secondBadge = Number(topRows[1]?.badge || 0);
  const topBadge = Number(topRow.badge || maxLb || 0);
  const topName = cleanName(topRow.name || '');
  const hasSpaceLeader = topName && topBadge >= 5 && topBadge > secondBadge;
  const tierSpan = groupedLadder.value.length;
  let qualityTitle = hasSpaceLeader ? `${topName}打开${topBadge}板高度` : '梯队承接';
  let qualitySub = hasSpaceLeader ? '市场空间核心，先看它对高标与同题材的带动。' : `连板覆盖 ${tierSpan} 个梯队，先看前排能否继续晋级。`;
  if (!hasSpaceLeader && accelCnt + warmCnt >= Math.max(3, Math.ceil(total * 0.55))) {
    qualityTitle = '确认型占优';
    qualitySub = `加速/温和放量 ${accelCnt + warmCnt} 只，前排承接偏稳。`;
  } else if (!hasSpaceLeader && rottenCnt + resealCnt >= Math.max(2, Math.ceil(total * 0.35))) {
    qualityTitle = '分歧板偏多';
    qualitySub = `烂板/反复回封 ${rottenCnt + resealCnt} 只，次日更看去弱留强。`;
  } else if (!hasSpaceLeader && highTurnCnt >= Math.max(2, Math.ceil(total * 0.25))) {
    qualityTitle = '换手承接';
    qualitySub = `高换手承接 ${highTurnCnt} 只，资金偏向换手确认。`;
  }
  return {
    total,
    promote,
    yest,
    jj,
    zt,
    maxLb,
    zbRate,
    qualityTitle,
    qualitySub,
  };
});

const firstBoards = computed(() => {
  const ztgc = Array.isArray(marketData.value?.ztgc) ? marketData.value.ztgc : [];
  return ztgc
    .filter((s: any) => Number(s?.lbc ?? s?.lbHeight ?? 0) === 1)
    .map((s: any) => ({
      name: String(s?.mc || s?.name || ''),
      code: String(s?.dm || s?.code || ''),
      zj: Number(s?.zj ?? 0),
      zbc: Number(s?.zbc ?? 0),
    }))
    .filter((x: any) => x.name && x.code)
    .sort((a: any, b: any) => b.zj - a.zj || a.zbc - b.zbc)
    .slice(0, 24);
});

const brokenListText = computed(() => {
  const items = Array.isArray(marketData.value?.brokenList) ? marketData.value.brokenList : [];
  if (!items.length) return '';
  return items.map((x: any) => `${x.name || '-'}(${x.lb || '-'}板)`).join(' / ');
});

const heightChartRef = ref<HTMLElement | null>(null);
const heightOptions = computed<any>(() => {
  const data = marketData.value?.heightTrend;
  const dates = Array.isArray(data?.dates) ? data.dates : [];
  if (dates.length < 2) return null;
  const labels = data?.labels || { main: [], sub: [], gem: [] };
  const themeTone = document.body.getAttribute('data-market-tone') || 'mixed';
  const tonePalette =
    themeTone === 'bull'
      ? ['#ef4444', '#f59e0b', '#94a3b8']
      : themeTone === 'bear'
        ? ['#0ea5e9', '#10b981', '#94a3b8']
        : ['#f59e0b', '#ef4444', '#2563eb'];
  const colors = Array.isArray(data?.palette) && data.palette.length ? data.palette : tonePalette;
  const vals = []
    .concat(Array.isArray(data?.main) ? data.main : [])
    .concat(Array.isArray(data?.sub) ? data.sub : [])
    .concat(Array.isArray(data?.gem) ? data.gem : [])
    .map((v) => Number(v))
    .filter((v) => Number.isFinite(v));
  const maxV = vals.length ? Math.max(...vals) : 8;
  const yMax = Math.max(4, Math.min(12, Math.ceil(maxV + 0.8)));
  const lastIdx = dates.length - 1;
  const fmtBoard = (v: unknown) => {
    const n = Number(v);
    if (!Number.isFinite(n)) return '';
    return `${n.toFixed(0)}板`;
  };
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line' },
      formatter: (params: any[]) => {
        if (!params?.length) return '';
        const date = params[0]?.axisValue || '';
        let res = `<div style="font-weight:950;margin-bottom:6px">${date}</div>`;
        params.forEach((p) => {
          res += `<div style="display:flex;justify-content:space-between;gap:12px;font-size:12px">
            <span style="color:var(--text-muted);font-weight:800">${p.seriesName}</span>
            <span style="font-weight:950;color:${p.color}">${fmtBoard(p.data)}</span>
          </div>`;
        });
        return res;
      },
    },
    legend: {
      data: ['最高板', '次高板', '创业板'],
      bottom: 0,
      textStyle: { color: 'var(--text-muted)', fontWeight: 600, fontSize: 11 },
      icon: 'circle',
    },
    grid: { top: '12%', left: '3%', right: '5%', bottom: '20%', containLabel: true },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: 'var(--text-muted)' } },
      axisLabel: { color: 'var(--text-muted)', fontWeight: 800, fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: yMax,
      interval: 1,
      splitLine: { lineStyle: { type: 'dashed', color: 'var(--border)' } },
      axisLabel: { color: 'var(--text-muted)', fontWeight: 700, fontSize: 10 },
    },
    series: [
      {
        name: '最高板',
        type: 'line',
        data: Array.isArray(data?.main) ? data.main : [],
        smooth: true,
        lineStyle: { width: 4, color: colors[0] },
        itemStyle: { color: colors[0] },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: echarts.color.modifyAlpha(colors[0], 0.16) },
            { offset: 1, color: echarts.color.modifyAlpha(colors[0], 0.02) },
          ]),
        },
        symbolSize: 8,
        label: {
          show: true,
          position: 'top',
          formatter: (params: any) => {
            const t = labels.main?.[params.dataIndex];
            if (t) return t;
            if (params.dataIndex !== lastIdx) return '';
            return fmtBoard(params.value);
          },
          color: colors[0],
          fontWeight: 800,
          fontSize: 10,
          backgroundColor: echarts.color.modifyAlpha(colors[0], 0.12),
          padding: [2, 4],
          borderRadius: 4,
          borderColor: colors[0],
          borderWidth: 0.5,
        },
      },
      {
        name: '次高板',
        type: 'line',
        data: Array.isArray(data?.sub) ? data.sub : [],
        smooth: true,
        lineStyle: { width: 3, color: colors[1], type: 'dashed' },
        itemStyle: { color: colors[1] },
        symbolSize: 6,
        label: {
          show: true,
          position: 'top',
          formatter: (params: any) => {
            const t = labels.sub?.[params.dataIndex];
            if (t) return t;
            if (params.dataIndex !== lastIdx) return '';
            return fmtBoard(params.value);
          },
          color: colors[1],
          fontWeight: 800,
          fontSize: 10,
        },
      },
      {
        name: '创业板',
        type: 'line',
        data: Array.isArray(data?.gem) ? data.gem : [],
        smooth: true,
        lineStyle: { width: 2, color: colors[2] },
        itemStyle: { color: colors[2] },
        symbolSize: 4,
        label: {
          show: true,
          position: 'top',
          formatter: (params: any) => {
            const t = labels.gem?.[params.dataIndex];
            if (t) return t;
            if (params.dataIndex !== lastIdx) return '';
            return fmtBoard(params.value);
          },
          color: colors[2],
          fontWeight: 800,
          fontSize: 10,
        },
      },
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

      <div class="ladder-summary" id="ladderSummary" v-if="ladderRows.length">
        <div class="ladder-summary-item">
          <div class="ladder-summary-icon">🎯</div>
          <div class="ladder-summary-v">{{ ladderSummary.total }}</div>
          <div class="ladder-summary-k">连板家数</div>
          <div class="ladder-summary-sub">晋级 {{ ladderSummary.promote }} / 昨日 {{ ladderSummary.yest }}</div>
        </div>
        <div class="ladder-summary-item">
          <div class="ladder-summary-icon">🔥</div>
          <div class="ladder-summary-v">{{ ladderSummary.jj }}</div>
          <div class="ladder-summary-k">昨日晋级率</div>
          <div class="ladder-summary-sub">最高板 {{ ladderSummary.maxLb }}</div>
        </div>
        <div class="ladder-summary-item">
          <div class="ladder-summary-icon" :class="brokenPremium.avg > 0 ? 'kpi-red' : 'kpi-blue'">💔</div>
          <div class="ladder-summary-v" :class="brokenPremium.avg > 0 ? 'red-text' : 'blue-text'">
            {{ brokenPremium.avg > 0 ? '+' : '' }}{{ brokenPremium.avg.toFixed(2) }}%
          </div>
          <div class="ladder-summary-k">断板反馈 (Premium)</div>
          <div class="ladder-summary-sub" v-if="brokenPremium.list.length">
            昨日断板 {{ brokenPremium.list.length }} 只，中位 {{ brokenPremium.median.toFixed(2) }}%
          </div>
        </div>
        <div class="ladder-summary-item wide">
          <div class="ladder-summary-icon">💡</div>
          <div class="ladder-summary-v">{{ ladderSummary.qualityTitle }}</div>
          <div class="ladder-summary-k">梯队结构分析</div>
          <div class="ladder-summary-sub">{{ ladderSummary.qualitySub }}</div>
        </div>
      </div>

      <div class="ladder-rows" id="ladderBody">
        <div class="ladder-row" v-for="group in groupedLadder" :key="'ladder-'+group.badge">
          <div class="ladder-left">
            <div class="ladder-left-top">
              <span class="ladder-badge" :class="group.badgeClass">{{ group.badge }}板</span>
            </div>
            <div class="ladder-left-meta">
              <span class="muted">成员</span>
              <span class="val">{{ group.count }}</span>
            </div>
            <div class="ladder-left-meta" v-if="group.topSectors && group.topSectors.length">
            <span class="muted">核心板块</span>
            <div class="sector-row">
              <span class="val-sector" v-for="s in group.topSectors" :key="s.name">{{ s.name }}</span>
            </div>
          </div>
          <div class="ladder-left-kpi">
            <div class="kpi-item">
              <span class="muted">接力情绪 / 共振分</span>
              <div class="kpi-row">
                <span :class="group.relayCls">{{ group.relaySentiment }}</span>
                <span class="kpi-res-score">🔥 {{ group.resonanceScore }}</span>
              </div>
            </div>
              <div class="kpi-item">
                <span class="muted">回封率</span>
                <span :class="group.resealCls">{{ group.resealRate }}%</span>
              </div>
            </div>
          </div>

          <div class="ladder-stock-list">
            <div class="ladder-stock-card" v-for="row in group.rows" :key="`${row.code || row.name}-${group.badge}`">
              <div class="ladder-stock-top">
                <div class="ladder-stock-name">
                  <a v-if="row.code" class="stock-link" :href="xqUrl(row.code || row.dm || '')" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
                  <template v-else>{{ row.name }}</template>
                </div>
                <div class="ladder-stock-tags">
                  <span class="ladder-chip ladder-chip-mini red-text" v-if="row.zf !== undefined && row.zf !== null">+{{ Number(row.zf).toFixed(1) }}%</span>
                  <span class="ladder-chip ladder-chip-mini ladder-chip-time" :class="timeClass(fmtHhmm(row.fbt))" v-if="fmtHhmm(row.fbt)">{{ fmtHhmm(row.fbt) }}</span>
                </div>
              </div>
              <div class="ladder-meta-row" v-if="(row.qualityTags || []).length || row.zbc || row.zj">
                <span class="ladder-chip" v-for="(t, i) in (row.qualityTags || [])" :key="`${row.code || row.name}-tag-${i}`" :class="t.cls">{{ t.text }}</span>
                <span class="ladder-chip ladder-chip-warn orange-text" v-if="Number(row.zbc || 0) >= 2">{{ Number(row.zbc) }}次开板</span>
                <span class="ladder-chip ladder-chip-cool orange-text" v-else-if="Number(row.zbc || 0) >= 1">回封</span>
                <span class="ladder-chip" :class="Number(row.zj || 0) / 1e8 >= 5 ? 'ladder-chip-strong red-text' : 'ladder-chip-cool orange-text'" v-if="Number(row.zj || 0) > 0">
                  {{ fmtYi(Number(row.zj || 0) / 1e8) }}封
                </span>
              </div>
              <div class="ladder-meta-row" v-if="themesFor(row.code).length" style="margin-top: 4px">
                <span
                  class="ladder-chip ladder-chip-mini"
                  v-for="(theme, i) in themesFor(row.code)"
                  :key="`${row.code || row.name}-th-${i}`"
                  :class="isMainThemeChip(theme) ? 'ladder-chip-strong red-text' : 'ladder-chip-cool'"
                  :title="isMainThemeChip(theme) ? '今日主线题材' : ''">
                  <span v-if="isMainThemeChip(theme)" style="margin-right: 2px">★</span>{{ theme }}
                </span>
              </div>
              <div class="ladder-chip-note" v-if="row.note">{{ row.note }}</div>
            </div>
          </div>

          <div class="ladder-row-footer">
            <span class="pill">分歧：<span :class="group.resealCls">回封{{ group.resealRate }}%</span> · <span :class="group.multiCls">多开{{ group.multiOpenRate }}%</span></span>
            <span class="pill">封板资金：中位{{ fmtYi(group.sealMed) }} · 最大{{ fmtYi(group.sealMax) }}</span>
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
        <summary style="cursor:pointer; color:var(--text-muted); font-weight:900; font-size:12px;">展开首板（{{ firstBoards.length }}）</summary>
        <div class="ladder-row" style="margin-top:10px;">
          <div class="ladder-left">
            <div class="ladder-left-top">
              <span class="ladder-badge badge-1">首板</span>
            </div>
            <div class="ladder-left-meta">{{ firstBoards.length }}只</div>
            <div class="ladder-left-kpi">按封单排序 · 默认折叠</div>
          </div>
          <div class="ladder-stock-list">
            <div class="ladder-stock-card" v-for="x in firstBoards" :key="`first-${x.code}`">
              <div class="ladder-stock-top">
                <div class="ladder-stock-name"><a class="stock-link" :href="xqUrl(x.code)" target="_blank" rel="noopener noreferrer">{{ x.name }}</a></div>
                <div class="ladder-stock-tags">
                  <span class="ladder-chip ladder-chip-mini orange-text">首板</span>
                  <span class="ladder-chip ladder-chip-mini orange-text" v-if="Number(x.zbc || 0) >= 1">{{ Number(x.zbc) }}次开板</span>
                  <span class="ladder-chip ladder-chip-mini" :class="Number(x.zj || 0) / 1e8 >= 5 ? 'red-text' : 'orange-text'" v-if="Number(x.zj || 0) > 0">{{ fmtYi(Number(x.zj || 0) / 1e8) }}封</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </details>
    </div>

    <ShortReminderFooter />
  </div>
</template>

<style scoped src="./LadderPage.css"></style>
