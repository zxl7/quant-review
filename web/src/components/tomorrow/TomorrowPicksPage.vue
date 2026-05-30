<script setup lang="ts">
import { onMounted, computed, ref, watch } from 'vue';
import { useTomorrowPicks } from './useTomorrowPicks';
import ShortReminderFooter from '../common/ShortReminderFooter.vue';

const {
  themes, loading, error, selectedThemeCode,
  stocks, stocksLoading, fetchThemes, selectTheme,
} = useTomorrowPicks();

onMounted(() => fetchThemes());

const selectedDate = ref('');

// 所有日期（按时间排序）
const dates = computed(() => {
  const set = new Set<string>();
  for (const t of themes.value) {
    if (t.tradeDate) set.add(t.tradeDate);
  }
  return Array.from(set).sort((a, b) => b.localeCompare(a)); // 最新在前
});

// 过滤当前日期的主题
const filteredThemes = computed(() => {
  if (!selectedDate.value) return themes.value;
  return themes.value.filter((t) => t.tradeDate === selectedDate.value);
});

// 按日期分组显示时（未选择具体日期），还是分组
const dateGroups = computed(() => {
  const map = new Map<string, typeof themes.value>();
  for (const item of themes.value) {
    const d = item.tradeDate || '待定';
    if (!map.has(d)) map.set(d, []);
    map.get(d)!.push(item);
  }
  return Array.from(map.entries());
});

const selectedTheme = computed(() => themes.value.find((t) => t.themeCode === selectedThemeCode.value));

// 自动选中最新日期
watch(dates, (val) => {
  if (val.length && !selectedDate.value) selectedDate.value = val[0];
}, { immediate: true });

const fmtGain = (v: number) => {
  if (!Number.isFinite(v)) return '--';
  return `${v > 0 ? '+' : ''}${v.toFixed(2)}%`;
};

const signedClass = (v: number) => (v > 0 ? 'up' : v < 0 ? 'down' : 'flat');

const xqUrl = (code: string) => {
  const c = String(code || '').trim();
  if (!c) return '#';
  return `https://xueqiu.com/S/${c.startsWith('6') ? 'SH' : 'SZ'}${c}`;
};
</script>

