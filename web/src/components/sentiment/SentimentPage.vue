<script setup lang="ts">
import { computed, ref } from 'vue';
import * as echarts from 'echarts';
import { useMarketData } from '../../composables/useMarketData';
import { useECharts } from '../../composables/useECharts';
import { useThemeHotStore } from '../../composables/useThemeHotStore';
import ShortReminderFooter from '../common/ShortReminderFooter.vue';

const { marketData, marketToneClass } = useMarketData();
const { narrativeHitForTheme, xgbPlates, tmrThemes, xgbUpdatedAt, tmrUpdatedAt, xgbHotPlateNames } = useThemeHotStore();

const heatColor = (v: number) => {
  const n = Number(v || 0);
  if (n <= 45) return '#f59e0b';
  if (n <= 70) return '#ff4d4f';
  return '#e60012';
};

const riskColor = (v: number) => {
  const n = Number(v || 0);
  if (n <= 45) return '#16a34a';
  if (n <= 75) return '#0db110ff';
  return '#f59e0b';
};

const signedClass = (v?: string | number | null) => {
  const n = Number(String(v ?? '').replace('%', ''));
  if (Number.isNaN(n)) return '';
  if (n > 0) return 'red-text';
  if (n < 0) return 'green-text';
  return 'orange-text';
};

const toNum = (v: unknown, d = 0) => {
  if (v === undefined || v === null || v === '') return d;
  if (typeof v === 'string') return Number(v.replace('%', '').replace('亿', '').trim()) || d;
  const n = Number(v);
  return Number.isFinite(n) ? n : d;
};

const moodGroup = (label: string) => {
  const carry = new Set(['连板晋级率', '2进3成功率', '3进4成功率', '连板断板率']);
  const cons = new Set(['早盘封板占比', '平均封板资金', '涨停换手(中位)', '涨停炸板次数(均)']);
  if (carry.has(label)) return 'carry';
  if (cons.has(label)) return 'cons';
  return 'risk';
};

const moodCardsBy = (group: string) => (marketData.value.moodCards || []).filter((card: any) => moodGroup(card.label) === group);

const topZtTheme = computed<any>(() => (marketData.value?.themePanels?.ztTop || [])[0] || null);

const ztTotalCount = computed(() => {
  const fromMood = Number(marketData.value?.features?.mood_inputs?.zt_count);
  if (Number.isFinite(fromMood) && fromMood > 0) return fromMood;
  return (marketData.value?.themePanels?.ztTop || []).reduce((s: number, x: any) => s + Number(x?.count || 0), 0);
});

const topZtConcRatio = computed(() => {
  const c = Number(topZtTheme.value?.count || 0);
  const total = ztTotalCount.value;
  if (!c || !total) return 0;
  return Math.round((c / total) * 1000) / 10;
});

const concRatioCls = computed(() => {
  const r = topZtConcRatio.value;
  if (r >= 35) return 'red-text';
  if (r >= 20) return 'orange-text';
  return 'green-text';
});

const concRatioLabel = computed(() => {
  const r = topZtConcRatio.value;
  if (r >= 35) return '高度抱团';
  if (r >= 20) return '主线明确';
  if (r > 0) return '资金分散';
  return '-';
});

const topPlate = computed<any>(() => (marketData.value?.plateRankTop10 || [])[0] || null);

const rotationInfo = computed<any>(() => marketData.value?.rotation || null);

