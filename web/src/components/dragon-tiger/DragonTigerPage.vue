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

<style scoped src="./DragonTigerPage.css"></style>
