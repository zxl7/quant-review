import { computed, reactive } from 'vue';

export interface XgbHotPlate {
  id: string;
  name: string;
  description: string;
}

export interface XgbHotStock {
  code: string;
  name: string;
  changePct: number;
  limitUpDays?: number;
  reason: string;
  label: string;
  plateId?: string;
}

export interface TomorrowThemeLite {
  id: string;
  themeCode: string;
  themeName: string;
  title: string;
  summary: string;
  ztCount: number;
  cumulateGain: number;
  isHot: boolean;
}

interface ThemeHotState {
  xgbPlates: XgbHotPlate[];
  xgbStocksByPlateId: Record<string, XgbHotStock[]>;
  xgbUpdatedAt: number;
  tmrThemes: TomorrowThemeLite[];
  tmrUpdatedAt: number;
}

const state = reactive<ThemeHotState>({
  xgbPlates: [],
  xgbStocksByPlateId: {},
  xgbUpdatedAt: 0,
  tmrThemes: [],
  tmrUpdatedAt: 0,
});

const normalizeName = (raw: unknown) => String(raw || '').trim().replace(/\s+/g, '');

let xgbBootInflight: Promise<void> | null = null;
let tmrBootInflight: Promise<void> | null = null;

const parseXgbPlatesFromJson = (json: any): XgbHotPlate[] => {
  const out: XgbHotPlate[] = [];
  const seen = new Set<string>();
  const walk = (node: any) => {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    const id = node.id !== undefined ? String(node.id).trim() : '';
    const name = node.name !== undefined ? String(node.name).trim() : '';
    if (id && name && id !== '-1' && !seen.has(id)) {
      seen.add(id);
      out.push({ id, name, description: String(node.description || node.desc || '').trim() });
    }
    Object.values(node).forEach(walk);
  };
  walk(json);
  return out;
};

async function ensureXgbPlatesLoaded(force = false): Promise<void> {
  if (!force && state.xgbPlates.length) return;
  if (xgbBootInflight) return xgbBootInflight;
  xgbBootInflight = (async () => {
    try {
      const res = await fetch(`https://flash-api.xuangubao.cn/api/surge_stock/plates?_ts=${Date.now()}`, {
        cache: 'no-store',
        headers: {
          'Accept': 'application/json, text/plain, */*',
          'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
        },
      });
      if (!res.ok) return;
      const json = await res.json();
      const plates = parseXgbPlatesFromJson(json);
      if (plates.length) {
        state.xgbPlates = plates;
        state.xgbUpdatedAt = Date.now();
      }
    } catch { /* swallow */ } finally {
      xgbBootInflight = null;
    }
  })();
  return xgbBootInflight;
}

async function ensureTomorrowLoaded(force = false): Promise<void> {
  if (!force && state.tmrThemes.length) return;
  if (tmrBootInflight) return tmrBootInflight;
  tmrBootInflight = (async () => {
    try {
      const ts = String(Date.now());
      const rc = (ts + Date.now() + Math.random().toString(36).substring(2, 10)).substring(0, 32);
      const res = await fetch('https://emcfgdata.eastmoney.com/api/themeInvest/getFryTomorrowList', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
        },
        body: JSON.stringify({
          args: { pageSize: 15, lastTradeDate: '' },
          client: 'wap', clientType: 'cfw', clientVersion: '9001',
          randomCode: rc, timestamp: ts,
        }),
        signal: AbortSignal.timeout(10000),
      });
      if (!res.ok) return;
      const json = await res.json();
      if (json?.code !== 0) return;
      const data = json.data || {};
      const items: TomorrowThemeLite[] = [];
      Object.keys(data).filter((k) => /^\d+$/.test(k)).sort((a, b) => Number(a) - Number(b)).forEach((k) => {
        const it = data[k]; if (!it) return;
        items.push({
          id: String(it.eid || it.sortNum || ''),
          themeCode: String(it.themeCode || ''),
          themeName: String(it.themeName || '').trim(),
          title: String(it.title || ''),
          summary: String(it.summary || ''),
          ztCount: Number(it.fex3) || 0,
          cumulateGain: Number(it.cumulateF3) || 0,
          isHot: it.isHot === 1 || it.isHot === '1',
        });
      });
      if (items.length) {
        state.tmrThemes = items.filter((t) => t.themeName);
        state.tmrUpdatedAt = Date.now();
      }
    } catch { /* swallow */ } finally {
      tmrBootInflight = null;
    }
  })();
  return tmrBootInflight;
}

