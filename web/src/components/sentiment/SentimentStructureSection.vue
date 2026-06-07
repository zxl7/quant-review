<script setup lang="ts">
import { computed } from 'vue';
import { useSentimentView } from './useSentimentView';

const {
  marketData,
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
} = useSentimentView();

const structureSummary = computed<any[]>(() => (Array.isArray(marketData.value?.structureV2?.summary) ? marketData.value.structureV2.summary : []));
const structureEvidence = computed<any>(() => marketData.value?.structureV2?.evidence || null);
</script>

<template>
  <div id="sec-panorama"></div>
  <div class="card" data-page="sentiment" id="sec-thermo">
    <div class="card-header"><div class="card-title">结构拆解</div></div>

    <div id="sec-structure"></div>
    <div class="section-header" style="margin-top: 14px">结构拆解</div>
    <div style="color: var(--text-muted); font-weight: 800; font-size: 12px; margin-top: -2px">基础统计已在上方「市场全景 · 7日对比」展示；这里聚焦：空间、断层、分歧与风险。</div>

    <div class="engine-kpis" v-if="structureSummary.length" style="margin-top: 10px">
      <div class="engine-kpi" v-for="(c, i) in structureSummary" :key="'sv2-'+c.key+'-'+i">
        <div class="ek-row"><span class="k">{{ c.title }}</span><span class="v" :class="c.status==='good'?'red-text':(c.status==='warn'?'orange-text':'green-text')">{{ c.value }}</span></div>
        <div class="s">{{ c.note }}</div>
      </div>
    </div>

    <div class="evidence-chain" style="margin-top: 12px" v-if="structureEvidence">
      <div class="evidence-chain-header">证据链</div>

      <div class="evidence-group">
        <div class="evidence-group-title">梯队与断层</div>
        <div class="evi-grid">
          <div class="evi-card compact">
            <div>
              <div class="evi-k">空间高度</div>
              <div class="evi-note">高度看空间，断层看接力是否顺畅</div>
            </div>
            <div class="evi-v">{{ structureEvidence.ladder?.maxHeight ?? '-' }} 板</div>
          </div>
          <div class="evi-card">
            <div>
              <div class="evi-k">断层</div>
              <div class="evi-note">2板/3板断层会直接破坏接力链路</div>
            </div>
            <div class="evi-v">{{ (structureEvidence.ladder?.gaps || []).length ? (structureEvidence.ladder.gaps.join('、') + '（板）') : '无' }}</div>
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
            <div class="evi-v">{{ structureEvidence.overlap?.score ?? '-' }}</div>
          </div>
          <div class="evi-card">
            <div>
              <div class="evi-k">重叠题材</div>
              <div class="evi-note">仅作提示，不等同结论</div>
            </div>
            <div class="evi-v">{{ (structureEvidence.overlap?.themes || []).join(' / ') || '-' }}</div>
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
              <span class="lvl-badge" :class="concRatioBadgeClass" style="margin-left: 6px">{{ concRatioLabel }}</span>
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
</template>
