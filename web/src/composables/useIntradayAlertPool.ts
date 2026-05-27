import { computed, ref } from 'vue';

type AlertLevel = 'high' | 'mid' | 'low';
type AlertTone = 'red' | 'green';

export type IntradayAlertItem = {
  id: string;
  bucketKey: string;
  isPlate: boolean;
  title: string;
  subtitle: string;
  eventType: number;
  eventTypeLabel: string;
  tone: AlertTone;
  priorityLevel: AlertLevel;
  priorityLabel: string;
  valueText: string;
  momentText: string;
  time: string;
  eventTimestamp: number;
  primarySymbol: string;
  relatedNames: string[];
  unread: boolean;
  pcp?: number;
  mtm?: number;
};

const ALERT_FETCH_TYPES = [11000, 11001, 10005, 10006, 10003, 10004, 10009, 10010, 10008, 10007];
const ALERT_P1_TYPES = new Set([11000, 10005, 10006, 10003, 10004, 10010, 10008, 10007, 99999]);
const ALERT_P2_TYPES = new Set([11001, 10009]);
const ALERT_POLL_MS = 5000;
const ALERT_DEDUPE_BUCKET_SEC = 180;
const ALERT_KEEP_COUNT = 300;
const ALERT_RAW_SEEN_LIMIT = 800;
const RESONANCE_THRESHOLD_COUNT = 3;
const RESONANCE_WINDOW_SEC = 300;
const STORAGE_KEY = 'quant_review_alert_history';

const getPersistentHistory = (): IntradayAlertItem[] => {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const data = JSON.parse(raw);
    const today = new Date().toDateString();
    return data
      .filter((item: any) => new Date(item.eventTimestamp * 1000).toDateString() === today)
      .map((item: any) => {
        const meta = eventMeta(item.eventType, item.pcp, item.mtm);
        return {
          ...item,
          tone: meta.tone,
          eventTypeLabel: meta.label,
        };
      });
  } catch {
    return [];
  }
};

const savePersistentHistory = (items: IntradayAlertItem[]) => {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, 300)));
  } catch (e) {
    console.error('Failed to save alert history', e);
  }
};

const eventMetaMap: Record<number, { label: string; tone: AlertTone }> = {
  10003: { label: '打开涨停', tone: 'green' },
  10004: { label: '打开跌停', tone: 'red' },
  10005: { label: '逼近涨停', tone: 'red' },
  10006: { label: '逼近跌停', tone: 'green' },
  10007: { label: '封板跌停', tone: 'green' },
  10008: { label: '封板涨停', tone: 'red' },
  10009: { label: '大幅拉升', tone: 'red' },
  10010: { label: '快速跳水', tone: 'green' },
  11000: { label: '板块拉升', tone: 'red' },
  11001: { label: '板块跳水', tone: 'green' },
  99999: { label: '共振爆发', tone: 'red' },
};

const eventMeta = (eventType: number, pcp?: number, mtm?: number) => {
  const meta = { ...(eventMetaMap[eventType] || { label: `异动 ${eventType}`, tone: 'red' as AlertTone }) };
  if (pcp !== undefined) {
    const isPositive = pcp >= 0;
    const isNegative = pcp < 0;
    const actionUp = (mtm || 0) > 0;
    if (isNegative) {
      meta.tone = 'green';
    } else if (isPositive) {
      if (eventType === 10003) {
        meta.tone = 'green';
      } else {
        meta.tone = 'red';
      }
    }
    if (isNegative) {
      if (meta.label.includes('涨停') && eventType !== 10003) meta.label = '封板跌停';
      else if (meta.label.includes('逼近') && meta.label.includes('涨停')) meta.label = '逼近跌停';
      else if (meta.label.includes('拉升')) meta.label = actionUp ? '低位回升' : '板块跳水';
      else if (meta.label === '共振爆发') meta.label = '共振跳水';
    } else if (isPositive) {
      if (meta.label.includes('跌停') && eventType !== 10004) meta.label = '封板涨停';
      else if (meta.label.includes('逼近') && meta.label.includes('跌停')) meta.label = '逼近涨停';
      else if (meta.label.includes('跳水')) meta.label = actionUp ? '快速回升' : '高位回落';
    }
  }
  return meta;
};

