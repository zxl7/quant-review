<script setup lang="ts">
import { heatColor, riskColor, useSentimentView } from "./useSentimentView"

const { marketData, marketToneClass } = useSentimentView()
</script>

<template>
  <div class="page-block summarybar" :class="'mood-' + marketToneClass" data-page="sentiment">
    <div class="thermo-mini">
      <div class="thermo-mini-head">
        <div class="thermo-mini-title">情绪温度</div>
        <div class="thermo-mini-meta">综合 {{ marketData.mood?.score ?? "-" }} / 短线 {{ marketData.mood?.short_score ?? "-" }} / 大盘 {{ marketData.mood?.market_score ?? "-" }}</div>
      </div>

      <div class="thermo-mini-rows">
        <div class="thermo-mini-row">
          <span class="thermo-mini-label">短线热度</span>
          <div class="insight-meter" style="margin-top: 0">
            <div class="insight-meter-fill" :style="{ width: String(marketData.mood?.heat ?? 0) + '%', background: heatColor(marketData.mood?.heat ?? 0) }"></div>
          </div>
          <span class="val">{{ marketData.mood?.heat ?? "-" }}</span>
        </div>
        <div class="thermo-mini-row">
          <span class="thermo-mini-label">短线风险</span>
          <div class="insight-meter" style="margin-top: 0">
            <div class="insight-meter-fill" :style="{ width: String(marketData.mood?.risk ?? 0) + '%', background: riskColor(marketData.mood?.risk ?? 0) }"></div>
          </div>
          <span class="val">{{ marketData.mood?.risk ?? "-" }}</span>
        </div>
        <div class="thermo-mini-row">
          <span class="thermo-mini-label">大盘强弱</span>
          <div class="insight-meter" style="margin-top: 0">
            <div class="insight-meter-fill" :style="{ width: String(marketData.mood?.market_score ?? 0) + '%', background: heatColor(marketData.mood?.market_score ?? 0) }"></div>
          </div>
          <span class="val">{{ marketData.mood?.market_score ?? "-" }}</span>
        </div>
      </div>

      <div class="thermo-mini-meta" style="margin-top: 8px">
        {{ marketData.mood?.market_label || "-" }}
        · 指数 {{ marketData.mood?.market_components?.index_score ?? "-" }} / 广度 {{ marketData.mood?.market_components?.breadth_score ?? "-" }} / 量能
        {{ marketData.mood?.market_components?.volume_score ?? "-" }}
      </div>

      <div class="dim-grid" style="margin-top: 10px">
        <div class="dim-item" v-for="it in marketData.sentimentExplainDims || []" :key="'txb-' + it.key">
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
            <div class="dim-fill" :style="{ width: String(it.bar ?? 0) + '%', background: it.kind === 'risk' ? riskColor(it.bar ?? 0) : heatColor(it.bar ?? 0) }"></div>
          </div>
          <div class="dim-mini">
            <span class="dim-chip" v-if="it.vs">{{ it.vs }}</span>
            <code v-if="it.trendHtml" v-html="'趋势：' + it.trendHtml"></code>
          </div>
        </div>
      </div>
    </div>

    <div class="action-advisor" v-if="marketData.actionAdvisor && marketData.actionAdvisor.action_line">
      <div class="aa-line1">
        <div class="txt">{{ marketData.actionAdvisor.summary || marketData.actionAdvisor.action_line }}</div>
        <div class="aa-pill">{{ marketData.actionAdvisor.posture }}</div>
      </div>
      <div class="aa-evidences" v-if="marketData.actionAdvisor.evidences && marketData.actionAdvisor.evidences.length">
        <div class="aa-evidence" v-for="(x, i) in marketData.actionAdvisor.evidences" :key="'aae-' + i">
          <div class="icon">{{ x.icon }}</div>
          <div class="txt">{{ x.text }}</div>
        </div>
      </div>
      <div class="aa-tags" v-if="marketData.actionAdvisor.tags && marketData.actionAdvisor.tags.length">
        <span class="aa-tag" v-for="(t, i) in marketData.actionAdvisor.tags" :key="'aat-' + i">
          {{ t.key }}：{{ t.value }}
          <small v-if="t.detail">({{ t.detail }})</small>
        </span>
      </div>
    </div>
  </div>
</template>
