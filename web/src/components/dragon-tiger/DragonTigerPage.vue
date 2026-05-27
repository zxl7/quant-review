<script setup lang="ts">
import { onMounted, computed } from 'vue';
import { useDragonTiger, type DragonTigerRow } from './useDragonTiger';
import { useMarketData } from '../../composables/useMarketData';
import ShortReminderFooter from '../common/ShortReminderFooter.vue';

const { marketData } = useMarketData();
const { dateOptions: dates, rows: records, loading, error, selectedDate, refresh: init, formatMoney: fmtAmount } = useDragonTiger();

onMounted(() => init());

function xqUrl(code: string) {
  if (!code) return '#';
  const mkt = code.startsWith('6') ? 'SH' : 'SZ';
  return `https://xueqiu.com/S/${mkt}${code}`;
}

const getSector = (code: string) => {
  const idx = (marketData.value as any)?.watchlist_stock_index;
  if (!idx) return null;
  const info = idx[code];
  return info?.primary_sector || info?.main_line || null;
};

// 按股票分组，每只股票的买入前5和卖出前5分别排序
const stockGroups = computed(() => {
  const map = new Map<string, {
    code: string; name: string;
    totalBuy: number; totalSell: number;
    topBuy: DragonTigerRow[];  // 买入前5
    topSell: DragonTigerRow[]; // 卖出前5
  }>();
  for (const r of records.value) {
    const key = r.gpdm;
    if (!map.has(key)) {
      map.set(key, { code: r.gpdm, name: r.gpmc, totalBuy: 0, totalSell: 0, topBuy: [], topSell: [] });
    }
    const g = map.get(key)!;
    if (r.mrje != null) g.totalBuy += r.mrje;
    if (r.mcje != null) g.totalSell += r.mcje;
    g.topBuy.push(r);
    g.topSell.push(r);
  }

  const groups = Array.from(map.values());
  for (const g of groups) {
    // 买入前5：按 mrje 降序（只取有买入的）
    g.topBuy = g.topBuy
      .filter((r) => r.mrje != null)
      .sort((a, b) => (b.mrje || 0) - (a.mrje || 0))
      .slice(0, 5);
    // 卖出前5：按 mcje 降序（只取有卖出的）
    g.topSell = g.topSell
      .filter((r) => r.mcje != null)
      .sort((a, b) => (b.mcje || 0) - (a.mcje || 0))
      .slice(0, 5);
  }

  return groups.sort((a, b) => (b.totalBuy + b.totalSell) - (a.totalBuy + a.totalSell));
});
</script>

<template>
  <div class="card" data-page="dragonTiger" id="sec-dragon-tiger">
    <div class="dt-top-bar">
      <span class="dt-top-title">龙虎榜单</span>
      <select v-model="selectedDate" class="dt-date-select" @change="() => init()">
        <option v-for="d in dates" :key="d" :value="d">{{ d }}</option>
      </select>
    </div>

    <div v-if="loading" class="dt-sk-list">
      <div v-for="i in 8" :key="'sk-'+i" class="dt-sk-row">
        <div class="dt-sk-line w15"></div><div class="dt-sk-line w10"></div>
        <div class="dt-sk-line w20"></div><div class="dt-sk-line w25"></div>
      </div>
    </div>

    <div v-else-if="error" class="dt-error">{{ error }}</div>

    <div v-else class="dt-grid-container">
      <div v-for="sg in stockGroups" :key="sg.code" class="dt-stock-block">
        <!-- 股票头部 -->
        <div class="dt-stock-head">
          <span class="dt-stock-code">{{ sg.code }}</span>
          <a :href="xqUrl(sg.code)" target="_blank" rel="noopener" class="dt-link dt-stock-name">{{ sg.name }}</a>
          <span v-if="getSector(sg.code)" class="dt-stock-sector">{{ getSector(sg.code) }}</span>
          <span class="dt-stock-summary">
            <span class="dt-ss-buy">买 {{ fmtAmount(sg.totalBuy) }}</span>
            <span class="dt-ss-sell">卖 {{ fmtAmount(sg.totalSell) }}</span>
            <span :class="sg.totalBuy >= sg.totalSell ? 'dt-net-buy' : 'dt-net-sell'">
              {{ sg.totalBuy >= sg.totalSell ? '净买' : '净卖' }} {{ fmtAmount(Math.abs(sg.totalBuy - sg.totalSell)) }}
            </span>
          </span>
        </div>

        <!-- 买卖双栏 -->
        <div class="dt-columns">
          <!-- 买入前5 -->
          <div class="dt-col">
            <div class="dt-col-title dt-buy-title">买入前{{ sg.topBuy.length }}席</div>
            <div v-if="!sg.topBuy.length" class="dt-empty-col">--</div>
            <div v-for="(r, i) in sg.topBuy" :key="'b-'+i" class="dt-col-row">
              <span class="dt-rank-sm">{{ i + 1 }}</span>
              <span class="dt-col-trader">{{ r.yzmc }}</span>
              <span class="dt-col-amt dt-up">{{ fmtAmount(r.mrje) }}</span>
              <span class="dt-col-yyb">{{ r.yyb }}</span>
            </div>
          </div>
          <!-- 卖出前5 -->
          <div class="dt-col">
            <div class="dt-col-title dt-sell-title">卖出前{{ sg.topSell.length }}席</div>
            <div v-if="!sg.topSell.length" class="dt-empty-col">--</div>
            <div v-for="(r, i) in sg.topSell" :key="'s-'+i" class="dt-col-row">
              <span class="dt-rank-sm">{{ i + 1 }}</span>
              <span class="dt-col-trader">{{ r.yzmc }}</span>
              <span class="dt-col-amt dt-down">{{ fmtAmount(r.mcje) }}</span>
              <span class="dt-col-yyb">{{ r.yyb }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <ShortReminderFooter />
  </div>
</template>

<style scoped>
.dt-top-bar {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 14px; padding-bottom: 8px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
}
.dt-top-title { font-size: 16px; font-weight: 1050; color: var(--text-primary); }
.dt-date-select {
  padding: 4px 10px; border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text-primary); font-size: 12px; font-weight: 800;
  outline: none; cursor: pointer;
}
[data-theme="dark"] .dt-date-select { background: rgba(30, 41, 59, 0.5); color: var(--text-primary); }

