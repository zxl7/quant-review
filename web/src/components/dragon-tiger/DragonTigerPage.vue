<script setup lang="ts">
import { computed, onMounted } from 'vue';
import ShortReminderFooter from '../common/ShortReminderFooter.vue';
import { useDragonTiger } from './useDragonTiger';

const {
  loading,
  error,
  lastUpdated,
  dateOptions,
  selectedDate,
  rowCount,
  stockCount,
  focusNames,
  groupSummaries,
  selectedGroup,
  selectedGroupSummary,
  selectedRows,
  selectedStocks,
  selectedSeats,
  keyword,
  formatMoney,
  formatUnsignedMoney,
  formatSignedPct,
  marketLabel,
  xueqiuUrl,
  isThreeDay,
  setSelectedGroup,
  fetchRows,
  refresh,
} = useDragonTiger();

const displayedGroups = computed(() => {
  const list = [...groupSummaries.value];
  return list.sort((a, b) => Math.abs(b.net) - Math.abs(a.net)).slice(0, 18);
});

const stockRowsByGroup = (group: string) => selectedRows.value.filter((row) => row.yzmc === group);

const stockSummariesByGroup = (group: string) => {
  const map = new Map<string, any>();
  stockRowsByGroup(group).forEach((row) => {
    const prev = map.get(row.gpdm) || {
      code: row.gpdm,
      name: row.gpmc,
      net: 0,
      buy: 0,
      sell: 0,
      price: row.price,
      changePct: row.changePct,
    };
    prev.buy += row.mrje;
    prev.sell += row.mcje;
    prev.net += row.net;
    if (prev.price === undefined && row.price !== undefined) prev.price = row.price;
    if (prev.changePct === undefined && row.changePct !== undefined) prev.changePct = row.changePct;
    map.set(row.gpdm, prev);
  });
  return Array.from(map.values()).sort((a, b) => Math.abs(b.net) - Math.abs(a.net)).slice(0, 5);
};

const seatRowsByStock = (group: string, code: string) =>
  selectedRows.value.filter((row) => row.yzmc === group && row.gpdm === code);

onMounted(() => {
  void refresh(true);
});
</script>

