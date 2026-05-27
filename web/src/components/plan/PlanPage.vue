<script setup lang="ts">
import { computed } from 'vue';
import { useMarketData } from '../../composables/useMarketData';
import { useThemeHotStore } from '../../composables/useThemeHotStore';
import ShortReminderFooter from '../common/ShortReminderFooter.vue';

const { marketData } = useMarketData();
const { xgbUpdatedAt, tmrUpdatedAt, xgbPlates, tmrThemes } = useThemeHotStore();

const xqUrl = (code?: string | null) => {
  const raw = String(code || '').trim();
  if (!raw) return 'https://xueqiu.com';
  const upper = raw.toUpperCase();
  if (upper.includes('.')) {
    const [num, suffix] = upper.split('.');
    const market = suffix === 'SH' ? 'SH' : suffix === 'SZ' ? 'SZ' : '';
    return market ? `https://xueqiu.com/S/${market}${num}` : `https://xueqiu.com/S/${upper}`;
  }
  const market = raw.startsWith('6') ? 'SH' : 'SZ';
  return `https://xueqiu.com/S/${market}${raw}`;
};

const formatPosition = (v: unknown) => {
  if (v === undefined || v === null || v === '') return '-';
  if (typeof v === 'number') return `${Math.round(v * 100)}%`;
  return String(v);
};

const planGuide = computed(() => marketData.value?.planGuide || null);
const planGuidePills = computed(() => {
  const g = planGuide.value;
  if (!g) return [];
  return [
    { text: `右侧：${g.rightsideText || '-'}`, primary: true },
    ...(g.mainline ? [{ text: `主线：${g.mainline}`, primary: false }] : []),
    ...(g.nature ? [{ text: `性质：${g.nature}`, primary: false }] : []),
    ...(g.resonance ? [{ text: `共振：${g.resonance}`, primary: false }] : []),
  ];
});
const planGuideWarnings = computed(() => Array.isArray(planGuide.value?.warnings) ? planGuide.value?.warnings : []);

const planFocusChips = computed(() => {
  const raw = String(marketData.value?.actionGuideV2?.meta?.title || '').replace(/^🧩\s*/, '');
  if (!raw) return [];
  const alias: Record<string, string> = {
    盘面基调: '基调',
    主线: '主线',
    模式: '模式',
    仓位: '姿态',
  };
  return raw
    .split('｜')
    .map((seg) => {
      const [k, ...rest] = String(seg || '').split('：');
      const v = rest.join('：').trim();
      if (!k || !v) return null;
      return { k: alias[k.trim()] || k.trim(), v };
    })
    .filter(Boolean) as Array<{ k: string; v: string }>;
});
const planFocusNote = computed(() => String(marketData.value?.actionGuideV2?.meta?.detail || marketData.value?.actionAdvisor?.summary || '').trim());
const planFocusEvidences = computed(() => {
  const rows = Array.isArray(marketData.value?.actionAdvisor?.evidences) ? marketData.value.actionAdvisor.evidences : [];
  return rows.slice(0, 3);
});

const positionAdvice = computed(() => {
  const finalPosition = formatPosition(marketData.value?.planGuide?.position);
  if (finalPosition && finalPosition !== '-') {
    const rightside = String(marketData.value?.planGuide?.rightsideText || '');
    const stance = rightside === '禁止' ? '防守' : rightside === '允许' ? '进攻' : '均衡';
    const cls = stance === '进攻' ? 'pos-attack' : stance === '防守' ? 'pos-def' : 'pos-balance';
    const pillCls = stance === '进攻' ? 'attack' : stance === '防守' ? 'def' : 'balance';
    return { stance, range: finalPosition, note: '', cls, pillCls };
  }
  const heat = Number(marketData.value?.mood?.heat ?? 0);
  const risk = Number(marketData.value?.mood?.risk ?? 0);
  const stage = String(marketData.value?.moodStage?.type || '');
  let stance = '均衡';
  let range = '35–50%';
  let note = '围绕主线核心，低位试错为主；不追高位一致。';
  if (stage === 'fire') {
    stance = '防守';
    range = '15–30%';
    note = '退潮/冰点：只做低位试错，回避高位接力；优先看修复信号。';
  } else if (risk >= heat + 10) {
    stance = '防守';
    range = '20–35%';
    note = '风险压过热度：轻仓、分散、快进快出；等确定性再加仓。';
  } else if (heat >= risk + 10) {
    stance = '进攻';
    range = '50–70%';
    note = '热度占优：围绕主线核心与确认节点加仓；不做无辨识度扩散。';
  }
  const cls = stance === '进攻' ? 'pos-attack' : stance === '防守' ? 'pos-def' : 'pos-balance';
  const pillCls = stance === '进攻' ? 'attack' : stance === '防守' ? 'def' : 'balance';
  return { stance, range, note, cls, pillCls };
});

