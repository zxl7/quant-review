<script setup lang="ts">
import { computed } from 'vue';
import { useMarketData } from '../../composables/useMarketData';
import ShortReminderFooter from '../common/ShortReminderFooter.vue';

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

const formatPosition = (v: unknown) => {
  if (v === undefined || v === null || v === '') return '-';
  if (typeof v === 'number') return `${Math.round(v * 100)}%`;
  return String(v);
};

const planGuide = computed(() => marketData.value?.planGuide || null);
const planGuidePills = computed(() => {
  const g = planGuide.value;
  if (!g) return [];
  return [
    { text: `右侧：${g.rightsideText || '-'}`, primary: true },
    ...(g.mainline ? [{ text: `主线：${g.mainline}`, primary: false }] : []),
    ...(g.nature ? [{ text: `性质：${g.nature}`, primary: false }] : []),
    ...(g.resonance ? [{ text: `共振：${g.resonance}`, primary: false }] : []),
  ];
});
const planGuideWarnings = computed(() => Array.isArray(planGuide.value?.warnings) ? planGuide.value?.warnings : []);

const planFocusChips = computed(() => {
  const raw = String(marketData.value?.actionGuideV2?.meta?.title || '').replace(/^🧩\s*/, '');
  if (!raw) return [];
  const alias: Record<string, string> = {
    盘面基调: '基调',
    主线: '主线',
    模式: '模式',
    仓位: '姿态',
  };
  return raw
    .split('｜')
    .map((seg) => {
      const [k, ...rest] = String(seg || '').split('：');
      const v = rest.join('：').trim();
      if (!k || !v) return null;
      return { k: alias[k.trim()] || k.trim(), v };
    })
    .filter(Boolean) as Array<{ k: string; v: string }>;
});
const planFocusNote = computed(() => String(marketData.value?.actionGuideV2?.meta?.detail || marketData.value?.actionAdvisor?.summary || '').trim());
const planFocusEvidences = computed(() => {
  const rows = Array.isArray(marketData.value?.actionAdvisor?.evidences) ? marketData.value.actionAdvisor.evidences : [];
  return rows.slice(0, 3);
});

const positionAdvice = computed(() => {
  const finalPosition = formatPosition(marketData.value?.planGuide?.position);
  if (finalPosition && finalPosition !== '-') {
    const rightside = String(marketData.value?.planGuide?.rightsideText || '');
    const stance = rightside === '禁止' ? '防守' : rightside === '允许' ? '进攻' : '均衡';
    const cls = stance === '进攻' ? 'pos-attack' : stance === '防守' ? 'pos-def' : 'pos-balance';
    const pillCls = stance === '进攻' ? 'attack' : stance === '防守' ? 'def' : 'balance';
    return { stance, range: finalPosition, note: '', cls, pillCls };
  }
  const heat = Number(marketData.value?.mood?.heat ?? 0);
  const risk = Number(marketData.value?.mood?.risk ?? 0);
  const stage = String(marketData.value?.moodStage?.type || '');
  let stance = '均衡';
  let range = '35–50%';
  let note = '围绕主线核心，低位试错为主；不追高位一致。';
  if (stage === 'fire') {
    stance = '防守';
    range = '15–30%';
    note = '退潮/冰点：只做低位试错，回避高位接力；优先看修复信号。';
  } else if (risk >= heat + 10) {
    stance = '防守';
    range = '20–35%';
    note = '风险压过热度：轻仓、分散、快进快出；等确定性再加仓。';
  } else if (heat >= risk + 10) {
    stance = '进攻';
    range = '50–70%';
    note = '热度占优：围绕主线核心与确认节点加仓；不做无辨识度扩散。';
  }
  const cls = stance === '进攻' ? 'pos-attack' : stance === '防守' ? 'pos-def' : 'pos-balance';
  const pillCls = stance === '进攻' ? 'attack' : stance === '防守' ? 'def' : 'balance';
  return { stance, range, note, cls, pillCls };
});

const ztRelaySorted = computed(() => (marketData.value?.ztAnalysis?.relay || []).slice());
const ztWatchSorted = computed(() => (marketData.value?.ztAnalysis?.watch || []).slice());