const resonanceVerdict = computed(() => {
  void xgbUpdatedAt.value;
  void tmrUpdatedAt.value;
  const conc = topZtConcRatio.value;
  const style = String(rotationInfo.value?.style || '');
  const highRatio = Number(rotationInfo.value?.highLevelRatio || 0);
  const overlapScoreRaw = String(marketData.value?.structureV2?.evidence?.overlap?.score || '').replace('%', '');
  const overlap = Number(overlapScoreRaw);
  const narrative = narrativeHitForTheme(topZtTheme.value?.name);
  if (!conc) return { text: '-', cls: '' };
  if (Number.isFinite(overlap) && overlap >= 50) return { text: '主线与炸板高度重叠,主线在分歧/退潮,情绪面承压', cls: 'orange-text' };
  if (conc >= 35 && narrative.hit) return { text: `主线抱团 + ${narrative.sources.join('/')}narrative 双重确认,情绪偏强`, cls: 'red-text' };
  if (conc >= 35 && /高位|加速|主升/.test(style)) return { text: '主线抱团 + 高位接力,情绪偏热,警惕兑现', cls: 'orange-text' };
  if (conc >= 35) return { text: '主线抱团明显,接力链条值得追踪', cls: 'red-text' };
  if (conc >= 20 && narrative.hit) return { text: `主线初现 + ${narrative.sources.join('/')}narrative 加持,题材有发酵潜力`, cls: 'red-text' };
  if (conc >= 20 && /低位|试错/.test(style)) return { text: '主线初现 + 低位试错,题材有发酵潜力', cls: 'red-text' };
  if (conc < 20 && highRatio >= 30) return { text: '题材分散 + 高位拥挤,易出现高位接力风险', cls: 'orange-text' };
  if (conc < 20 && !narrative.hit) return { text: '资金分散且 narrative 未共振,主线尚未形成', cls: 'green-text' };
  if (conc < 20) return { text: '资金分散,主线尚未形成', cls: 'green-text' };
  return { text: '主线一般,关注后续切换', cls: 'orange-text' };
});

const narrativeOverview = computed(() => {
  void xgbUpdatedAt.value;
  void tmrUpdatedAt.value;
  const xgbCnt = xgbPlates.value.length;
  const tmrHot = tmrThemes.value.filter((t) => t.isHot).length;
  const tmrAll = tmrThemes.value.length;
  if (!xgbCnt && !tmrAll) return null;
  const topZtName = String(topZtTheme.value?.name || '');
  const hit = topZtName ? narrativeHitForTheme(topZtName) : { hit: false, sources: [] };
  return {
    xgbCnt,
    tmrHot,
    tmrAll,
    topZtName,
    hit: hit.hit,
    sources: hit.sources,
  };
});

const narrativeCoverage = computed(() => {
  void xgbUpdatedAt.value;
  void tmrUpdatedAt.value;
  const themesMap = (marketData.value?.zt_code_themes || {}) as Record<string, string[]>;
  const codes = Object.keys(themesMap);
  if (!codes.length) return null;
  const hotSet = xgbHotPlateNames.value;
  if (!hotSet.size) return null;
  let hit = 0;
  const hitCodes: string[] = [];
  codes.forEach((code) => {
    const themes = Array.isArray(themesMap[code]) ? themesMap[code] : [];
    if (themes.some((t) => hotSet.has(String(t || '').trim().replace(/\s+/g, '')))) {
      hit += 1;
      if (hitCodes.length < 6) hitCodes.push(code);
    }
  });
  const ratio = codes.length ? Math.round((hit / codes.length) * 100) : 0;
  let verdict = '';
  let cls = '';
  if (ratio >= 40) { verdict = 'narrative 驱动 — 涨停股大面积命中 narrative 主线'; cls = 'red-text'; }
  else if (ratio >= 20) { verdict = '部分共振 — 主线在但未全面发酵'; cls = 'orange-text'; }
  else { verdict = 'narrative 脱节 — 涨停与今日叙事相关度低'; cls = 'green-text'; }
  return { total: codes.length, hit, ratio, hitCodes, verdict, cls };
});

const narrativeHitNames = computed(() => {
  if (!narrativeCoverage.value) return '';
  const codes = narrativeCoverage.value.hitCodes;
  const zt = Array.isArray(marketData.value?.ztgc) ? marketData.value.ztgc : [];
  const codeToName = new Map<string, string>();
  zt.forEach((s: any) => { const k = String(s?.dm || s?.code || '').trim(); if (k) codeToName.set(k, String(s?.mc || s?.name || k)); });
  return codes.map((c) => codeToName.get(c) || c).join(' / ');
});

