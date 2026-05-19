<script setup lang="ts">
import { computed, ref } from 'vue';
import { useMarketData } from '../../composables/useMarketData';
import ShortReminderFooter from '../common/ShortReminderFooter.vue';

const { marketData } = useMarketData();

const abnormalFilterST = ref(true);
const abnormalSelectedTypes = ref<number[]>([10009]);
const abnormalLoading = computed(() => false);
const abnormalError = computed(() => '');
const abnormalHasMore = computed(() => false);
const abnormalEvents = computed(() => Array.isArray(marketData.value?.abnormalEvents) ? marketData.value.abnormalEvents : []);

const abnormalPlateTypeOptions = computed(() => [
  { type: 11000, label: '板块拉升' },
  { type: 11001, label: '板块跳水' },
]);

const abnormalStockTypeOptions = computed(() => [
  { type: 10001, label: '封涨停板' },
  { type: 10005, label: '逼近涨停' },
  { type: 10003, label: '打开涨停' },
  { type: 10007, label: '将开涨停' },
  { type: 10002, label: '封跌停板' },
  { type: 10006, label: '逼近跌停' },
  { type: 10004, label: '打开跌停' },
  { type: 10008, label: '将开跌停' },
  { type: 10014, label: '开板回封' },
  { type: 10009, label: '大幅拉升' },
  { type: 10010, label: '快速跳水' },
  { type: 10012, label: '新股开板' },
]);

const abnormalSelectedPlateTypes = computed(() => abnormalSelectedTypes.value.filter((x) => x >= 11000));
const abnormalSelectedStockTypes = computed(() => abnormalSelectedTypes.value.filter((x) => x < 11000));
const abnormalDisplayEvents = computed(() =>
  abnormalEvents.value.slice().sort((a: any, b: any) => {
    const diff = Number(b?.watchScore || 0) - Number(a?.watchScore || 0);
    if (diff) return diff;
    return Number(b?.eventTimestamp || 0) - Number(a?.eventTimestamp || 0);
  }),
);
const abnormalPlateEvents = computed(() => abnormalDisplayEvents.value.filter((item: any) => item && item.isPlate));
const abnormalStockEvents = computed(() => abnormalDisplayEvents.value.filter((item: any) => item && !item.isPlate));

const toggleAbnormalType = (type: number) => {
  const idx = abnormalSelectedTypes.value.indexOf(type);
  if (idx >= 0) abnormalSelectedTypes.value.splice(idx, 1);
  else abnormalSelectedTypes.value.push(type);
};

const toggleAbnormalSTFilter = () => {
  abnormalFilterST.value = !abnormalFilterST.value;
};

const abnormalValueClass = (value?: string | null) => {
  const text = String(value || '');
  if (!text) return '';
  if (text.includes('+') || text.includes('拉升') || text.includes('涨')) return 'red-text';
  if (text.includes('-') || text.includes('跳水') || text.includes('跌')) return 'green-text';
  return 'orange-text';
};

const abnormalPriorityTone = (item: any) => item?.priorityTone || item?.tone || '';
const abnormalCardClass = (item: any) => [item?.tone || '', item?.isWarn ? 'warn' : ''].filter(Boolean).join(' ');

const abnormalOpenSymbol = (symbol?: string | null) => {
  const raw = String(symbol || '').trim();
  if (!raw || typeof window === 'undefined') return;
  const market = raw.startsWith('6') ? 'SH' : 'SZ';
  window.open(`https://xueqiu.com/S/${market}${raw}`, '_blank', 'noopener');
};

const abnormalCopyCode = async (code?: string | null) => {
  const text = String(code || '').trim();
  if (!text || typeof navigator === 'undefined' || !navigator.clipboard) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch {}
};

const onAbnormalItemClick = (item: any) => {
  if (item?.primarySymbol) abnormalOpenSymbol(item.primarySymbol);
};

const refreshAbnormalEvents = (_force = false) => {};
const abnormalHandleScroll = () => {};
</script>

