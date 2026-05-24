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
          <span class="tp-date-label">日期</span>
          <select v-model="selectedDate" class="tp-date-select">
            <option v-for="d in dates" :key="d" :value="d">{{ d }}</option>
          </select>
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

<style scoped>
.tp-layout {
  display: flex;
  gap: 12px;
  min-height: 420px;
}

/* === 左侧 === */
.tp-left {
  flex: 0 0 340px;
  max-width: 340px;
  overflow-y: auto;
}

/* 日期选择器 */
.tp-date-picker {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 10px; padding-bottom: 8px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
}
.tp-date-label { font-size: 12px; font-weight: 900; color: var(--text-secondary); }
.tp-date-select {
  flex: 1;
  padding: 4px 8px; border-radius: 6px;
  border: 1px solid color-mix(in oklab, rgba(148, 163, 184, 0.18) 65%, var(--theme-glow) 35%);
  background: color-mix(in oklab, var(--theme-soft) 8%, rgba(255, 255, 255, 0.5));
  color: var(--text-primary); font-size: 12px; font-weight: 800;
  outline: none; cursor: pointer; font-variant-numeric: tabular-nums;
}
[data-theme="dark"] .tp-date-select {
  background: rgba(15, 23, 42, 0.5);
  border-color: rgba(148, 163, 184, 0.22);
  color: var(--text-primary);
}
.tp-date-select:focus { border-color: var(--theme-accent); }

.tp-group { margin-bottom: 10px; }
.tp-date {
  font-size: 11px; font-weight: 900; color: var(--text-muted);
  padding: 4px 0; border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  margin-bottom: 6px;
}

