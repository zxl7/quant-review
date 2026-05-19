<script setup lang="ts">
defineProps<{
  marketData: any
  modeView: 'review' | 'intraday'
  marketToneClass: string
  badgeIcon: string
  heroCycleText: string
  heroDateText: string
  heroUpdatedAt: string
  heatClass: (v: unknown) => string
  riskClass: (v: unknown) => string
  ringStyle: (val: unknown, r: number, kind?: string) => Record<string, string>
  sparklinePoints: (arr: unknown[]) => string
  indexChgClass: (chg?: string) => string
  indexCardToneClass: (chg?: string) => string
  indexChgIcon: (chg?: string) => string
}>()

const emit = defineEmits<{
  (e: 'set-mode', mode: 'review' | 'intraday'): void
}>()
</script>

<template>
  <header class="hero">
    <div class="hero-grain" aria-hidden="true"></div>
    <div class="hero-controls">
      <div class="view-switch" role="tablist" aria-label="视图模式">
        <button class="view-switch-btn" :class="{ active: modeView === 'review' }" type="button" @click="emit('set-mode', 'review')">复盘</button>
        <button class="view-switch-btn" :class="{ active: modeView === 'intraday' }" type="button" @click="emit('set-mode', 'intraday')">盘中</button>
      </div>
    </div>
    <div class="hero-grid">
      <div class="hero-top">
        <div class="cycle-tag mood-badge" :class="'mood-' + marketToneClass">
          <span class="badge-icon">{{ badgeIcon }}</span>
          <span>{{ heroCycleText }}</span>
        </div>
        <div class="hero-date">{{ heroDateText }}</div>
        <div class="hero-subtitle">
          公众号：风中一刀的主升浪
          <span class="sep">丨</span>
          <span class="meta">更新时间 {{ heroUpdatedAt }}</span>
        </div>
      </div>

      <div class="hero-panel">
        <div class="hero-panel-title">
          <span>今日概览</span>
          <span style="opacity: 0.78; font-weight: 900">{{ marketData.mood?.score ?? '-' }} 分</span>
        </div>
        <div class="hero-panel-sub">一眼看清：阶段 · 热/险 · 量能 · 高度</div>
        <div class="hero-kpi-grid">
          <div class="hero-kpi">
            <div class="k">情绪阶段</div>
            <div class="v">{{ marketData.moodStage?.title || '-' }}</div>
            <div class="s">总分 {{ marketData.mood?.score ?? '-' }} · {{ marketData.moodStage?.type || '-' }}</div>
          </div>
          <div class="hero-kpi">
            <div class="k">热 / 险</div>
            <div class="ring-pack">
              <svg class="ring" viewBox="0 0 60 60" aria-hidden="true">
                <circle class="track" cx="30" cy="30" r="22"></circle>
                <circle class="arc heat" cx="30" cy="30" r="22" :style="ringStyle(marketData.mood?.heat, 22, 'heat')"></circle>
                <circle class="track" cx="30" cy="30" r="16" style="stroke-width: 5"></circle>
                <circle class="arc risk" cx="30" cy="30" r="16" style="stroke-width: 5" :style="ringStyle(marketData.mood?.risk, 16, 'risk')"></circle>
              </svg>
              <div class="ring-center">
                <div class="big">
                  <span :class="heatClass(marketData.mood?.heat)">{{ marketData.mood?.heat ?? '-' }}</span>
                  /
                  <span :class="riskClass(marketData.mood?.risk)">{{ marketData.mood?.risk ?? '-' }}</span>
                </div>
                <div class="small">综合 {{ marketData.mood?.score ?? '-' }} 分</div>
              </div>
            </div>
          </div>
          <div class="hero-kpi">
            <div class="k">量能（较昨）</div>
            <div class="v">{{ marketData.volume?.change ?? '-' }}</div>
            <div class="s">两市 {{ marketData.volume?.total ?? '-' }}</div>
            <svg class="spark mini" viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true" v-if="(marketData.volume?.values || []).length >= 2">
              <path class="grid" d="M0 27H100" />
              <polyline class="line" :stroke="'rgba(255,255,255,0.78)'" :points="sparklinePoints(marketData.volume?.values || [])" />
            </svg>
          </div>
          <div class="hero-kpi">
            <div class="k">高度 / 质量</div>
            <div class="v">{{ marketData.ladder?.[0]?.badge ?? '-' }} 板</div>
            <div class="s">
              封板 {{ marketData.panorama?.ratio ?? '-' }} · 晋级
              {{ (marketData.features?.mood_inputs?.jj_rate === undefined || marketData.features?.mood_inputs?.jj_rate === null) ? '-' : Number(marketData.features.mood_inputs.jj_rate).toFixed(1) + '%' }}
            </div>
            <svg class="spark mini" viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true" v-if="(marketData.heightTrend?.main || []).length >= 2">
              <path class="grid" d="M0 27H100" />
              <polyline class="line" :stroke="'rgba(255,255,255,0.78)'" :points="sparklinePoints(marketData.heightTrend?.main || [])" />
            </svg>
          </div>
        </div>
      </div>
    </div>
    <div class="index-strip" role="group" aria-label="三大指数">
      <div v-for="(idx, i) in marketData.indices" :key="i" :class="['index-item', indexCardToneClass(idx.chg)]">
        <div class="index-row">
          <div class="index-name">{{ idx.name }}</div>
          <div class="index-val" :class="indexChgClass(idx.chg)">{{ idx.val }}</div>
          <div class="index-pct" :class="indexChgClass(idx.chg)">{{ indexChgIcon(idx.chg) }} {{ idx.chg }}</div>
        </div>
      </div>
    </div>
  </header>
</template>
