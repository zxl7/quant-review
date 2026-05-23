<script setup lang="ts">
import { computed } from "vue"

const props = defineProps<{
  marketData: any
  modeView: "review" | "intraday"
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

const toNum = (v: unknown, d = 0) => {
  const n = Number(v)
  return Number.isFinite(n) ? n : d
}

const ringSegments = computed(() => {
  const radius = 22
  const circumference = 2 * Math.PI * radius
  const heat = Math.max(0, toNum(props.marketData?.mood?.heat, 0))
  const risk = Math.max(0, toNum(props.marketData?.mood?.risk, 0))
  const total = heat + risk
  if (!total) {
    return {
      heatStyle: {
        strokeDasharray: `0 ${circumference.toFixed(2)}`,
        strokeDashoffset: "0",
      },
      riskStyle: {
        strokeDasharray: `0 ${circumference.toFixed(2)}`,
        strokeDashoffset: "0",
      },
    }
  }
  const heatLen = circumference * (heat / total)
  const riskLen = circumference * (risk / total)
  return {
    heatStyle: {
      strokeDasharray: `${heatLen.toFixed(2)} ${circumference.toFixed(2)}`,
      strokeDashoffset: "0",
    },
    riskStyle: {
      strokeDasharray: `${riskLen.toFixed(2)} ${circumference.toFixed(2)}`,
      strokeDashoffset: `${(-heatLen).toFixed(2)}`,
    },
  }
})

const emit = defineEmits<{
  (e: "set-mode", mode: "review" | "intraday"): void
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
          <span style="opacity: 0.78; font-weight: 900">{{ marketData.mood?.score ?? "-" }} 分</span>
        </div>
        <div class="hero-panel-sub">一眼看清：阶段 · 热/险 · 量能 · 高度</div>
        <div class="hero-kpi-grid">
          <div class="hero-kpi hero-kpi-stage">
            <div class="k">情绪阶段</div>
            <div class="v">{{ marketData.moodStage?.title || "-" }}</div>
            <div class="s">总分 {{ marketData.mood?.score ?? "-" }} · {{ marketData.moodStage?.type || "-" }}</div>
          </div>
          <div class="hero-kpi">
            <div class="ring-pack">
              <div class="ring-center hero-kpi-thermo">
                <div class="k">热 / 险</div>
                <div class="big">
                  <span :class="heatClass(marketData.mood?.heat)">{{ marketData.mood?.heat ?? "-" }}</span>
                  /
                  <span :class="riskClass(marketData.mood?.risk)">{{ marketData.mood?.risk ?? "-" }}</span>
                </div>
                <div class="small">综合 {{ marketData.mood?.score ?? "-" }} 分</div>
              </div>
              <svg class="ring ring-dual" viewBox="0 0 60 60" aria-hidden="true">
                <circle class="track outer" cx="30" cy="30" r="22"></circle>
                <circle class="arc heat outer" cx="30" cy="30" r="22" :style="ringStyle(marketData.mood?.heat, 22, 'heat')"></circle>
                <circle class="track inner" cx="30" cy="30" r="16"></circle>
                <circle class="arc risk inner" cx="30" cy="30" r="16" :style="ringStyle(marketData.mood?.risk, 16, 'risk')"></circle>
              </svg>
            </div>
          </div>
          <div class="hero-kpi hero-kpi-balanced">
            <div class="k">量能（较昨）</div>
            <div class="v">{{ marketData.volume?.change ?? "-" }}</div>
            <div class="s">两市 {{ marketData.volume?.total ?? "-" }}</div>
          </div>
          <div class="hero-kpi hero-kpi-balanced">
            <div class="k">高度 / 质量</div>
            <div class="v">{{ marketData.ladder?.[0]?.badge ?? "-" }} 板</div>
            <div class="s">
              封板 {{ marketData.panorama?.ratio ?? "-" }} · 晋级
              {{
                marketData.features?.mood_inputs?.jj_rate === undefined || marketData.features?.mood_inputs?.jj_rate === null ? "-" : Number(marketData.features.mood_inputs.jj_rate).toFixed(1) + "%"
              }}
            </div>
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