export function useThemeHotStore() {
  const xgbPlates = computed(() => state.xgbPlates);
  const xgbStocksByPlateId = computed(() => state.xgbStocksByPlateId);
  const tmrThemes = computed(() => state.tmrThemes);
  const xgbUpdatedAt = computed(() => state.xgbUpdatedAt);
  const tmrUpdatedAt = computed(() => state.tmrUpdatedAt);

  const xgbHotPlateNames = computed<Set<string>>(() => new Set(state.xgbPlates.map((p) => normalizeName(p.name)).filter(Boolean)));
  const tmrHotThemeNames = computed<Set<string>>(() => new Set(state.tmrThemes.filter((t) => t.isHot).map((t) => normalizeName(t.themeName)).filter(Boolean)));
  const tmrAllThemeNames = computed<Set<string>>(() => new Set(state.tmrThemes.map((t) => normalizeName(t.themeName)).filter(Boolean)));

  const xgbHotCodes = computed<Set<string>>(() => {
    const set = new Set<string>();
    Object.values(state.xgbStocksByPlateId).forEach((arr) => arr.forEach((s) => { if (s.code) set.add(String(s.code).trim()); }));
    return set;
  });

  const narrativeHitForTheme = (themeOrPlateName: unknown): { hit: boolean; sources: string[] } => {
    const key = normalizeName(themeOrPlateName);
    if (!key) return { hit: false, sources: [] };
    const sources: string[] = [];
    if (xgbHotPlateNames.value.has(key)) sources.push('选股宝热点');
    if (tmrHotThemeNames.value.has(key)) sources.push('东财明日热门');
    else if (tmrAllThemeNames.value.has(key)) sources.push('东财明日');
    if (!sources.length) {
      const partial = state.xgbPlates.some((p) => normalizeName(p.name).includes(key) || key.includes(normalizeName(p.name)));
      if (partial) sources.push('选股宝热点(模糊)');
    }
    return { hit: sources.length > 0, sources };
  };

  const narrativeHitForStock = (code: unknown): boolean => xgbHotCodes.value.has(String(code || '').trim());

  const setXgbPlates = (plates: XgbHotPlate[]) => {
    state.xgbPlates = Array.isArray(plates) ? plates.map((p) => ({
      id: String(p?.id || '').trim(),
      name: String(p?.name || '').trim(),
      description: String(p?.description || '').trim(),
    })).filter((p) => p.id && p.name) : [];
    state.xgbUpdatedAt = Date.now();
  };

  const setXgbStocksForPlate = (plateId: string, stocks: XgbHotStock[]) => {
    const pid = String(plateId || '').trim();
    if (!pid) return;
    const list = Array.isArray(stocks) ? stocks.map((s) => ({
      code: String(s?.code || '').trim(),
      name: String(s?.name || '').trim(),
      changePct: Number(s?.changePct) || 0,
      limitUpDays: Number(s?.limitUpDays) || 0,
      reason: String(s?.reason || '').trim(),
      label: String(s?.label || '').trim(),
      plateId: pid,
    })).filter((s) => s.code) : [];
    state.xgbStocksByPlateId = { ...state.xgbStocksByPlateId, [pid]: list };
  };

  const setTomorrowThemes = (themes: TomorrowThemeLite[]) => {
    state.tmrThemes = Array.isArray(themes) ? themes.map((t) => ({
      id: String(t?.id || ''),
      themeCode: String(t?.themeCode || ''),
      themeName: String(t?.themeName || '').trim(),
      title: String(t?.title || ''),
      summary: String(t?.summary || ''),
      ztCount: Number(t?.ztCount) || 0,
      cumulateGain: Number(t?.cumulateGain) || 0,
      isHot: Boolean(t?.isHot),
    })).filter((t) => t.themeName) : [];
    state.tmrUpdatedAt = Date.now();
  };

  return {
    xgbPlates,
    xgbStocksByPlateId,
    xgbUpdatedAt,
    tmrThemes,
    tmrUpdatedAt,
    xgbHotPlateNames,
    tmrHotThemeNames,
    tmrAllThemeNames,
    xgbHotCodes,
    narrativeHitForTheme,
    narrativeHitForStock,
    setXgbPlates,
    setXgbStocksForPlate,
    setTomorrowThemes,
    ensureXgbPlatesLoaded,
    ensureTomorrowLoaded,
  };
}