.dt-sk-list { display: flex; flex-direction: column; gap: 6px; padding: 10px 0; }
.dt-sk-row { display: flex; gap: 8px; }
.dt-sk-line {
  height: 12px; border-radius: 3px;
  background: linear-gradient(90deg, rgba(148,163,184,0.12) 0%, rgba(148,163,184,0.30) 50%, rgba(148,163,184,0.12) 100%);
  background-size: 200% 100%; animation: dt-shimmer 1.4s infinite;
}
.dt-sk-line.w10 { width: 10%; } .dt-sk-line.w15 { width: 15%; }
.dt-sk-line.w20 { width: 20%; } .dt-sk-line.w25 { width: 25%; }
@keyframes dt-shimmer { 0% { background-position: -200% 0; } 100% { background-position: 200% 0; } }

/* Stock grid */
.dt-grid-container {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: 12px;
  align-items: start;
}

/* Stock block */
.dt-stock-block {
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg-card);
  padding: 10px 12px;
}
[data-theme="dark"] .dt-stock-block {
  background: rgba(30, 41, 59, 0.4);
  border-color: rgba(148, 163, 184, 0.12);
}

/* Stock header */
.dt-stock-head {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 8px; padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.dt-stock-code { font-size: 12px; font-weight: 900; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.dt-stock-name { font-size: 14px; font-weight: 1050; }
.dt-stock-sector {
  font-size: 10px; font-weight: 800; color: var(--text-muted);
  background: rgba(148, 163, 184, 0.1); padding: 1px 6px; border-radius: 4px;
  white-space: nowrap;
}
.dt-stock-summary { margin-left: auto; display: flex; gap: 8px; font-size: 11px; font-weight: 900; }
.dt-ss-buy { color: #dc2626; }
.dt-ss-sell { color: #059669; }
.dt-net-buy { color: #dc2626; }
.dt-net-sell { color: #059669; }

/* Dual columns */
.dt-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.dt-col { min-width: 0; }

.dt-col-title {
  font-size: 10px; font-weight: 950; padding-bottom: 4px; margin-bottom: 4px;
  border-bottom: 2px solid transparent;
}
.dt-buy-title { color: #dc2626; border-color: rgba(220, 38, 38, 0.25); }
.dt-sell-title { color: #059669; border-color: rgba(5, 150, 105, 0.25); }

.dt-col-row {
  display: flex; align-items: center; gap: 4px; padding: 2px 0;
  font-size: 10px;
}
.dt-rank-sm {
  width: 14px; text-align: center; flex-shrink: 0;
  font-weight: 1000; color: var(--text-muted); font-size: 9px;
}
.dt-col-trader {
  font-weight: 850; color: var(--text-primary);
  width: 54px; flex-shrink: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.dt-col-amt {
  font-weight: 900; font-variant-numeric: tabular-nums;
  white-space: nowrap; margin-left: auto;
  min-width: 42px; text-align: right;
}
.dt-col-yyb {
  font-size: 9px; color: var(--text-muted); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; flex: 1;
  min-width: 0; margin-left: 6px;
}

.dt-up { color: #dc2626; }
.dt-down { color: #059669; }
.dt-empty-col { font-size: 10px; color: var(--text-muted); padding: 4px 0; }

.dt-link { color: #2563eb; text-decoration: none; }
[data-theme="dark"] .dt-link { color: #60a5fa; }
.dt-link:hover { text-decoration: underline; }
.dt-error { font-size: 12px; font-weight: 850; color: #ef4444; padding: 30px; text-align: center; }

@media (max-width: 640px) {
  .dt-grid-container {
    grid-template-columns: 1fr;
  }
}
</style>
