<script setup lang="ts">
import { computed, ref } from 'vue';
import { useMarketData } from '../../composables/useMarketData';
import ShortReminderFooter from '../common/ShortReminderFooter.vue';

const { marketData } = useMarketData();

const selectedPlateThemeKey = ref('');

const toNum = (v: unknown, d = 0) => {
  if (v === undefined || v === null || v === '') return d;
  if (typeof v === 'string') return Number(v.replace('%', '').replace('亿', '').trim()) || d;
  const n = Number(v);
  return Number.isFinite(n) ? n : d;
};

const clamp100 = (v: unknown) => {
  const n = Number(v);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
};

const signedClass = (v?: string | number | null) => {
  const n = Number(String(v ?? '').replace('%', ''));
  if (Number.isNaN(n)) return '';
  if (n > 0) return 'red-text';
  if (n < 0) return 'green-text';
  return 'orange-text';
};

const formatSigned = (val: unknown, unit = '') => {
  const n = Number(val);
  if (!Number.isFinite(n)) return '-';
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}${unit}`;
};

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

const linePath = (series: unknown[], w = 300, h = 80, pad = 8) => {
  const vals = (Array.isArray(series) ? series : []).map((v) => toNum(v, 0));
  if (!vals.length) return { line: '', area: '' };
  if (vals.length === 1) {
    const y = h - pad;
    return {
      line: `M ${pad} ${y} L ${w - pad} ${y}`,
      area: `M ${pad} ${h - pad} L ${pad} ${y} L ${w - pad} ${y} L ${w - pad} ${h - pad} Z`,
    };
  }
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const points = vals.map((v, i) => {
    const x = pad + (i / Math.max(vals.length - 1, 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / span) * (h - pad * 2);
    return { x, y };
  });
  const line = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(' ');
  const area = `${line} L ${points[points.length - 1].x.toFixed(2)} ${(h - pad).toFixed(2)} L ${points[0].x.toFixed(2)} ${(h - pad).toFixed(2)} Z`;
  return { line, area };
};

const conceptTop10ByChg = computed(() => {
  const plateRows = Array.isArray(marketData.value?.plateRankTop10) ? [...marketData.value.plateRankTop10] : [];
  if (plateRows.length) {
    plateRows.sort((a, b) => toNum(b?.strength, -1e9) - toNum(a?.strength, -1e9));
    const maxStrength = Math.max(...plateRows.map((x) => toNum(x?.strength, 0)), 0);
    return plateRows.slice(0, 10).map((r) => ({
      ...r,
      displayValue: toNum(r?.strength, 0) > 0 ? String(Math.round(toNum(r?.strength, 0))) : '-',
      displayClass: r?.displayClass || 'red-text',
      barPct: maxStrength > 0 ? (toNum(r?.strength, 0) / maxStrength) * 100 : 0,
    }));
  }

  const rows = Array.isArray(marketData.value?.conceptFundFlowTop) ? [...marketData.value.conceptFundFlowTop] : [];
  rows.sort((a, b) => {
    const ac = toNum(a?.chg_pct, -1e9);
    const bc = toNum(b?.chg_pct, -1e9);
    if (bc !== ac) return bc - ac;
    const an = toNum(a?.net, -1e9);
    const bn = toNum(b?.net, -1e9);
    return bn - an;
  });
  return rows.slice(0, 10).map((r) => ({
    ...r,
    displayValue: r?.chg_pct === undefined || r?.chg_pct === null ? '-' : `${formatSigned(r.chg_pct)}%`,
    displayClass: signedClass(r?.chg_pct),
    barPct: toNum(r?.chg_pct, 0) * 10,
  }));
});

const selectedPlateTheme = computed(() => {
  const rows = conceptTop10ByChg.value || [];
  if (!rows.length) return null;
  const key = String(selectedPlateThemeKey.value || '');
  return rows.find((r) => String(r?.code || r?.name || '') === key) || rows[0];
});

const selectedPlateDetail = computed(() => {
  const row = selectedPlateTheme.value;
  if (!row) return null;
  const code = String(row?.code || '');
  const detailMap = marketData.value?.plateRotateDetailByCode || {};
  return code && detailMap && detailMap[code] ? detailMap[code] : null;
});

const selectedPlateLeaders = computed(() => {
  const row = selectedPlateTheme.value;
  if (!row) return [];
  return Array.isArray(row.leaders) ? row.leaders : [];
});

const selectedPlateStrengthSeries = computed(() => Array.isArray(selectedPlateDetail.value?.strengthSeries) ? selectedPlateDetail.value.strengthSeries : []);
const selectedPlateVolumeSeries = computed(() => Array.isArray(selectedPlateDetail.value?.volumeSeries) ? selectedPlateDetail.value.volumeSeries : []);
const selectedPlateStrengthLine = computed(() => linePath(selectedPlateStrengthSeries.value || []));
const selectedPlateVolumeLine = computed(() => linePath(selectedPlateVolumeSeries.value || []));
const selectedPlateStrengthPeak = computed(() => {
  const arr = (selectedPlateStrengthSeries.value || []).map((v) => toNum(v, 0));
  const max = Math.max(...arr, 0);
  return max > 0 ? Math.round(max) : '-';
});
const selectedPlateVolumePeak = computed(() => {
  const arr = (selectedPlateVolumeSeries.value || []).map((v) => toNum(v, 0));
  const max = Math.max(...arr, 0);
  return max > 0 ? `${Math.round(max)}亿` : '-';
});

const selectPlateTheme = (row: any) => {
  selectedPlateThemeKey.value = String(row?.code || row?.name || '');
};
</script>

<template>
  <div class="themes-page">
    <div class="card" data-page="themes" id="sec-hot">
      <div class="card-title">板块题材</div>

      <div class="tier-card" v-if="conceptTop10ByChg.length">
        <div class="tier-title">板块题材排行 TOP10（{{ (marketData.plateRotateTop || []).length ? '按强度' : '按涨幅' }}）</div>
        <div class="tier-desc" style="margin-top: 4px">
          {{ (marketData.plateRotateTop || []).length ? '口径：短线侠板块轮动；数字为当日板块强度。' : '口径：概念/题材级资金流向（AkShare/东财）；排序：按涨跌幅从高到低（净流仅作参考）。' }}
        </div>
        <div class="theme-tools">
          <a class="theme-open-btn" :href="'https://www.duanxianxia.com/web/platerotat'" target="_blank" rel="noopener noreferrer">打开短线侠板块轮动</a>
        </div>
        <div class="theme-rank-list">
          <div
            class="theme-rank-item"
            v-for="(c, i) in conceptTop10ByChg"
            :key="'cff-top10-'+c.name+'-'+i"
            :class="{ 'is-active': selectedPlateTheme && (selectedPlateTheme.code || selectedPlateTheme.name) === (c.code || c.name) }"
            @click="selectPlateTheme(c)">
            <div class="theme-rank-mid">
              <div class="theme-rank-name">{{ c.name }}</div>
              <div class="theme-rank-sub" v-if="c.lead || c.companies !== undefined || c.volume !== undefined || c.net !== undefined || c.sourceNote">
                <template v-if="c.lead">领涨 {{ c.lead }}</template>
                <template v-if="c.lead_chg_pct !== undefined && c.lead_chg_pct !== null">
                  <span class="sep">|</span>
                  <span :class="signedClass(c.lead_chg_pct)">{{ formatSigned(c.lead_chg_pct) }}%</span>
                </template>
                <template v-if="c.companies !== undefined && c.companies !== null">
                  <span class="sep">|</span>
                  成分 {{ c.companies }}
                </template>
                <template v-if="c.volume !== undefined && c.volume !== null && c.volume !== ''">
                  <span class="sep">|</span>
                  量能 {{ c.volume }}亿
                </template>
                <template v-if="c.net !== undefined && c.net !== null && !(marketData.plateRotateTop || []).length">
                  <span class="sep">|</span>
                  净额
                  <span :class="signedClass(c.net)">{{ formatSigned(c.net) }}</span>
                </template>
                <template v-if="c.sourceNote">
                  <span v-if="c.lead || c.companies !== undefined || c.volume !== undefined || c.net !== undefined" class="sep">|</span>
                  {{ c.sourceNote }}
                </template>
              </div>
            </div>
            <div class="theme-rank-right">
              <div class="theme-rank-chg" :class="c.displayClass || signedClass(c.chg_pct)">{{ c.displayValue }}</div>
              <div class="theme-rank-microbar" aria-hidden="true">
                <i :style="{ width: clamp100(toNum(c.barPct, 0)) + '%' }"></i>
              </div>
            </div>
          </div>
        </div>

        <div class="theme-detail-card" v-if="(marketData.plateRotateTop || []).length && selectedPlateTheme">
          <div class="theme-detail-head">
            <div>
              <div class="theme-detail-title">{{ selectedPlateTheme.name }}</div>
              <div class="theme-detail-sub">当前查看：板块轮动明细。点击上方排行可切换领涨龙头与近20日强度/量能。</div>
            </div>
            <div class="theme-detail-kpis">
              <div class="theme-detail-kpi">
                <div class="k">当日强度</div>
                <div class="v">{{ selectedPlateTheme.displayValue || '-' }}</div>
              </div>
              <div class="theme-detail-kpi">
                <div class="k">当日领涨</div>
                <div class="v" style="font-size: 14px">{{ selectedPlateTheme.lead || '-' }}</div>
              </div>
              <div class="theme-detail-kpi">
                <div class="k">当日量能</div>
                <div class="v">{{ selectedPlateTheme.volume !== undefined && selectedPlateTheme.volume !== null ? (selectedPlateTheme.volume + '亿') : '-' }}</div>
              </div>
            </div>
          </div>

          <div class="theme-detail-grid">
            <div class="theme-detail-panel">
              <div class="hd">当日领涨龙头</div>
              <div class="theme-leader-list">
                <a
                  class="theme-leader-chip"
                  v-for="(x, idx) in selectedPlateLeaders"
                  :key="'plate-leader-'+(x.code||x.name||idx)+'-'+idx"
                  :href="xqUrl(x.code)"
                  target="_blank"
                  rel="noopener noreferrer">
                  <span class="rk">{{ x.rank || ('龙' + (idx + 1)) }}</span>
                  <span class="nm">{{ x.name || '-' }}</span>
                </a>
                <div class="theme-leader-chip" v-if="!selectedPlateLeaders.length">
                  <span class="nm">当日无领涨</span>
                </div>
              </div>
            </div>

            <div class="theme-detail-panel">
              <div class="hd">近20日强度</div>
              <div class="theme-mini-chart">
                <div class="theme-mini-line" v-if="selectedPlateStrengthSeries.length">
                  <svg viewBox="0 0 300 80" preserveAspectRatio="none" aria-hidden="true">
                    <line class="theme-mini-axis" x1="0" y1="72" x2="300" y2="72"></line>
                    <path class="theme-mini-area strength" :d="selectedPlateStrengthLine.area"></path>
                    <path class="theme-mini-path strength" :d="selectedPlateStrengthLine.line"></path>
                  </svg>
                </div>
                <div class="theme-mini-meta">
                  <span>最新 <strong>{{ selectedPlateTheme.strengthByDate ?? selectedPlateTheme.strength ?? '-' }}</strong></span>
                  <span>峰值 <strong>{{ selectedPlateStrengthPeak }}</strong></span>
                </div>
              </div>
            </div>

            <div class="theme-detail-panel">
              <div class="hd">近20日量能</div>
              <div class="theme-mini-chart">
                <div class="theme-mini-line" v-if="selectedPlateVolumeSeries.length">
                  <svg viewBox="0 0 300 80" preserveAspectRatio="none" aria-hidden="true">
                    <line class="theme-mini-axis" x1="0" y1="72" x2="300" y2="72"></line>
                    <path class="theme-mini-area volume" :d="selectedPlateVolumeLine.area"></path>
                    <path class="theme-mini-path volume" :d="selectedPlateVolumeLine.line"></path>
                  </svg>
                </div>
                <div class="theme-mini-meta">
                  <span>最新 <strong>{{ selectedPlateTheme.volume !== undefined && selectedPlateTheme.volume !== null ? (selectedPlateTheme.volume + '亿') : '-' }}</strong></span>
                  <span>峰值 <strong>{{ selectedPlateVolumePeak }}</strong></span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="card" data-page="themes" id="sec-top10">
      <div class="card-title">成交额 TOP10</div>
      <table class="ladder-table">
        <thead>
          <tr>
            <th>#</th>
            <th>个股</th>
            <th>涨幅</th>
            <th>成交额</th>
            <th>板块</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in marketData.top10" :key="row.rank">
            <td><span :style="'color: var(--danger); font-weight: ' + row.weight">{{ row.rank }}</span></td>
            <td class="stock-name-cell">{{ row.mc }}</td>
            <td :class="row.pct_class">{{ row.zf_str }}</td>
            <td :style="'font-weight: ' + row.weight">{{ row.cje_yi }}</td>
            <td>{{ row.sector }}</td>
          </tr>
        </tbody>
      </table>
      <div style="margin-top: 10px; font-size: 12px; color: var(--text-muted)">
        TOP5合计：
        <strong style="color: var(--text-primary)">{{ marketData.top10Summary?.top5_sum_yi }}</strong>
        | {{ marketData.top10Summary?.top5_sectors }}
      </div>
    </div>

    <ShortReminderFooter />
  </div>
</template>