const ztRelaySorted = computed(() => (marketData.value?.ztAnalysis?.relay || []).slice());
const ztWatchSorted = computed(() => (marketData.value?.ztAnalysis?.watch || []).slice());

const ztTagRows = (row: any) => Array.isArray(row?.tagRows) ? row.tagRows : [];

// 算法建议（picks_advisor）：来自 inject_data.py 透传的 watchlist.picks_advisor
type PickStock = {
  code: string; name: string; action: string; score: number;
  main_line: string; primary_sector: string; primary_confidence: number;
  reasons: string[]; cautions: string[];
  lbc: number; cje_yi: number; seal_fund_yi: number; turnover: number;
  breakdown?: Record<string, number>; bonus?: number;
};
type MainLinePicks = {
  main_line: string; confidence: number; is_chain: boolean; constituents: string[];
  buy: PickStock[]; watch: PickStock[]; summary: string;
  diagnostics?: { member_count: number; avg_score: number };
};

const picksAdvisor = computed(() => {
  const pa = (marketData.value as any)?.picks_advisor;
  if (!pa || typeof pa !== 'object') return null;
  const picks = Array.isArray(pa.main_line_picks) ? pa.main_line_picks as MainLinePicks[] : [];
  if (!picks.length) return null;
  return {
    main_line_picks: picks,
    diagnostics: pa.diagnostics || {},
    generated_at_bj: (marketData.value as any)?.watchlist?.generated_at_bj || '',
  };
});

const confClass = (c: number) => {
  if (c >= 0.7) return 'conf-strong';
  if (c >= 0.5) return 'conf-mid';
  return 'conf-weak';
};

const scoreClass = (s: number) => {
  if (s >= 70) return 'score-strong';
  if (s >= 50) return 'score-mid';
  return 'score-weak';
};

// watchlist 反向索引：code → { primary_sector, primary_confidence, main_line, main_line_confidence }
// 数据来自 inject_data.py 的 _build_watchlist_stock_index（M3/M4 多源融合结果）。
const mainLineOf = (code: unknown) => {
  const k = String(code || '').trim();
  if (!k) return null;
  const idx = (marketData.value as any)?.watchlist_stock_index;
  if (!idx || typeof idx !== 'object') return null;
  const info = idx[k];
  if (!info) return null;
  return {
    primary_sector: String(info.primary_sector || ''),
    primary_confidence: Number(info.primary_confidence || 0),
    main_line: String(info.main_line || ''),
    main_line_confidence: Number(info.main_line_confidence || 0),
  };
};

type ZtStockPick = {
  code: string;
  name: string;
  lbc: number;
  cjeYi: number;
  zjYi: number;
  zbc: number;
};

type SectorBucket = {
  theme: string;
  source: 'realtime' | 'fallback';
  sources: string[];
  description: string;
  count: number;
  maxLbc: number;
  highTier: ZtStockPick[];
  midTier: ZtStockPick[];
  baseTier: ZtStockPick[];
  plateStrength?: number;
  plateLead?: string;
  matchedLocalThemes: string[];
};

const plateStrengthByName = computed(() => {
  const map = new Map<string, { strength: number; lead: string }>();
  (marketData.value?.plateRankTop10 || []).forEach((p: any) => {
    const name = String(p?.name || '').trim();
    if (!name) return;
    map.set(name, { strength: Number(p?.strength || 0), lead: String(p?.lead || '').trim() });
  });
  return map;
});

const normalizeThemeName = (raw: unknown) => String(raw || '').trim().replace(/\s+/g, '');