const moodCardValueClass = (group: string, card: any) => {
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

const volumeChartRef = ref<HTMLElement | null>(null);
const volumeOptions = computed<any>(() => {
  const data = marketData.value.volume;
  if (!data?.dates?.length || data.dates.length < 2) return null;
  const vals = data.values.map((v: unknown) => Number(v));
  const maxV = Math.max(...vals.filter((v: number) => isFinite(v)));
  const yMax = isFinite(maxV) ? Math.ceil(maxV / 5000) * 5000 + 2000 : 40000;
  const trendColor = marketToneClass.value === 'good' ? '#ef4444' : marketToneClass.value === 'fire' ? '#0ea5e9' : '#f59e0b';
  const isUp = (i: number) => i === 0 || vals[i] >= vals[i - 1];
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
        data: vals.map((v: number, i: number) => ({
          value: v,
          itemStyle: {
            color: isUp(i) ? 'rgba(239,68,68,0.75)' : 'rgba(16,185,129,0.75)',
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
  <div class="sentiment-page">
    <div class="page-block summarybar" :class="'mood-' + marketToneClass" data-page="sentiment">
      <div class="thermo-mini">
        <div class="thermo-mini-head">
          <div class="thermo-mini-title">情绪温度</div>
          <div class="thermo-mini-meta">热 / 险 · {{ marketData.mood?.score ?? '-' }}/100</div>
        </div>

        <div class="thermo-mini-rows">
          <div class="thermo-mini-row">
            <span class="thermo-mini-label">情绪热度</span>
            <div class="insight-meter" style="margin-top: 0">
              <div class="insight-meter-fill" :style="{ width: String((marketData.mood?.heat ?? 0)) + '%', background: heatColor(marketData.mood?.heat ?? 0) }"></div>
            </div>
            <span class="val">{{ marketData.mood?.heat ?? '-' }}</span>
          </div>
          <div class="thermo-mini-row">
            <span class="thermo-mini-label">风险压力</span>
            <div class="insight-meter" style="margin-top: 0">
              <div class="insight-meter-fill" :style="{ width: String((marketData.mood?.risk ?? 0)) + '%', background: riskColor(marketData.mood?.risk ?? 0) }"></div>
            </div>
            <span class="val">{{ marketData.mood?.risk ?? '-' }}</span>
          </div>
        </div>

        <details style="margin-top: 10px" v-if="(marketData.sentimentExplainDims || []).length" open data-open-default="1">
          <summary style="cursor: pointer; color: var(--text-muted); font-weight: 900; font-size: 12px">更多维度</summary>
          <div class="dim-grid" style="margin-top: 10px">
            <div class="dim-item" v-for="it in (marketData.sentimentExplainDims || [])" :key="'txb-'+it.key">
              <div class="dim-top">
                <span class="dim-k">
                  {{ it.title }}
                  <span class="lvl-badge" :class="it.levelCls" style="margin-left: 6px">
                    {{ it.level }}
                    <span v-if="it.chgStr" class="lvl-chg" :class="it.chgCls">{{ it.chgStr }}</span>
                  </span>
                </span>
                <span class="dim-v">{{ it.value }}</span>
              </div>
              <div class="dim-bar">
                <div class="dim-fill" :style="{ width: String(it.bar ?? 0) + '%', background: (it.kind === 'risk') ? riskColor(it.bar ?? 0) : heatColor(it.bar ?? 0) }"></div>
              </div>
              <div class="dim-mini">
                <span class="dim-chip" v-if="it.vs">{{ it.vs }}</span>
                <code v-if="it.trendHtml" v-html="'趋势：' + it.trendHtml"></code>
              </div>
            </div>
          </div>
        </details>
      </div>

      <div class="action-advisor" v-if="marketData.actionAdvisor && marketData.actionAdvisor.action_line">
        <div class="aa-line1">
          <div class="txt">{{ marketData.actionAdvisor.summary || marketData.actionAdvisor.action_line }}</div>
          <div class="aa-pill">{{ marketData.actionAdvisor.posture }}</div>
        </div>
        <div class="aa-evidences" v-if="marketData.actionAdvisor.evidences && marketData.actionAdvisor.evidences.length">
          <div class="aa-evidence" v-for="(x, i) in marketData.actionAdvisor.evidences" :key="'aae-'+i">
            <div class="icon">{{ x.icon }}</div>
            <div class="txt">{{ x.text }}</div>
          </div>
        </div>
        <div class="aa-tags" v-if="marketData.actionAdvisor.tags && marketData.actionAdvisor.tags.length">
          <span class="aa-tag" v-for="(t, i) in marketData.actionAdvisor.tags" :key="'aat-'+i">
            {{ t.key }}：{{ t.value }}
            <small v-if="t.detail">({{ t.detail }})</small>
          </span>
        </div>
      </div>
    </div>

    <div class="card" data-page="sentiment" id="sec-volume">
      <div class="card-header"><div class="card-title">市场全景 · 7日对比</div></div>

      <div class="section-header">7日对比总览</div>
      <div class="inset" v-if="marketData.marketOverview7d">
        <div class="ov7-head" v-if="(marketData.marketOverview7d.series || []).length">
          <div class="ov7-item" v-for="it in (marketData.marketOverview7d.series || []).slice(0, 4)" :key="'ov7-'+it.key">
            <div class="ek-row"><span class="k">{{ it.label }}</span><span class="v">{{ it.current }}</span></div>
            <div class="s">{{ it.note }}</div>
          </div>
        </div>
        <ul class="ov7-highlights" v-if="(marketData.marketOverview7d.highlights || []).length">
          <li v-for="(x, i) in (marketData.marketOverview7d.highlights || [])" :key="'ov7h-'+i">{{ x }}</li>
        </ul>
      </div>

      <div class="section-header">量能趋势</div>
      <div class="inset">
        <div class="inset-head">
          <div class="h">两市成交额</div>
          <div class="s">近 7 日 · 量能回流强弱</div>
        </div>
        <div ref="volumeChartRef" class="chart-container" style="margin-bottom: 0"></div>

        <div class="mc-panels">
          <div class="mc-panel" style="--mc-accent: rgba(239, 68, 68, 0.9)">
            <div class="mc-head">
              <div class="mc-title"><span class="dot"></span>承接</div>
              <div class="mc-pill">晋级/断板</div>
            </div>
            <div class="mc-items">
              <div class="mc-item" v-for="(card, idx) in moodCardsBy('carry')" :key="'mood-carry-'+idx">
                <div class="mc-left">
                  <div class="mc-k">{{ card.label }}</div>
                  <div class="mc-note">{{ card.note }}</div>
                </div>
                <div class="mc-v" :class="moodCardValueClass('carry', card)">{{ card.value }}</div>
              </div>
            </div>
          </div>

          <div class="mc-panel" style="--mc-accent: rgba(245, 158, 11, 0.92)">
            <div class="mc-head">
              <div class="mc-title"><span class="dot"></span>一致性</div>
              <div class="mc-pill">早封/资金</div>
            </div>
            <div class="mc-items">
              <div class="mc-item" v-for="(card, idx) in moodCardsBy('cons')" :key="'mood-cons-'+idx">
                <div class="mc-left">
                  <div class="mc-k">{{ card.label }}</div>
                  <div class="mc-note">{{ card.note }}</div>
                </div>
                <div class="mc-v" :class="moodCardValueClass('cons', card)">{{ card.value }}</div>
              </div>
            </div>
          </div>

          <div class="mc-panel" style="--mc-accent: rgba(16, 185, 129, 0.9)">
            <div class="mc-head">
              <div class="mc-title"><span class="dot"></span>风险</div>
              <div class="mc-pill">高度/拥挤</div>
            </div>
            <div class="mc-items">
              <div class="mc-item" v-for="(card, idx) in moodCardsBy('risk')" :key="'mood-risk-'+idx">
                <div class="mc-left">
                  <div class="mc-k">{{ card.label }}</div>
                  <div class="mc-note">{{ card.note }}</div>
                </div>
                <div class="mc-v" :class="moodCardValueClass('risk', card)">{{ card.value }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div id="sec-panorama"></div>
    <div class="card" data-page="sentiment" id="sec-thermo">
      <div class="card-header"><div class="card-title">结构拆解</div></div>

      <div id="sec-structure"></div>
      <div class="section-header" style="margin-top: 14px">结构拆解</div>
      <div style="color: var(--text-muted); font-weight: 800; font-size: 12px; margin-top: -2px">基础统计已在上方「市场全景 · 7日对比」展示；这里聚焦：空间、断层、分歧与风险。</div>

      <div class="engine-kpis" v-if="(marketData.structureV2?.summary || []).length" style="margin-top: 10px">
        <div class="engine-kpi" v-for="(c, i) in marketData.structureV2.summary" :key="'sv2-'+c.key+'-'+i">
          <div class="ek-row"><span class="k">{{ c.title }}</span><span class="v" :class="c.status==='good'?'red-text':(c.status==='warn'?'orange-text':'green-text')">{{ c.value }}</span></div>
          <div class="s">{{ c.note }}</div>
        </div>
      </div>

      <div class="evidence-chain" style="margin-top: 12px" v-if="marketData.structureV2?.evidence">
        <div class="evidence-chain-header">证据链</div>

        <div class="evidence-group">
          <div class="evidence-group-title">梯队与断层</div>
          <div class="evi-grid">
            <div class="evi-card compact">
              <div>
                <div class="evi-k">空间高度</div>
                <div class="evi-note">高度看空间，断层看接力是否顺畅</div>
              </div>
              <div class="evi-v">{{ marketData.structureV2.evidence.ladder?.maxHeight ?? '-' }} 板</div>
            </div>
            <div class="evi-card">
              <div>
                <div class="evi-k">断层</div>
                <div class="evi-note">2板/3板断层会直接破坏接力链路</div>
              </div>
              <div class="evi-v">{{ (marketData.structureV2.evidence.ladder?.gaps || []).length ? (marketData.structureV2.evidence.ladder.gaps.join('、') + '（板）') : '无' }}</div>
            </div>
          </div>
        </div>

        <div class="evidence-group" v-if="marketData.highPositionRisk">
          <div class="evidence-group-title">高位风险预警</div>
          <div class="evi-grid">
            <div class="evi-card">
              <div>
                <div class="evi-k">是否触发</div>
                <div class="evi-note">阈值：≥ {{ marketData.highPositionRisk.triggerHeight ?? 4 }} 板</div>
              </div>
              <div class="evi-v">{{ marketData.highPositionRisk.triggered ? '触发' : '未触发' }}</div>
            </div>
            <div class="evi-card">
              <div>
                <div class="evi-k">风险指数</div>
                <div class="evi-note">用于提示高位兑现/分化概率，避免和上面的空间高度重复</div>
              </div>
              <div class="evi-v">{{ marketData.highPositionRisk.score ?? 0 }}/100</div>
            </div>
          </div>
        </div>

        <div class="evidence-group" v-if="marketData.features?.mood_inputs">
          <div class="evidence-group-title">断板负反馈</div>
          <div class="evi-grid">
            <div class="evi-card compact">
              <div>
                <div class="evi-k">断板率 / 高位断板</div>
                <div class="evi-note">只统计昨日连板股今日断板后的负反馈强度</div>
              </div>
              <div class="evi-v">
                {{ marketData.features.mood_inputs?.broken_lb_rate_adj ?? marketData.features.mood_inputs?.broken_lb_rate ?? '-' }}% · {{ marketData.features.mood_inputs?.duanban_high_count ?? 0 }}只高位断板
              </div>
            </div>
            <div class="evi-card compact">
              <div>
                <div class="evi-k">代表股杀伤</div>
                <div class="evi-note">看高点到低点/收盘的回撤，判断负反馈力度</div>
              </div>
              <div class="evi-v">
                {{ marketData.features.mood_inputs?.duanban_worst_name || '—' }} {{ marketData.features.mood_inputs?.duanban_worst_lb || '-' }}板 · 高低点{{ marketData.features.mood_inputs?.duanban_max_drop_hl ?? '-' }}%
              </div>
            </div>
          </div>
        </div>

        <div class="evidence-group">
          <div class="evidence-group-title">主线分歧重叠</div>
          <div class="evi-grid">
            <div class="evi-card compact">
              <div>
                <div class="evi-k">主线（涨停）与主杀（炸板）重叠度</div>
                <div class="evi-note">越高越提示：主线在分歧/退潮</div>
              </div>
              <div class="evi-v">{{ marketData.structureV2.evidence.overlap?.score ?? '-' }}</div>
            </div>
            <div class="evi-card">
              <div>
                <div class="evi-k">重叠题材</div>
                <div class="evi-note">仅作提示，不等同结论</div>
              </div>
              <div class="evi-v">{{ (marketData.structureV2.evidence.overlap?.themes || []).join(' / ') || '-' }}</div>
            </div>
          </div>
        </div>

        <div class="evidence-group" v-if="topZtTheme || topPlate || rotationInfo">
          <div class="evidence-group-title">板块·题材共振</div>
          <div class="evi-grid">
            <div class="evi-card compact" v-if="topZtTheme">
              <div>
                <div class="evi-k">主线题材</div>
                <div class="evi-note">涨停题材抱团强度 · 集中度越高越认主线</div>
              </div>
              <div class="evi-v">
                {{ topZtTheme.name }}
                <small style="font-weight: 700; color: var(--text-muted)">· {{ topZtTheme.count }}只 / 占 {{ topZtConcRatio }}%</small>
                <span class="lvl-badge" :class="concRatioCls === 'red-text' ? 'high' : concRatioCls === 'orange-text' ? 'mid' : 'low'" style="margin-left: 6px">{{ concRatioLabel }}</span>
              </div>
            </div>
            <div class="evi-card compact" v-if="topPlate">
              <div>
                <div class="evi-k">强势板块</div>
                <div class="evi-note">价格端是否同步：板块强度 TOP1 + 领涨龙头</div>
              </div>
              <div class="evi-v">
                {{ topPlate.name }}
                <small style="font-weight: 700; color: var(--text-muted)">· 强度 {{ Math.round(Number(topPlate.strength || 0)) }} · 领涨 {{ topPlate.lead || '-' }}</small>
              </div>
            </div>
            <div class="evi-card compact" v-if="rotationInfo">
              <div>
                <div class="evi-k">风格定调</div>
                <div class="evi-note">高位占比反映拥挤，辅助判断接力 vs 试错</div>
              </div>
              <div class="evi-v">
                {{ rotationInfo.style || '-' }}
                <small v-if="rotationInfo.highLevelRatio !== undefined && rotationInfo.highLevelRatio !== null" style="font-weight: 700; color: var(--text-muted)">· 高位占比 {{ Number(rotationInfo.highLevelRatio || 0).toFixed(1) }}%</small>
              </div>
            </div>
            <div class="evi-card compact" v-if="narrativeOverview">
              <div>
                <div class="evi-k">narrative 共振</div>
                <div class="evi-note">热点 + 明日题材的活数据</div>
              </div>
              <div class="evi-v">
                <span v-if="narrativeOverview.hit" class="red-text">{{ narrativeOverview.topZtName }} 命中 {{ narrativeOverview.sources.join('/') }}</span>
                <span v-else-if="narrativeOverview.topZtName" class="orange-text">{{ narrativeOverview.topZtName }} 未在 narrative 榜上</span>
                <span v-else>-</span>
                <small style="margin-left: 6px; font-weight: 700; color: var(--text-muted)">
                  · {{ narrativeOverview.xgbCnt }} · {{ narrativeOverview.tmrHot }}/{{ narrativeOverview.tmrAll }}
                </small>
              </div>
            </div>
            <div class="evi-card compact" v-if="narrativeCoverage">
              <div>
                <div class="evi-k">涨停×热点 narrative 覆盖率</div>
                <div class="evi-note">涨停股题材落在选股宝热点上的比例 · 反映"叙事 ↔ 价格"是否同向</div>
              </div>
              <div class="evi-v" :class="narrativeCoverage.cls">
                {{ narrativeCoverage.hit }}/{{ narrativeCoverage.total }} · {{ narrativeCoverage.ratio }}%
                <small style="margin-left: 6px; font-weight: 700; color: var(--text-muted)">{{ narrativeCoverage.verdict }}</small>
                <div v-if="narrativeHitNames" style="margin-top: 4px; font-size: 11px; font-weight: 700; color: var(--text-muted)">命中：{{ narrativeHitNames }}</div>
              </div>
            </div>
            <div class="evi-card compact">
              <div>
                <div class="evi-k">共振判定</div>
                <div class="evi-note">主线集中度 × 风格 × 重叠度 × narrative,给情绪因子一层旁证</div>
              </div>
              <div class="evi-v" :class="resonanceVerdict.cls">{{ resonanceVerdict.text }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <ShortReminderFooter />
  </div>
</template>

<style scoped src="./SentimentPage.css"></style>