<template>
  <div class="abnormal-page">
    <div class="card" data-page="abnormal" id="sec-abnormal">
      <div class="abnormal-panel">
        <div class="abnormal-head">
          <div class="abnormal-head-main">
            <div class="title">超短异动提醒</div>
            <div class="meta">3秒刷新 · 个股实时 · 板块续拉</div>
          </div>
          <div class="action">
            <span class="wb-chip" :class="{ on: abnormalFilterST }">过滤ST</span>
            <button class="abnormal-btn" type="button" @click="refreshAbnormalEvents(true)">刷新</button>
          </div>
        </div>
        <div class="abnormal-settings">
          <div class="abnormal-section-title">
            <span>板块</span>
            <span class="meta">{{ abnormalSelectedPlateTypes.length }} 项</span>
          </div>
          <div class="abnormal-switch-row">
            <label class="abnormal-switch" v-for="item in abnormalPlateTypeOptions" :key="'apt-'+item.type">
              <input type="checkbox" :checked="abnormalSelectedTypes.includes(item.type)" @change="toggleAbnormalType(item.type)">
              <span>{{ item.label }}</span>
            </label>
          </div>
          <div class="abnormal-section-title">
            <span>个股</span>
            <span class="meta">{{ abnormalSelectedStockTypes.length }} 项</span>
          </div>
          <div class="abnormal-switch-row">
            <label class="abnormal-switch" v-for="item in abnormalStockTypeOptions" :key="'ast-'+item.type">
              <input type="checkbox" :checked="abnormalSelectedTypes.includes(item.type)" @change="toggleAbnormalType(item.type)">
              <span>{{ item.label }}</span>
            </label>
          </div>
          <div class="abnormal-filter">
            <div>
              <div class="label">筛选</div>
              <div class="tip">保留全量类型，后续再收口</div>
            </div>
            <button class="abnormal-btn" type="button" @click="toggleAbnormalSTFilter()">{{ abnormalFilterST ? '已过滤ST' : '显示ST' }}</button>
          </div>
        </div>
        <div class="abnormal-list-wrap abnormal-scroll" @scroll="abnormalHandleScroll">
          <div v-if="abnormalLoading && !abnormalEvents.length" class="abnormal-loading">正在拉取异动数据...</div>
          <div v-else-if="abnormalError" class="abnormal-error">{{ abnormalError }}</div>
          <div v-else-if="!abnormalDisplayEvents.length" class="abnormal-empty">当前没有符合筛选条件的异动</div>
          <div v-else class="abnormal-columns">
            <div class="abnormal-column plate-column">
              <div class="abnormal-col-head">
                <div class="abnormal-col-title">板块异动</div>
                <div class="abnormal-col-meta">{{ abnormalPlateEvents.length }} 条</div>
              </div>
              <div class="abnormal-list">
                <article class="abnormal-item" :class="abnormalCardClass(item)" v-for="item in abnormalPlateEvents" :key="item.id" @click="onAbnormalItemClick(item)">
                  <div class="abnormal-top">
                    <div>
                      <div class="abnormal-name">{{ item.title }}</div>
                      <div class="abnormal-priority" :class="abnormalPriorityTone(item)" v-if="item.priorityLabel">{{ item.priorityLabel }}</div>
                    </div>
                    <div class="abnormal-time">{{ item.time }}</div>
                  </div>
                  <div class="abnormal-sub">{{ item.subtitle }}</div>
                  <div class="abnormal-tags">
                    <span class="abnormal-tag" :class="item.tone" v-if="item.eventTypeLabel">{{ item.eventTypeLabel }}</span>
                    <span class="abnormal-tag" :class="abnormalPriorityTone(item)" v-if="item.scoreText">{{ item.scoreText }}</span>
                    <span class="abnormal-tag" :class="item.valueTone" v-if="item.valueText">{{ item.valueText }}</span>
                    <span class="abnormal-tag" v-for="(tag, idx) in item.tags" :key="'abt-p-'+item.id+'-'+idx">{{ tag }}</span>
                  </div>
                  <div class="abnormal-sublines" v-if="item.relatedRows && item.relatedRows.length">
                    <div class="abnormal-subline" v-for="(row, idx) in item.relatedRows" :key="'asr-p-'+item.id+'-'+idx">
                      <div class="abnormal-subleft">
                        <span class="abnormal-subname" :class="{ 'abnormal-link': row.code }" @click.stop="row.code && abnormalOpenSymbol(row.code)">{{ row.name }}</span>
                        <span class="abnormal-subcode" :class="{ 'abnormal-link': row.code }" v-if="row.code" @click.stop="abnormalOpenSymbol(row.code)">({{ row.code }})</span>
                        <button class="abnormal-copy" v-if="row.code" type="button" @click.stop="abnormalCopyCode(row.code)">复制</button>
                      </div>
                      <div class="abnormal-subleft">
                        <span class="abnormal-submeta strong" :class="abnormalValueClass(row.mtmText)" v-if="row.mtmText">{{ row.mtmText }}</span>
                        <span class="abnormal-submeta strong" :class="abnormalValueClass(row.pcpText)" v-if="row.pcpText">{{ row.pcpText }}</span>
                      </div>
                    </div>
                  </div>
                </article>
              </div>
            </div>

            <div class="abnormal-column">
              <div class="abnormal-col-head">
                <div class="abnormal-col-title">个股异动</div>
                <div class="abnormal-col-meta">{{ abnormalStockEvents.length }} 条</div>
              </div>
              <div class="abnormal-list">
                <article class="abnormal-item" :class="abnormalCardClass(item)" v-for="item in abnormalStockEvents" :key="item.id" @click="onAbnormalItemClick(item)">
                  <div class="abnormal-top">
                    <div>
                      <div class="abnormal-name">{{ item.title }}</div>
                      <div class="abnormal-priority" :class="abnormalPriorityTone(item)" v-if="item.priorityLabel">{{ item.priorityLabel }}</div>
                    </div>
                    <div class="abnormal-time">{{ item.time }}</div>
                  </div>
                  <div class="abnormal-sub">{{ item.subtitle }}</div>
                  <div class="abnormal-tags">
                    <span class="abnormal-tag" :class="item.tone" v-if="item.eventTypeLabel">{{ item.eventTypeLabel }}</span>
                    <span class="abnormal-tag" :class="abnormalPriorityTone(item)" v-if="item.scoreText">{{ item.scoreText }}</span>
                    <span class="abnormal-tag" :class="item.valueTone" v-if="item.valueText">{{ item.valueText }}</span>
                    <span class="abnormal-tag" v-for="(tag, idx) in item.tags" :key="'abt-s-'+item.id+'-'+idx">{{ tag }}</span>
                  </div>
                  <div class="abnormal-sublines" v-if="item.relatedRows && item.relatedRows.length">
                    <div class="abnormal-subline" v-for="(row, idx) in item.relatedRows" :key="'asr-s-'+item.id+'-'+idx">
                      <div class="abnormal-subleft">
                        <span class="abnormal-subname" :class="{ 'abnormal-link': row.code }" @click.stop="row.code && abnormalOpenSymbol(row.code)">{{ row.name }}</span>
                        <span class="abnormal-subcode" :class="{ 'abnormal-link': row.code }" v-if="row.code" @click.stop="abnormalOpenSymbol(row.code)">({{ row.code }})</span>
                        <button class="abnormal-copy" v-if="row.code" type="button" @click.stop="abnormalCopyCode(row.code)">复制</button>
                      </div>
                      <div class="abnormal-subleft">
                        <span class="abnormal-submeta strong" :class="abnormalValueClass(row.mtmText)" v-if="row.mtmText">{{ row.mtmText }}</span>
                        <span class="abnormal-submeta strong" :class="abnormalValueClass(row.pcpText)" v-if="row.pcpText">{{ row.pcpText }}</span>
                      </div>
                    </div>
                  </div>
                </article>
              </div>
            </div>
          </div>
          <div class="abnormal-more" v-if="abnormalHasMore && abnormalSelectedTypes.length && abnormalSelectedTypes.every((type) => Number(type) >= 11000)">
            <button class="abnormal-btn" type="button" @click="refreshAbnormalEvents(false)">加载更多</button>
          </div>
        </div>
      </div>
    </div>

    <ShortReminderFooter />
  </div>
</template>
