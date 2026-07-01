<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { DatePicker } from 'ant-design-vue';
import dayjs, { type Dayjs } from 'dayjs';
import ShortReminderFooter from '../common/ShortReminderFooter.vue';
import { useThemeHotStore } from '../../composables/useThemeHotStore';

const { setXgbPlates, setXgbStocksForPlate } = useThemeHotStore();

type HotPlate = {
  id: string;
  name: string;
  description: string;
};

type HotStock = {
  code: string;
  name: string;
  changePct: number;
  price?: number;
  limitUpDays?: number;
  reason: string;
  label: string;
  relatedDesc: string;
};

const todayText = () => {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
};

const hotDate = ref(todayText());
const hotPlates = ref<HotPlate[]>([]);
const hotSelectedPlateId = ref('');
const hotSelectedPlateName = ref('');
const hotMode = ref<'leader' | 'all'>('leader');
const hotStocks = ref<HotStock[]>([]);
const hotLoading = ref(false);
const hotStockLoading = ref(false);
const hotError = ref('');
const hotLastUpdated = ref('');
const hotExpandedCodes = ref<string[]>([]);

const hotDateParam = computed(() => hotDate.value.replace(/-/g, ''));
const hotDateValue = computed<Dayjs | undefined>({
  get: () => (hotDate.value ? dayjs(hotDate.value, 'YYYY-MM-DD') : undefined),
  set: (value) => {
    hotDate.value = value ? value.format('YYYY-MM-DD') : todayText();
  },
});
const isToday = computed(() => hotDate.value === todayText());
const selectedPlate = computed(() => hotPlates.value.find((x) => x.id === hotSelectedPlateId.value));
const sortedStocks = computed(() => [...hotStocks.value].sort((a, b) => Number(b.changePct || 0) - Number(a.changePct || 0)));
const hotStats = computed(() => ({
  plates: hotPlates.value.length,
  stocks: hotStocks.value.length,
  limit: hotStocks.value.filter((x) => Number(x.limitUpDays || 0) > 0).length,
}));

const normalizeCode = (value: unknown) => String(value || '').trim().replace(/\.(SZ|SS|SH)$/i, '');
const toXgbSymbol = (code: string) => {
  const raw = normalizeCode(code);
  if (!raw) return '';
  return `${raw}.${raw.startsWith('6') ? 'SS' : 'SZ'}`;
};
const isStockCode = (code: string) => /^(00|30|60|68)\d{4}$/.test(normalizeCode(code));
const toNum = (value: unknown, fallback = 0) => {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
};
const formatPct = (value: unknown) => {
  const n = toNum(value, 0);
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
};

/**
 * 将包含换行符的文本分割为行数组，并移除常见的序号前缀（如 1、 1. 等）
 * 符合函数式编程：无副作用，纯函数处理字符串
 * @param text 待处理的文本内容
 */
const splitLines = (text: string | undefined): string[] => {
  if (!text) return [];
  
  // 1. 处理字面量 "\n" 字符（有些接口返回的是字符串形式的 \n 而不是真实换行符）
  let processed = String(text).replace(/\\n/g, '\n');
  
  // 2. 兼容性切割：如果文本中没有换行符，但存在类似 "；2、" 或 "。2、" 的结构，强制补齐换行
  // 这能处理那些把多条信息挤在同一行且只用序号分隔的情况
  if (!processed.includes('\n')) {
    processed = processed.replace(/([;；。!！?？])\s*(\d+[、.．])/g, '$1\n$2');
  }

  return processed
    .split(/\n+/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => line.replace(/^\d+[、.．]\s*/, ''));
};

const collectObjects = (value: unknown, guard: (row: Record<string, any>) => boolean, limit = 800) => {
  const out: Record<string, any>[] = [];
  const seen = new Set<unknown>();
  const walk = (node: unknown) => {
    if (out.length >= limit || node === null || node === undefined || seen.has(node)) return;
    if (typeof node !== 'object') return;
    seen.add(node);
    if (Array.isArray(node)) {
      node.forEach(walk);
      return;
    }
    const row = node as Record<string, any>;
    if (guard(row)) out.push(row);
    Object.values(row).forEach(walk);
  };
  walk(value);
  return out;
};