<template>
  <div class="dragon-page">
    <div class="card dragon-card" data-page="dragonTiger" id="sec-dragon-tiger">
      <div class="card-header">
        <div>
          <div class="card-title">游资龙虎榜</div>
          <div class="dragon-subtitle">实时接口直连数据已改成本地注入 · 关系导图视图</div>
        </div>
        <div class="card-badge">LIVE</div>
      </div>

      <div class="dragon-toolbar">
        <div class="dragon-toolbar-left">
          <label class="dragon-date-picker">
            <span>日期</span>
            <select v-model="selectedDate" @change="fetchRows(selectedDate)">
              <option v-for="item in dateOptions" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <button class="dragon-btn" type="button" @click="refresh(true)">刷新本地数据</button>
          <input v-model="keyword" class="dragon-search" type="text" placeholder="筛选股票 / 营业部" />
        </div>
        <div class="dragon-toolbar-right">
          <span>游资 <b>{{ groupSummaries.length }}</b></span>
          <span>席位 <b>{{ rowCount }}</b></span>
          <span>个股 <b>{{ stockCount }}</b></span>
          <span v-if="lastUpdated">更新 <b>{{ lastUpdated }}</b></span>
        </div>
      </div>

      <div v-if="focusNames.length" class="dragon-focus-row">
        <button
          v-for="name in focusNames"
          :key="name"
          class="dragon-focus-chip"
          :class="{ active: selectedGroup === name }"
          type="button"
          @click="setSelectedGroup(name)">
          {{ name }}
        </button>
      </div>

      <div v-if="error" class="dragon-error">{{ error }}</div>

      <div class="dragon-summary-card">
        <div>
          <div class="dragon-main-title">{{ selectedGroupSummary?.name || '龙虎榜总览' }}</div>
          <div class="dragon-main-subtitle">
            <span v-if="selectedGroupSummary?.tags?.length">{{ selectedGroupSummary.tags.join(' · ') }}</span>
            <span v-else>只保留关系层级，不做花哨图表</span>
          </div>
        </div>
        <div class="dragon-summary-grid">
          <div class="dragon-kpi">
            <div class="dragon-kpi-label">总买入</div>
            <div class="dragon-kpi-value up">{{ formatMoney(selectedGroupSummary?.buy || 0) }}</div>
          </div>
          <div class="dragon-kpi">
            <div class="dragon-kpi-label">总卖出</div>
            <div class="dragon-kpi-value down">{{ formatMoney(-(selectedGroupSummary?.sell || 0)) }}</div>
          </div>
          <div class="dragon-kpi">
            <div class="dragon-kpi-label">净额</div>
            <div class="dragon-kpi-value" :class="(selectedGroupSummary?.net || 0) >= 0 ? 'up' : 'down'">
              {{ formatMoney(selectedGroupSummary?.net || 0) }}
            </div>
          </div>
          <div class="dragon-kpi">
            <div class="dragon-kpi-label">个股 / 席位</div>
            <div class="dragon-kpi-value neutral">{{ selectedGroupSummary?.stockCount || 0 }} / {{ selectedGroupSummary?.seatCount || 0 }}</div>
          </div>
        </div>
      </div>

      <div class="dragon-mindmap-container">
        <div class="dragon-mindmap">
          <!-- Root -->
          <div class="dragon-root-wrapper">
            <div class="dragon-root-node">
              <div class="dragon-root-label">龙虎榜</div>
              <div class="dragon-root-meta">{{ selectedDate || '--' }}</div>
            </div>
          </div>

          <!-- Branches -->
          <div class="dragon-branches">
            <div
              v-for="group in displayedGroups"
              :key="group.name"
              class="dragon-branch">
              
              <!-- Group Node -->
              <div class="dragon-group-node-wrapper">
                <div class="dragon-group-node">
                  <span class="dragon-group-name">{{ group.name }}</span>
                  <span class="dragon-group-net" :class="group.net >= 0 ? 'up' : 'down'">{{ formatMoney(group.net) }}</span>
                </div>
              </div>

              <!-- Stocks Column -->
              <div class="dragon-stocks-wrapper">
                <div v-for="stock in stockSummariesByGroup(group.name)" :key="stock.code" class="dragon-stock-branch">
                  <!-- Stock Node -->
                  <div class="dragon-stock-node-wrapper">
                    <div class="dragon-stock-node" :class="(stock.changePct || 0) >= 0 ? 'up' : 'down'">
                      <div class="dragon-stock-main">
                        <span v-if="isThreeDay(group.name, stock.code)" class="dragon-day-tag">3日</span>
                        <span class="dragon-stock-name">{{ stock.name }}</span>
                      </div>
                      <span class="dragon-stock-value">{{ formatMoney(stock.net) }}</span>
                    </div>
                  </div>

                  <!-- Seats Column -->
                  <div class="dragon-seats-wrapper">
                    <div v-for="row in seatRowsByStock(group.name, stock.code).slice(0, 3)" :key="`${row.yzmc}-${row.yyb}-${row.gpdm}-${row.sblx}`" class="dragon-seat-node">
                      <span class="dragon-seat-name">{{ row.yyb }}</span>
                      <span class="dragon-seat-net" :class="row.net >= 0 ? 'up' : 'down'">{{ formatMoney(row.net) }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="dragon-detail-strip">
        <div class="dragon-detail-block">
          <div class="dragon-detail-block-title">当前筛选个股</div>
          <div class="dragon-detail-chip-list">
            <a
              v-for="item in selectedStocks.slice(0, 8)"
              :key="item.code"
              class="dragon-detail-chip"
              :href="xueqiuUrl(item.code)"
              target="_blank"
              rel="noopener noreferrer">
              <span class="name">{{ item.name }}</span>
              <span class="value" :class="item.net >= 0 ? 'up' : 'down'">{{ formatMoney(item.net) }}</span>
            </a>
          </div>
        </div>

        <div class="dragon-detail-block">
          <div class="dragon-detail-block-title">当前筛选营业部</div>
          <div class="dragon-seat-list">
            <div v-for="item in selectedSeats.slice(0, 8)" :key="item.seat + item.type" class="dragon-seat-item">
              <div class="dragon-seat-name">{{ item.seat }}</div>
              <div class="dragon-seat-meta">
                <span>{{ item.type || '--' }}</span>
                <span :class="item.net >= 0 ? 'up' : 'down'">{{ formatMoney(item.net) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <ShortReminderFooter />
  </div>
</template>