const formatTime = (timestamp: unknown) => {
  if (timestamp === undefined || timestamp === null || timestamp === '') return '--';
  const n = Number(timestamp);
  const d = Number.isFinite(n) ? new Date(n * 1000) : new Date(String(timestamp));
  if (Number.isNaN(d.getTime())) return '--';
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
};

const toPctText = (val: unknown, withPlus = true) => {
  const v = Number(val || 0);
  const sign = withPlus && v >= 0 ? '+' : '';
  return `${sign}${(v * 100).toFixed(2)}%`;
};

const toMomentText = (mtm: unknown) => {
  const m = Number(mtm || 0);
  if (m === 0) return '';
  return `${m > 0 ? '↑' : '↓'}${Math.abs(m * 100).toFixed(2)}%`;
};

const horrorValue = (pcp: any) => toPctText(pcp);
const horrorMoment = (mtm: any) => toMomentText(mtm);

const priorityForType = (eventType: number): { level: AlertLevel; label: string } => {
  if (ALERT_P1_TYPES.has(eventType)) return { level: 'high', label: '高优' };
  if (ALERT_P2_TYPES.has(eventType)) return { level: 'mid', label: '跟踪' };
  return { level: 'low', label: '观察' };
};

const isSt = (title: string) => String(title || '').toUpperCase().includes('ST');

const buildSymbolUrl = (symbol?: string | null) => {
  const raw = String(symbol || '').trim().replace(/\..*$/, '');
  if (!raw) return 'https://xueqiu.com';
  const market = raw.startsWith('6') ? 'SH' : 'SZ';
  return `https://xueqiu.com/S/${market}${raw}`;
};

const parseAlertItem = (event: any): IntradayAlertItem | null => {
  if (!event || typeof event !== 'object') return null;
  const eventType = Number(event.event_type || 0);
  if (!ALERT_FETCH_TYPES.includes(eventType)) return null;
  const isPlate = eventType >= 11000;
  const eventTimestamp = Number(event.event_timestamp || 0);
  const bucket = Math.floor(eventTimestamp / ALERT_DEDUPE_BUCKET_SEC);

  if (isPlate) {
    const plate = event.plate_abnormal_event_data || {};
    const meta = eventMeta(eventType, plate.pcp, plate.mtm);
    const title = String(plate.plate_name || meta.label).trim();
    if (!title || isSt(title)) return null;
    const priority = priorityForType(eventType);
    const relatedStocks = Array.isArray(plate.related_stocks) ? plate.related_stocks.slice(0, 4) : [];
    const relatedNames = relatedStocks.map((x: any) => String(x?.name || '').trim()).filter(Boolean);
    const primarySymbol = String(relatedStocks[0]?.symbol || '').trim().replace(/\..*$/, '');
    return {
      id: `${eventType}-${eventTimestamp}-${title}`,
      bucketKey: `plate:${title}:${eventType}:${bucket}`,
      isPlate: true,
      title,
      subtitle: relatedNames.length ? `关联 ${relatedNames.join(' / ')}` : '板块异动',
      eventType,
      eventTypeLabel: meta.label,
      tone: meta.tone,
      priorityLevel: priority.level,
      priorityLabel: priority.label,
      valueText: horrorValue(plate.pcp),
      momentText: horrorMoment(plate.mtm),
      time: formatTime(eventTimestamp),
      eventTimestamp,
      primarySymbol,
      relatedNames,
      unread: true,
      pcp: plate.pcp,
      mtm: plate.mtm,
    };
  }

  const stock = event.stock_abnormal_event_data || {};
  const meta = eventMeta(eventType, stock.pcp, stock.mtm);
  const title = String(stock.name || meta.label).trim();
  if (!title || isSt(title)) return null;
  const priority = priorityForType(eventType);
  const relatedPlates = Array.isArray(stock.related_plates) ? stock.related_plates.slice(0, 3) : [];
  const relatedNames = relatedPlates.map((x: any) => String(x?.plate_name || '').trim()).filter(Boolean);
  const primarySymbol = String(event.target || '').trim().replace(/\..*$/, '');
  return {
    id: `${eventType}-${eventTimestamp}-${primarySymbol || title}`,
    bucketKey: `stock:${primarySymbol || title}:${eventType}:${bucket}`,
    isPlate: false,
    title,
    subtitle: relatedNames.length ? `题材 ${relatedNames.join(' / ')}` : '个股异动',
    eventType,
    eventTypeLabel: meta.label,
    tone: meta.tone,
    priorityLevel: priority.level,
    priorityLabel: priority.label,
    valueText: horrorValue(stock.pcp),
    momentText: horrorMoment(stock.mtm),
    time: formatTime(eventTimestamp),
    eventTimestamp,
    primarySymbol,
    relatedNames,
    unread: true,
    pcp: stock.pcp,
    mtm: stock.mtm,
  };
};