const ztTagRows = (row: any) => Array.isArray(row?.tagRows) ? row.tagRows : [];
</script>

<template>
  <div class="plan-page">
    <div class="card" data-page="plan" id="sec-action">
      <div class="card-title">明日行动指南</div>
      <div class="plan-top-grid">
        <div class="plan-main-stack">
          <div class="v2-strategy" v-if="planGuide">
            <div class="row">
              <div class="head-main">
                <div class="tone">{{ planGuide.phase || '-' }}</div>
                <span class="plan-score-badge">情绪 <strong>{{ planGuide.score ?? '-' }}</strong></span>
              </div>
              <div class="cap">仓位上限：{{ formatPosition(planGuide.position) }}</div>
            </div>
            <div class="advice" :class="planGuide.rightsideText === '禁止' ? 'danger' : (planGuide.rightsideText === '允许' ? '' : 'warn')" v-if="planGuide.advice">{{ planGuide.advice }}</div>
            <div class="kpis">
              <span v-for="(pill, idx) in planGuidePills" :key="'pg-pill-'+idx" class="pill" :class="{ primary: pill.primary }">{{ pill.text }}</span>
            </div>
            <details v-if="planGuideWarnings.length">
              <summary>展开提示</summary>
              <ul class="rules">
                <li v-for="(r, i) in planGuideWarnings" :key="'c-w-'+i">{{ r }}</li>
              </ul>
            </details>
          </div>
          <div class="pos-card" v-if="marketData.mood">
            <div class="pos-left">
              <span class="pos-k">最终仓位上限：</span>
              <span class="pos-v" :class="positionAdvice.cls">{{ positionAdvice.range }}</span>
              <div class="pos-sub">{{ positionAdvice.note }}</div>
            </div>
            <div class="pos-tags">
              <span class="pos-pill" :class="positionAdvice.pillCls">{{ positionAdvice.stance }}</span>
              <span class="pos-pill">热{{ marketData.mood?.heat ?? '-' }}/险{{ marketData.mood?.risk ?? '-' }}</span>
              <span class="pos-pill">{{ marketData.moodStage?.title || '-' }}</span>
            </div>
          </div>
        </div>
        <div class="plan-side-stack">
          <div class="plan-focus-card" v-if="planFocusChips.length || planFocusNote || planFocusEvidences.length">
            <div class="plan-focus-head">
              <div class="plan-focus-title">盘面聚焦</div>
              <div class="plan-focus-posture" v-if="marketData.actionAdvisor">{{ marketData.actionAdvisor.posture }}</div>
            </div>
            <div class="plan-focus-chips" v-if="planFocusChips.length">
              <span class="plan-focus-chip" v-for="(chip, idx) in planFocusChips" :key="'pfc-'+idx">
                <em>{{ chip.k }}</em>
                <strong>{{ chip.v }}</strong>
              </span>
            </div>
            <div class="plan-focus-note" v-if="planFocusNote">{{ planFocusNote }}</div>
            <div class="plan-focus-evidences" v-if="planFocusEvidences.length">
              <span class="plan-focus-evidence" v-for="(x, i) in planFocusEvidences" :key="'pfe-'+i">
                <span class="icon">{{ x.icon }}</span>
                <span>{{ x.text }}</span>
              </span>
            </div>
          </div>
        </div>
      </div>
      <div class="summary3" v-if="marketData.summary3?.lines && marketData.summary3.lines.length">
        <div class="summary3-line" v-for="(l, i) in marketData.summary3.lines" :key="'plan-s3-'+i"><strong>{{ i+1 }}.</strong> {{ l }}</div>
      </div>
    </div>

    <div class="card" data-page="plan" id="sec-zt-analysis">
      <div class="card-header">
        <div>
          <div class="card-title">涨停数据分析（明日接力 / 观察）</div>
          <div style="margin-top: 6px; font-size: 12px; color: var(--text-muted); font-weight: 750">
            梯队板块（≥3只涨停）：
            <span class="blue-text" style="font-weight: 900">{{ marketData.ztAnalysis?.meta?.tierThemeCount ?? '-' }}</span>
            <span v-if="marketData.ztAnalysis?.meta?.tierThemeTop">｜TOP：{{ marketData.ztAnalysis?.meta?.tierThemeTop }}</span>
            <span style="margin-left: 10px">
              ｜涨停池
              <span class="orange-text" style="font-weight: 900">{{ marketData.ztgc?.length ?? 0 }}</span>
              只 ｜题材映射
              <span class="orange-text" style="font-weight: 900">{{ marketData.zt_code_themes ? Object.keys(marketData.zt_code_themes).length : 0 }}</span>
              只
            </span>
          </div>
        </div>
        <div class="card-badge">封单 · 板块归属 · 量能 · 炸板 · 梯队</div>
      </div>
      <div class="zt-panel">
        <div class="zt-col">
          <div class="section-header">接力候选</div>
          <div class="zt-list">
            <div class="zt-item" v-for="(row, i) in ztRelaySorted" :key="'relay-'+i">
              <div class="zt-top">
                <div>
                  <div class="zt-name">
                    <a v-if="row.code" class="stock-link" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
                    <span v-else>{{ row.name }}</span>
                  </div>
                  <div class="zt-sub" v-html="row.reason"></div>
                </div>
                <div class="zt-score" :class="row.superLeaderTone || ''" :title="row.factorHint || ''">
                  <div class="v">{{ row.factorScore ?? row.score }}</div>
                  <div class="k">{{ row.scoreLabel || '接力优先' }}</div>
                  <div class="g" v-if="row.scoreSubLabel">{{ row.scoreSubLabel }}</div>
                </div>
              </div>
              <div class="zt-tags">
                <div class="zt-tag-row" v-for="tagRow in ztTagRows(row)" :key="'relay-tag-row-'+i+'-'+tagRow.tone" :class="'zt-tag-row-' + tagRow.tone">
                  <span class="ladder-chip" v-for="(t, ti) in tagRow.tags" :key="'relay-tag-'+i+'-'+tagRow.tone+'-'+ti" :class="t.cls">{{ t.text }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="zt-col">
          <div class="section-header">观察池（大容量/前龙头，看情绪反馈）</div>
          <div class="zt-list">
            <div class="zt-item" v-for="(row, i) in ztWatchSorted" :key="'watch-'+i">
              <div class="zt-top">
                <div>
                  <div class="zt-name">
                    <a v-if="row.code" class="stock-link" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
                    <span v-else>{{ row.name }}</span>
                  </div>
                  <div class="zt-sub" v-html="row.reason"></div>
                </div>
                <div class="zt-score" :class="row.superLeaderTone || ''" :title="row.factorHint || ''">
                  <div class="v">{{ row.factorScore ?? row.score }}</div>
                  <div class="k">{{ row.scoreLabel || row.watchGroup || '观察参考' }}</div>
                  <div class="g" v-if="row.scoreSubLabel || row.watchGroup">{{ row.scoreSubLabel || row.watchGroup }}</div>
                </div>
              </div>
              <div class="zt-tags">
                <div class="zt-tag-row" v-for="tagRow in ztTagRows(row)" :key="'watch-tag-row-'+i+'-'+tagRow.tone" :class="'zt-tag-row-' + tagRow.tone">
                  <span class="ladder-chip" v-for="(t, ti) in tagRow.tags" :key="'watch-tag-'+i+'-'+tagRow.tone+'-'+ti" :class="t.cls">{{ t.text }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="summary-box" v-if="!marketData.ztgc || !marketData.ztgc.length">
        <div class="summary-text">未注入当日涨停池明细（ztgc）。请用渲染脚本从 pools_cache.json 注入后再查看本模块。</div>
      </div>
      <div class="summary-box" v-else-if="!((marketData.ztAnalysis?.relay || []).length || (marketData.ztAnalysis?.watch || []).length)">
        <div class="summary-text">涨停分析暂未生成，请检查涨停池、题材映射或前端派生逻辑。</div>
      </div>
    </div>

    <ShortReminderFooter />
  </div>
</template>