const makeXgbHeaders = () => {
  return {
    'Accept': 'application/json, text/plain, */*',
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
  };
};

const fetchText = async (url: string) => {
  const res = await fetch(`${url}${url.includes('?') ? '&' : '?'}_ts=${Date.now()}`, {
    cache: 'no-store',
    headers: makeXgbHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.text();
};

const fetchJson = async (url: string) => {
  const text = await fetchText(url);
  return JSON.parse(text);
};

const hydrateStocksWithQuote = async (stocks: HotStock[]) => {
  const codes = Array.from(new Set(stocks.map((x) => normalizeCode(x.code)).filter(isStockCode)));
  if (!codes.length) return stocks;
  const symbols = codes.map(toXgbSymbol).filter(Boolean);
  const url = `https://flash-api.xuangubao.cn/api/stock/data?fields=symbol,stock_chi_name,change_percent,price,limit_up_days&strict=true&symbols=${symbols.join(',')}`;
  const json = await fetchJson(url);
  const quoteData = json?.data || {};
  return stocks.map((stock) => {
    const code = normalizeCode(stock.code);
    const symbol = toXgbSymbol(code);
    const quote = quoteData[symbol] || quoteData[code] || {};
    return {
      ...stock,
      code,
      name: String(quote.stock_chi_name || stock.name || code).trim(),
      changePct: quote.change_percent === undefined || quote.change_percent === null ? stock.changePct : toNum(quote.change_percent, 0) * 100,
      price: quote.price === undefined || quote.price === null ? stock.price : toNum(quote.price, 0),
      limitUpDays: quote.limit_up_days === undefined || quote.limit_up_days === null ? stock.limitUpDays : toNum(quote.limit_up_days, 0),
    };
  });
};

const parseHotPlates = (json: any): HotPlate[] => {
  const rows = collectObjects(json, (row) => row.id !== undefined && row.name !== undefined);
  const map = new Map<string, HotPlate>();
  rows.forEach((row) => {
    const id = String(row.id ?? '').trim();
    const name = String(row.name ?? '').trim();
    if (!id || !name || id === '-1') return;
    if (!map.has(id)) {
      map.set(id, {
        id,
        name,
        description: String(row.description || row.desc || '').trim(),
      });
    }
  });
  return Array.from(map.values());
};

const parseLeaderStocksFromText = (text: string, plateId: string): HotStock[] => {
  const raw = String(text || '').replace(/ /g, '').replace(/(.SZ")|(.SS")|(.SH")/g, '"').replace(/"id":-1,"name":"其他"/g, '"id":-2,"name":"其他"');
  const out: HotStock[] = [];
  const seen = new Set<string>();

  const pushRow = (segment: string, first = false) => {
    const matched = first ? segment.match(/\[\[([\s\S]*)/) : segment.match(/\],\[([\s\S]*)/);
    const row = matched?.[1] || segment.replace(/^\[\[/, '').replace(/^\],\[/, '');
    if (!row.includes(`"id":${plateId}`) && !row.includes(`"id":"${plateId}"`)) return;
    const stockPart = row.replace(/\[\{[\s\S]*?\}\]/, '');
    const cells = (stockPart.match(/"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?/g) || []).map((x) => x.replace(/^"|"$/g, ''));
    
    // 自动识别字段索引
    const codeIdx = cells.findIndex((cell) => isStockCode(cell));
    if (codeIdx === -1) return;
    const code = normalizeCode(cells[codeIdx]);

    const nameIdx = cells.findIndex((cell, idx) => idx !== codeIdx && cell.length >= 2 && cell.length <= 10 && !isStockCode(cell));
    const name = nameIdx !== -1 ? cells[nameIdx].trim() : '';

    const strings = cells
      .map((val, idx) => ({ val, idx }))
      .filter((item) => item.idx !== codeIdx && item.idx !== nameIdx);
    const descItem = strings.sort((a, b) => b.val.length - a.val.length)[0];
    const desc = descItem && descItem.val.length > 10 ? descItem.val.trim() : '';

    const rawPct = cells.map((x) => Number(x)).find((x) => Number.isFinite(x) && Math.abs(x) <= 1);
    const label = cells.find((x) => /板|涨停|连板|首板|开板|炸板/.test(x) && x.length < 20) || '';

    if (!code || !name || seen.has(code)) return;
    seen.add(code);
    out.push({
      code,
      name,
      changePct: toNum(rawPct, 0) * 100,
      limitUpDays: /首板/.test(label) ? 1 : Number((label.match(/(\d+)连板/) || [])[1] || 0),
      reason: desc,
      label,
      relatedDesc: desc,
    });
  };

  (raw.match(/(\[\[).*?(?=\],\[)/g) || []).forEach((segment) => pushRow(segment, true));
  (raw.match(/(\],\[).*?((?=\],\[)|(?=\]\]))/g) || []).forEach((segment) => pushRow(segment, false));
  if (!out.length && raw.includes('[[')) pushRow(raw.split(']]')[0], true);

  return out;
};

const parseLeaderStocks = (json: any, plateId: string): HotStock[] => {
  const arrayRows: any[][] = [];
  const seenArrays = new Set<unknown>();
  const walkArrays = (node: unknown) => {
    if (!node || typeof node !== 'object' || seenArrays.has(node)) return;
    seenArrays.add(node);
    if (Array.isArray(node)) {
      // 检查板块ID是否存在于数组的某个位置（通常是索引0或索引8）
      const hasPlate = node.some((cell) => {
        if (Array.isArray(cell)) {
          return cell.some((x: any) => String(x?.id ?? x?.plate_id ?? '') === plateId);
        }
        return false;
      });

      if (
        hasPlate &&
        node.some((cell) => typeof cell === 'string' && isStockCode(cell))
      ) {
        arrayRows.push(node);
      }
      node.forEach(walkArrays);
      return;
    }
    Object.values(node).forEach(walkArrays);
  };
  walkArrays(json);

  if (arrayRows.length) {
    const seen = new Set<string>();
    return arrayRows
      .map((row) => {
        // 自动识别字段索引
        // 1. 查找代码 (符合 6位数字 或 带 .SS/.SZ)
        const codeIdx = row.findIndex((cell) => typeof cell === 'string' && isStockCode(cell));
        if (codeIdx === -1) return null;
        const code = normalizeCode(row[codeIdx]);

        // 2. 查找名称 (通常在代码后面)
        const nameIdx = row.findIndex((cell, idx) => idx !== codeIdx && typeof cell === 'string' && cell.length >= 2 && cell.length <= 10 && !isStockCode(cell));
        const name = nameIdx !== -1 ? String(row[nameIdx]).trim() : '';

        // 3. 查找描述 (最长的字符串，且不是代码或名称)
        const strings = row
          .map((cell, idx) => ({ val: cell, idx }))
          .filter((item) => typeof item.val === 'string' && item.idx !== codeIdx && item.idx !== nameIdx);
        const descItem = strings.sort((a, b) => String(b.val).length - String(a.val).length)[0];
        const desc = descItem && String(descItem.val).length > 10 ? String(descItem.val).trim() : '';

        // 4. 查找标签 (包含"板"等关键字的短字符串)
        const labelItem = strings.find((item) => /板|涨停|连板|首板|开板|炸板/.test(String(item.val)) && String(item.val).length < 20);
        const label = labelItem ? String(labelItem.val).trim() : '';

        // 5. 查找涨幅
        const changeRaw = row.find((cell) => typeof cell === 'number' && Math.abs(cell) <= 100);
        const changePct = Math.abs(Number(changeRaw)) <= 1 ? Number(changeRaw) * 100 : Number(changeRaw);

        if (!code || !name || seen.has(code)) return null;
        seen.add(code);

        return {
          code,
          name,
          changePct: toNum(changePct, 0),
          limitUpDays: /首板/.test(label) ? 1 : Number((label.match(/(\d+)连板/) || [])[1] || 0),
          reason: desc,
          label,
          relatedDesc: desc,
        };
      })
      .filter(Boolean) as HotStock[];
  }

  const rows = collectObjects(json, (row) => {
    const code = row.code ?? row.symbol;
    const name = row.prod_name ?? row.stock_chi_name ?? row.name;
    return code !== undefined && name !== undefined;
  });
  const out: HotStock[] = [];
  const seen = new Set<string>();
  rows.forEach((row) => {
    const related = collectObjects(row, (x) => String(x.id ?? '') === plateId || String(x.plate_id ?? '') === plateId, 20);
    if (plateId && related.length === 0 && JSON.stringify(row).indexOf(`"id":${plateId}`) === -1 && JSON.stringify(row).indexOf(`"id":"${plateId}"`) === -1) return;
    const code = normalizeCode(row.code ?? row.symbol);
    const name = String(row.prod_name ?? row.stock_chi_name ?? row.name ?? '').trim();
    if (!code || !name || seen.has(code)) return;
    seen.add(code);
    const rawPct = row.zf ?? row.change_percent ?? 0;
    const changePct = Math.abs(Number(rawPct)) <= 1 ? Number(rawPct) * 100 : Number(rawPct);
    out.push({
      code,
      name,
      changePct: toNum(changePct, 0),
      limitUpDays: toNum(row.limit_up_days, 0),
      reason: String(row.xq || row.desc || row.description || '').trim(),
      label: String(row.label || row.lb || '').trim(),
      relatedDesc: String(row.xq || row.desc || '').trim(),
    });
  });
  return out;
};

const parsePlateStocks = async (json: any): Promise<HotStock[]> => {
  const stockRows = collectObjects(json, (row) => row.symbol !== undefined || row.code !== undefined, 1000);
  const symbols = Array.from(new Set(stockRows.map((row) => normalizeCode(row.symbol ?? row.code)).filter(isStockCode))).slice(0, 80);
  if (!symbols.length) return [];

  const descByCode = new Map<string, string>();
  stockRows.forEach((row) => {
    const code = normalizeCode(row.symbol ?? row.code);
    const desc = String(row.desc || row.description || '').trim();
    if (code && desc && !descByCode.has(code)) descByCode.set(code, desc);
  });

  const quoteSymbols = symbols.map(toXgbSymbol).filter(Boolean);
  const quoteUrl = `https://flash-api.xuangubao.cn/api/stock/data?fields=symbol,stock_chi_name,change_percent,price,limit_up_days&strict=true&symbols=${quoteSymbols.join(',')}`;
  const labelUrl = `https://flash-api.xuangubao.cn/api/stock_label/labels?symbols=${quoteSymbols.join(',')}`;
  const [quoteJson, labelJson] = await Promise.all([fetchJson(quoteUrl), fetchJson(labelUrl).catch(() => ({ data: {} }))]);
  const quoteData = quoteJson?.data || {};
  const labelData = labelJson?.data || {};

  return symbols.map((code) => {
    const symbol = toXgbSymbol(code);
    const row = quoteData[symbol] || quoteData[code] || {};
    const labelRows = labelData[symbol] || labelData[code] || [];
    const labels = Array.isArray(labelRows)
      ? labelRows.map((x: any) => String(x?.label_name || '').trim()).filter(Boolean).join(',')
      : '';
    return {
      code,
      name: String(row.stock_chi_name || row.name || code).trim(),
      changePct: toNum(row.change_percent, 0) * 100,
      limitUpDays: toNum(row.limit_up_days, 0),
      reason: descByCode.get(code) || '',
      label: labels,
      relatedDesc: descByCode.get(code) || '',
    };
  });
};

const loadHotPlates = async (keepSelection = false) => {
  hotLoading.value = true;
  hotError.value = '';
  try {
    const url = isToday.value
      ? 'https://flash-api.xuangubao.cn/api/surge_stock/plates'
      : `https://flash-api.xuangubao.cn/api/surge_stock/plates?date=${Math.round(new Date(hotDate.value).getTime() / 1000)}`;
    const json = await fetchJson(url);
    hotPlates.value = parseHotPlates(json);
    if (isToday.value) setXgbPlates(hotPlates.value);
    if (!keepSelection || !hotPlates.value.some((x) => x.id === hotSelectedPlateId.value)) {
      const first = hotPlates.value[0];
      hotSelectedPlateId.value = first?.id || '';
      hotSelectedPlateName.value = first?.name || '';
    }
    hotLastUpdated.value = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    if (hotSelectedPlateId.value) await loadHotStocks(hotMode.value);
  } catch (e: any) {
    hotError.value = `热点解答获取失败：${String(e?.message || e)}`;
  } finally {
    hotLoading.value = false;
  }
};

const loadHotStocks = async (mode = hotMode.value) => {
  if (!hotSelectedPlateId.value) return;
  hotMode.value = mode;
  hotStockLoading.value = true;
  hotError.value = '';
  hotExpandedCodes.value = [];
  try {
    if (mode === 'leader') {
      const url = isToday.value
        ? 'https://flash-api.xuangubao.cn/api/surge_stock/stocks?normal=true&uplimit=true'
        : `https://flash-api.xuangubao.cn/api/surge_stock/stocks?date=${hotDateParam.value}&normal=true&uplimit=true`;
      const text = await fetchText(url);
      hotStocks.value = parseLeaderStocksFromText(text, hotSelectedPlateId.value);
      if (!hotStocks.value.length) hotStocks.value = parseLeaderStocks(JSON.parse(text), hotSelectedPlateId.value);
      hotStocks.value = await hydrateStocksWithQuote(hotStocks.value);
    } else {
      const json = await fetchJson(`https://flash-api.xuangubao.cn/api/plate/plate_set?id=${hotSelectedPlateId.value}`);
      hotStocks.value = await parsePlateStocks(json);
    }
    if (isToday.value) setXgbStocksForPlate(hotSelectedPlateId.value, hotStocks.value);
  } catch (e: any) {
    hotError.value = `股票明细获取失败：${String(e?.message || e)}`;
  } finally {
    hotStockLoading.value = false;
  }
};

const selectHotPlate = async (plate: HotPlate) => {
  hotSelectedPlateId.value = plate.id;
  hotSelectedPlateName.value = plate.name;
  await loadHotStocks(hotMode.value);
};

const toggleHotDetail = (code: string) => {
  const next = normalizeCode(code);
  hotExpandedCodes.value = hotExpandedCodes.value.includes(next)
    ? hotExpandedCodes.value.filter((x) => x !== next)
    : [...hotExpandedCodes.value, next];
};

const xueqiuUrl = (code: string) => `https://xueqiu.com/S/${code.startsWith('6') ? 'SH' : 'SZ'}${code}`;

const refreshHotAnswer = () => loadHotPlates(true);

onMounted(() => {
  void loadHotPlates(false);
});
</script>

<template>
  <div class="hot-page">
    <div class="card hot-card" data-page="hotAnswer" id="sec-hot-answer">
      <div class="card-header">
        <div>
          <div class="card-title">热点解答</div>
        </div>
      </div>

      <div class="hot-toolbar">
        <div class="hot-toolbar-left">
          <label class="hot-date">
            <span>日期</span>
            <DatePicker
              v-model:value="hotDateValue"
              class="hot-date-picker"
              format="YYYY-MM-DD"
              :allow-clear="false"
              :input-read-only="true"
              @change="loadHotPlates(false)"
            />
          </label>
          <button class="hot-btn" type="button" @click="refreshHotAnswer()">刷新</button>
          <button class="hot-btn" :class="{ active: hotMode === 'leader' }" type="button" @click="loadHotStocks('leader')">领涨</button>
          <button class="hot-btn" :class="{ active: hotMode === 'all' }" type="button" @click="loadHotStocks('all')">全部</button>
        </div>
        <div class="hot-toolbar-right">
          <span>板块 <b class="hot-stat-num">{{ hotStats.plates }}</b></span>
          <span>个股 <b class="hot-stat-num">{{ hotStats.stocks }}</b></span>
          <span>涨停 <b class="hot-stat-num highlight">{{ hotStats.limit }}</b></span>
          <span v-if="hotLastUpdated">更新 <b class="hot-stat-num">{{ hotLastUpdated }}</b></span>
        </div>
      </div>

      <div v-if="hotError" class="hot-error">{{ hotError }}</div>

      <div class="hot-layout">
        <aside class="hot-plates">
          <!-- Plate Loading Skeleton -->
          <div v-if="hotLoading && !hotPlates.length" class="hot-skeleton-list">
            <div v-for="i in 6" :key="'hsk-p-'+i" class="hot-skeleton-plate">
              <div class="hot-sk-title"></div>
              <div class="hot-sk-line"></div>
            </div>
          </div>

          <template v-else>
            <button
              v-for="plate in hotPlates"
              :key="plate.id"
              class="hot-plate"
              :class="{ active: plate.id === hotSelectedPlateId }"
              type="button"
              @click="selectHotPlate(plate)">
              <span class="hot-plate-name">{{ plate.name }}</span>
              <span v-if="plate.description" class="hot-plate-desc">{{ plate.description }}</span>
            </button>
          </template>
        </aside>

        <section class="hot-detail">
          <div v-if="selectedPlate || hotSelectedPlateName" class="hot-detail-content">
            <div class="hot-detail-head">
              <div>
                <div class="hot-detail-title">{{ selectedPlate?.name || hotSelectedPlateName }}</div>
                <div class="hot-detail-desc">
                  <template v-if="splitLines(selectedPlate?.description).length > 1">
                    <ul class="hot-desc-list">
                      <li v-for="(line, i) in splitLines(selectedPlate?.description)" :key="i">{{ line }}</li>
                    </ul>
                  </template>
                  <template v-else>
                    {{ selectedPlate?.description }}
                  </template>
                </div>
              </div>
              <div class="hot-mode">{{ hotMode === 'leader' ? '领涨' : '全部' }}</div>
            </div>

            <!-- Stock Loading Skeleton -->
            <div v-if="hotStockLoading" class="hot-skeleton-list small">
              <div v-for="i in 4" :key="'hsk-s-'+i" class="hot-skeleton-stock">
                <div class="hot-sk-row">
                  <div class="hot-sk-name"></div>
                  <div class="hot-sk-pct"></div>
                </div>
                <div class="hot-sk-line"></div>
              </div>
            </div>

            <div v-else-if="!sortedStocks.length" class="hot-empty">暂无个股明细</div>
            
            <div v-else class="hot-stock-list">
              <article v-for="stock in sortedStocks" :key="stock.code" class="hot-stock">
                <div class="hot-stock-main">
                  <div class="hot-stock-title">
                    <a class="hot-stock-name" :href="xueqiuUrl(stock.code)" target="_blank" rel="noopener noreferrer">{{ stock.name }}</a>
                    <span v-if="stock.price" class="hot-price">{{ stock.price.toFixed(2) }}</span>
                    <span :class="['hot-pct', stock.changePct >= 0 ? 'up' : 'down']">{{ formatPct(stock.changePct) }}</span>
                    <span v-if="stock.limitUpDays" class="hot-limit">{{ stock.limitUpDays === 1 ? '首板' : stock.limitUpDays + '连板' }}</span>
                    <span v-if="stock.label" class="hot-label">{{ stock.label }}</span>
                  </div>
                  <button v-if="hotMode === 'all' && (stock.reason || stock.relatedDesc)" class="hot-detail-toggle" type="button" @click="toggleHotDetail(stock.code)">
                    {{ hotExpandedCodes.includes(stock.code) ? '收起' : '详情' }}
                  </button>
                </div>
                <div v-if="(stock.reason || stock.relatedDesc) && (hotMode === 'leader' || hotExpandedCodes.includes(stock.code))" class="hot-reason">
                  <ol v-if="splitLines(stock.reason || stock.relatedDesc).length > 1" class="hot-reason-list">
                    <li v-for="(line, index) in splitLines(stock.reason || stock.relatedDesc)" :key="index">
                      {{ line }}
                    </li>
                  </ol>
                  <template v-else>
                    {{ splitLines(stock.reason || stock.relatedDesc)[0] || (stock.reason || stock.relatedDesc) }}
                  </template>
                </div>
              </article>
            </div>
          </div>
          <div v-else class="hot-empty-state">
            <div class="hot-empty-icon">👈</div>
            <div class="hot-empty-text">请在左侧选择感兴趣的热点板块</div>
          </div>
        </section>
      </div>
    </div>

    <ShortReminderFooter />
  </div>
</template>

<style scoped src="./HotAnswerPage.css"></style>
