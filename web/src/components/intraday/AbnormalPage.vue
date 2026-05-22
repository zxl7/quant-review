<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import ShortReminderFooter from '../common/ShortReminderFooter.vue';
import { useMarketData } from '../../composables/useMarketData';

type AbnormalRow = {
  name: string;
  code: string;
  mtmText?: string;
  pcpText?: string;
};

type AbnormalScoreKind = 'opportunity' | 'risk' | 'observe';

type AbnormalItem = {
  id: string;
  isPlate: boolean;
  title: string;
  time: string;
  subtitle: string;
  eventTypeLabel: string;
  valueText: string;
  momentText?: string;
  momentTone?: string;
  tone: string;
  valueTone: string;
  watchScore: number;
  scoreText: string;
  scoreLabel: string;
  scoreKind: AbnormalScoreKind;
  priorityLevel: string;
  priorityLabel: string;
  tags: string[];
  relatedRows: AbnormalRow[];
  primarySymbol: string;
  primaryCode?: string;
  eventType: number;
  eventTimestamp: number;
  extraCount?: number;
  mergedTitles?: string[];
  coreBadges?: string[];
  aggregateKey?: string;
  themeKey?: string;
};

const { marketData } = useMarketData();

const abnormalFilterST = ref(true);
const abnormalSelectedTypes = ref<number[]>([11000, 11001, 10005, 10009, 10010]);
const abnormalLoading = ref(false);
const abnormalError = ref('');
const abnormalHasMore = ref(false);
const abnormalEvents = ref<AbnormalItem[]>([]);
const abnormalLastTimestamp = ref<number | null>(null);
const abnormalLastRequestTime = ref(0);
const abnormalExpandedKeys = ref<string[]>([]);

let abnormalTimer: number | null = null;
let abnormalReqInFlight = false;

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

const collectRowTags = (row: any) => {
  if (Array.isArray(row?.tagRows) && row.tagRows.length) {
    return row.tagRows.flatMap((x: any) => (Array.isArray(x?.tags) ? x.tags : [])).map((x: any) => String(x?.text || '').trim()).filter(Boolean);
  }
  return Array.isArray(row?.tags) ? row.tags.map((x: any) => String(x?.text || x || '').trim()).filter(Boolean) : [];
};

const abnormalCoreStockMap = computed(() => {
  const map = new Map<string, Set<string>>();
  const push = (codeLike: unknown, labels: string[]) => {
    const code = String(codeLike || '').trim().replace(/\..*$/, '');
    if (!code) return;
    const slot = map.get(code) || new Set<string>();
    labels.filter(Boolean).forEach((x) => slot.add(x));
    map.set(code, slot);
  };

  const relay = Array.isArray(marketData.value?.ztAnalysis?.relay) ? marketData.value.ztAnalysis.relay : [];
  relay.forEach((row: any) => push(row?.code, ['主升']));

  const watch = Array.isArray(marketData.value?.ztAnalysis?.watch) ? marketData.value.ztAnalysis.watch : [];
  watch.forEach((row: any) => push(row?.code, ['观察']));

  const ladder = Array.isArray(marketData.value?.ladder) ? marketData.value.ladder : [];
  ladder.forEach((row: any) => {
    const labels = [];
    if (Number(row?.badge || 0) >= 5) labels.push('情绪龙');
    if (Number(row?.badge || 0) >= 3) labels.push('高标');
    if (collectRowTags(row).some((x: string) => /高换手|换手/.test(x))) labels.push('容量');
    push(row?.code || row?.dm, labels);
  });

  const top10 = Array.isArray(marketData.value?.top10) ? marketData.value.top10 : [];
  top10.slice(0, 5).forEach((row: any) => push(row?.code, ['容量']));

  return map;
});

const abnormalEventMetaMap: Record<number, { label: string; tone: string }> = {
  10001: { label: '封涨停板', tone: 'red' },
  10002: { label: '封跌停板', tone: 'green' },
  10003: { label: '打开涨停', tone: 'orange' },
  10004: { label: '打开跌停', tone: 'orange' },
  10005: { label: '逼近涨停', tone: 'red' },
  10006: { label: '逼近跌停', tone: 'green' },
  10007: { label: '将开涨停', tone: 'orange' },
  10008: { label: '将开跌停', tone: 'orange' },
  10009: { label: '大幅拉升', tone: 'red' },
  10010: { label: '快速跳水', tone: 'green' },
  10012: { label: '新股开板', tone: 'orange' },
  10014: { label: '开板回封', tone: 'red' },
  11000: { label: '板块拉升', tone: 'red' },
  11001: { label: '板块跳水', tone: 'green' },
};