const fetchAlertRows = async (count = 40) => {
  const url = `https://flash-api.xuangubao.cn/api/event/history?count=${count}&types=${ALERT_FETCH_TYPES.join(',')}&_ts=${Date.now()}`;
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const json = await res.json();
  return Array.isArray(json?.data) ? json.data : [];
};

export function useIntradayAlertPool() {
  const items = ref<IntradayAlertItem[]>(getPersistentHistory());
  const loading = ref(false);
  const error = ref('');
  const open = ref(false);
  const historyOpen = ref(false);
  const enabled = ref(true);
  const unreadCount = ref(0);
  const lastUpdatedAt = ref(0);

  let timer: number | null = null;
  let inFlight = false;
  const rawSeenKeys = new Set<string>(getPersistentHistory().map(x => x.id));
  const rawSeenQueue: string[] = Array.from(rawSeenKeys);
  const poolByBucket = new Map<string, IntradayAlertItem>();

  items.value.forEach(item => poolByBucket.set(item.bucketKey, item));

  const trimSeenQueue = () => {
    while (rawSeenQueue.length > ALERT_RAW_SEEN_LIMIT) {
      const key = rawSeenQueue.shift();
      if (key) rawSeenKeys.delete(key);
    }
  };

  const railItems = computed(() => items.value.slice(0, 50));
  const allHistory = computed(() => items.value);

  const statusText = computed(() => {
    if (!enabled.value) return '静默中';
    if (loading.value) return '更新中';
    if (error.value) return '抓取异常';
    if (!items.value.length) return '等待异动';
    return `今日记录 ${items.value.length} 条`;
  });

  const openSymbol = (symbol?: string | null) => {
    const url = buildSymbolUrl(symbol);
    if (typeof window !== 'undefined') window.open(url, '_blank', 'noopener');
  };

  const markAllRead = () => {
    items.value = items.value.map((item) => ({ ...item, unread: false }));
    unreadCount.value = 0;
  };

  const toggleOpen = () => {
    open.value = !open.value;
    if (open.value) markAllRead();
  };

  const toggleHistory = () => {
    historyOpen.value = !historyOpen.value;
  };

  const setEnabled = (next: boolean) => {
    enabled.value = next;
    if (!next) {
      stop();
      markAllRead();
      return;
    }
    start();
  };

  const clearItems = () => {
    items.value = [];
    unreadCount.value = 0;
    poolByBucket.clear();
    savePersistentHistory([]);
  };

  const onItemClick = (item: IntradayAlertItem) => {
    if (!item.isPlate && item.primarySymbol) openSymbol(item.primarySymbol);
    markAllRead();
  };

  const detectResonance = (allCurrentItems: IntradayAlertItem[]) => {
    const sectorHits = new Map<string, { count: number; symbols: Set<string>; lastTs: number }>();
    const now = Math.floor(Date.now() / 1000);

    allCurrentItems.forEach(item => {
      if (item.eventTimestamp < now - RESONANCE_WINDOW_SEC) return;
      if (item.eventType === 99999) return;

      const sectors = item.isPlate ? [item.title] : item.relatedNames;
      sectors.forEach(s => {
        if (!sectorHits.has(s)) sectorHits.set(s, { count: 0, symbols: new Set(), lastTs: 0 });
        const hit = sectorHits.get(s)!;
        hit.count += 1;
        if (item.primarySymbol) hit.symbols.add(item.primarySymbol);
        hit.lastTs = Math.max(hit.lastTs, item.eventTimestamp);
      });
    });

    const newResonanceItems: IntradayAlertItem[] = [];
    sectorHits.forEach((hit, sector) => {
      if (hit.count >= RESONANCE_THRESHOLD_COUNT) {
        const key = `resonance:${sector}:${Math.floor(hit.lastTs / 300)}`;
        if (poolByBucket.has(key)) return;

        const latestItem = allCurrentItems.find(x => x.relatedNames.includes(sector) || x.title === sector);
        const pcp = latestItem?.pcp;
        const meta = eventMeta(99999, pcp);

        const resItem: IntradayAlertItem = {
          id: `resonance-${hit.lastTs}-${sector}`,
          bucketKey: key,
          isPlate: true,
          title: `🔥 板块共振：${sector}`,
          subtitle: `${hit.count} 只异动联动`,
          eventType: 99999,
          eventTypeLabel: meta.label,
          tone: meta.tone,
          priorityLevel: 'high',
          priorityLabel: '共振',
          valueText: pcp !== undefined ? horrorValue(pcp) : '',
          momentText: '',
          time: formatTime(hit.lastTs),
          eventTimestamp: hit.lastTs,
          primarySymbol: '',
          relatedNames: [sector],
          unread: true,
          pcp,
          mtm: 0,
        };
        newResonanceItems.push(resItem);
      }
    });
    return newResonanceItems;
  };

  const addItem = (item: IntradayAlertItem) => {
    const existing = poolByBucket.get(item.bucketKey);
    if (existing) {
      existing.pcp = item.pcp;
      existing.mtm = item.mtm;
      existing.valueText = item.valueText;
      existing.momentText = item.momentText;
      existing.eventTypeLabel = item.eventTypeLabel;
      existing.tone = item.tone;
      existing.subtitle = item.subtitle;
      existing.relatedNames = item.relatedNames;
      existing.unread = item.unread;
      return false;
    }
    poolByBucket.set(item.bucketKey, item);
    items.value = [item, ...items.value].slice(0, ALERT_KEEP_COUNT);
    unreadCount.value += 1;
    savePersistentHistory(items.value);
    return true;
  };

  const refresh = async (forceReset?: boolean) => {
    if (inFlight) return;
    inFlight = true;
    loading.value = true;
    error.value = '';
    try {
      const rows = await fetchAlertRows(40);
      const now = Math.floor(Date.now() / 1000);
      const freshItems: IntradayAlertItem[] = [];
      for (const event of rows) {
        const parsed = parseAlertItem(event);
        if (!parsed) continue;
        if (!rawSeenKeys.has(parsed.id)) {
          rawSeenKeys.add(parsed.id);
          rawSeenQueue.push(parsed.id);
        }
        addItem(parsed);
        freshItems.push(parsed);
      }
      trimSeenQueue();

      const resonances = detectResonance(freshItems);
      for (const res of resonances) {
        addItem(res);
      }

      lastUpdatedAt.value = now;
    } catch (e: any) {
      error.value = String(e?.message || e);
    } finally {
      loading.value = false;
      inFlight = false;
    }
  };

  const start = () => {
    stop();
    void refresh(true);
    timer = window.setInterval(() => {
      void refresh();
    }, ALERT_POLL_MS);
  };

  const stop = () => {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  };

  return {
    items,
    loading,
    error,
    open,
    historyOpen,
    enabled,
    unreadCount,
    lastUpdatedAt,
    railItems,
    allHistory,
    statusText,
    toggleOpen,
    toggleHistory,
    setEnabled,
    clearItems,
    markAllRead,
    onItemClick,
    refresh,
    start,
    stop,
  };
}
