import { computed, ref } from 'vue';

export type DragonTigerRow = {
  yzmc: string;
  yyb: string;
  sblx: string;
  gpdm: string;
  gpmc: string;
  sc: string;
  mrje: number;
  mcje: number;
  rq: string;
  net: number;
  price?: number;
  changePct?: number;
};

export type DragonTigerStockSummary = {
  code: string;
  name: string;
  market: string;
  buy: number;
  sell: number;
  net: number;
  appearances: number;
  seats: string[];
  price?: number;
  changePct?: number;
};

export type DragonTigerSeatSummary = {
  seat: string;
  type: string;
  buy: number;
  sell: number;
  net: number;
  rows: DragonTigerRow[];
};

export type DragonTigerGroupSummary = {
  name: string;
  buy: number;
  sell: number;
  net: number;
  rowCount: number;
  stockCount: number;
  seatCount: number;
  topStocks: string[];
  tags: string[];
};

export type DragonTigerGraphNodeType = 'root' | 'group' | 'stock' | 'seat';

export type DragonTigerGraphNode = {
  id: string;
  name: string;
  type: DragonTigerGraphNodeType;
  category: number;
  value: number;
  amount: number;
  itemStyle: { color: string };
  symbolSize: number;
  meta?: Record<string, unknown>;
};

export type DragonTigerGraphLink = {
  source: string;
  target: string;
  value: number;
  lineStyle: {
    color: string;
    width: number;
    opacity: number;
    curveness: number;
  };
};

type DragonTigerPayload = {
  date?: string;
  updatedAt?: string;
  dateOptions?: string[];
  rows?: DragonTigerRow[];
};

const ROOT_GROUP_NAME = '全部游资';
const NET_RED = '#ef4444';
const NET_GREEN = '#10b981';
const NET_NEUTRAL = '#94a3b8';
const ROOT_COLOR = '#2563eb';
const FOCUS_NAMES = [
  '机构专用',
  '量化打板',
  '量化基金',
  '陈小群',
  '赵老哥',
  '炒股养家',
  '章盟主',
  '上塘路',
  '呼家楼',
  '六一路',
  '欢乐海岸',
  '新闸路',
  '宁波桑田路',
  '沪股通专用',
  '深股通专用',
  '金田路',
  'T王',
  'Asking',
];

const normalizeText = (value: unknown) => String(value ?? '').trim();
const normalizeCode = (value: unknown) => normalizeText(value).replace(/\.(SH|SZ|SS)$/i, '');

const toNumber = (value: unknown) => {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
};

const netColor = (value: number) => {
  if (value > 0) return NET_RED;
  if (value < 0) return NET_GREEN;
  return NET_NEUTRAL;
};

const scaleSize = (amount: number, min: number, max: number) => {
  const abs = Math.abs(amount);
  if (!abs) return min;
  const log = Math.log10(abs + 1);
  const scaled = min + log * 5.2;
  return Math.max(min, Math.min(max, scaled));
};

const marketLabel = (value: string) => {
  if (value === '1') return '沪A';
  if (value === '0') return '深A';
  if (value === '2') return '北交';
  return value || '--';
};

const formatMoney = (value: number) => {
  const abs = Math.abs(value);
  if (abs >= 1e8) return `${value >= 0 ? '+' : '-'}${(abs / 1e8).toFixed(abs >= 5e8 ? 1 : 2)}亿`;
  if (abs >= 1e4) return `${value >= 0 ? '+' : '-'}${(abs / 1e4).toFixed(abs >= 1e7 ? 0 : 1)}万`;
  return `${value >= 0 ? '+' : '-'}${abs.toFixed(0)}`;
};

const formatUnsignedMoney = (value: number) => {
  const abs = Math.abs(value);
  if (abs >= 1e8) return `${(abs / 1e8).toFixed(abs >= 5e8 ? 1 : 2)}亿`;
  if (abs >= 1e4) return `${(abs / 1e4).toFixed(abs >= 1e7 ? 0 : 1)}万`;
  return abs.toFixed(0);
};

const formatSignedPct = (value?: number) => {
  if (!Number.isFinite(Number(value))) return '--';
  const n = Number(value);
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
};