const abnormalEventMeta = (eventType: number) => abnormalEventMetaMap[eventType] || { label: `异动 ${eventType}`, tone: 'orange' };

const decorateCoreBadges = (item: AbnormalItem) => {
  const code = String(item?.primarySymbol || item?.primaryCode || '').trim();
  if (!code) return [];
  const hit = abnormalCoreStockMap.value.get(code);
  if (!hit) return [];
  const order = ['主升', '情绪龙', '容量', '高标', '观察'];
  return order.filter((x) => hit.has(x)).slice(0, 3);
};

const abnormalMergeTexts = (values: string[], limit = 6) =>
  Array.from(new Set((Array.isArray(values) ? values : []).map((x) => String(x || '').trim()).filter(Boolean))).slice(0, limit);

const abnormalDeriveAggregateFields = (item: AbnormalItem): AbnormalItem => {
  const meta = abnormalEventMeta(item.eventType);
  const priorityMeta = abnormalPriorityMeta(item.eventType, Number(item.watchScore || 0));
  const scoreKind = abnormalScoreKind(item.eventType);
  const tags = abnormalMergeTexts(item.tags || [], item.isPlate ? 6 : 5);
  const extraCount = Number(item.extraCount || 0);
  let subtitle = item.subtitle || '';
  if (item.isPlate) {
    subtitle = extraCount > 0 ? `板块连续异动：${item.title} +${extraCount}` : `相关个股：${tags.join(' / ') || '无'}`;
  } else if (item.themeKey) {
    subtitle = extraCount > 0 ? `同题材异动：${item.themeKey} +${extraCount}` : `关联板块：${tags.join(' / ') || '无'}`;
  } else {
    subtitle = `关联板块：${tags.join(' / ') || '无'}`;
  }
  return {
    ...item,
    tone: meta.tone,
    eventTypeLabel: meta.label,
    priorityLevel: priorityMeta.level,
    priorityLabel: priorityMeta.label,
    scoreKind,
    scoreLabel: abnormalScoreLabel(item.eventType),
    scoreText: `${Number(item.watchScore || 0)}分`,
    subtitle,
    tags,
    valueTone: abnormalToPct(item.valueText) > 0 ? 'red' : abnormalToPct(item.valueText) < 0 ? 'green' : 'orange',
    momentTone: abnormalToPct(item.momentText) > 0 ? 'red' : abnormalToPct(item.momentText) < 0 ? 'green' : 'orange',
  };
};

const aggregateAbnormalItems = (items: AbnormalItem[]) => {
  const merged = new Map<string, AbnormalItem>();
  const order: string[] = [];
  for (const item of items) {
    const themeKey = !item.isPlate ? String(item.themeKey || item.tags[0] || '').trim() : '';
    const key = item.isPlate
      ? `plate:${item.title}:${item.eventType}`
      : themeKey
        ? `theme:${themeKey}:${item.eventType}`
        : `stock:${item.primarySymbol || item.title}:${item.eventType}`;
    const prev = merged.get(key);
    if (!prev) {
      merged.set(key, {
        ...item,
        extraCount: 0,
        mergedTitles: [item.title],
        aggregateKey: key,
      });
      order.push(key);
      continue;
    }
    prev.extraCount = Number(prev.extraCount || 0) + 1;
    prev.mergedTitles = abnormalMergeTexts([...(prev.mergedTitles || []), item.title], 4);
    prev.tags = abnormalMergeTexts([...(prev.tags || []), ...(item.tags || [])], prev.isPlate ? 6 : 5);
    prev.watchScore = Math.max(Number(prev.watchScore || 0), Number(item.watchScore || 0));
    if (Number(item.eventTimestamp || 0) > Number(prev.eventTimestamp || 0)) {
      prev.time = item.time;
      prev.eventTimestamp = item.eventTimestamp;
      prev.valueText = item.valueText || prev.valueText;
      prev.momentText = item.momentText || prev.momentText;
      prev.valueTone = item.valueTone || prev.valueTone;
      prev.momentTone = item.momentTone || prev.momentTone;
      prev.relatedRows = Array.isArray(item.relatedRows) ? item.relatedRows : prev.relatedRows;
    }
  }
  return order.map((key) => abnormalDeriveAggregateFields(merged.get(key)!)).filter(Boolean);
};

