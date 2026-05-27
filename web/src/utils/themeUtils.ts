/**
 * 题材名称归一化工具
 * 用于解决不同数据源（选股宝、东财、短线侠、本地映射）之间题材名称不一致的问题
 */

const THEME_ALIAS_MAP: Record<string, string> = {
  // 低空经济类
  '低空经济': '低空经济',
  '飞行汽车': '低空经济',
  '通用航空': '低空经济',
  '无人机': '低空经济',
  
  // 半导体类
  '半导体': '半导体',
  '芯片': '半导体',
  '集成电路': '半导体',
  '光刻机': '半导体',
  '光刻胶': '半导体',
  
  // AI/算力类
  '人工智能': '人工智能',
  'AI算力': '人工智能',
  '算力租赁': '人工智能',
  '大模型': '人工智能',
  'CPO': '人工智能',
  
  // 汽车类
  '汽车整车': '汽车产业链',
  '汽车零部件': '汽车产业链',
  '华为汽车': '汽车产业链',
  '小米汽车': '汽车产业链',
  '智能驾驶': '汽车产业链',
  
  // 电力/能源类
  '电力': '绿色能源',
  '特高压': '绿色能源',
  '虚拟电厂': '绿色能源',
  '风电': '绿色能源',
  '光伏': '绿色能源',
  '储能': '绿色能源',
};

/**
 * 归一化题材名称
 * @param name 原始名称
 * @returns 归一化后的名称
 */
export function normalizeThemeName(name: string): string {
  const n = String(name || '').trim();
  if (!n) return '';
  
  // 1. 查表匹配
  if (THEME_ALIAS_MAP[n]) return THEME_ALIAS_MAP[n];
  
  // 2. 模糊匹配逻辑（可选）
  for (const [alias, standard] of Object.entries(THEME_ALIAS_MAP)) {
    if (n.includes(alias) || alias.includes(n)) return standard;
  }
  
  return n;
}

/**
 * 计算多个题材的交集或共振
 * @param themes 题材数组
 */
export function getResonantTheme(themes: string[]): string {
  const normalized = themes.map(normalizeThemeName).filter(Boolean);
  const counts = new Map<string, number>();
  normalized.forEach(t => counts.set(t, (counts.get(t) || 0) + 1));
  
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])[0]?.[0] || '';
}
