import { ref } from 'vue';

export interface DragonTigerRecord {
  yzmc: string
  yyb: string
  sblx: string
  gpdm: string
  gpmc: string
  sc: number
  mrje: number | null   // 买入金额（元），null = 未上榜
  mcje: number | null   // 卖出金额（元），null = 未上榜
  rq: string
}

const API_URL = 'http://page1.tdx.com.cn:7615/TQLEX?Entry=CWServ.cfg_fx_yzlhb';

export function useDragonTiger() {
  const dates = ref<string[]>([]);
  const records = ref<DragonTigerRecord[]>([]);
  const loading = ref(false);
  const error = ref('');
  const selectedDate = ref('');

  function parseRecords(rows: any[][]): DragonTigerRecord[] {
    // 先解析，再按 (gpdm + yzmc + yyb) 去重合并
    const raw = rows.map((r) => ({
      yzmc: String(r[0] || ''),
      yyb: String(r[1] || ''),
      sblx: String(r[2] || ''),
      gpdm: String(r[3] || ''),
      gpmc: String(r[4] || ''),
      sc: Number(r[5]) || 0,
      mrje: r[6] != null ? Number(r[6]) : (null as number | null),
      mcje: r[7] != null ? Number(r[7]) : (null as number | null),
      rq: String(r[8] || '').split(' ')[0],
    }));

    const merged = new Map<string, DragonTigerRecord>();
    for (const r of raw) {
      const key = `${r.gpdm}|${r.yzmc}|${r.yyb}`;
      const existing = merged.get(key);
      if (existing) {
        // 合并：取非 null 的最大值（去重时保留单条最完整的买卖额）
        if (r.mrje != null && (existing.mrje == null || r.mrje > existing.mrje)) existing.mrje = r.mrje;
        if (r.mcje != null && (existing.mcje == null || r.mcje > existing.mcje)) existing.mcje = r.mcje;
      } else {
        merged.set(key, { ...r });
      }
    }
    return Array.from(merged.values());
  }

  async function fetchRecords() {
    loading.value = true;
    error.value = '';

    const injected = (window as any).__DRAGON_TIGER_DATA__;
    if (injected && Array.isArray(injected.records) && injected.records.length) {
      records.value = injected.records;
      dates.value = injected.dates || [];
      loading.value = false;
      if (dates.value.length && !selectedDate.value) selectedDate.value = dates.value[0];
      return;
    }

    try {
      const resp = await fetch('./dragon_tiger_data.json');
      if (resp.ok) {
        const data = await resp.json();
        if (Array.isArray(data.records) && data.records.length) {
          records.value = data.records;
          dates.value = data.dates || [];
          loading.value = false;
          if (dates.value.length && !selectedDate.value) selectedDate.value = dates.value[0];
          return;
        }
      }
    } catch {}

    const date = selectedDate.value || '';
    try {
      const resp = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ Params: ['yzlhb', date, '', '', '', 0, 500] }),
        signal: AbortSignal.timeout(10000),
      });
      const d = await resp.json();
      if (d.ErrorCode === 0 && d.ResultSets?.[0]?.Content) {
        records.value = parseRecords(d.ResultSets[0].Content);
        if (!dates.value.length) {
          try {
            const rd = await fetch(API_URL, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ Params: ['rq', '', '', '', '', 0, 20] }),
              signal: AbortSignal.timeout(5000),
            });
            const jd = await rd.json();
            if (jd.ErrorCode === 0) {
              dates.value = (jd.ResultSets?.[0]?.Content || [])
                .map((r: string[]) => (r[0] || '').split(' ')[0])
                .filter(Boolean).reverse();
            }
          } catch {}
        }
      } else {
        error.value = '暂无龙虎榜数据';
      }
    } catch {
      error.value = '数据加载失败';
    } finally {
      loading.value = false;
    }
  }

  async function init() {
    await fetchRecords();
    if (!selectedDate.value && dates.value.length) selectedDate.value = dates.value[0];
  }

  return { dates, records, loading, error, selectedDate, init };
}

export function fmtAmount(v: number | null): string {
  if (v == null) return '--';
  const abs = Math.abs(v);
  if (abs >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(v / 1e4).toFixed(0)}万`;
  return `${v.toFixed(0)}`;
}