const abnormalDisplayEvents = computed(() =>
  aggregateAbnormalItems(
    abnormalEvents.value
      .map((item) => ({
        ...item,
        coreBadges: decorateCoreBadges(item),
      }))
      .slice()
      .sort((a, b) => {
        const rankDiff = abnormalSortRank(a) - abnormalSortRank(b);
        if (rankDiff) return rankDiff;
        const weightDiff = abnormalSortWeight(b) - abnormalSortWeight(a);
        if (weightDiff) return weightDiff;
        return Number(b?.eventTimestamp || 0) - Number(a?.eventTimestamp || 0);
      }),
  ).map((item) => ({
    ...item,
    coreBadges: decorateCoreBadges(item),
  })),
);
const abnormalPlateEvents = computed(() => abnormalDisplayEvents.value.filter((item) => item && item.isPlate));
const abnormalStockEvents = computed(() => abnormalDisplayEvents.value.filter((item) => item && !item.isPlate));

const toggleAbnormalType = (type: number) => {
  const idx = abnormalSelectedTypes.value.indexOf(type);
  if (idx >= 0) abnormalSelectedTypes.value.splice(idx, 1);
  else abnormalSelectedTypes.value.push(type);
  startAbnormalPolling(true);
};

const toggleAbnormalSTFilter = () => {
  abnormalFilterST.value = !abnormalFilterST.value;
  void refreshAbnormalEvents(true);
};

const abnormalValueClass = (value?: string | null) => {
  const text = String(value || '');
  if (!text) return '';
  if (text.includes('+') || text.includes('拉升') || text.includes('涨')) return 'red-text';
  if (text.includes('-') || text.includes('跳水') || text.includes('跌')) return 'green-text';
  return 'orange-text';
};

const abnormalToPct = (value?: string | null) => {
  const n = Number(String(value || '').replace('%', '').trim());
  return Number.isFinite(n) ? n : 0;
};

const abnormalRowToneClass = (row: AbnormalRow) => {
  const raw = String(row?.pcpText || '').trim();
  if (!raw) return '';
  const n = Number(raw.replace('%', ''));
  if (!Number.isFinite(n)) return abnormalValueClass(raw);
  if (n > 0) return 'red-text';
  if (n < 0) return 'green-text';
  return 'orange-text';
};

const abnormalPriorityTone = (item: AbnormalItem) => item?.priorityLevel || item?.tone || '';
const abnormalCardClass = (item: AbnormalItem) => [item?.tone || '', item?.watchScore >= 62 ? 'urgent' : ''].filter(Boolean).join(' ');
const abnormalIsExpanded = (item: AbnormalItem) => abnormalExpandedKeys.value.includes(String(item.aggregateKey || item.id || ''));
const toggleAbnormalExpanded = (item: AbnormalItem) => {
  const key = String(item.aggregateKey || item.id || '');
  if (!key) return;
  const idx = abnormalExpandedKeys.value.indexOf(key);
  if (idx >= 0) abnormalExpandedKeys.value.splice(idx, 1);
  else abnormalExpandedKeys.value.push(key);
};

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

const formatAbnormalTime = (timestamp: unknown) => {
  if (timestamp === undefined || timestamp === null || timestamp === '') return '--';
  const n = Number(timestamp);
  const d = Number.isFinite(n) ? new Date(n * 1000) : new Date(String(timestamp));
  if (!(d instanceof Date) || Number.isNaN(d.getTime())) return '--';
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
};

