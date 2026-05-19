<script setup lang="ts">
import { computed, ref } from 'vue';
import { useMarketData } from '../../composables/useMarketData';
import { useECharts } from '../../composables/useECharts';

const { marketData, marketToneClass } = useMarketData();

const heatColor = (v: number) => {
  const n = Number(v || 0);
  if (n <= 45) return '#f59e0b';
  if (n <= 70) return '#ff4d4f';
  return '#e60012';
};

const riskColor = (v: number) => {
  const n = Number(v || 0);
  if (n <= 45) return '#16a34a';
  if (n <= 75) return '#65a30d';
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
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { top: '12%', left: '3%', right: '3%', bottom: '12%', containLabel: true },
    xAxis: { type: 'category', data: data.dates, axisLabel: { color: '#64748b', fontWeight: 700, fontSize: 10 } },
    yAxis: { type: 'value', max: yMax, axisLabel: { color: '#64748b', fontWeight: 700, fontSize: 10 } },
    series: [
      { name: '两市成交额', type: 'bar', data: vals, barWidth: '42%' },
      { name: '成交趋势', type: 'line', data: vals, smooth: true, showSymbol: false, lineStyle: { width: 3, color: trendColor } },
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
        <div class="vol-strip">
          <div class="vol-pill">两市成交 <strong>{{ marketData.volume?.total ?? '-' }}</strong></div>
          <div class="vol-pill">增量 <strong>{{ marketData.volume?.increase ?? '-' }}</strong></div>
          <div class="vol-pill">较昨 <span :class="signedClass(marketData.volume?.change)"><strong>{{ marketData.volume?.change ?? '-' }}</strong></span></div>
        </div>

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
      </div>
    </div>
  </div>
</template>
