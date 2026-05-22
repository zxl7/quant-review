<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import ShortReminderFooter from '../common/ShortReminderFooter.vue';

type FlashStock = {
  name: string;
  symbol: string;
};

type FlashItem = {
  id: string;
  title: string;
  summary: string;
  timeText: string;
  isWarn: boolean;
  stocks: FlashStock[];
};

const flashFilter = ref<'all' | 'warn'>('all');
const flashItems = ref<FlashItem[]>([]);
const flashLastUpdated = ref('');
const flashLoading = ref(false);
const flashError = ref('');

let flashTimer: number | null = null;
let flashReqInFlight = false;

const filteredFlashItems = computed(() =>
  flashFilter.value === 'warn' ? flashItems.value.filter((x) => x.isWarn) : flashItems.value,
);

const setFlashFilter = (mode: 'all' | 'warn') => {
  flashFilter.value = mode === 'warn' ? 'warn' : 'all';
};

const flashToneClass = (item: FlashItem) => {
  const text = `${item.title || ''} ${item.summary || ''}`;
  if (/跳水|跌停|走弱|风险|回落|分歧/.test(text)) return 'down';
  if (/涨停|拉升|走强|回封|新高|修复|反弹/.test(text)) return 'up';
  return 'neutral';
};

const formatFlashTime = (value: unknown) => {
  let date: Date | null = null;
  if (typeof value === 'number' && Number.isFinite(value)) {
    date = new Date(value * 1000);
  } else if (typeof value === 'string' && value.trim()) {
    date = new Date(value);
  }
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return '--';
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  const ss = String(date.getSeconds()).padStart(2, '0');
  return `${y}-${m}-${d} ${hh}:${mm}:${ss}`;
};

const normalizeFlashItems = (messages: unknown) => {
  const rows = Array.isArray(messages) ? messages : [];
  return rows
    .filter((x): x is Record<string, any> => Boolean(x) && typeof x === 'object')
    .map((x, index) => {
      const subjIds = Array.isArray(x.subj_ids) ? x.subj_ids.map((v: unknown) => Number(v)) : [];
      return {
        id: String(x.id || x.msg_id || x.created_at || index),
        title: String(x.title || '').trim(),
        summary: String(x.summary || '').trim(),
        timeText: formatFlashTime(x.created_at),
        isWarn: subjIds.includes(10),
        stocks: Array.isArray(x.stocks)
          ? x.stocks
              .filter((s: unknown): s is Record<string, any> => Boolean(s) && typeof s === 'object')
              .map((s) => ({
                name: String(s.name || '').trim(),
                symbol: String(s.symbol || s.code || '').trim(),
              }))
              .filter((s) => s.name)
          : [],
      };
    })
    .filter((x) => x.title);
};

const refreshFlash = async (force = false) => {
  try {
    if (!force && flashReqInFlight) return;
    if (flashReqInFlight) return;
    flashReqInFlight = true;
    flashLoading.value = true;
    flashError.value = '';
    const url = 'https://baoer-api.xuangubao.cn/api/v6/message/newsflash?subj_ids=9,10,723,35,469,821&platform=pcweb';
    const res = await fetch(`${url}&_ts=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    flashItems.value = normalizeFlashItems(json?.data?.messages);
    flashLastUpdated.value = formatFlashTime(new Date().toISOString());
  } catch (e: any) {
    flashError.value = `快讯获取失败：${String(e?.message || e)}`;
  } finally {
    flashLoading.value = false;
    flashReqInFlight = false;
  }
};

const startFlashPolling = (forceRestart = false) => {
  if (flashTimer && !forceRestart) return;
  if (flashTimer && forceRestart) {
    window.clearInterval(flashTimer);
    flashTimer = null;
  }
  refreshFlash(false);
  flashTimer = window.setInterval(() => {
    void refreshFlash(false);
  }, 15000);
};

const stopFlashPolling = () => {
  if (flashTimer) {
    window.clearInterval(flashTimer);
    flashTimer = null;
  }
};

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

onMounted(() => {
  startFlashPolling(true);
});

onBeforeUnmount(() => {
  stopFlashPolling();
});
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
        <article class="flash-item" :class="[flashToneClass(item), { warn: item.isWarn }]" v-for="item in filteredFlashItems" :key="item.id">
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