const abnormalBuildScore = (eventType: number, valuePct: number, eventTimestamp: unknown) => {
  const value = Math.abs(Number(valuePct || 0));
  let score = 28;
  if ([10001, 10005, 10014, 11000].includes(eventType)) score += 12;
  else if ([10009].includes(eventType)) score += 10;
  else if ([10002, 10006, 11001, 10010, 10004, 10008].includes(eventType)) score += 9;
  else if ([10003, 10007, 10012].includes(eventType)) score += 4;

  if ([10002, 10006, 11001, 10010, 10004, 10008].includes(eventType)) {
    score += Math.min(12, value * 0.9);
  } else {
    score += Math.min(16, value * 1.3);
  }

  const hhmm = formatAbnormalTime(eventTimestamp).slice(0, 5);
  if (hhmm >= '09:30' && hhmm <= '10:00') score += 3;
  if (hhmm >= '14:20') score += 2;
  return Math.max(0, Math.min(100, Math.round(score)));
};

const abnormalPriorityMeta = (eventType: number, score: number) => {
  const riskTypes = [10002, 10004, 10006, 10008, 10010, 11001];
  if (riskTypes.includes(eventType)) {
    if (score >= 60) return { level: 'high', label: '风险预警' };
    if (score >= 45) return { level: 'mid', label: '风险观察' };
    return { level: 'low', label: '普通提醒' };
  }
  if (score >= 62) return { level: 'high', label: '高优先级' };
  if (score >= 48) return { level: 'mid', label: '重点观察' };
  return { level: 'low', label: '普通提醒' };
};

const abnormalScoreKind = (eventType: number): AbnormalScoreKind => {
  const riskTypes = [10002, 10004, 10006, 10008, 10010, 11001];
  const observeTypes = [10003, 10007, 10012];
  if (riskTypes.includes(eventType)) return 'risk';
  if (observeTypes.includes(eventType)) return 'observe';
  return 'opportunity';
};

const abnormalScoreLabel = (eventType: number) => {
  const kind = abnormalScoreKind(eventType);
  if (kind === 'risk') return '风险分';
  if (kind === 'observe') return '观察分';
  return '机会分';
};

const abnormalSortRank = (item: AbnormalItem) => {
  if (item?.scoreKind === 'opportunity') return 0;
  if (item?.scoreKind === 'observe') return 1;
  return 2;
};

const abnormalCoreRank = (item: AbnormalItem) => {
  const badges = Array.isArray(item?.coreBadges) ? item.coreBadges : [];
  let score = 0;
  if (badges.includes('主升')) score += 9;
  if (badges.includes('情绪龙')) score += 7;
  if (badges.includes('容量')) score += 4;
  if (badges.includes('高标')) score += 3;
  if (badges.includes('观察')) score += 1;
  return score;
};

const abnormalSortWeight = (item: AbnormalItem) => {
  const score = Number(item?.watchScore || 0);
  const pcp = Math.abs(abnormalToPct(item?.valueText));
  const mtm = Math.abs(abnormalToPct(item?.momentText));
  const themeBoost = Number(item?.extraCount || 0);
  const coreBoost = abnormalCoreRank(item);
  return score * 100 + coreBoost * 10 + mtm * 3 + pcp * 2 + themeBoost;
};

