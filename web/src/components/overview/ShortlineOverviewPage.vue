<script setup lang="ts">
import { computed } from "vue"
import { useMarketData } from "../../composables/useMarketData"
import ShortReminderFooter from "../common/ShortReminderFooter.vue"

type ReviewTabId = "overview" | "sentiment" | "hotAnswer" | "tomorrow" | "themes" | "ladder" | "plan" | "backtest"

const emit = defineEmits<{
  (e: "jump", tab: ReviewTabId): void
}>()

const { marketData } = useMarketData()
const decision = computed<any>(() => marketData.value?.shortlineDecision || {})
const stanceTone = computed(() => String(decision.value?.stanceTone || "watch"))
const stanceLabel = computed(() => String(decision.value?.stanceLabel || "可试错"))
const stanceLead = computed(() => String(decision.value?.stanceLead || "先看情绪、主线和接力环境，再决定是否出手。"))
const heroTags = computed<string[]>(() => (Array.isArray(decision.value?.heroTags) ? decision.value.heroTags : []))
const marketPulse = computed<any[]>(() => (Array.isArray(decision.value?.marketPulse) ? decision.value.marketPulse : []))
const radarCards = computed<any[]>(() => (Array.isArray(decision.value?.radarCards) ? decision.value.radarCards : []))
const mainline = computed<any>(() => decision.value?.mainline || {})
const risk = computed<any>(() => decision.value?.risk || {})
const decisionSteps = computed<any[]>(() => (Array.isArray(decision.value?.decisionSteps) ? decision.value.decisionSteps : []))
const tradePlan = computed<any>(() => decision.value?.tradePlan || {})
const scripts = computed<any>(() => decision.value?.scripts || {})
const backtestCorrection = computed<any>(() => decision.value?.backtestCorrection || {})
const currentPool = computed<any>(() => decision.value?.currentPool || {})
const indices = computed<any>(() => decision.value?.indices || {})

const xqUrl = (code?: string | null) => {
  const raw = String(code || "").trim()
  if (!raw) return "https://xueqiu.com"
  const upper = raw.toUpperCase()
  if (upper.includes(".")) {
    const [num, suffix] = upper.split(".")
    const market = suffix === "SH" ? "SH" : suffix === "SZ" ? "SZ" : ""
    return market ? `https://xueqiu.com/S/${market}${num}` : `https://xueqiu.com/S/${upper}`
  }
  const market = raw.startsWith("6") ? "SH" : "SZ"
  return `https://xueqiu.com/S/${market}${raw}`
}

const openXq = (code?: string | null) => {
  if (typeof window === "undefined") return
  window.open(xqUrl(code), "_blank", "noopener,noreferrer")
}
</script>