const themeToZtStocks = computed(() => {
  const out = new Map<string, ZtStockPick[]>();
  const ztgc = Array.isArray(marketData.value?.ztgc) ? marketData.value.ztgc : [];
  const themesMap = (marketData.value?.zt_code_themes || {}) as Record<string, string[]>;
  ztgc.forEach((s: any) => {
    const code = String(s?.dm || s?.code || '').trim();
    if (!code) return;
    const themes = (themesMap[code] && themesMap[code].length ? themesMap[code] : (s?.hy ? [String(s.hy)] : [])).filter(Boolean);
    if (!themes.length) return;
    const pick: ZtStockPick = {
      code,
      name: String(s?.mc || s?.name || code),
      lbc: Number(s?.lbc || 0),
      cjeYi: Number(s?.cje || 0) / 1e8,
      zjYi: Number(s?.zj || 0) / 1e8,
      zbc: Number(s?.zbc || 0),
    };
    themes.forEach((t) => {
      const k = String(t).trim();
      if (!k) return;
      if (!out.has(k)) out.set(k, []);
      const list = out.get(k)!;
      if (!list.some((x) => x.code === pick.code)) list.push(pick);
    });
  });
  return out;
});

const findMatchingLocalThemes = (hotName: string): string[] => {
  const key = normalizeThemeName(hotName);
  if (!key) return [];
  const matches: string[] = [];
  themeToZtStocks.value.forEach((_v, k) => {
    const kk = normalizeThemeName(k);
    if (!kk) return;
    if (kk === key) { matches.unshift(k); return; }
    if (kk.includes(key) || (key.length >= 3 && key.includes(kk))) matches.push(k);
  });
  return matches;
};

const aggregateStocksForTheme = (hotName: string): { stocks: ZtStockPick[]; matched: string[] } => {
  const matched = findMatchingLocalThemes(hotName);
  const dedup = new Map<string, ZtStockPick>();
  matched.forEach((t) => {
    (themeToZtStocks.value.get(t) || []).forEach((s) => {
      if (!dedup.has(s.code)) dedup.set(s.code, s);
    });
  });
  const stocks = Array.from(dedup.values());
  stocks.sort((a, b) => (b.lbc - a.lbc) || (b.zjYi - a.zjYi) || (b.cjeYi - a.cjeYi));
  return { stocks, matched };
};

const makeBucket = (
  theme: string,
  source: 'realtime' | 'fallback',
  sources: string[],
  description: string,
  stocks: ZtStockPick[],
  matched: string[],
): SectorBucket => {
  const maxLbc = stocks[0]?.lbc || 0;
  const plateInfo = plateStrengthByName.value.get(theme) || (matched.length ? plateStrengthByName.value.get(matched[0]) : undefined);
  return {
    theme,
    source,
    sources,
    description,
    count: stocks.length,
    maxLbc,
    highTier: stocks.filter((s) => s.lbc >= 3).slice(0, 4),
    midTier: stocks.filter((s) => s.lbc === 2).slice(0, 4),
    baseTier: stocks.filter((s) => s.lbc <= 1).slice(0, 6),
    plateStrength: plateInfo?.strength,
    plateLead: plateInfo?.lead,
    matchedLocalThemes: matched,
  };
};