const parseAbnormalItem = (event: any): AbnormalItem | null => {
  if (!event || typeof event !== 'object') return null;
  const eventType = Number(event.event_type || 0);
  const isPlate = eventType >= 11000;
  const meta = abnormalEventMeta(eventType);
  if (isPlate) {
    const plate = event.plate_abnormal_event_data || {};
    const valuePct = Number(plate.pcp || 0) * 100;
    const watchScore = abnormalBuildScore(eventType, valuePct, event.event_timestamp);
    const rel = Array.isArray(plate.related_stocks) ? plate.related_stocks.slice(0, 4) : [];
    const tags = rel.map((x: any) => String(x.name || '').trim()).filter(Boolean);
    const relatedRows = rel.map((x: any) => ({
      name: String(x?.name || '').trim(),
      code: String(x?.symbol || '').trim().replace(/\..*$/, ''),
      mtmText: x?.mtm !== undefined && x?.mtm !== null ? `${Number(x.mtm * 100).toFixed(2)}%` : '',
      pcpText: x?.pcp !== undefined && x?.pcp !== null ? `${Number(x.pcp * 100).toFixed(2)}%` : '',
    }));
    const valueText = plate.pcp !== undefined && plate.pcp !== null ? `${(Number(plate.pcp) * 100).toFixed(2)}%` : '';
    const momentText = plate.mtm !== undefined && plate.mtm !== null ? `${(Number(plate.mtm) * 100).toFixed(2)}%` : '';
    return {
      id: `${event.event_type}-${event.event_timestamp}-${plate.plate_name || ''}`,
      isPlate: true,
      title: plate.plate_name || meta.label,
      time: formatAbnormalTime(event.event_timestamp),
      subtitle: `相关个股：${tags.join(' / ') || '无'}`,
      eventTypeLabel: meta.label,
      valueText,
      momentText,
      momentTone: Number(plate.mtm || 0) >= 0 ? 'red' : 'green',
      tone: meta.tone,
      valueTone: Number(plate.pcp || 0) >= 0 ? 'red' : 'green',
      watchScore,
      scoreText: `${watchScore}分`,
      scoreLabel: abnormalScoreLabel(eventType),
      scoreKind: abnormalScoreKind(eventType),
      priorityLevel: abnormalPriorityMeta(eventType, watchScore).level,
      priorityLabel: abnormalPriorityMeta(eventType, watchScore).label,
      tags,
      relatedRows,
      primarySymbol: relatedRows[0]?.code || '',
      eventType,
      eventTimestamp: Number(event.event_timestamp || 0),
      themeKey: '',
    };
  }

  const stock = event.stock_abnormal_event_data || {};
  const valuePct = Number(stock.pcp || 0) * 100;
  const watchScore = abnormalBuildScore(eventType, valuePct, event.event_timestamp);
  const relPlates = Array.isArray(stock.related_plates) ? stock.related_plates.slice(0, 4) : [];
  const tags = relPlates.map((x: any) => String(x.plate_name || '').trim()).filter(Boolean);
  const relatedRows = relPlates.map((x: any) => ({
    name: String(x?.plate_name || '').trim(),
    code: '',
    pcpText: x?.plate_pcp !== undefined && x?.plate_pcp !== null ? `${Number(x.plate_pcp * 100).toFixed(2)}%` : '',
    mtmText: '',
  }));
  const primarySymbol = String(event.target || '').trim().replace(/\..*$/, '');
  const valueText = stock.pcp !== undefined && stock.pcp !== null ? `${(Number(stock.pcp) * 100).toFixed(2)}%` : '';
  const momentText = stock.mtm !== undefined && stock.mtm !== null ? `${(Number(stock.mtm) * 100).toFixed(2)}%` : '';
  return {
    id: `${event.event_type}-${event.event_timestamp}-${stock.name || ''}`,
    isPlate: false,
    title: stock.name || meta.label,
    time: formatAbnormalTime(event.event_timestamp),
    subtitle: tags.length ? `关联板块：${tags.join(' / ')}` : '关联板块：无',
    eventTypeLabel: meta.label,
    valueText,
    momentText,
    momentTone: Number(stock.mtm || 0) >= 0 ? 'red' : 'green',
    tone: meta.tone,
    valueTone: Number(stock.pcp || 0) >= 0 ? 'red' : 'green',
    watchScore,
    scoreText: `${watchScore}分`,
    scoreLabel: abnormalScoreLabel(eventType),
    scoreKind: abnormalScoreKind(eventType),
    priorityLevel: abnormalPriorityMeta(eventType, watchScore).level,
    priorityLabel: abnormalPriorityMeta(eventType, watchScore).label,
    tags,
    relatedRows,
    primarySymbol,
    primaryCode: primarySymbol,
    eventType,
    eventTimestamp: Number(event.event_timestamp || 0),
    themeKey: tags[0] || '',
  };
};

const onAbnormalItemClick = (item: AbnormalItem) => {
  if (item?.primarySymbol) abnormalOpenSymbol(item.primarySymbol);
};