.tp-card {
  border: 1px solid color-mix(in oklab, rgba(148, 163, 184, 0.18) 65%, var(--theme-glow) 35%);
  border-radius: 10px;
  background: linear-gradient(135deg, color-mix(in oklab, var(--theme-soft) 12%, rgba(255, 255, 255, 0.55)), rgba(255, 255, 255, 0.55));
  padding: 8px 10px; margin-bottom: 5px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
[data-theme="dark"] .tp-card {
  background: rgba(15, 23, 42, 0.45);
  border-color: rgba(148, 163, 184, 0.22);
}
.tp-card:hover { border-color: var(--theme-accent-2); }
.tp-card.active {
  border-color: var(--theme-accent);
  background: linear-gradient(135deg, color-mix(in oklab, var(--theme-soft) 22%, rgba(255, 255, 255, 0.7)), rgba(255, 255, 255, 0.65));
}
[data-theme="dark"] .tp-card.active {
  background: color-mix(in oklab, var(--theme-soft) 18%, rgba(15, 23, 42, 0.6));
  border-color: var(--theme-accent);
}

.tp-card-head { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }

.tp-rank {
  display: inline-flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; border-radius: 5px;
  font-size: 11px; font-weight: 1000; flex-shrink: 0; color: #1e293b;
}
.tp-rank.rank-1 { background: #ef4444; color: #fff; }
.tp-rank.rank-2 { background: #f59e0b; }
.tp-rank.rank-3 { background: #f59e0b; }
.tp-rank.rank-4 { background: var(--text-muted); color: #fff; }

.tp-sector {
  font-size: 11px; font-weight: 950; padding: 1px 5px; border-radius: 4px;
  background: color-mix(in oklab, var(--theme-soft) 18%, transparent);
  color: var(--theme-accent); white-space: nowrap;
}
.tp-hot {
  display: inline-flex; align-items: center; justify-content: center;
  padding: 1px 4px; border-radius: 3px;
  font-size: 9px; font-weight: 1000; background: #ef4444; color: #fff;
}
.tp-zt { margin-left: auto; font-size: 11px; font-weight: 800; color: #dc2626; white-space: nowrap; }

.tp-card-title {
  font-size: 12px; font-weight: 950; color: var(--text-primary);
  margin-bottom: 3px; line-height: 1.35;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}
.tp-card-meta { display: flex; gap: 10px; font-size: 11px; font-weight: 800; }
.tp-card-gain.up { color: #dc2626; }
.tp-card-gain.down { color: #059669; }
.tp-card-gain.flat { color: var(--text-muted); }
.tp-card-cum { color: var(--text-muted); }

/* === Loading Skeleton === */
.tp-skeleton-list { display: flex; flex-direction: column; gap: 6px; }
.tp-skeleton-card {
  border: 1px solid rgba(148, 163, 184, 0.10);
  border-radius: 10px; padding: 10px 10px;
  background: rgba(255, 255, 255, 0.3);
}
[data-theme="dark"] .tp-skeleton-card { background: rgba(15, 23, 42, 0.2); }

.tp-sk-row { display: flex; gap: 6px; margin-bottom: 8px; }
.tp-sk-rank {
  width: 24px; height: 24px; border-radius: 5px;
  background: linear-gradient(90deg, rgba(148, 163, 184, 0.15) 0%, rgba(148, 163, 184, 0.35) 50%, rgba(148, 163, 184, 0.15) 100%);
  background-size: 200% 100%;
  animation: tp-shimmer 1.4s infinite;
}
.tp-sk-badge {
  width: 48px; height: 20px; border-radius: 4px;
  background: linear-gradient(90deg, rgba(148, 163, 184, 0.15) 0%, rgba(148, 163, 184, 0.35) 50%, rgba(148, 163, 184, 0.15) 100%);
  background-size: 200% 100%;
  animation: tp-shimmer 1.4s infinite;
}
.tp-sk-hot {
  width: 32px; height: 18px; border-radius: 3px; margin-left: auto;
  background: linear-gradient(90deg, rgba(148, 163, 184, 0.12) 0%, rgba(148, 163, 184, 0.28) 50%, rgba(148, 163, 184, 0.12) 100%);
  background-size: 200% 100%;
  animation: tp-shimmer 1.4s infinite;
}
.tp-sk-line {
  height: 12px; border-radius: 4px; margin-bottom: 6px;
  background: linear-gradient(90deg, rgba(148, 163, 184, 0.12) 0%, rgba(148, 163, 184, 0.30) 50%, rgba(148, 163, 184, 0.12) 100%);
  background-size: 200% 100%;
  animation: tp-shimmer 1.4s infinite;
}
.tp-sk-line.long { width: 100%; }
.tp-sk-line.short { width: 55%; }
.tp-sk-line.mid { width: 70%; height: 14px; border-radius: 4px; margin-bottom: 4px; }
.tp-sk-line.shorter { width: 40%; height: 10px; border-radius: 3px; }

.tp-skeleton-stock {
  border: 1px solid rgba(148, 163, 184, 0.08);
  border-radius: 8px; padding: 10px 12px;
  background: rgba(255, 255, 255, 0.25);
}
[data-theme="dark"] .tp-skeleton-stock { background: rgba(15, 23, 42, 0.18); }

@keyframes tp-shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

.tp-loading-dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  background: var(--theme-accent);
  animation: tp-pulse 0.8s infinite alternate;
}
@keyframes tp-pulse {
  0% { opacity: 0.3; transform: scale(0.8); }
  100% { opacity: 1; transform: scale(1); }
}

/* === 右侧 === */
.tp-right {
  flex: 1; overflow-y: auto; border-radius: 12px;
  border: 1px solid color-mix(in oklab, rgba(148, 163, 184, 0.18) 65%, var(--theme-glow) 35%);
  background: linear-gradient(135deg, color-mix(in oklab, var(--theme-soft) 10%, rgba(255, 255, 255, 0.55)), rgba(255, 255, 255, 0.55));
  padding: 14px 16px;
}
[data-theme="dark"] .tp-right {
  background: rgba(15, 23, 42, 0.45);
  border-color: rgba(148, 163, 184, 0.22);
}

.tp-right-head { margin-bottom: 12px; padding-bottom: 10px; border-bottom: 1px solid rgba(148, 163, 184, 0.14); }

.tp-right-title-row {
  display: flex; align-items: flex-start; gap: 10px; margin-bottom: 8px;
}
.tp-rank-lg {
  display: inline-flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; border-radius: 7px;
  font-size: 15px; font-weight: 1000; color: #1e293b; flex-shrink: 0;
}
.tp-rank-lg.rank-1 { background: #ef4444; color: #fff; }
.tp-rank-lg.rank-2 { background: #f59e0b; }
.tp-rank-lg.rank-3 { background: #f59e0b; }
.tp-rank-lg.rank-4 { background: var(--text-muted); color: #fff; }

.tp-right-title-text { flex: 1; min-width: 0; }
.tp-right-name { font-size: 18px; font-weight: 1050; color: var(--text-primary); }
.tp-theme-gain {
  font-size: 20px; font-weight: 1100; font-variant-numeric: tabular-nums;
  white-space: nowrap; flex-shrink: 0;
}
.tp-theme-gain.up { color: #dc2626; }
.tp-theme-gain.down { color: #059669; }
.tp-theme-gain.flat { color: var(--text-muted); }

.tp-right-subtitle {
  font-size: 13px; font-weight: 900; color: var(--text-primary);
  margin-bottom: 6px; line-height: 1.4;
}
.tp-right-desc {
  font-size: 12px; font-weight: 700; color: var(--text-secondary);
  line-height: 1.55;
}

.tp-stock-count {
  font-size: 13px; font-weight: 850; color: var(--text-secondary);
  margin: 12px 0 8px; display: flex; align-items: center; gap: 6px;
}
.tp-stock-count strong { color: var(--theme-accent); font-weight: 1000; }

.tp-stock-list { display: flex; flex-direction: column; gap: 6px; }

.tp-stock-item {
  display: flex; flex-direction: column; gap: 4px;
  padding: 10px 12px; border-radius: 10px;
  border: 1px solid rgba(148, 163, 184, 0.10);
  background: rgba(255, 255, 255, 0.35);
  text-decoration: none;
  transition: border-color 0.15s;
}
[data-theme="dark"] .tp-stock-item {
  background: rgba(15, 23, 42, 0.28);
  border-color: rgba(148, 163, 184, 0.14);
}
.tp-stock-item:hover { border-color: var(--theme-accent-2); }

.tp-si-top { display: flex; align-items: center; justify-content: space-between; }
.tp-si-left { display: flex; align-items: center; gap: 8px; }
.tp-si-name { font-size: 15px; font-weight: 1050; color: var(--text-primary); }
.tp-si-label {
  font-size: 10px; font-weight: 850; padding: 1px 5px; border-radius: 3px;
  background: rgba(239, 68, 68, 0.12); color: #dc2626;
}
.tp-si-gain { font-size: 16px; font-weight: 1100; font-variant-numeric: tabular-nums; }
.tp-si-gain.up { color: #dc2626; }
.tp-si-gain.down { color: #059669; }
.tp-si-gain.flat { color: var(--text-muted); }

.tp-si-mid {
  display: flex; align-items: center; justify-content: space-between;
}
.tp-si-code { font-size: 11px; font-weight: 700; color: var(--text-muted); }
.tp-si-price {
  font-size: 11px; font-weight: 700; color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.tp-si-reason {
  font-size: 12px; font-weight: 750; color: var(--text-secondary);
  line-height: 1.55; padding-top: 6px;
  border-top: 1px solid rgba(148, 163, 184, 0.10);
  display: flex; gap: 6px;
}
.tp-si-reason-label {
  font-size: 10px; font-weight: 950; padding: 1px 5px; border-radius: 3px;
  background: color-mix(in oklab, var(--theme-soft) 14%, transparent);
  color: var(--theme-accent); white-space: nowrap; flex-shrink: 0;
  align-self: flex-start; margin-top: 1px;
}

.tp-loading, .tp-error, .tp-empty {
  font-size: 12px; font-weight: 850; color: var(--text-muted);
  padding: 20px; text-align: center;
}
.tp-error { color: #ef4444; }
</style>