<template>
  <div class="card" data-page="tomorrow" id="sec-tomorrow">
    <div class="tp-layout">
      <!-- 左侧：策略列表 -->
      <div class="tp-left">
        <!-- 日期选择器 -->
        <div class="tp-date-picker" v-show="!loading && dates.length">
          <div class="tp-date-left">
            <span class="tp-date-label">日期</span>
            <select v-model="selectedDate" class="tp-date-select">
              <option v-for="d in dates" :key="d" :value="d">{{ d }}</option>
            </select>
          </div>
          <button class="tp-refresh-btn" @click="fetchThemes(true)" :disabled="loading">
            {{ loading ? '刷新中...' : '刷新' }}
          </button>
        </div>

        <!-- Loading 骨架 -->
        <div v-if="loading" class="tp-skeleton-list">
          <div v-for="i in 5" :key="'sk-'+i" class="tp-skeleton-card">
            <div class="tp-sk-row">
              <div class="tp-sk-rank"></div>
              <div class="tp-sk-badge"></div>
              <div class="tp-sk-hot"></div>
            </div>
            <div class="tp-sk-line long"></div>
            <div class="tp-sk-line short"></div>
          </div>
        </div>

        <!-- 错误 -->
        <div v-else-if="error" class="tp-error">{{ error }}</div>

        <!-- 内容 -->
        <template v-else>
          <template v-if="selectedDate">
            <!-- 单日期视图 -->
            <div class="tp-group">
              <div class="tp-date">{{ selectedDate }} · {{ filteredThemes.length }}个主题</div>
              <div
                v-for="item in filteredThemes"
                :key="item.id"
                class="tp-card"
                :class="{ active: selectedThemeCode === item.themeCode }"
                @click="selectTheme(item.themeCode)"
              >
                <div class="tp-card-head">
                  <span class="tp-rank" :class="'rank-' + Math.min(item.rank, 4)">{{ item.rank }}</span>
                  <span class="tp-sector">{{ item.themeName }}</span>
                  <span v-if="item.isHot" class="tp-hot">HOT</span>
                  <span class="tp-zt">{{ item.ztCount }}家涨停</span>
                </div>
                <div class="tp-card-title">{{ item.title }}</div>
                <div class="tp-card-meta">
                  <span :class="['tp-card-gain', signedClass(item.gain)]">{{ fmtGain(item.gain) }}</span>
                  <span class="tp-card-cum">历年累计 {{ fmtGain(item.cumulateGain) }}</span>
                </div>
              </div>
            </div>
          </template>
          <template v-else>
            <!-- 全部日期分组视图 -->
            <div v-for="[date, items] in dateGroups" :key="date" class="tp-group">
              <div class="tp-date">{{ date }}</div>
              <div
                v-for="item in items"
                :key="item.id"
                class="tp-card"
                :class="{ active: selectedThemeCode === item.themeCode }"
                @click="selectTheme(item.themeCode)"
              >
                <div class="tp-card-head">
                  <span class="tp-rank" :class="'rank-' + Math.min(item.rank, 4)">{{ item.rank }}</span>
                  <span class="tp-sector">{{ item.themeName }}</span>
                  <span v-if="item.isHot" class="tp-hot">HOT</span>
                  <span class="tp-zt">{{ item.ztCount }}家涨停</span>
                </div>
                <div class="tp-card-title">{{ item.title }}</div>
                <div class="tp-card-meta">
                  <span :class="['tp-card-gain', signedClass(item.gain)]">{{ fmtGain(item.gain) }}</span>
                  <span class="tp-card-cum">历年累计 {{ fmtGain(item.cumulateGain) }}</span>
                </div>
              </div>
            </div>
          </template>
        </template>
      </div>

      <!-- 右侧：成分股详情 -->
      <div class="tp-right">
        <template v-if="selectedTheme">
          <div class="tp-right-head">
            <div class="tp-right-title-row">
              <span class="tp-rank-lg" :class="'rank-' + Math.min(selectedTheme.rank, 4)">{{ selectedTheme.rank }}</span>
              <div class="tp-right-title-text">
                <span class="tp-right-name">{{ selectedTheme.themeName }}</span>
              </div>
              <span class="tp-theme-gain" :class="signedClass(selectedTheme.gain)">{{ fmtGain(selectedTheme.gain) }}</span>
            </div>
            <div class="tp-right-subtitle">{{ selectedTheme.title }}</div>
            <div class="tp-right-desc">{{ selectedTheme.summary }}</div>
          </div>

          <div class="tp-stock-count">
            成分股 <strong>{{ stocks.length }}</strong> 只
            <span v-if="stocksLoading" class="tp-loading-dot"></span>
          </div>

          <!-- Stocks loading skeleton -->
          <div v-if="stocksLoading" class="tp-skeleton-list small">
            <div v-for="i in 4" :key="'ssk-'+i" class="tp-skeleton-stock">
              <div class="tp-sk-line mid"></div>
              <div class="tp-sk-line shorter"></div>
            </div>
          </div>

          <!-- Stock list -->
          <div v-else class="tp-stock-list">
            <a
              v-for="s in stocks"
              :key="s.code"
              class="tp-stock-item"
              :href="xqUrl(s.code)"
              target="_blank"
              rel="noopener"
            >
              <div class="tp-si-top">
                <div class="tp-si-left">
                  <span class="tp-si-name">{{ s.name }}</span>
                  <span v-if="s.label" class="tp-si-label">{{ s.label }}</span>
                </div>
                <div class="tp-si-right">
                  <span class="tp-si-gain" :class="signedClass(s.gain)">{{ fmtGain(s.gain) }}</span>
                </div>
              </div>
              <div class="tp-si-mid">
                <span class="tp-si-code">{{ s.code }} · {{ s.industry }}</span>
                <span class="tp-si-price">¥{{ s.price?.toFixed(2) || '--' }}</span>
              </div>
              <div v-if="s.reason" class="tp-si-reason">
                <span class="tp-si-reason-label">入选理由</span>
                {{ s.reason }}
              </div>
            </a>
          </div>
        </template>

        <div v-else class="tp-empty">点击左侧卡片查看成分股</div>
      </div>
    </div>

    <ShortReminderFooter />
  </div>
</template>

<style scoped src="./TomorrowPicksPage.css"></style>