const xueqiuUrl = (code: string) => {
  const raw = normalizeCode(code);
  if (!raw) return 'https://xueqiu.com';
  return `https://xueqiu.com/S/${raw.startsWith('6') ? 'SH' : 'SZ'}${raw}`;
};

const groupTags = (name: string) => {
  const tags: string[] = [];
  if (/机构/.test(name)) tags.push('机构');
  if (/量化/.test(name)) tags.push('量化');
  if (/股通专用/.test(name)) tags.push('北向');
  if (FOCUS_NAMES.includes(name)) tags.push('重点');
  return tags;
};

const buildStockSummaries = (rows: DragonTigerRow[]) => {
  const map = new Map<string, DragonTigerStockSummary>();
  rows.forEach((row) => {
    const key = row.gpdm;
    const prev = map.get(key) || {
      code: row.gpdm,
      name: row.gpmc,
      market: marketLabel(row.sc),
      buy: 0,
      sell: 0,
      net: 0,
      appearances: 0,
      seats: [],
      price: row.price,
      changePct: row.changePct,
    };
    prev.buy += toNumber(row.mrje);
    prev.sell += toNumber(row.mcje);
    prev.net += toNumber(row.net);
    prev.appearances += 1;
    if (!prev.seats.includes(row.yyb)) prev.seats.push(row.yyb);
    if (prev.price === undefined && row.price !== undefined) prev.price = row.price;
    if (prev.changePct === undefined && row.changePct !== undefined) prev.changePct = row.changePct;
    map.set(key, prev);
  });
  return Array.from(map.values()).sort((a, b) => b.net - a.net || b.buy - a.buy);
};

const buildSeatSummaries = (rows: DragonTigerRow[]) => {
  const map = new Map<string, DragonTigerSeatSummary>();
  rows.forEach((row) => {
    const key = `${row.yyb}__${row.sblx}`;
    const prev = map.get(key) || {
      seat: row.yyb,
      type: row.sblx,
      buy: 0,
      sell: 0,
      net: 0,
      rows: [],
    };
    prev.buy += toNumber(row.mrje);
    prev.sell += toNumber(row.mcje);
    prev.net += toNumber(row.net);
    prev.rows.push(row);
    map.set(key, prev);
  });
  return Array.from(map.values()).sort((a, b) => b.net - a.net || b.buy - a.buy);
};

const makeNodeId = (type: DragonTigerGraphNodeType, value: string) => `${type}:${value}`;

async function tryLoadDragonTigerScript(src: string) {
  return await new Promise<boolean>((resolve) => {
    const existed = document.querySelector(`script[data-dragon-tiger-data="${src}"]`) as HTMLScriptElement | null;
    if (existed) {
      existed.addEventListener('load', () => resolve(true), { once: true });
      existed.addEventListener('error', () => resolve(false), { once: true });
      resolve(Boolean((window as any).__DRAGON_TIGER_DATA__));
      return;
    }

    const script = document.createElement('script');
    script.src = src;
    script.async = true;
    script.dataset.dragonTigerData = src;
    script.onload = () => resolve(Boolean((window as any).__DRAGON_TIGER_DATA__));
    script.onerror = () => resolve(false);
    document.head.appendChild(script);
  });
}

async function loadDragonTigerPayload(): Promise<DragonTigerPayload> {
  const injected = (window as any).__DRAGON_TIGER_DATA__;
  if (injected && typeof injected === 'object') return injected as DragonTigerPayload;

  const scriptUrls = ['./dragon_tiger_data.js', 'dragon_tiger_data.js', '/dragon_tiger_data.js'];
  for (const src of scriptUrls) {
    try {
      const ok = await tryLoadDragonTigerScript(src);
      const next = (window as any).__DRAGON_TIGER_DATA__;
      if (ok && next && typeof next === 'object') return next as DragonTigerPayload;
    } catch {
      // noop
    }
  }

  const jsonUrls = ['./dragon_tiger_data.json', 'dragon_tiger_data.json', '/dragon_tiger_data.json'];
  for (const url of jsonUrls) {
    try {
      const resp = await fetch(url);
      if (resp.ok) {
        const data = await resp.json();
        if (data && typeof data === 'object') return data as DragonTigerPayload;
      }
    } catch {
      // noop
    }
  }

  return {};
}

