<script setup lang="ts">
import { computed, ref } from 'vue';
import { useMarketData } from '../../composables/useMarketData';
import ShortReminderFooter from '../common/ShortReminderFooter.vue';

const { marketData } = useMarketData();

const flashFilter = ref<'all' | 'warn'>('all');

const flashItems = computed(() => Array.isArray(marketData.value?.flashItems) ? marketData.value.flashItems : []);
const flashLastUpdated = computed(() => marketData.value?.flashLastUpdated || marketData.value?.meta?.asOf?.quotes || '');
const flashLoading = computed(() => false);
const flashError = computed(() => '');
const filteredFlashItems = computed(() => (flashFilter.value === 'warn' ? flashItems.value.filter((x: any) => x.isWarn) : flashItems.value));

const setFlashFilter = (mode: 'all' | 'warn') => {
  flashFilter.value = mode === 'warn' ? 'warn' : 'all';
};

const refreshFlash = (_force = false) => {};

const flashStockUrl = (symbol?: string | null) => {
  const raw = String(symbol || '').trim();
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
</script>

<template>
  <div class="flash-page">
    <div class="card" data-page="flash" id="sec-flash">
      <div class="card-header">
        <div class="card-title">股通快讯</div>
        <div class="card-badge">15s</div>
      </div>
      <div class="flash-toolbar">
        <div class="flash-toolbar-left">
          <button class="flash-btn" :class="{ active: flashFilter === 'all' }" type="button" @click="setFlashFilter('all')">全部</button>
          <button class="flash-btn" :class="{ active: flashFilter === 'warn' }" type="button" @click="setFlashFilter('warn')">警示</button>
          <button class="flash-btn" type="button" @click="refreshFlash(true)">刷新</button>
        </div>
        <div class="flash-toolbar-right">
          <span v-if="flashLastUpdated">更新 {{ flashLastUpdated }}</span>
          <span v-else>等待首次拉取</span>
          <span>共 {{ filteredFlashItems.length }} 条</span>
        </div>
      </div>
      <div v-if="flashLoading && !filteredFlashItems.length" class="flash-loading">正在拉取快讯...</div>
      <div v-else-if="flashError" class="flash-error">{{ flashError }}</div>
      <div v-else-if="!filteredFlashItems.length" class="flash-empty">暂无符合条件的快讯</div>
      <div v-else class="flash-list">
        <article class="flash-item" :class="{ warn: item.isWarn }" v-for="item in filteredFlashItems" :key="item.id">
          <div class="flash-head">
            <span class="flash-time">{{ item.timeText }}</span>
            <div class="flash-title">{{ item.title }}</div>
          </div>
          <div class="flash-summary" v-if="item.summary">{{ item.summary }}</div>
          <div class="flash-stocks" v-if="item.stocks && item.stocks.length">
            <a
              class="flash-stock"
              v-for="stock in item.stocks"
              :key="item.id + '-' + stock.symbol"
              :href="flashStockUrl(stock.symbol)"
              target="_blank"
              rel="noopener noreferrer">
              {{ stock.name }}
            </a>
          </div>
        </article>
      </div>
    </div>

    <ShortReminderFooter />
  </div>
</template>
