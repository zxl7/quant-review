import { computed, ref } from 'vue';

type AlertLevel = 'high' | 'mid' | 'low';
type AlertTone = 'red' | 'green' | 'orange';

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
};

const ALERT_FETCH_TYPES = [11000, 11001, 10005, 10003, 10009, 10010];
const ALERT_P1_TYPES = new Set([11000, 10005, 10003, 10010]);
const ALERT_P2_TYPES = new Set([11001, 10009]);
const ALERT_POLL_MS = 5000;
const ALERT_DEDUPE_BUCKET_SEC = 180;
const ALERT_KEEP_COUNT = 8;
const ALERT_RAW_SEEN_LIMIT = 600;

const eventMetaMap: Record<number, { label: string; tone: AlertTone }> = {
  10003: { label: '打开涨停', tone: 'orange' },
  10005: { label: '逼近涨停', tone: 'red' },
  10009: { label: '大幅拉升', tone: 'red' },
  10010: { label: '快速跳水', tone: 'green' },
  11000: { label: '板块拉升', tone: 'red' },
  11001: { label: '板块跳水', tone: 'green' },
};

const eventMeta = (eventType: number) => eventMetaMap[eventType] || { label: `异动 ${eventType}`, tone: 'orange' as AlertTone };

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

const toPctText = (value: unknown) => {
  if (value === undefined || value === null || value === '') return '';
  const n = Number(value);
  if (!Number.isFinite(n)) return '';
  return `${n >= 0 ? '+' : ''}${(n * 100).toFixed(2)}%`;
};

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
  const meta = eventMeta(eventType);
  const priority = priorityForType(eventType);
  const eventTimestamp = Number(event.event_timestamp || 0);
  const bucket = Math.floor(eventTimestamp / ALERT_DEDUPE_BUCKET_SEC);

  if (isPlate) {
    const plate = event.plate_abnormal_event_data || {};
    const title = String(plate.plate_name || meta.label).trim();
    if (!title || isSt(title)) return null;
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
      valueText: toPctText(plate.pcp),
      momentText: toPctText(plate.mtm),
      time: formatTime(eventTimestamp),
      eventTimestamp,
      primarySymbol,
      relatedNames,
      unread: true,
    };
  }

  const stock = event.stock_abnormal_event_data || {};
  const title = String(stock.name || meta.label).trim();
  if (!title || isSt(title)) return null;
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
    valueText: toPctText(stock.pcp),
    momentText: toPctText(stock.mtm),
    time: formatTime(eventTimestamp),
    eventTimestamp,
    primarySymbol,
    relatedNames,
    unread: true,
  };
};

const fetchAlertRows = async () => {
  const url = `https://flash-api.xuangubao.cn/api/event/history?count=40&types=${ALERT_FETCH_TYPES.join(',')}&_ts=${Date.now()}`;
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const json = await res.json();
  return Array.isArray(json?.data) ? json.data : [];
};

export function useIntradayAlertPool() {
  const items = ref<IntradayAlertItem[]>([]);
  const loading = ref(false);
  const error = ref('');
  const open = ref(false);
  const enabled = ref(true);
  const unreadCount = ref(0);
  const lastUpdatedAt = ref(0);

  let timer: number | null = null;
  let inFlight = false;
  const rawSeenKeys = new Set<string>();
  const rawSeenQueue: string[] = [];
  const poolByBucket = new Map<string, IntradayAlertItem>();

  const trimSeenQueue = () => {
    while (rawSeenQueue.length > ALERT_RAW_SEEN_LIMIT) {
      const key = rawSeenQueue.shift();
      if (key) rawSeenKeys.delete(key);
    }
  };

  const railItems = computed(() => items.value.slice(0, ALERT_KEEP_COUNT));
  const statusText = computed(() => {
    if (!enabled.value) return '静默中';
    if (loading.value) return '更新中';
    if (error.value) return '抓取异常';
    if (!railItems.value.length) return '等待异动';
    return `最近 ${railItems.value.length} 条`;
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
  };

  const onItemClick = (item: IntradayAlertItem) => {
    if (!item.isPlate && item.primarySymbol) openSymbol(item.primarySymbol);
    markAllRead();
  };

  const ingestRows = (rows: any[]) => {
    const ordered = [...rows]
      .map((row) => parseAlertItem(row))
      .filter(Boolean)
      .sort((a, b) => Number(a!.eventTimestamp || 0) - Number(b!.eventTimestamp || 0)) as IntradayAlertItem[];

    let nextUnread = 0;
    let shouldAutoOpen = false;

    for (const item of ordered) {
      const rawKey = item.id;
      if (rawSeenKeys.has(rawKey)) continue;
      rawSeenKeys.add(rawKey);
      rawSeenQueue.push(rawKey);
      trimSeenQueue();

      const prev = poolByBucket.get(item.bucketKey);
      if (prev) {
        const merged = { ...prev, ...item, unread: prev.unread || item.unread };
        poolByBucket.set(item.bucketKey, merged);
        items.value = items.value.map((x) => (x.bucketKey === item.bucketKey ? merged : x));
        continue;
      }

      const next = { ...item, unread: true };
      poolByBucket.set(item.bucketKey, next);
      items.value = [next, ...items.value]
        .sort((a, b) => Number(b.eventTimestamp || 0) - Number(a.eventTimestamp || 0))
        .slice(0, ALERT_KEEP_COUNT);

      if (enabled.value) {
        nextUnread += 1;
        if (next.priorityLevel === 'high') shouldAutoOpen = true;
      }
    }

    if (nextUnread > 0) unreadCount.value += nextUnread;
    if (shouldAutoOpen && enabled.value) open.value = true;
  };

  const refresh = async (force = false) => {
    try {
      if (!enabled.value && !force) return;
      const now = Date.now();
      if (!force && inFlight) return;
      if (typeof document !== 'undefined' && document.hidden && !force) return;
      inFlight = true;
      loading.value = true;
      error.value = '';
      const rows = await fetchAlertRows();
      ingestRows(rows);
      lastUpdatedAt.value = now;
    } catch (e: any) {
      error.value = `提醒抓取失败：${String(e?.message || e)}`;
    } finally {
      loading.value = false;
      inFlight = false;
    }
  };

  const start = () => {
    if (!enabled.value) return;
    if (timer) return;
    void refresh(true);
    timer = window.setInterval(() => {
      void refresh(false);
    }, ALERT_POLL_MS);
  };

  const stop = () => {
    if (timer) {
      window.clearInterval(timer);
      timer = null;
    }
  };

  return {
    railItems,
    loading,
    error,
    open,
    enabled,
    unreadCount,
    statusText,
    lastUpdatedAt,
    toggleOpen,
    markAllRead,
    setEnabled,
    clearItems,
    onItemClick,
    refresh,
    start,
    stop,
  };
}