const refreshAbnormalEvents = async (force = false) => {
  try {
    const now = Date.now();
    if (!force && now - Number(abnormalLastRequestTime.value || 0) < 1000) return;
    if (abnormalReqInFlight) return;
    abnormalReqInFlight = true;
    abnormalLastRequestTime.value = now;
    abnormalLoading.value = true;
    abnormalError.value = '';
    let url = 'https://flash-api.xuangubao.cn/api/event/history?count=50';
    if (abnormalSelectedTypes.value.length) url += `&types=${abnormalSelectedTypes.value.join(',')}`;
    const isStockEvent = abnormalSelectedTypes.value.some((type) => Number(type) < 11000);
    if (!force && !isStockEvent && abnormalLastTimestamp.value) {
      url += `&timestamp=${Number(abnormalLastTimestamp.value) - 3}`;
    }
    const res = await fetch(`${url}&_ts=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const rows = Array.isArray(json?.data) ? json.data : [];
    const items = rows.map((x: any) => parseAbnormalItem(x)).filter(Boolean) as AbnormalItem[];
    const filtered = abnormalFilterST.value
      ? items.filter((it) => !(String(it.title || '').includes('ST') || String(it.title || '').includes('*ST')))
      : items;
    if (force || !abnormalLastTimestamp.value || isStockEvent) abnormalEvents.value = filtered;
    else abnormalEvents.value = abnormalEvents.value.concat(filtered);
    if (!isStockEvent && rows.length) {
      abnormalLastTimestamp.value = rows[rows.length - 1]?.event_timestamp || abnormalLastTimestamp.value;
    } else if (isStockEvent) {
      abnormalLastTimestamp.value = null;
    }
    abnormalHasMore.value = isStockEvent ? true : rows.length >= 30;
  } catch (e: any) {
    abnormalError.value = `异动获取失败：${String(e?.message || e)}`;
  } finally {
    abnormalLoading.value = false;
    abnormalReqInFlight = false;
  }
};

const startAbnormalPolling = (forceRestart = false) => {
  if (abnormalTimer && !forceRestart) return;
  if (abnormalTimer && forceRestart) {
    window.clearInterval(abnormalTimer);
    abnormalTimer = null;
  }
  void refreshAbnormalEvents(true);
  abnormalTimer = window.setInterval(() => {
    void refreshAbnormalEvents(false);
  }, 3000);
};

const stopAbnormalPolling = () => {
  if (abnormalTimer) {
    window.clearInterval(abnormalTimer);
    abnormalTimer = null;
  }
};

const abnormalHandleScroll = (event: Event) => {
  const onlyPlate = abnormalSelectedTypes.value.length > 0 && abnormalSelectedTypes.value.every((type) => Number(type) >= 11000);
  if (!onlyPlate) return;
  const el = event.target as HTMLElement | null;
  if (!el) return;
  if (el.scrollHeight - el.scrollTop - el.clientHeight < 120) {
    void refreshAbnormalEvents(false);
  }
};

onMounted(() => {
  startAbnormalPolling(true);
});

onBeforeUnmount(() => {
  stopAbnormalPolling();
});
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
                      <div class="abnormal-name">
                        <span>{{ item.title }}</span>
                        <span class="abnormal-name-move" :class="abnormalValueClass(item.valueText)" v-if="item.valueText">{{ item.valueText }}</span>
                        <span class="abnormal-name-move abnormal-moment" :class="abnormalValueClass(item.momentText)" v-if="item.momentText">{{ item.momentText }}</span>
                        <div class="abnormal-head-tags">
                          <div class="abnormal-priority" :class="abnormalPriorityTone(item)" v-if="item.priorityLabel">{{ item.priorityLabel }}</div>
                          <span class="abnormal-tag subtle" :class="item.tone" v-if="item.eventTypeLabel">{{ item.eventTypeLabel }}</span>
                        </div>
                      </div>
                    </div>
                    <div class="abnormal-time">{{ item.time }}</div>
                  </div>
                  <div class="abnormal-sub">{{ item.subtitle }}</div>
                  <div class="abnormal-tags">
                    <span class="abnormal-tag high" v-for="(badge, bi) in (item.coreBadges || [])" :key="'pcb-'+item.id+'-'+bi">{{ badge }}</span>
                    <span class="abnormal-tag abnormal-score-tag" :class="abnormalPriorityTone(item)" v-if="item.scoreText">{{ item.scoreLabel }} {{ item.scoreText }}</span>
                    <button class="abnormal-tag mid abnormal-expand-btn" type="button" v-if="item.extraCount" @click.stop="toggleAbnormalExpanded(item)">
                      同题材 +{{ item.extraCount }}{{ abnormalIsExpanded(item) ? ' 收起' : ' 展开' }}
                    </button>
                    <span class="abnormal-tag" v-for="(tag, idx) in item.tags" :key="'abt-p-'+item.id+'-'+idx">{{ tag }}</span>
                  </div>
                  <div class="abnormal-merged-list" v-if="item.extraCount && abnormalIsExpanded(item)">
                    <span class="abnormal-merged-chip" v-for="(name, mi) in (item.mergedTitles || []).slice(1)" :key="'pm-'+item.id+'-'+mi">{{ name }}</span>
                  </div>
                  <div class="abnormal-sublines" v-if="item.relatedRows && item.relatedRows.length">
                    <div class="abnormal-subline" v-for="(row, idx) in item.relatedRows" :key="'asr-p-'+item.id+'-'+idx">
                      <div class="abnormal-subleft">
                        <span class="abnormal-subname" :class="[abnormalRowToneClass(row), { 'abnormal-link': row.code }]" @click.stop="row.code && abnormalOpenSymbol(row.code)">{{ row.name }}</span>
                        <span class="abnormal-subcode" :class="[abnormalRowToneClass(row), { 'abnormal-link': row.code }]" v-if="row.code" @click.stop="abnormalOpenSymbol(row.code)">({{ row.code }})</span>
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
                      <div class="abnormal-name">
                        <span>{{ item.title }}</span>
                        <span class="abnormal-name-move" :class="abnormalValueClass(item.valueText)" v-if="item.valueText">{{ item.valueText }}</span>
                        <span class="abnormal-name-move abnormal-moment" :class="abnormalValueClass(item.momentText)" v-if="item.momentText">{{ item.momentText }}</span>
                        <div class="abnormal-head-tags">
                          <div class="abnormal-priority" :class="abnormalPriorityTone(item)" v-if="item.priorityLabel">{{ item.priorityLabel }}</div>
                          <span class="abnormal-tag subtle" :class="item.tone" v-if="item.eventTypeLabel">{{ item.eventTypeLabel }}</span>
                        </div>
                      </div>
                    </div>
                    <div class="abnormal-time">{{ item.time }}</div>
                  </div>
                  <div class="abnormal-sub">{{ item.subtitle }}</div>
                  <div class="abnormal-tags">
                    <span class="abnormal-tag high" v-for="(badge, bi) in (item.coreBadges || [])" :key="'scb-'+item.id+'-'+bi">{{ badge }}</span>
                    <span class="abnormal-tag abnormal-score-tag" :class="abnormalPriorityTone(item)" v-if="item.scoreText">{{ item.scoreLabel }} {{ item.scoreText }}</span>
                    <button class="abnormal-tag mid abnormal-expand-btn" type="button" v-if="item.extraCount" @click.stop="toggleAbnormalExpanded(item)">
                      同题材 +{{ item.extraCount }}{{ abnormalIsExpanded(item) ? ' 收起' : ' 展开' }}
                    </button>
                    <span class="abnormal-tag" v-for="(tag, idx) in item.tags" :key="'abt-s-'+item.id+'-'+idx">{{ tag }}</span>
                  </div>
                  <div class="abnormal-merged-list" v-if="item.extraCount && abnormalIsExpanded(item)">
                    <span class="abnormal-merged-chip" v-for="(name, mi) in (item.mergedTitles || []).slice(1)" :key="'sm-'+item.id+'-'+mi">{{ name }}</span>
                  </div>
                  <div class="abnormal-sublines" v-if="item.relatedRows && item.relatedRows.length">
                    <div class="abnormal-subline" v-for="(row, idx) in item.relatedRows" :key="'asr-s-'+item.id+'-'+idx">
                      <div class="abnormal-subleft">
                        <span class="abnormal-subname" :class="[abnormalRowToneClass(row), { 'abnormal-link': row.code }]" @click.stop="row.code && abnormalOpenSymbol(row.code)">{{ row.name }}</span>
                        <span class="abnormal-subcode" :class="[abnormalRowToneClass(row), { 'abnormal-link': row.code }]" v-if="row.code" @click.stop="abnormalOpenSymbol(row.code)">({{ row.code }})</span>
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