const sectorTierPicks = computed<SectorBucket[]>(() => {
  void xgbUpdatedAt.value;
  void tmrUpdatedAt.value;

  const ztgcLen = Array.isArray(marketData.value?.ztgc) ? marketData.value.ztgc.length : 0;
  if (!ztgcLen) return [];

  const xgb = xgbPlates.value;
  const tmr = tmrThemes.value;

  // 实时优先:用选股宝热点板块 / 东财明日题材驱动
  const realtimeBuckets = new Map<string, SectorBucket>();
  xgb.forEach((p) => {
    const name = String(p.name || '').trim();
    if (!name || realtimeBuckets.has(name)) return;
    const { stocks, matched } = aggregateStocksForTheme(name);
    realtimeBuckets.set(name, makeBucket(name, 'realtime', ['选股宝热点'], p.description || '', stocks, matched));
  });
  tmr.forEach((t) => {
    const name = String(t.themeName || '').trim();
    if (!name) return;
    if (realtimeBuckets.has(name)) {
      const exist = realtimeBuckets.get(name)!;
      if (!exist.sources.includes(t.isHot ? '东财明日热门' : '东财明日')) {
        exist.sources.push(t.isHot ? '东财明日热门' : '东财明日');
      }
      if (!exist.description && t.summary) exist.description = t.summary;
      return;
    }
    // 只让明日热门进入(非热门跳过避免噪音)
    if (!t.isHot) return;
    const { stocks, matched } = aggregateStocksForTheme(name);
    realtimeBuckets.set(name, makeBucket(name, 'realtime', ['东财明日热门'], t.summary || '', stocks, matched));
  });

  let buckets = Array.from(realtimeBuckets.values());

  // 实时数据完全为空 → 本地兜底:按 ztgc theme 命中数最高的前 N 个 theme
  if (!xgb.length && !tmr.length) {
    const themeCount = new Map<string, number>();
    const themesMap = (marketData.value?.zt_code_themes || {}) as Record<string, string[]>;
    Object.values(themesMap).forEach((arr: any) => {
      (Array.isArray(arr) ? arr : []).forEach((t: any) => {
        const k = String(t || '').trim();
        if (!k) return;
        themeCount.set(k, (themeCount.get(k) || 0) + 1);
      });
    });
    const sortedThemes = Array.from(themeCount.entries()).sort((a, b) => b[1] - a[1]).map(([t]) => t).slice(0, 8);
    sortedThemes.forEach((t) => {
      const { stocks, matched } = aggregateStocksForTheme(t);
      buckets.push(makeBucket(t, 'fallback', ['本地涨停归集'], '', stocks, matched));
    });
  } else {
    // 实时有数据,但有些 hot plate 在涨停池里完全没匹配到 → 仍然展示(空梯队),提示"narrative热但价格未跟"
    // (已经包含在 realtimeBuckets,无需额外动作)
  }

  // 排序:有涨停股的在前 → maxLbc → count
  buckets.sort((a, b) => {
    const aHas = a.count > 0 ? 1 : 0;
    const bHas = b.count > 0 ? 1 : 0;
    if (aHas !== bHas) return bHas - aHas;
    if (b.maxLbc !== a.maxLbc) return b.maxLbc - a.maxLbc;
    return b.count - a.count;
  });

  return buckets.slice(0, 6);
});

const sectorPicksMeta = computed(() => {
  void xgbUpdatedAt.value;
  void tmrUpdatedAt.value;
  const buckets = sectorTierPicks.value;
  const realtimeCnt = buckets.filter((b) => b.source === 'realtime').length;
  const fallbackUsed = buckets.some((b) => b.source === 'fallback');
  return {
    bucketTotal: buckets.length,
    realtimeCnt,
    fallbackUsed,
    xgbCnt: xgbPlates.value.length,
    tmrCnt: tmrThemes.value.length,
    tmrHotCnt: tmrThemes.value.filter((t) => t.isHot).length,
  };
});
</script>