export function useDragonTiger() {
  const loading = ref(false);
  const error = ref('');
  const lastUpdated = ref('');
  const dateOptions = ref<string[]>([]);
  const selectedDate = ref('');
  const allRows = ref<DragonTigerRow[]>([]);
  const selectedGroup = ref(ROOT_GROUP_NAME);
  const keyword = ref('');
  const activeNodeId = ref(makeNodeId('root', ROOT_GROUP_NAME));

  const rows = computed(() =>
    allRows.value.filter((row) => {
      const matchDate = !selectedDate.value || row.rq === selectedDate.value;
      return matchDate;
    }),
  );

  const rowCount = computed(() => rows.value.length);
  const stockCount = computed(() => new Set(rows.value.map((row) => row.gpdm)).size);

  const groupSummaries = computed<DragonTigerGroupSummary[]>(() => {
    const map = new Map<string, DragonTigerGroupSummary>();
    rows.value.forEach((row) => {
      const prev = map.get(row.yzmc) || {
        name: row.yzmc,
        buy: 0,
        sell: 0,
        net: 0,
        rowCount: 0,
        stockCount: 0,
        seatCount: 0,
        topStocks: [],
        tags: groupTags(row.yzmc),
      };
      prev.buy += toNumber(row.mrje);
      prev.sell += toNumber(row.mcje);
      prev.net += toNumber(row.net);
      prev.rowCount += 1;
      map.set(row.yzmc, prev);
    });

    const stockMap = new Map<string, Set<string>>();
    const seatMap = new Map<string, Set<string>>();
    const topStockMap = new Map<string, Map<string, number>>();

    rows.value.forEach((row) => {
      const stockSet = stockMap.get(row.yzmc) || new Set<string>();
      stockSet.add(row.gpdm);
      stockMap.set(row.yzmc, stockSet);

      const seatSet = seatMap.get(row.yzmc) || new Set<string>();
      seatSet.add(row.yyb);
      seatMap.set(row.yzmc, seatSet);

      const stockRankMap = topStockMap.get(row.yzmc) || new Map<string, number>();
      stockRankMap.set(row.gpmc, (stockRankMap.get(row.gpmc) || 0) + Math.max(toNumber(row.net), toNumber(row.mrje)));
      topStockMap.set(row.yzmc, stockRankMap);
    });

    map.forEach((item, name) => {
      item.stockCount = stockMap.get(name)?.size || 0;
      item.seatCount = seatMap.get(name)?.size || 0;
      item.topStocks = Array.from(topStockMap.get(name)?.entries() || [])
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map((entry) => entry[0]);
    });

    return Array.from(map.values()).sort((a, b) => b.net - a.net || b.buy - a.buy);
  });

  const focusNames = computed(() => FOCUS_NAMES.filter((name) => groupSummaries.value.some((item) => item.name === name)));

  const selectedRows = computed(() => {
    const search = normalizeText(keyword.value).toLowerCase();
    return rows.value.filter((row) => {
      if (selectedGroup.value !== ROOT_GROUP_NAME && row.yzmc !== selectedGroup.value) return false;
      if (!search) return true;
      return `${row.gpmc} ${row.gpdm} ${row.yyb}`.toLowerCase().includes(search);
    });
  });

  const selectedGroupSummary = computed(() => {
    if (selectedGroup.value === ROOT_GROUP_NAME) {
      return {
        name: ROOT_GROUP_NAME,
        buy: rows.value.reduce((sum, row) => sum + toNumber(row.mrje), 0),
        sell: rows.value.reduce((sum, row) => sum + toNumber(row.mcje), 0),
        net: rows.value.reduce((sum, row) => sum + toNumber(row.net), 0),
        rowCount: rows.value.length,
        stockCount: new Set(rows.value.map((row) => row.gpdm)).size,
        seatCount: new Set(rows.value.map((row) => row.yyb)).size,
        topStocks: buildStockSummaries(rows.value)
          .slice(0, 3)
          .map((item) => item.name),
        tags: ['全量'],
      } satisfies DragonTigerGroupSummary;
    }
    return groupSummaries.value.find((item) => item.name === selectedGroup.value) || null;
  });

  const selectedStocks = computed(() => buildStockSummaries(selectedRows.value));
  const selectedSeats = computed(() => buildSeatSummaries(selectedRows.value));

  const graphData = computed(() => {
    const rootSummary = selectedGroupSummary.value;
    const baseRows = selectedRows.value;
    const groupNodes =
      selectedGroup.value === ROOT_GROUP_NAME ? groupSummaries.value : groupSummaries.value.filter((item) => item.name === selectedGroup.value);
    const stockNodes = buildStockSummaries(baseRows).slice(0, selectedGroup.value === ROOT_GROUP_NAME ? 14 : 18);
    const seatNodes = buildSeatSummaries(baseRows).slice(0, 22);

    const nodes: DragonTigerGraphNode[] = [];
    const links: DragonTigerGraphLink[] = [];

    nodes.push({
      id: makeNodeId('root', ROOT_GROUP_NAME),
      name: '龙虎榜',
      type: 'root',
      category: 0,
      value: Math.abs(rootSummary?.net || 0),
      amount: rootSummary?.net || 0,
      itemStyle: { color: ROOT_COLOR },
      symbolSize: 62,
      meta: {
        subtitle: selectedDate.value || '',
        buy: rootSummary?.buy || 0,
        sell: rootSummary?.sell || 0,
        net: rootSummary?.net || 0,
        rowCount: rootSummary?.rowCount || 0,
        stockCount: rootSummary?.stockCount || 0,
        seatCount: rootSummary?.seatCount || 0,
      },
    });

    groupNodes.forEach((item) => {
      const id = makeNodeId('group', item.name);
      nodes.push({
        id,
        name: item.name,
        type: 'group',
        category: 1,
        value: Math.abs(item.net),
        amount: item.net,
        itemStyle: { color: netColor(item.net) },
        symbolSize: scaleSize(item.net, 40, 68),
        meta: item,
      });
      links.push({
        source: makeNodeId('root', ROOT_GROUP_NAME),
        target: id,
        value: Math.abs(item.net),
        lineStyle: {
          color: netColor(item.net),
          width: Math.max(1.5, Math.min(7, Math.log10(Math.abs(item.net) + 10) * 1.3)),
          opacity: 0.7,
          curveness: 0.18,
        },
      });
    });

    stockNodes.forEach((item) => {
      const id = makeNodeId('stock', item.code);
      nodes.push({
        id,
        name: item.name,
        type: 'stock',
        category: 2,
        value: Math.abs(item.net),
        amount: item.net,
        itemStyle: { color: netColor(item.net) },
        symbolSize: scaleSize(item.net, 28, 56),
        meta: item,
      });
      if (selectedGroup.value === ROOT_GROUP_NAME) {
        const owner = groupNodes
          .map((group) => ({
            name: group.name,
            net: baseRows
              .filter((row) => row.yzmc === group.name && row.gpdm === item.code)
              .reduce((sum, row) => sum + toNumber(row.net), 0),
          }))
          .sort((a, b) => Math.abs(b.net) - Math.abs(a.net))[0];
        if (owner && owner.name) {
          links.push({
            source: makeNodeId('group', owner.name),
            target: id,
            value: Math.abs(owner.net),
            lineStyle: {
              color: netColor(owner.net),
              width: Math.max(1.2, Math.min(6, Math.log10(Math.abs(owner.net) + 10) * 1.2)),
              opacity: 0.62,
              curveness: 0.14,
            },
          });
        }
      } else {
        links.push({
          source: makeNodeId('group', selectedGroup.value),
          target: id,
          value: Math.abs(item.net),
          lineStyle: {
            color: netColor(item.net),
            width: Math.max(1.2, Math.min(6, Math.log10(Math.abs(item.net) + 10) * 1.2)),
            opacity: 0.62,
            curveness: 0.14,
          },
        });
      }
    });

    seatNodes.forEach((item) => {
      const firstRow = item.rows[0];
      if (!firstRow) return;
      const stockId = makeNodeId('stock', firstRow.gpdm);
      if (!stockNodes.some((stock) => stock.code === firstRow.gpdm)) return;
      const seatId = makeNodeId('seat', `${firstRow.gpdm}__${item.seat}__${item.type}`);
      nodes.push({
        id: seatId,
        name: item.seat,
        type: 'seat',
        category: 3,
        value: Math.abs(item.net),
        amount: item.net,
        itemStyle: { color: netColor(item.net) },
        symbolSize: scaleSize(item.net, 18, 34),
        meta: {
          ...item,
          stockCode: firstRow.gpdm,
          stockName: firstRow.gpmc,
        },
      });
      links.push({
        source: stockId,
        target: seatId,
        value: Math.abs(item.net),
        lineStyle: {
          color: netColor(item.net),
          width: Math.max(1, Math.min(4.5, Math.log10(Math.abs(item.net) + 10))),
          opacity: 0.5,
          curveness: 0.08,
        },
      });
    });

    return { nodes, links };
  });

  const activeNode = computed(() => graphData.value.nodes.find((item) => item.id === activeNodeId.value) || graphData.value.nodes[0] || null);

  const activeNodeDetail = computed(() => {
    const node = activeNode.value;
    if (!node) return null;
    if (node.type === 'root') {
      return {
        type: 'root' as const,
        title: '龙虎榜全景',
        subtitle: `${selectedDate.value || '--'} · ${rowCount.value} 条席位`,
        net: selectedGroupSummary.value?.net || 0,
        buy: selectedGroupSummary.value?.buy || 0,
        sell: selectedGroupSummary.value?.sell || 0,
        summary: selectedGroupSummary.value,
        topStocks: selectedStocks.value.slice(0, 8),
        seats: selectedSeats.value.slice(0, 8),
        rows: selectedRows.value.slice(0, 12),
      };
    }
    if (node.type === 'group') {
      const groupName = String(node.name);
      const groupRows = rows.value.filter((row) => row.yzmc === groupName);
      return {
        type: 'group' as const,
        title: groupName,
        subtitle: `${groupRows.length} 条席位 · ${new Set(groupRows.map((row) => row.gpdm)).size} 只个股`,
        net: groupRows.reduce((sum, row) => sum + toNumber(row.net), 0),
        buy: groupRows.reduce((sum, row) => sum + toNumber(row.mrje), 0),
        sell: groupRows.reduce((sum, row) => sum + toNumber(row.mcje), 0),
        summary: groupSummaries.value.find((item) => item.name === groupName) || null,
        topStocks: buildStockSummaries(groupRows).slice(0, 8),
        seats: buildSeatSummaries(groupRows).slice(0, 8),
        rows: groupRows.slice(0, 12),
      };
    }
    if (node.type === 'stock') {
      const code = String(node.meta?.code || '').trim() || String(node.id.split(':')[1] || '');
      const stockRows = rows.value.filter((row) => row.gpdm === code && (selectedGroup.value === ROOT_GROUP_NAME || row.yzmc === selectedGroup.value));
      const summary = buildStockSummaries(stockRows)[0] || null;
      return {
        type: 'stock' as const,
        title: summary?.name || code,
        subtitle: `${code} · ${summary?.market || '--'}`,
        net: summary?.net || 0,
        buy: summary?.buy || 0,
        sell: summary?.sell || 0,
        summary,
        topStocks: [],
        seats: buildSeatSummaries(stockRows).slice(0, 10),
        rows: stockRows.slice(0, 16),
      };
    }
    const meta = node.meta || {};
    const seat = String(meta.seat || node.name);
    const stockCode = String(meta.stockCode || '').trim();
    const seatRows = rows.value.filter(
      (row) =>
        row.yyb === seat &&
        (!stockCode || row.gpdm === stockCode) &&
        (selectedGroup.value === ROOT_GROUP_NAME || row.yzmc === selectedGroup.value),
    );
    return {
      type: 'seat' as const,
      title: seat,
      subtitle: `${String(meta.type || '--')} · ${String(meta.stockName || stockCode || '--')}`,
      net: seatRows.reduce((sum, row) => sum + toNumber(row.net), 0),
      buy: seatRows.reduce((sum, row) => sum + toNumber(row.mrje), 0),
      sell: seatRows.reduce((sum, row) => sum + toNumber(row.mcje), 0),
      summary: meta,
      topStocks: buildStockSummaries(seatRows).slice(0, 6),
      seats: [],
      rows: seatRows.slice(0, 12),
    };
  });

  const setSelectedGroup = (name: string) => {
    selectedGroup.value = normalizeText(name) || ROOT_GROUP_NAME;
    activeNodeId.value =
      selectedGroup.value === ROOT_GROUP_NAME ? makeNodeId('root', ROOT_GROUP_NAME) : makeNodeId('group', selectedGroup.value);
  };

  const setActiveNode = (nodeId: string) => {
    activeNodeId.value = nodeId || makeNodeId('root', ROOT_GROUP_NAME);
    const node = graphData.value.nodes.find((item) => item.id === activeNodeId.value);
    if (node?.type === 'group') selectedGroup.value = node.name;
  };

  const resetToOverview = () => {
    selectedGroup.value = ROOT_GROUP_NAME;
    activeNodeId.value = makeNodeId('root', ROOT_GROUP_NAME);
  };

  const refresh = async (_force = false) => {
    loading.value = true;
    error.value = '';
    try {
      const payload = await loadDragonTigerPayload();
      const rawRows = Array.isArray(payload.rows) ? payload.rows : [];
      allRows.value = rawRows
        .map((row) => ({
          ...row,
          gpdm: normalizeCode(row.gpdm),
          mrje: toNumber(row.mrje),
          mcje: toNumber(row.mcje),
          net: toNumber(row.net ?? toNumber(row.mrje) - toNumber(row.mcje)),
          price: row.price === undefined || row.price === null ? undefined : toNumber(row.price),
          changePct: row.changePct === undefined || row.changePct === null ? undefined : toNumber(row.changePct),
          rq: normalizeText(row.rq).slice(0, 10),
        }))
        .filter((row) => row.yzmc && row.gpdm);
      dateOptions.value = Array.isArray(payload.dateOptions)
        ? payload.dateOptions.map((item) => normalizeText(item)).filter(Boolean)
        : Array.from(new Set(allRows.value.map((row) => row.rq).filter(Boolean))).sort((a, b) => b.localeCompare(a));
      if (!selectedDate.value && dateOptions.value.length) selectedDate.value = dateOptions.value[0];
      if (selectedDate.value && dateOptions.value.length && !dateOptions.value.includes(selectedDate.value)) {
        selectedDate.value = dateOptions.value[0];
      }
      lastUpdated.value = normalizeText(payload.updatedAt) || new Date().toLocaleTimeString('zh-CN', { hour12: false });
      if (!groupSummaries.value.some((item) => item.name === selectedGroup.value)) {
        resetToOverview();
      } else if (selectedGroup.value !== ROOT_GROUP_NAME) {
        activeNodeId.value = makeNodeId('group', selectedGroup.value);
      }
    } catch (err: any) {
      error.value = `龙虎榜本地数据加载失败：${String(err?.message || err)}`;
      allRows.value = [];
    } finally {
      loading.value = false;
    }
  };

  const fetchRows = async (date = selectedDate.value) => {
    selectedDate.value = normalizeText(date);
    if (!selectedDate.value && dateOptions.value.length) selectedDate.value = dateOptions.value[0];
    if (!groupSummaries.value.some((item) => item.name === selectedGroup.value)) {
      resetToOverview();
    }
  };

  const isThreeDay = (groupName: string, stockCode: string) => {
    return rows.value.some(
      (row) => row.yzmc === groupName && row.gpdm === stockCode && row.sblx?.includes('3日'),
    );
  };

  return {
    loading,
    error,
    lastUpdated,
    dateOptions,
    selectedDate,
    rows,
    rowCount,
    stockCount,
    focusNames,
    groupSummaries,
    selectedGroup,
    selectedGroupSummary,
    selectedRows,
    selectedStocks,
    selectedSeats,
    graphData,
    activeNode,
    activeNodeId,
    activeNodeDetail,
    keyword,
    formatMoney,
    formatUnsignedMoney,
    formatSignedPct,
    marketLabel,
    xueqiuUrl,
    isThreeDay,
    setSelectedGroup,
    setActiveNode,
    resetToOverview,
    fetchRows,
    refresh,
  };
}