<template>
  <section class="overview-page">
    <article class="overview-hero" :data-tone="stanceTone">
      <div class="overview-hero-copy">
        <div class="eyebrow">短线总指挥</div>
        <h1>{{ stanceLabel }}</h1>
        <p class="lead">{{ stanceLead }}</p>
        <div class="hero-tags">
          <span v-for="tag in heroTags" :key="tag" class="hero-tag">{{ tag }}</span>
        </div>
      </div>

      <div class="overview-hero-side">
        <div class="pulse-grid">
          <div v-for="item in marketPulse" :key="item.label" class="pulse-card">
            <div class="pulse-label">{{ item.label }}</div>
            <div class="pulse-value">{{ item.value }}</div>
          </div>
        </div>
        <button class="hero-jump" type="button" @click="emit('jump', 'plan')">直接看个股研究</button>
      </div>
    </article>

    <section class="radar-grid">
      <article v-for="card in radarCards" :key="card.label" class="radar-card" :data-tone="card.tone">
        <div class="radar-label">{{ card.label }}</div>
        <div class="radar-value">{{ card.value }}</div>
        <div class="radar-note">{{ card.note }}</div>
      </article>
    </section>

    <section class="command-grid">
      <article class="command-card command-card-mainline">
        <div class="section-kicker">主线候选</div>
        <h2>{{ mainline.title || "今天先看哪些方向" }}</h2>
        <p>{{ mainline.hint || "等待主线进一步聚焦。" }}</p>
        <div class="chip-row">
          <span v-for="name in mainline.candidates || []" :key="name" class="info-chip">{{ name }}</span>
          <span v-if="!(mainline.candidates || []).length" class="info-chip">等待下一轮聚焦</span>
        </div>
        <button class="inline-link" type="button" @click="emit('jump', (mainline.jumpTab || 'themes') as ReviewTabId)">{{ mainline.jumpLabel || "展开主线证据" }}</button>
      </article>

      <article class="command-card command-card-risk">
        <div class="section-kicker">风险清单</div>
        <h2>{{ risk.title || "今天最容易亏在哪" }}</h2>
        <ul class="warning-list">
          <li v-for="warning in risk.warnings || []" :key="warning">{{ warning }}</li>
          <li v-if="!(risk.warnings || []).length">当前没有额外风控提示，仍然优先尊重情绪与承接。</li>
        </ul>
        <button class="inline-link" type="button" @click="emit('jump', (risk.jumpTab || 'sentiment') as ReviewTabId)">{{ risk.jumpLabel || "回到情绪细节" }}</button>
      </article>
    </section>

    <section class="execution-card">
      <div class="section-kicker">执行链</div>
      <h2>从复盘到下单，按这条线走</h2>
      <div class="execution-steps">
        <article v-for="(step, index) in decisionSteps" :key="step.title" class="step-card">
          <div class="step-index">0{{ index + 1 }}</div>
          <div class="step-title">{{ step.title }}</div>
          <div class="step-detail">{{ step.detail }}</div>
          <button class="step-link" type="button" @click="emit('jump', step.tab)">{{ step.cta }}</button>
        </article>
      </div>
    </section>

    <section class="command-grid">
      <article class="command-card command-card-trade">
        <div class="section-kicker">今日出手分层</div>
        <h2>{{ tradePlan.title || "先买谁，再观察谁" }}</h2>
        <p>{{ tradePlan.summary || "等待个股研究给出更明确的候选。" }}</p>
        <div class="gate-row">
          <span class="gate-pill">市场闸门：{{ tradePlan.marketGate || "按情绪择时" }}</span>
          <span class="gate-pill">潮汐：{{ tradePlan.tideGate || "neutral" }}</span>
        </div>
        <div class="candidate-stack" v-if="(tradePlan.primaryCandidates || []).length">
          <button
            v-for="row in tradePlan.primaryCandidates || []"
            :key="`buy-${row.code}`"
            class="candidate-card"
            :data-tone="row.tone || 'watch'"
            type="button"
            @click="emit('jump', (tradePlan.jumpTab || 'plan') as ReviewTabId)">
            <div class="candidate-head">
              <div>
                <span class="stock-link" role="link" tabindex="0" @click.stop="openXq(row.code)" @keydown.enter.stop="openXq(row.code)" @keydown.space.prevent.stop="openXq(row.code)">
                  <strong>{{ row.name }}</strong>
                  <span class="pool-code">{{ row.code }}</span>
                </span>
              </div>
              <span class="candidate-score">{{ row.bucket || "优先跟踪" }} {{ row.score }}</span>
            </div>
            <div class="candidate-meta">{{ row.line || "待归因" }} · {{ row.styleTag || "主线候选" }}</div>
            <div class="candidate-note">{{ row.reasonText || "等待更多确认条件。" }}</div>
          </button>
        </div>
        <p v-else class="empty-hint">当前没有明确“可直接出手”的票，先按观察池节奏跟踪，不做强行接力。</p>
        <button class="inline-link" type="button" @click="emit('jump', (tradePlan.jumpTab || 'plan') as ReviewTabId)">{{ tradePlan.jumpLabel || "展开全部个股研究" }}</button>
      </article>

      <article class="command-card command-card-observe">
        <div class="section-kicker">观察清单</div>
        <h2>低位试错和备选观察</h2>
        <div class="candidate-stack" v-if="(tradePlan.watchCandidates || []).length">
          <button
            v-for="row in tradePlan.watchCandidates || []"
            :key="`watch-${row.code}`"
            class="candidate-card"
            :data-tone="row.tone || 'watch'"
            type="button"
            @click="emit('jump', (tradePlan.jumpTab || 'plan') as ReviewTabId)">
            <div class="candidate-head">
              <div>
                <span class="stock-link" role="link" tabindex="0" @click.stop="openXq(row.code)" @keydown.enter.stop="openXq(row.code)" @keydown.space.prevent.stop="openXq(row.code)">
                  <strong>{{ row.name }}</strong>
                  <span class="pool-code">{{ row.code }}</span>
                </span>
              </div>
              <span class="candidate-score is-watch">{{ row.bucket || "观察确认" }} {{ row.score }}</span>
            </div>
            <div class="candidate-meta">{{ row.line || "待归因" }} · {{ row.primarySector || row.styleTag || "观察池" }}</div>
            <div class="candidate-note">{{ row.reasonText || "继续观察承接和量能。" }}</div>
          </button>
        </div>
        <p v-else class="empty-hint">当前没有额外观察票，优先等待主线进一步收敛。</p>
      </article>
    </section>

    <section class="execution-card">
      <div class="section-kicker">明日剧本卡</div>
      <h2>{{ scripts.title || "次日 9:25 重点怎么判" }}</h2>
      <div class="script-grid" v-if="(scripts.cards || []).length">
        <article v-for="row in scripts.cards || []" :key="`script-${row.code}`" class="script-card" :data-tone="row.tone || 'watch'">
          <div class="script-head">
            <div>
              <a class="stock-link" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">
                <strong>{{ row.name }}</strong>
                <span class="pool-code">{{ row.code }}</span>
              </a>
            </div>
            <span class="script-step">{{ row.nextStep }}</span>
          </div>
          <div class="script-meta">{{ row.line || "待归因" }} · {{ row.bucket === "buy" ? "优先跟踪" : "观察确认" }}</div>
          <div class="script-rule">
            <span class="script-label is-super">超预期</span>
            <p>{{ row.superExpected || "高开与量能同步强化时再提高预期。" }}</p>
          </div>
          <div class="script-rule">
            <span class="script-label is-expected">预期内</span>
            <p>{{ row.expected || "按预期量能和开盘位置判断是否保留跟踪。" }}</p>
          </div>
          <div class="script-rule">
            <span class="script-label is-low">低预期</span>
            <p>{{ row.lowExpected || "低于预期就不强上，先观察承接。" }}</p>
          </div>
        </article>
      </div>
      <p v-else class="empty-hint">当前没有可展开的次日剧本，等待待验证池和竞价预期继续补齐。</p>
      <button class="inline-link" type="button" @click="emit('jump', (scripts.jumpTab || 'backtest') as ReviewTabId)">{{ scripts.jumpLabel || "展开回测与竞价验证" }}</button>
    </section>

    <section class="execution-card">
      <div class="section-kicker">回测纠偏卡</div>
      <h2>{{ backtestCorrection.title || "最近样本在提醒我们什么" }}</h2>
      <div class="correction-kpis">
        <div v-for="item in backtestCorrection.kpis || []" :key="item.label" class="correction-kpi">
          <div class="correction-kpi-label">{{ item.label }}</div>
          <div class="correction-kpi-value">{{ item.value }}</div>
        </div>
      </div>
      <div class="correction-grid">
        <article class="correction-card is-good">
          <div class="correction-title">继续做</div>
          <p>{{ backtestCorrection.continueText || "当前样本还少，先继续按低位确认和同源条件过滤。" }}</p>
        </article>
        <article class="correction-card is-bad">
          <div class="correction-title">少做或别做</div>
          <p>{{ backtestCorrection.avoidText || "亏损样本主要说明接力仍要看竞价质量和承接。" }}</p>
        </article>
      </div>
      <div class="correction-actions">
        <div class="correction-actions-title">今天怎么修正</div>
        <ul class="correction-list">
          <li v-for="item in backtestCorrection.actionItems || []" :key="item">{{ item }}</li>
        </ul>
      </div>
      <button class="inline-link" type="button" @click="emit('jump', (backtestCorrection.jumpTab || 'backtest') as ReviewTabId)">{{ backtestCorrection.jumpLabel || "回到回测明细" }}</button>
    </section>

    <section class="command-grid">
      <article class="command-card command-card-pool">
        <div class="section-kicker">待验证池</div>
        <h2>{{ currentPool.title || "次日优先盯哪些票" }}</h2>
        <div class="pool-list" v-if="(currentPool.rows || []).length">
          <button v-for="row in currentPool.rows || []" :key="row.code" class="pool-row" type="button" @click="emit('jump', (currentPool.jumpTab || 'backtest') as ReviewTabId)">
            <div>
              <span class="stock-link" role="link" tabindex="0" @click.stop="openXq(row.code)" @keydown.enter.stop="openXq(row.code)" @keydown.space.prevent.stop="openXq(row.code)">
                <strong>{{ row.name }}</strong>
                <span class="pool-code">{{ row.code }}</span>
              </span>
            </div>
            <div class="pool-meta">{{ row.line || "待归因" }} · {{ row.nextStep || "待验证" }}</div>
          </button>
        </div>
        <p v-else class="empty-hint">当前没有待验证池，先看个股研究和历史回测的有效样本。</p>
      </article>

      <article class="command-card command-card-index">
        <div class="section-kicker">指数背景</div>
        <h2>{{ indices.title || "指数和环境怎么配合" }}</h2>
        <div class="index-list">
          <div v-for="row in indices.rows || []" :key="row.code" class="index-row">
            <span>{{ row.name }}</span>
            <strong>{{ row.chg || "-" }}</strong>
          </div>
        </div>
        <p class="index-foot">{{ indices.foot || "等待指数与情绪共振进一步确认。" }}</p>
      </article>
    </section>

    <ShortReminderFooter />
  </section>
</template>

<style scoped src="./ShortlineOverviewPage.css"></style>