<template>
  <div class="plan-page">
    <div class="card" data-page="plan" id="sec-action">
      <div class="card-title">明日行动指南</div>
      <div class="plan-top-grid">
        <div class="plan-main-stack">
          <div class="v2-strategy" v-if="planGuide">
            <div class="row">
              <div class="head-main">
                <div class="tone">{{ planGuide.phase || '-' }}</div>
                <span class="plan-score-badge">情绪 <strong>{{ planGuide.score ?? '-' }}</strong></span>
              </div>
              <div class="cap">仓位上限：{{ formatPosition(planGuide.position) }}</div>
            </div>
            <div class="advice" :class="planGuide.rightsideText === '禁止' ? 'danger' : (planGuide.rightsideText === '允许' ? '' : 'warn')" v-if="planGuide.advice">{{ planGuide.advice }}</div>
            <div class="kpis">
              <span v-for="(pill, idx) in planGuidePills" :key="'pg-pill-'+idx" class="pill" :class="{ primary: pill.primary }">{{ pill.text }}</span>
            </div>
            <details v-if="planGuideWarnings.length">
              <summary>展开提示</summary>
              <ul class="rules">
                <li v-for="(r, i) in planGuideWarnings" :key="'c-w-'+i">{{ r }}</li>
              </ul>
            </details>
          </div>
          <div class="pos-card" v-if="marketData.mood">
            <div class="pos-left">
              <span class="pos-k">最终仓位上限：</span>
              <span class="pos-v" :class="positionAdvice.cls">{{ positionAdvice.range }}</span>
              <div class="pos-sub">{{ positionAdvice.note }}</div>
            </div>
            <div class="pos-tags">
              <span class="pos-pill" :class="positionAdvice.pillCls">{{ positionAdvice.stance }}</span>
              <span class="pos-pill">热{{ marketData.mood?.heat ?? '-' }}/险{{ marketData.mood?.risk ?? '-' }}</span>
              <span class="pos-pill">{{ marketData.moodStage?.title || '-' }}</span>
            </div>
          </div>
        </div>
        <div class="plan-side-stack">
          <div class="plan-focus-card" v-if="planFocusChips.length || planFocusNote || planFocusEvidences.length">
            <div class="plan-focus-head">
              <div class="plan-focus-title">盘面聚焦</div>
              <div class="plan-focus-posture" v-if="marketData.actionAdvisor">{{ marketData.actionAdvisor.posture }}</div>
            </div>
            <div class="plan-focus-chips" v-if="planFocusChips.length">
              <span class="plan-focus-chip" v-for="(chip, idx) in planFocusChips" :key="'pfc-'+idx">
                <em>{{ chip.k }}</em>
                <strong>{{ chip.v }}</strong>
              </span>
            </div>
            <div class="plan-focus-note" v-if="planFocusNote">{{ planFocusNote }}</div>
            <div class="plan-focus-evidences" v-if="planFocusEvidences.length">
              <span class="plan-focus-evidence" v-for="(x, i) in planFocusEvidences" :key="'pfe-'+i">
                <span class="icon">{{ x.icon }}</span>
                <span>{{ x.text }}</span>
              </span>
            </div>
          </div>
        </div>
      </div>
      <div class="summary3" v-if="marketData.summary3?.lines && marketData.summary3.lines.length">
        <div class="summary3-line" v-for="(l, i) in marketData.summary3.lines" :key="'plan-s3-'+i"><strong>{{ Number(i)+1 }}.</strong> {{ l }}</div>
      </div>
    </div>

    <div class="card" data-page="plan" id="sec-picks-advisor" v-if="picksAdvisor">
      <div class="card-header">
        <div>
          <div class="card-title">算法建议（买入 · 观察）</div>
          <div class="advisor-subtitle">
            <strong class="orange-text">{{ picksAdvisor.diagnostics?.total_buy ?? 0 }}</strong> 买入 /
            <strong class="blue-text">{{ picksAdvisor.diagnostics?.total_watch ?? 0 }}</strong> 观察
            <span class="advisor-meta" v-if="picksAdvisor.generated_at_bj">· 更新 {{ picksAdvisor.generated_at_bj.slice(11, 16) }}</span>
          </div>
        </div>
      </div>
      <div class="advisor-grid">
        <div class="advisor-mainline" v-for="ml in picksAdvisor.main_line_picks" :key="'adv-ml-'+ml.main_line">
          <div class="advisor-ml-header">
            <span class="advisor-ml-name">{{ ml.main_line }}</span>
            <span class="advisor-ml-chain" v-if="ml.is_chain" :title="ml.constituents.join('·')">产业链</span>
            <span class="advisor-ml-count">{{ ml.diagnostics?.member_count ?? 0 }}只成员</span>
          </div>

          <div class="advisor-section" v-if="ml.buy?.length">
            <div class="advisor-label advisor-label-buy">📈 买入</div>
            <div class="advisor-row advisor-row-buy" v-for="s in ml.buy" :key="'b-'+s.code">
              <div class="advisor-row-top">
                <a class="advisor-name" :href="xqUrl(s.code)" target="_blank" rel="noopener noreferrer">{{ s.name }}</a>
                <span class="advisor-score" :class="scoreClass(s.score)">{{ s.score }}</span>
                <span class="advisor-tier" v-if="s.lbc >= 2">{{ s.lbc }}板</span>
                <span class="advisor-tier" v-else-if="s.lbc === 1">首板</span>
                <span class="advisor-tier" v-else-if="s.cje_yi >= 100">容量</span>
              </div>
              <div class="advisor-reasons">
                <span class="advisor-reason" v-for="(r, ri) in s.reasons" :key="'r-'+s.code+'-'+ri">✓ {{ r }}</span>
              </div>
              <div class="advisor-cautions" v-if="s.cautions?.length">
                <span class="advisor-caution" v-for="(c, ci) in s.cautions" :key="'c-'+s.code+'-'+ci">⚠ {{ c }}</span>
              </div>
            </div>
          </div>

          <div class="advisor-section" v-if="ml.watch?.length">
            <div class="advisor-label advisor-label-watch">👁 观察</div>
            <div class="advisor-watch-grid">
              <a class="advisor-watch-item" v-for="s in ml.watch" :key="'w-'+s.code"
                :href="xqUrl(s.code)" target="_blank" rel="noopener noreferrer"
                :title="s.reasons.join(' · ')">
                <span class="advisor-name">{{ s.name }}</span>
                <span class="advisor-watch-score" :class="scoreClass(s.score)">{{ s.score }}</span>
                <span class="advisor-watch-lbc" v-if="s.lbc >= 2">{{ s.lbc }}板</span>
                <span class="advisor-watch-lbc" v-else-if="s.lbc === 1">首板</span>
                <span class="advisor-watch-cje" v-else-if="s.cje_yi >= 30">{{ s.cje_yi.toFixed(0) }}亿</span>
              </a>
            </div>
          </div>

          <div class="advisor-summary">{{ ml.summary }}</div>
        </div>
      </div>
    </div>

    <div class="card" data-page="plan" id="sec-sector-tier-picks" v-if="sectorTierPicks.length">
      <div class="card-header">
        <div>
          <div class="card-title">板块·梯队推票</div>
          <div class="stp-subtitle">
            <span class="stp-dot-realtime"></span>
            实时驱动 <strong>{{ sectorPicksMeta.realtimeCnt }}</strong>
            <span class="stp-sep">·</span>
            选股宝 {{ sectorPicksMeta.xgbCnt }}
            <span class="stp-sep">·</span>
            东财明日热门 {{ sectorPicksMeta.tmrHotCnt }}/{{ sectorPicksMeta.tmrCnt }}
            <template v-if="sectorPicksMeta.fallbackUsed">
              <span class="stp-sep">·</span>
              <span class="orange-text" style="font-weight: 900" title="实时接口无数据,退回本地涨停归集">⚠ 本地兜底</span>
            </template>
          </div>
        </div>
        <div class="card-badge">narrative × 涨停 × 梯队</div>
      </div>
      <div class="sector-tier-grid">
        <div
          v-for="(bucket, i) in sectorTierPicks"
          :key="'stp-'+bucket.theme+'-'+i"
          class="sector-tier-card"
          :class="[bucket.source === 'realtime' ? 'is-realtime' : 'is-fallback', !bucket.count ? 'is-empty' : '']">
          <div class="stp-head">
            <div class="stp-name">
              <span class="stp-rank">{{ i + 1 }}</span>
              <span class="stp-name-text">{{ bucket.theme }}</span>
            </div>
            <span class="stp-source-pill" :class="bucket.sources[0] && bucket.sources[0].includes('选股宝') ? 'src-xgb' : (bucket.sources[0] && bucket.sources[0].includes('东财') ? 'src-tmr' : 'src-local')" :title="bucket.sources.join(' · ')">
              <template v-if="bucket.sources[0] && bucket.sources[0].includes('选股宝')">🔥 选股宝</template>
              <template v-else-if="bucket.sources[0] && bucket.sources[0].includes('东财')">⏭ 东财明日</template>
              <template v-else>本地</template>
            </span>
          </div>
          <div class="stp-meta">
            <span class="stp-kv"><strong :class="bucket.count >= 3 ? 'red-text' : 'orange-text'">{{ bucket.count }}</strong>只涨停</span>
            <span class="stp-sep" v-if="bucket.maxLbc >= 2">·</span>
            <span class="stp-kv" v-if="bucket.maxLbc >= 2">最高 <strong class="red-text">{{ bucket.maxLbc }}</strong>板</span>
            <span class="stp-sep" v-if="bucket.plateStrength">·</span>
            <span class="stp-kv" v-if="bucket.plateStrength">强度 <strong>{{ Math.round(bucket.plateStrength) }}</strong></span>
            <span class="stp-sep" v-if="bucket.plateLead">·</span>
            <span class="stp-kv" v-if="bucket.plateLead">领涨 <strong>{{ bucket.plateLead }}</strong></span>
          </div>
          <div class="stp-desc" v-if="bucket.description" :title="bucket.description">{{ bucket.description }}</div>
          <div class="stp-empty" v-if="!bucket.count">
            narrative 热但涨停池暂未跟上 · 留意首板异动
          </div>
          <div class="stp-tiers" v-else>
            <div class="stp-tier-block" v-if="bucket.highTier.length">
              <div class="stp-tier-label tier-high">高位 ≥3连</div>
              <div class="stp-high-rows">
                <a v-for="s in bucket.highTier" :key="'h-'+bucket.theme+'-'+s.code"
                  class="stp-high-row" :href="xqUrl(s.code)" target="_blank" rel="noopener noreferrer">
                  <span class="stp-star">★</span>
                  <span class="stp-high-name">{{ s.name }}</span>
                  <span class="stp-high-tag">{{ s.lbc }}板</span>
                  <span class="stp-high-fund" v-if="s.zjYi >= 1">封 {{ s.zjYi.toFixed(1) }}亿</span>
                  <span class="stp-high-fund" v-else-if="s.cjeYi >= 1">{{ s.cjeYi.toFixed(1) }}亿</span>
                </a>
              </div>
            </div>
            <div class="stp-tier-block" v-if="bucket.midTier.length">
              <div class="stp-tier-label tier-mid">中位 2连</div>
              <div class="stp-name-row">
                <a v-for="(s, mi) in bucket.midTier" :key="'m-'+bucket.theme+'-'+s.code"
                  class="stp-name-link mid" :href="xqUrl(s.code)" target="_blank" rel="noopener noreferrer">
                  {{ s.name }}<span v-if="mi < bucket.midTier.length - 1" class="stp-name-sep">·</span>
                </a>
              </div>
            </div>
            <div class="stp-tier-block" v-if="bucket.baseTier.length">
              <div class="stp-tier-label tier-base">首板 <span class="stp-tier-count">({{ bucket.count - bucket.highTier.length - bucket.midTier.length }})</span></div>
              <div class="stp-name-row">
                <a v-for="(s, bi) in bucket.baseTier" :key="'b-'+bucket.theme+'-'+s.code"
                  class="stp-name-link base" :href="xqUrl(s.code)" target="_blank" rel="noopener noreferrer">
                  {{ s.name }}<span v-if="bi < bucket.baseTier.length - 1" class="stp-name-sep">·</span>
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="card" data-page="plan" id="sec-zt-analysis">
      <div class="card-header">
        <div class="zt-header-left">
          <div class="card-title">
            <span>涨停数据分析</span>
            <span class="zt-header-sector" v-if="marketData.ztAnalysis?.meta?.tierThemeCount">
              梯队：{{ marketData.ztAnalysis?.meta?.tierThemeCount }}板块
              <template v-if="marketData.ztAnalysis?.meta?.tierThemeTop">（{{ marketData.ztAnalysis?.meta?.tierThemeTop }}）</template>
            </span>
            <div class="zt-header-meta-inline">
              <span class="sep">｜</span>
              涨停池 <span class="orange-text">{{ marketData.ztgc?.length ?? 0 }}</span>
              <span class="sep">·</span>
              题材映射 <span class="orange-text">{{ marketData.zt_code_themes ? Object.keys(marketData.zt_code_themes).length : 0 }}</span>
            </div>
          </div>
        </div>
        <div class="card-badge">封单 · 板块归属 · 量能 · 炸板 · 梯队</div>
      </div>
      <div class="zt-panel">
        <div class="zt-col">
          <div class="section-header">接力候选</div>
          <div class="zt-list">
            <div class="zt-item" v-for="(row, i) in ztRelaySorted" :key="'relay-'+i">
              <div class="zt-top">
                <div>
                  <div class="zt-name">
                    <a v-if="row.code" class="stock-link" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
                    <span v-else>{{ row.name }}</span>
                  </div>
                  <div class="zt-sub" v-html="row.reason"></div>
                </div>
                <div class="zt-score" :class="row.superLeaderTone || ''" :title="row.factorHint || ''">
                  <div class="v">{{ row.factorScore ?? row.score }}</div>
                  <div class="k">{{ row.scoreLabel || '接力优先' }}</div>
                  <div class="g" v-if="row.scoreSubLabel">{{ row.scoreSubLabel }}</div>
                </div>
              </div>
              <div class="zt-mainline-row" v-if="mainLineOf(row.code)">
                <span class="zt-ml-chip">
                  🏷 {{ mainLineOf(row.code)?.primary_sector }}
                </span>
                <span class="zt-ml-line" v-if="mainLineOf(row.code)?.main_line">
                  · 主线 <strong>{{ mainLineOf(row.code)?.main_line }}</strong>
                </span>
              </div>
              <div class="zt-enrich-row" v-if="row.emThemes?.length || row.capacityCore || row.crossSourceBoost">
                <span class="zt-enrich-chip" v-if="row.emThemes?.length" title="东方财富题材确认">东财: {{ row.emThemes.join(' · ') }}</span>
                <span class="zt-enrich-chip" v-if="row.xgbEvents?.length" title="选股宝异动确认">选股宝异动</span>
                <span class="zt-enrich-chip enrich-cap" v-if="row.capacityLabel && row.capacityLabel !== '小盘'">{{ row.capacityLabel }}</span>
                <span class="zt-enrich-chip enrich-boost" v-if="row.crossSourceBoost">+{{ row.crossSourceBoost }}</span>
              </div>
              <div class="zt-tags">
                <div class="zt-tag-row" v-for="tagRow in ztTagRows(row)" :key="'relay-tag-row-'+i+'-'+tagRow.tone" :class="'zt-tag-row-' + tagRow.tone">
                  <span class="ladder-chip" v-for="(t, ti) in tagRow.tags" :key="'relay-tag-'+i+'-'+tagRow.tone+'-'+ti" :class="t.cls">{{ t.text }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="zt-col">
          <div class="section-header">观察池（大容量/前龙头，看情绪反馈）</div>
          <div class="zt-list">
            <div class="zt-item" v-for="(row, i) in ztWatchSorted" :key="'watch-'+i">
              <div class="zt-top">
                <div>
                  <div class="zt-name">
                    <a v-if="row.code" class="stock-link" :href="xqUrl(row.code)" target="_blank" rel="noopener noreferrer">{{ row.name }}</a>
                    <span v-else>{{ row.name }}</span>
                  </div>
                  <div class="zt-sub" v-html="row.reason"></div>
                </div>
                <div class="zt-score" :class="row.superLeaderTone || ''" :title="row.factorHint || ''">
                  <div class="v">{{ row.factorScore ?? row.score }}</div>
                  <div class="k">{{ row.scoreLabel || row.watchGroup || '观察参考' }}</div>
                  <div class="g" v-if="row.scoreSubLabel || row.watchGroup">{{ row.scoreSubLabel || row.watchGroup }}</div>
                </div>
              </div>
              <div class="zt-mainline-row" v-if="mainLineOf(row.code)">
                <span class="zt-ml-chip">
                  🏷 {{ mainLineOf(row.code)?.primary_sector }}
                </span>
                <span class="zt-ml-line" v-if="mainLineOf(row.code)?.main_line">
                  · 主线 <strong>{{ mainLineOf(row.code)?.main_line }}</strong>
                </span>
              </div>
              <div class="zt-enrich-row" v-if="row.emThemes?.length || row.capacityCore || row.crossSourceBoost">
                <span class="zt-enrich-chip" v-if="row.emThemes?.length" title="东方财富题材确认">东财: {{ row.emThemes.join(' · ') }}</span>
                <span class="zt-enrich-chip" v-if="row.xgbEvents?.length" title="选股宝异动确认">选股宝异动</span>
                <span class="zt-enrich-chip enrich-cap" v-if="row.capacityLabel && row.capacityLabel !== '小盘'">{{ row.capacityLabel }}</span>
                <span class="zt-enrich-chip enrich-boost" v-if="row.crossSourceBoost">+{{ row.crossSourceBoost }}</span>
              </div>
              <div class="zt-tags">
                <div class="zt-tag-row" v-for="tagRow in ztTagRows(row)" :key="'watch-tag-row-'+i+'-'+tagRow.tone" :class="'zt-tag-row-' + tagRow.tone">
                  <span class="ladder-chip" v-for="(t, ti) in tagRow.tags" :key="'watch-tag-'+i+'-'+tagRow.tone+'-'+ti" :class="t.cls">{{ t.text }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="summary-box" v-if="!marketData.ztgc || !marketData.ztgc.length">
        <div class="summary-text">未注入当日涨停池明细（ztgc）。请用渲染脚本从 pools_cache.json 注入后再查看本模块。</div>
      </div>
      <div class="summary-box" v-else-if="!((marketData.ztAnalysis?.relay || []).length || (marketData.ztAnalysis?.watch || []).length)">
        <div class="summary-text">涨停分析暂未生成，请检查涨停池、题材映射或前端派生逻辑。</div>
      </div>
    </div>

    <ShortReminderFooter />
  </div>
</template>
