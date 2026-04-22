#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
短线复盘HTML报告生成器 v4 (ECharts版)
严格按照 /Users/zxl/Desktop/短线复盘利器-优化版.html 模板结构输出
"""

import json, urllib.request, time, sys, datetime, os
from pathlib import Path
from zoneinfo import ZoneInfo
from daily_review.metrics.mood import calc_stage as calc_mood_stage_unified
from daily_review.env import load_dotenv_if_needed

def _env(name: str, default: str = "") -> str:
    """
    纯函数：读取环境变量并做 strip。
    """
    return (os.getenv(name) or default).strip()

def _get_report_tz() -> datetime.tzinfo:
    """
    纯函数：确定“报告时间”的时区。

    规则：
    1) 如果设置了 REPORT_TZ（例如 Asia/Shanghai），优先使用
    2) 如果在 GitHub Actions 中运行（GITHUB_ACTIONS=true），默认用北京时间（Asia/Shanghai）
    3) 否则使用系统本地时区（无法识别时回退到 Asia/Shanghai）
    """
    tz_name = _env("REPORT_TZ", "")
    if tz_name:
        return ZoneInfo(tz_name)

    if _env("GITHUB_ACTIONS", "").lower() == "true":
        return ZoneInfo("Asia/Shanghai")

    # 本地运行：使用系统时区
    local_tz = datetime.datetime.now().astimezone().tzinfo
    return local_tz or ZoneInfo("Asia/Shanghai")


REPORT_TZ = _get_report_tz()


def now_report() -> datetime.datetime:
    """
    纯函数：获取“报告时间”（带时区）。
    """
    return datetime.datetime.now(tz=REPORT_TZ)

def infer_exchange(code6: str) -> str:
    """
    纯函数：根据 6 位代码推断交易所后缀（SH/SZ/BJ）。
    """
    c = str(code6 or "").strip()
    if c.startswith(("60", "68", "90", "11")):
        return "SH"
    if c.startswith(("00", "30", "20")):
        return "SZ"
    if c.startswith(("83", "87", "88", "43")):
        return "BJ"
    # 兜底：按 A 股最常见规则
    return "SH" if c.startswith("6") else "SZ"


def fetch_latest_daily_bar(code6: str):
    """
    有副作用函数：获取个股最近 1 根日线（用于严格识别“一字板”）。

    API（根据 biyingapi 文档/skill）：
    - hsstock/latest/{code.SH}/d/n/{TOKEN}?lt=1
    返回：list[{t,o,h,l,c,v,a,pc}]
    """
    ex = infer_exchange(code6)
    url = f"{BASE}/hsstock/latest/{code6}.{ex}/d/n/{TOKEN}?lt=1"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    if isinstance(data, list) and data:
        item = data[-1] or {}
        if isinstance(item, dict):
            return {
                "t": item.get("t"),
                "o": item.get("o"),
                "h": item.get("h"),
                "l": item.get("l"),
                "c": item.get("c"),
                "v": item.get("v"),
                "a": item.get("a"),
                "pc": item.get("pc"),
            }
    return {}


# 先尝试自动加载 .env，再读取环境变量
load_dotenv_if_needed(dotenv_path=Path(__file__).resolve().parent / ".env", required_keys=("BIYING_TOKEN",))

# 敏感信息：token 必须从环境变量注入，避免误提交到仓库
TOKEN = _env("BIYING_TOKEN", "")
if not TOKEN:
    raise RuntimeError("未设置环境变量 BIYING_TOKEN：请先 export BIYING_TOKEN=... 再运行脚本")

REQUEST_DATE = sys.argv[1] if len(sys.argv) > 1 else now_report().strftime("%Y-%m-%d")
DATE = REQUEST_DATE
DATE_NOTE = ""
BASE = _env("BIYING_BASE_URL", "https://api.biyingapi.com")

# ───────────────────────────────
# 本地化资源（替代 CDN）
# ───────────────────────────────
def asset_url(local_path: str, cdn_url: str, use_local: bool = True) -> str:
    """
    纯函数：根据开关选择本地资源或 CDN 资源。

    - use_local=True：生成的 HTML 将引用 ./vendor 下的文件，适合离线打开
    - use_local=False：引用 CDN
    """
    return local_path if use_local else cdn_url

USE_LOCAL_VENDOR = True
ECHARTS_SRC = asset_url(
    local_path="./vendor/echarts.min.js",
    cdn_url="https://fastly.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js",
    use_local=USE_LOCAL_VENDOR,
)
VUE_SRC = asset_url(
    local_path="./vendor/vue.global.prod.js",
    cdn_url="https://fastly.jsdelivr.net/npm/vue@3/dist/vue.global.prod.js",
    use_local=USE_LOCAL_VENDOR,
)

# ── 噪音过滤 ──
NOISE_PREFIXES = ('A股-分类', 'A股-指数成分', 'A股-证监会行业', 'A股-申万行业',
                   'A股-申万二级', 'A股-地域板块', '基金-', '港股-', '美股-', 'A股-概念板块')
NOISE_THEMES = {'小盘', '中盘', '大盘', '融资融券', 'QFII持股', '基金重仓',
                '年度强势', '深股通', '沪股通', '富时罗素'}
# 非题材归因（统计口径类“伪题材”），会显著污染题材强度/主线判断
EXCLUDE_THEME_NAMES = {"昨日涨停", "昨日连板"}

# ───────────────────────────────
# 工具函数区（必须在任何计算逻辑之前）
# ───────────────────────────────
def safe_rate(numer, denom):
    """
    纯函数：安全计算比例（百分数），避免除零。
    返回：0~100 的 float
    """
    return (numer / denom * 100) if denom else 0.0

def smooth_rate(numer: float, denom: float, *, a: float = 1.0, b: float = 1.0) -> float:
    """
    纯函数：对“成功率/占比”做贝叶斯平滑（Beta 先验）。

    目的：
    - 解决样本过小导致的情绪指标剧烈跳变（例如昨日连板只有 3~5 只时，晋级率/断板率会极端化）
    - 平滑只用于“情绪判定/评分”，展示口径仍可保留原始值（避免误导）

    参数：
    - a/b：Beta(a,b) 先验强度，a=b=1 表示中性（均值 50%）
    """
    if denom <= 0:
        return 0.0
    return ( (numer + a) / (denom + a + b) ) * 100.0

def try_load_cached_market_data(date_str: str):
    """
    从 cache/market_data-YYYYMMDD.json 读取上一交易日的已生成数据，用于计算“昨日对比Δ”。
    返回 dict 或 None
    """
    try:
        cache_dir = Path(__file__).resolve().parent / "cache"
        p = cache_dir / f"market_data-{date_str.replace('-', '')}.json"
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

def class_for_good_rate(rate, hi=60, mid=40):
    """
    纯函数：给“越高越好”的成功率/健康度分配颜色类名。
    - 高：红（偏强）
    - 中：橙（中性）
    - 低：绿（偏弱）
    """
    if rate >= hi:
        return "red-text"
    if rate >= mid:
        return "orange-text"
    return "green-text"

def class_for_bad_rate(rate, hi=30, mid=15):
    """
    纯函数：给“越高越糟”的风险率分配颜色类名（反向）。
    - 高：红（危险）
    - 中：橙（注意）
    - 低：绿（可控）
    """
    if rate >= hi:
        return "red-text"
    if rate >= mid:
        return "orange-text"
    return "green-text"

def median(values):
    """
    纯函数：计算中位数（空列表返回 0）。
    """
    xs = sorted([v for v in values if v is not None])
    n = len(xs)
    if n == 0:
        return 0
    mid = n // 2
    if n % 2 == 1:
        return xs[mid]
    return (xs[mid - 1] + xs[mid]) / 2

def is_hms_leq(hms: str, threshold_hms: str) -> bool:
    """
    纯函数：判断 HH:mm:ss 是否早于等于阈值时间。
    说明：HMS 固定格式下，字符串比较即可满足时序比较。
    """
    if not hms:
        return False
    return hms <= threshold_hms

def parse_lbc_from_tj(tj: str) -> int:
    """
    纯函数：从涨停统计 tj（x天/y板）中提取 y（连板数）。
    - tj 可能为空或格式异常，异常则返回 1
    """
    if not tj:
        return 1
    try:
        parts = str(tj).split("/")
        if len(parts) != 2:
            return 1
        return int(parts[1])
    except Exception:
        return 1

def read_json_file(path: Path) -> dict:
    """
    有副作用函数：读取 JSON 文件（不存在则返回空 dict）。
    """
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def write_json_file(path: Path, data: dict) -> None:
    """
    有副作用函数：写入 JSON 文件（UTF-8）。
    """
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ───────────────────────────────
# 近 N 日池子缓存（涨停/跌停/炸板）
# ───────────────────────────────
CACHE_VERSION = 1
# 默认保留最近 7 个交易日缓存；可用环境变量覆盖（例如 5）：
#   export CACHE_DAYS=5
try:
    CACHE_DAYS = int(_env("CACHE_DAYS", "7") or "7")
except Exception:
    CACHE_DAYS = 7

def cache_paths() -> dict:
    """
    纯函数：返回缓存目录与文件路径。
    """
    base_dir = Path(__file__).resolve().parent
    cache_dir = base_dir / "cache"
    return {
        "dir": cache_dir,
        "pools": cache_dir / "pools_cache.json",
        "height": cache_dir / "height_trend_cache.json",
        "themes": cache_dir / "theme_cache.json",
        "index_klines": cache_dir / "index_kline_cache.json",
        "trade_days": cache_dir / "trade_days_cache.json",
        "theme_trend": cache_dir / "theme_trend_cache.json",
    }

def load_pools_cache() -> dict:
    """
    有副作用函数：加载池子缓存。
    结构：
    {
      "version": 1,
      "pools": { "ztgc": { "YYYY-MM-DD": [...] }, "dtgc": {...}, "zbgc": {...} }
    }
    """
    paths = cache_paths()
    paths["dir"].mkdir(parents=True, exist_ok=True)
    cache = read_json_file(paths["pools"])
    if cache.get("version") != CACHE_VERSION:
        return {"version": CACHE_VERSION, "pools": {"ztgc": {}, "dtgc": {}, "zbgc": {}}}
    pools = cache.get("pools") or {}
    return {"version": CACHE_VERSION, "pools": {
        "ztgc": pools.get("ztgc") or {},
        "dtgc": pools.get("dtgc") or {},
        "zbgc": pools.get("zbgc") or {},
    }}

def save_pools_cache(cache: dict) -> None:
    """
    有副作用函数：写回池子缓存。
    """
    paths = cache_paths()
    cache["version"] = CACHE_VERSION
    write_json_file(paths["pools"], cache)

def prune_cache_days(pool_map: dict, keep_days: list) -> dict:
    """
    纯函数：只保留 keep_days 中存在的日期缓存，避免缓存无限增长。
    """
    keep_set = set(keep_days or [])
    return {d: v for d, v in (pool_map or {}).items() if d in keep_set}

def fetch_pool_data(pool_name: str, date_str: str, *, use_cache_first: bool, cache: dict) -> list:
    """
    有副作用函数：获取某日某池数据（支持缓存）。

    - use_cache_first=True：优先读缓存，缓存缺失才请求 API
    - use_cache_first=False：优先请求 API，失败再读缓存（适合当天/关键日期）
    """
    pools = cache["pools"]
    pool_cache = pools.get(pool_name) or {}

    if use_cache_first and date_str in pool_cache:
        return pool_cache.get(date_str) or []

    try:
        data = api(f"hslt/{pool_name}/{date_str}", exit_on_404=False, quiet_404=True)
        data = data or []
        pool_cache[date_str] = data
        pools[pool_name] = pool_cache
        return data
    except Exception:
        return pool_cache.get(date_str) or []

def get_trading_days_from_volume_k(n=7):
    """
    有副作用函数：用“成交量/成交额 日K接口”获取最近 n 个交易日。

    说明：
    - 这里用指数日K接口 hsindex/latest，字段 t 提供交易日序列；
    - 不再用“扫历史 ztgc 是否404”的方式推断交易日（避免多余接口）。
    """
    def _extract_dates(arr):
        out = []
        if isinstance(arr, list):
            for item in arr:
                t = item.get("t", "")
                if isinstance(t, str) and len(t) >= 10:
                    out.append(t[:10])
        return out

    # ───────────────────────────────
    # 交易日缓存：确认过的最近交易日直接复用，避免重复推断
    # ───────────────────────────────
    try:
        paths = cache_paths()
        paths["dir"].mkdir(parents=True, exist_ok=True)
        td_cache = read_json_file(paths["trade_days"])
        if isinstance(td_cache, dict):
            as_of = td_cache.get("as_of", "")
            days = td_cache.get("days", [])
            if as_of == DATE and isinstance(days, list) and len(days) >= n:
                return days[-n:]
    except Exception:
        pass

    try:
        # 规则：n<=5 用 latest；n>5 用 history（避免 latest 的 lt 上限/不稳定问题）
        if n <= 5:
            sh = api_get(f"{BASE}/hsindex/latest/000001.SH/d/{TOKEN}?lt={n}")
            sz = api_get(f"{BASE}/hsindex/latest/399001.SZ/d/{TOKEN}?lt={n}")
            uniq = sorted(set(_extract_dates(sh) + _extract_dates(sz)))
            result = uniq[-n:] if len(uniq) >= n else uniq
            # 写回缓存（至少保存最近5个交易日）
            try:
                paths = cache_paths()
                write_json_file(paths["trade_days"], {"version": 1, "as_of": DATE, "days": uniq})
            except Exception:
                pass
            return result

        et = DATE.replace("-", "")
        # 给一个足够大的窗口（过去 40 个自然日），再截取最后 n 个交易日
        st_dt = (datetime.datetime.strptime(DATE, "%Y-%m-%d") - datetime.timedelta(days=40)).strftime("%Y%m%d")
        sh = api_get(f"{BASE}/hsindex/history/000001.SH/d/{TOKEN}?st={st_dt}&et={et}")
        sz = api_get(f"{BASE}/hsindex/history/399001.SZ/d/{TOKEN}?st={st_dt}&et={et}")
        uniq = sorted(set(_extract_dates(sh) + _extract_dates(sz)))
        # 仅保留 <= DATE 的交易日（稳妥）
        uniq = [d for d in uniq if d <= DATE]
        result = uniq[-n:] if len(uniq) >= n else uniq
        try:
            paths = cache_paths()
            write_json_file(paths["trade_days"], {"version": 1, "as_of": DATE, "days": uniq})
        except Exception:
            pass
        return result
    except Exception:
        # 兜底：至少给出 latest 5 个交易日
        try:
            sh = api_get(f"{BASE}/hsindex/latest/000001.SH/d/{TOKEN}?lt=5")
            sz = api_get(f"{BASE}/hsindex/latest/399001.SZ/d/{TOKEN}?lt=5")
            uniq = sorted(set(_extract_dates(sh) + _extract_dates(sz)))
            result = uniq[-min(n, 5):]
            try:
                paths = cache_paths()
                write_json_file(paths["trade_days"], {"version": 1, "as_of": DATE, "days": uniq})
            except Exception:
                pass
            return result
        except Exception:
            return []

def clean_theme(name):
    if not name: return None
    if name in EXCLUDE_THEME_NAMES:
        return None
    for p in NOISE_PREFIXES:
        if name.startswith(p): return None
    if name.startswith('A股-热门概念-'):
        return name.replace('A股-热门概念-', '')
    return name

def api(path, exit_on_404=True, quiet_404=False):
    url = f"{BASE}/{path}/{TOKEN}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            if exit_on_404:
                if not quiet_404:
                    print(f"   ⚠️  未找到日期 {DATE} 的数据，请确认是否为交易日。")
                sys.exit(1)
            return None
        raise e

def api_get(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def get_recent_trade_dates(_n=15):
    """从指数K线提取最近交易日列表，用于非交易日自动回退。"""
    try:
        data = api_get(f"{BASE}/hsindex/latest/000001.SH/d/{TOKEN}?lt={max(_n, 12)}")
        if not isinstance(data, list):
            return []
        dates = []
        for item in data:
            dt_str = item.get('t', '')
            if len(dt_str) >= 10:
                dates.append(dt_str[:10])
        return sorted(set(dates))
    except Exception:
        return []

def resolve_report_date(requested_date):
    """将非交易日请求自动回退到最近交易日。"""
    try:
        request_day = datetime.datetime.strptime(requested_date, "%Y-%m-%d").date()
        if request_day.weekday() == 5:
            actual_day = request_day - datetime.timedelta(days=1)
            actual_date = actual_day.strftime("%Y-%m-%d")
            return actual_date, f"请求日期 {requested_date} 为周六，已自动切换到最近交易日 {actual_date}"
        if request_day.weekday() == 6:
            actual_day = request_day - datetime.timedelta(days=2)
            actual_date = actual_day.strftime("%Y-%m-%d")
            return actual_date, f"请求日期 {requested_date} 为周日，已自动切换到最近交易日 {actual_date}"
    except ValueError:
        pass

    trade_dates = get_recent_trade_dates(20)
    if not trade_dates:
        return requested_date, ""
    if requested_date in trade_dates:
        return requested_date, ""

    earlier_dates = [d for d in trade_dates if d <= requested_date]
    actual_date = earlier_dates[-1] if earlier_dates else trade_dates[-1]
    note = f"请求日期 {requested_date} 非交易日，已自动切换到最近交易日 {actual_date}"
    return actual_date, note

DATE, DATE_NOTE = resolve_report_date(REQUEST_DATE)

print("=" * 50)
print("📊 数据采集开始")
print("=" * 50)
if DATE_NOTE:
    print(f"⚠️  {DATE_NOTE}")

# ══════════════════════════
# ① 主要指数
# ══════════════════════════
print("\n[1/12] 获取主要指数...")
indices_data = []
indices_fetch_at = now_report().strftime("%H:%M:%S")
for code, name in [("000001.SH","上证指数"), ("399001.SZ","深证成指"),
                    ("399006.SZ","创业板指")]:
    try:
        # 实时盯盘：指数用 real/time（盘中持续更新）；历史K线/交易日序列仍用 latest/history
        rt = api_get(f"{BASE}/hsindex/real/time/{code}/{TOKEN}")
        close = rt.get("p", 0)          # 点位
        chg_pct = rt.get("pc", 0)       # 涨跌幅（%）
        vol_a = rt.get("cje", 0)        # 成交额（元）
        indices_data.append({
            'name': name, 'code': code,
            'close': close, 'pct': chg_pct,
            'vol': vol_a, 'up': chg_pct >= 0,
            't': rt.get("t", "")
        })
        print(f"   {name}: {close:.2f} ({chg_pct:+.2f}%)")
    except Exception as e:
        print(f"   {name} ERROR: {e}")

# 两市总量能 = 上证+深证成交额
total_vol_sh = indices_data[0]['vol'] if len(indices_data) > 0 else 0
total_vol_sz = indices_data[1]['vol'] if len(indices_data) > 1 else 0
today_total_vol = (total_vol_sh + total_vol_sz) / 1e8  # 亿
print(f"   两市合计: {today_total_vol:.2f}亿")

# ══════════════════════════
# ② 市场全景(涨停/炸板/跌停)
# ══════════════════════════
print("\n[2/12] 获取市场全景...")
pool_cache = load_pools_cache()

# 先用“成交量/成交额 日K接口”确定最近交易日列表（用于缓存裁剪与预热）
trade_days_7 = get_trading_days_from_volume_k(CACHE_DAYS) or [DATE]
keep_days = trade_days_7[-CACHE_DAYS:]
# 关键：无论 trade_days 如何返回，都必须包含本次请求日期 DATE
# 否则会出现“当天已拉取 ztgc/dtgc/zbgc，但随后的裁剪又把 DATE 删掉”的情况，
# 导致渲染时 ztgc 注入为空（页面看起来像没更新/数据不全）。
if DATE not in keep_days:
    keep_days = keep_days + [DATE]

# 预热 7 日缓存：涨停/跌停/炸板（首次会拉取，后续大部分走本地）
for d in keep_days:
    if d == DATE:
        continue
    fetch_pool_data("ztgc", d, use_cache_first=True, cache=pool_cache)
    fetch_pool_data("dtgc", d, use_cache_first=True, cache=pool_cache)
    fetch_pool_data("zbgc", d, use_cache_first=True, cache=pool_cache)

# 当天/请求日期：优先请求 API，失败再走缓存
zt_all = fetch_pool_data("ztgc", DATE, use_cache_first=False, cache=pool_cache)
dt_all = fetch_pool_data("dtgc", DATE, use_cache_first=False, cache=pool_cache)
zb_all = fetch_pool_data("zbgc", DATE, use_cache_first=False, cache=pool_cache)

# 强势股池（qsgc）：用于“昨日涨停今表现/强势反馈/热力图”等模块
# 说明：只增加 1 次接口调用（当日），并写入 pools_cache.json，便于后续调试复用缓存。
qs_all = fetch_pool_data("qsgc", DATE, use_cache_first=False, cache=pool_cache)
pools_fetch_at = now_report().strftime("%H:%M:%S")

# 缓存裁剪 + 写回
pool_cache["pools"]["ztgc"] = prune_cache_days(pool_cache["pools"]["ztgc"], keep_days)
pool_cache["pools"]["dtgc"] = prune_cache_days(pool_cache["pools"]["dtgc"], keep_days)
pool_cache["pools"]["zbgc"] = prune_cache_days(pool_cache["pools"]["zbgc"], keep_days)
pool_cache["pools"]["qsgc"] = prune_cache_days(pool_cache["pools"].get("qsgc", {}), keep_days)
save_pools_cache(pool_cache)

zt_count = len(zt_all)
dt_count = len(dt_all)
zb_count = len(zb_all)
qs_count = len(qs_all) if qs_all else 0
fb_rate = zt_count / (zt_count + zb_count) * 100 if (zt_count + zb_count) > 0 else 0
zb_rate = zb_count / (zt_count + zb_count) * 100 if (zt_count + zb_count) > 0 else 0

print(f"   涨停:{zt_count} 炸板:{zb_count} 跌停:{dt_count} 封板率:{fb_rate:.1f}%")

# 涨停总成交额
zt_total_cje = sum(s.get('cje', 0) for s in zt_all) / 1e8

# 炸板结构拆分（后续情绪指标会用到，需在早期定义）
zb_low_count = len([s for s in zb_all if s.get('lbc', 1) <= 1])
zb_mid_count = len([s for s in zb_all if 2 <= s.get('lbc', 1) <= 3])
zb_high_count = len([s for s in zb_all if s.get('lbc', 1) >= 4])
zb_high_names = '、'.join(
    s.get('mc', '') for s in sorted(zb_all, key=lambda x: x.get('lbc', 1), reverse=True)[:3]
) if zb_all else '无'

# ══════════════════════════
# ③ 近5日量能趋势（取最近K线数据）
# ══════════════════════════
print("\n[3/12] 获取近5日量能...")

def fetch_index_klines(code, n=5):
    """获取指数最近n根K线，返回 {日期: 成交额} 字典（带本地缓存）"""
    try:
        # 指数数据变化不大，做 5 日缓存复用，减少重复请求
        paths = cache_paths()
        paths["dir"].mkdir(parents=True, exist_ok=True)
        idx_cache = read_json_file(paths["index_klines"])
        codes_map = idx_cache.get("codes", {}) if isinstance(idx_cache, dict) else {}
        entry = codes_map.get(code, {}) if isinstance(codes_map, dict) else {}
        items = entry.get("items", []) if isinstance(entry, dict) else []
        as_of = entry.get("as_of", "")

        # 实时盯盘：当天的数据可能盘中持续变化或被接口修正，因此当天强制刷新；
        # 历史日仍可复用缓存。
        cached_dates = [it.get("t", "")[:10] for it in items if isinstance(it, dict) and isinstance(it.get("t", ""), str)]
        has_today = any(d == DATE for d in cached_dates)
        force_refresh_today = (as_of == DATE and has_today)  # 当天强制刷新
        if (not force_refresh_today) and as_of == DATE and len(items) >= n and has_today:
            d = items[-n:]
        else:
            d = api_get(f"{BASE}/hsindex/latest/{code}/d/{TOKEN}?lt={max(n, 5)}")
            # 写回缓存（只缓存最近5根，避免文件膨胀）
            if isinstance(d, list):
                codes_map = codes_map if isinstance(codes_map, dict) else {}
                codes_map[code] = {"as_of": DATE, "items": d[-5:]}
                write_json_file(paths["index_klines"], {"version": 1, "codes": codes_map})
        if isinstance(d, list):
            result = {}
            for k in d:
                dt_str = k.get('t', '')  # '2026-04-10 00:00:00'
                date_key = dt_str[:10] if len(dt_str) >= 10 else dt_str
                vol_a = k.get('a', 0)   # 成交额
                result[date_key] = vol_a
            return result
        return {}
    except Exception as e:
        print(f"   {code} K线获取失败: {e}")
        return {}

# 取上证和深证最近5日K线
sh_d = fetch_index_klines("000001.SH", 5)
sz_d = fetch_index_klines("399001.SZ", 5)

# 交易日由“成交量/成交额 日K接口”统一提供（用于昨日判定/晋级等）
all_dates = get_trading_days_from_volume_k(7) or [DATE]
# 实时盯盘：接口可能只返回“已收盘交易日”，但我们需要把 DATE 作为“当前点”纳入
if DATE not in all_dates:
    all_dates = all_dates + [DATE]
recent5_dates = sorted(set(all_dates))[-5:]
vol_history = []
prev_v = None
for d in recent5_dates:
    sh_v = sh_d.get(d, 0)
    sz_v = sz_d.get(d, 0)
    total = (sh_v + sz_v) / 1e8
    # 若日K未包含“当日”(盘中/未收盘常见)，用实时两市合计成交额兜底
    if d == DATE and (total <= 0) and (today_total_vol > 0):
        total = today_total_vol
    chg = (total - prev_v) / prev_v * 100 if prev_v else 0
    vol_history.append({'date': d[5:].replace('-', ''), 'vol': total, 'chg': chg})
    prev_v = total

for v in vol_history:
    print(f"   {v['date']}: {v['vol']:.0f}亿 ({v['chg']:+.1f}%)")


for v in vol_history:
    print(f"   {v['date']}: {v['vol']:.0f}亿")

# 计算较昨日变化
if len(vol_history) >= 2:
    yest_vol = vol_history[-2]['vol']
    today_v = vol_history[-1]['vol']
    vol_chg_pct = (today_v - yest_vol) / yest_vol * 100 if yest_vol else 0
    vol_diff = today_v - yest_vol
else:
    vol_chg_pct = 0
    vol_diff = 0

# ══════════════════════════
# ④ 连板天梯 & 昨日晋级分析
# ══════════════════════════
print("\n[4/12] 分析连板天梯...")
by_lbc = {}
for s in zt_all:
    # 优化：如接口返回缺失 lbc，可用 tj（x天/y板）兜底解析
    lb = s.get('lbc', None)
    lb = int(lb) if lb is not None else parse_lbc_from_tj(s.get("tj", ""))
    by_lbc.setdefault(lb, []).append(s)
for k in by_lbc:
    by_lbc[k].sort(key=lambda x: x.get('zf', 0), reverse=True)

max_lb = max(by_lbc.keys()) if by_lbc else 1
ladder_rows = []
for lb in sorted(by_lbc.keys(), reverse=True):
    if lb == 1:
        continue  # 跳过首板，只显示2板及以上连板
    for s in by_lbc[lb]:
        ladder_rows.append({
            'badge': lb,
            'name': s.get('mc', ''),
            'code': s.get('dm', ''),
            'zf': s.get('zf', 0),
            # 天梯增强字段（用于分歧标记/封板资金等，无需新增接口）
            'zbc': int(s.get('zbc', 0) or 0),      # 开板/炸板次数（>=1 可视作“回封”，>=3 视作分歧较大）
            'zj': float(s.get('zj', 0) or 0),      # 封板资金（元）
            'hs': float(s.get('hs', 0) or 0),      # 换手
            'cje': float(s.get('cje', 0) or 0),    # 成交额（元）
            'fbt': s.get('fbt', '') or '',         # 首次封板时间（HHMMSS）
            'note': ''
        })

# 昨日连板股今日是否存活
print("   获取昨日数据对比晋级...")
yest_zt = []
try:
    # 从 all_dates 寻找昨日
    yest_date = None
    for i, d in enumerate(all_dates):
        if d == DATE and i > 0:
            yest_date = all_dates[i-1]
            break
    if not yest_date:
        # 如果 DATE 不在 all_dates 中，找比 DATE 小的最大日期
        past_dates = [d for d in all_dates if d < DATE]
        if past_dates: yest_date = past_dates[-1]
    
    if yest_date:
        print(f"   昨日交易日: {yest_date}")
        # 优化：昨日涨停池也纳入 7 日缓存，避免重复请求
        yest_zt = fetch_pool_data("ztgc", yest_date, use_cache_first=True, cache=pool_cache)
    else:
        print("   警告: 无法确定昨日交易日")
except Exception as e:
    print(f"   获取昨日数据失败: {e}")

# ───────────────────────────────
# 昨日对比Δ：优先读取昨日 market_data 缓存；缺失则用 pools_cache 推算
# ───────────────────────────────
prev_snapshot = None
prev_metrics = {}
day_delta = {}
try:
    if yest_date:
        prev_snapshot = try_load_cached_market_data(yest_date)

    if prev_snapshot:
        prev_metrics = {
            "date": prev_snapshot.get("date", yest_date),
            "zt": int((prev_snapshot.get("panorama") or {}).get("limitUp", 0) or 0),
            "zb": int((prev_snapshot.get("panorama") or {}).get("broken", 0) or 0),
            "dt": int((prev_snapshot.get("panorama") or {}).get("limitDown", 0) or 0),
            "fb_rate": float(((prev_snapshot.get("features") or {}).get("mood_inputs") or {}).get("fb_rate", 0) or 0),
            "jj_rate": float(((prev_snapshot.get("features") or {}).get("mood_inputs") or {}).get("jj_rate", 0) or 0),
            "zb_rate": float(((prev_snapshot.get("features") or {}).get("mood_inputs") or {}).get("zb_rate", 0) or 0),
            "zt_early_ratio": float(((prev_snapshot.get("features") or {}).get("mood_inputs") or {}).get("zt_early_ratio", 0) or 0),
            "bf_count": int(((prev_snapshot.get("features") or {}).get("mood_inputs") or {}).get("bf_count", 0) or 0),
            "top3_theme_ratio": float(((prev_snapshot.get("features") or {}).get("style_inputs") or {}).get("top3_theme_ratio", 0) or 0),
            "max_lb": int(((prev_snapshot.get("features") or {}).get("style_inputs") or {}).get("max_lb", 0) or 0),
            "heat": float((prev_snapshot.get("mood") or {}).get("heat", 0) or 0),
            "risk": float((prev_snapshot.get("mood") or {}).get("risk", 0) or 0),
        }
    elif yest_date:
        # fallback：用 pools_cache 轻量推算（不再额外请求题材）
        yest_zt2 = yest_zt or fetch_pool_data("ztgc", yest_date, use_cache_first=True, cache=pool_cache)
        yest_zb2 = fetch_pool_data("zbgc", yest_date, use_cache_first=True, cache=pool_cache)
        yest_dt2 = fetch_pool_data("dtgc", yest_date, use_cache_first=True, cache=pool_cache)
        y_zt = len(yest_zt2)
        y_zb = len(yest_zb2)
        y_dt = len(yest_dt2)
        y_fb = safe_rate(y_zt, y_zt + y_zb)
        y_zb_rate = safe_rate(y_zb, y_zt + y_zb)
        y_early = safe_rate(sum(1 for s in yest_zt2 if is_hms_leq(s.get("fbt", ""), "10:00:00")), y_zt)
        prev_metrics = {
            "date": yest_date,
            "zt": y_zt,
            "zb": y_zb,
            "dt": y_dt,
            "fb_rate": y_fb,
            "zb_rate": y_zb_rate,
            "zt_early_ratio": y_early,
        }

except Exception as _e:
    prev_metrics = {}
    day_delta = {}

yest_lb_stocks = {}  # code -> {lbc, mc}
for s in yest_zt:
    lbc = s.get('lbc', 1)
    if lbc >= 2:
        yest_lb_stocks[s['dm']] = {'lbc': lbc, 'mc': s.get('mc', '')}

today_lb_codes = set()
for row in ladder_rows:
    if row['badge'] >= 2:
        today_lb_codes.add(row['code'])

jinwei_list = []  # 晋级成功
duanban_list = []  # 断板
for code, info in yest_lb_stocks.items():
    if code in today_lb_codes:
        jinwei_list.append(info)
    else:
        duanban_list.append(info)

jj_rate = len(jinwei_list) / len(yest_lb_stocks) * 100 if yest_lb_stocks else 0
# 情绪判定用“平滑版”，避免样本少时极端化（展示仍用 jj_rate）
jj_rate_adj = smooth_rate(len(jinwei_list), len(yest_lb_stocks), a=2, b=2) if yest_lb_stocks else 0

# 最高断板（用于“高位断板影响连板梯队”提示）
top_duanban = max(duanban_list, key=lambda x: int(x.get("lbc", 0) or 0), default=None) if duanban_list else None
top_duanban_lb = int(top_duanban.get("lbc", 0) or 0) if isinstance(top_duanban, dict) else 0
top_duanban_name = (top_duanban.get("mc", "") if isinstance(top_duanban, dict) else "") or ""
top_duanban_is_high = top_duanban_lb >= 6  # 经验阈值：6板及以上断板，往往会影响次高板与梯队情绪

# 首板晋级率: 昨日首板(lbc=1)中今日晋级到2板+
yest_1b_codes = set(s['dm'] for s in yest_zt if s.get('lbc', 1) == 1)
jinwei_from_1b = [c for c in today_lb_codes if c in yest_1b_codes]
jj_1b_rate = len(jinwei_from_1b) / len(yest_1b_codes) * 100 if yest_1b_codes else 0
jj_1b_rate_adj = smooth_rate(len(jinwei_from_1b), len(yest_1b_codes), a=1, b=1) if yest_1b_codes else 0

# ───────────────────────────────
# 情绪生态补充指标（2进3/3进4/高度差/高位炸板等）
# ───────────────────────────────
today_badge_map = {row.get('code'): int(row.get('badge', 0) or 0) for row in ladder_rows}

# 2进3 / 3进4 成功率：用“昨日 x 板 → 今日 >= x+1 板”衡量空间打开程度
yest_2b_codes = {s.get('dm') for s in yest_zt if s.get('lbc', 1) == 2 and s.get('dm')}
yest_3b_codes = {s.get('dm') for s in yest_zt if s.get('lbc', 1) == 3 and s.get('dm')}
succ_2to3 = sum(1 for c in yest_2b_codes if today_badge_map.get(c, 0) >= 3)
succ_3to4 = sum(1 for c in yest_3b_codes if today_badge_map.get(c, 0) >= 4)
rate_2to3 = safe_rate(succ_2to3, len(yest_2b_codes))
rate_3to4 = safe_rate(succ_3to4, len(yest_3b_codes))
rate_2to3_adj = smooth_rate(succ_2to3, len(yest_2b_codes), a=1, b=1) if yest_2b_codes else 0
rate_3to4_adj = smooth_rate(succ_3to4, len(yest_3b_codes), a=1, b=1) if yest_3b_codes else 0

# 连板断板率：昨日连板中今天未晋级（断板/掉队）的比例
broken_lb_rate = safe_rate(len(duanban_list), len(yest_lb_stocks))
broken_lb_rate_adj = (100.0 - jj_rate_adj) if yest_lb_stocks else 0

# 高度差：最高板 - 次高板，差距越大越容易形成“独苗”风险
lb_levels_sorted = sorted(by_lbc.keys(), reverse=True)
second_lb = lb_levels_sorted[1] if len(lb_levels_sorted) > 1 else 0
height_gap = max_lb - second_lb if second_lb else max_lb

# 高位炸板占比：炸板里 4 板+ 的占比（高位承接崩溃会明显伤情绪）
zb_high_ratio = safe_rate(zb_high_count, zb_count)

# ───────────────────────────────
# 细分情绪指标（封板时效 / 封单资金 / 换手结构 / 小票活跃）
# ───────────────────────────────
# 早盘封板占比：首次封板时间 <= 10:00:00 的涨停占比（越高通常代表情绪更一致）
zt_early_count = sum(1 for s in zt_all if is_hms_leq(s.get('fbt', ''), "10:00:00"))
zt_early_ratio = safe_rate(zt_early_count, zt_count)

# 封板资金强度：涨停池平均封板资金、TOP3 封板资金（单位：亿）
zt_seal_funds = [float(s.get('zj', 0) or 0) for s in zt_all]
avg_seal_fund_yi = (sum(zt_seal_funds) / len(zt_seal_funds) / 1e8) if zt_seal_funds else 0.0
top_seal = sorted(zt_all, key=lambda x: x.get('zj', 0) or 0, reverse=True)[:3]
top_seal_names = "、".join([f"{s.get('mc','')}{(s.get('zj',0) or 0)/1e8:.0f}亿" for s in top_seal]) if top_seal else "无"

# 涨停池炸板次数：均值 + 高炸板占比（zbc>=3）
zt_zbc_vals = [int(s.get('zbc', 0) or 0) for s in zt_all]
avg_zt_zbc = (sum(zt_zbc_vals) / len(zt_zbc_vals)) if zt_zbc_vals else 0.0
zt_zbc_ge3 = sum(1 for v in zt_zbc_vals if v >= 3)
zt_zbc_ge3_ratio = safe_rate(zt_zbc_ge3, zt_count)

# 换手结构（涨停池）：中位换手、>15% 高换手占比
zt_hs_vals = [float(s.get('hs', 0) or 0) for s in zt_all]
hs_median = float(median(zt_hs_vals))
hs_ge15 = sum(1 for v in zt_hs_vals if v >= 15)
hs_ge15_ratio = safe_rate(hs_ge15, zt_count)

# 小票/大票偏好：流通市值 < 50亿 的占比（越高越偏小票情绪）
smallcap_threshold = 50 * 1e8
smallcap_cnt = sum(1 for s in zt_all if float(s.get('lt', 0) or 0) < smallcap_threshold)
smallcap_ratio = safe_rate(smallcap_cnt, zt_count)

# 标记天梯状态
for row in ladder_rows:
    code = row['code']
    if code in yest_lb_stocks:
        row['status'] = '晋级'
    elif code in yest_1b_codes and row['badge'] == 2:
        row['status'] = '新晋'
    elif row['badge'] == 1:
        row['status'] = '首板'
    else:
        row['status'] = '新晋'

# 最高板标记 👑
if ladder_rows:
    ladder_rows[0]['name'] = f"👑 {ladder_rows[0]['name']}"

print(f"   天梯: 最高{max_lb}板, 共{len(ladder_rows)}只连板")
print(f"   昨日{len(yest_lb_stocks)}只连板→存活{len(jinwei_list)}只({jj_rate:.1f}%)")
duanban_preview = ', '.join([f"{s['mc']}({s['lbc']}板)" for s in duanban_list[:8]])
print(f"   断板: {duanban_preview}")

# 连板结构拆分
board_level_count = {}
for stock in zt_all:
    board_level = stock.get('lbc', 1)
    board_level_count[board_level] = board_level_count.get(board_level, 0) + 1

first_board_count = board_level_count.get(1, 0)
second_board_count = board_level_count.get(2, 0)
third_board_count = board_level_count.get(3, 0)
four_plus_count = sum(count for level, count in board_level_count.items() if level >= 4)
five_plus_count = sum(count for level, count in board_level_count.items() if level >= 5)
high_level_ratio = five_plus_count / zt_count * 100 if zt_count else 0
high_level_risk = "可控" if five_plus_count <= 2 else ("偏高" if five_plus_count <= 5 else "高")
high_level_note = f"5板及以上 {five_plus_count}只 / 占比 {high_level_ratio:.1f}%"

# ══════════════════════════
# ⑤ 近7日高度趋势
# ══════════════════════════
print("\n[5/12] 获取近7日高度趋势...")
his_dates = get_trading_days_from_volume_k(7) or [DATE]
# 实时盯盘：把 DATE 加入高度趋势“当前点”
if DATE not in his_dates:
    his_dates = his_dates + [DATE]
height_trend = {'dates': [], 'main': [], 'sub': [], 'gem': [], 'labels_main': [], 'labels_sub': [], 'labels_gem': []}

def calc_height_trend_row(day: str, day_data: list) -> dict:
    """
    纯函数：由某天的涨停池数据计算“高度趋势”单日结果。
    """
    data = day_data or []
    lbs = [int(s.get("lbc", 1) or 1) for s in data]
    main_max = max(lbs) if lbs else 0

    gem_data = [s for s in data if str(s.get("dm", "")).startswith("300")]
    gem_max = max((int(s.get("lbc", 1) or 1) for s in gem_data), default=0)

    sorted_lb = sorted(set(lbs), reverse=True)
    sub_max = sorted_lb[1] if len(sorted_lb) > 1 else 0

    top_stock = max(data, key=lambda x: x.get("lbc", 0) or 0, default={})
    top_name = (top_stock.get("mc", "") or "")[:4]

    sub_stock = next((s for s in data if int(s.get("lbc", 0) or 0) == sub_max), {})
    sub_name = (sub_stock.get("mc", "") or "")[:4]

    gem_stock = max(gem_data, key=lambda x: x.get("lbc", 0) or 0, default={}) if gem_data else {}
    gem_name = (gem_stock.get("mc", "") or "")[:4]

    return {
        "day": day,
        "main": main_max,
        "sub": sub_max,
        "gem": gem_max,
        "label_main": top_name if main_max >= 3 else "",
        "label_sub": sub_name if sub_max >= 2 else "",
        "label_gem": gem_name if gem_max >= 1 else "",
    }

# 缓存策略：历史前 6 天在收盘后固定，后续运行优先从本地读取，缺失才请求接口
paths = cache_paths()
paths["dir"].mkdir(parents=True, exist_ok=True)
HEIGHT_CACHE_PATH = paths["height"]
height_cache = read_json_file(HEIGHT_CACHE_PATH)
height_cache_days = height_cache.get("days", {})

for d in his_dates:
    try:
        # 约定：d 是 YYYY-MM-DD
        cached = height_cache_days.get(d) if d != DATE else None
        if cached:
            row = cached
        else:
            # 当天用已拉取的 zt_all，避免重复请求；历史日缺失优先走 7 日缓存
            day_data = zt_all if d == DATE else fetch_pool_data("ztgc", d, use_cache_first=True, cache=pool_cache)
            row = calc_height_trend_row(d, day_data)
            if d != DATE:
                height_cache_days[d] = row

        height_trend["dates"].append(d[5:])
        height_trend["main"].append(row.get("main", 0))
        height_trend["sub"].append(row.get("sub", 0))
        height_trend["gem"].append(row.get("gem", 0))
        height_trend["labels_main"].append(row.get("label_main", ""))
        height_trend["labels_sub"].append(row.get("label_sub", ""))
        height_trend["labels_gem"].append(row.get("label_gem", ""))

        print(f"   {d[5:]}: 主板{row.get('main',0)}板({row.get('label_main','')}) 次高{row.get('sub',0)}({row.get('label_sub','')}) 创板{row.get('gem',0)}板({row.get('label_gem','')})")
    except Exception:
        height_trend["dates"].append(d[5:])
        height_trend["main"].append(0)
        height_trend["sub"].append(0)
        height_trend["gem"].append(0)
        height_trend["labels_main"].append("")
        height_trend["labels_sub"].append("")
        height_trend["labels_gem"].append("")
        print(f"   {d[5:]}: 数据缺失，按0处理")

# 写回缓存（只缓存历史日，不缓存当天）
height_cache["version"] = 1
height_cache["days"] = height_cache_days
write_json_file(HEIGHT_CACHE_PATH, height_cache)

# ══════════════════════════
# ⑥ 题材聚合(每只涨停股查询)
# ══════════════════════════
print("\n[6/12] 聚合题材数据(逐票查询，耗时较长)...")
themes_fetch_started_at = now_report().strftime("%H:%M:%S")
theme_count = {}      # theme -> count
theme_stocks = {}     # theme -> [names]
zb_theme_count = {}   # 炸板题材
zb_theme_stocks = {}  # 炸板题材 -> [names]
dt_theme_count = {}   # 跌停题材（用于主线风险归因）
dt_theme_stocks = {}  # 跌停题材 -> [names]

# 题材归因缓存（落盘复用，避免每日重复打 hszg/zg）
paths = cache_paths()
paths["dir"].mkdir(parents=True, exist_ok=True)
_theme_cache_disk = read_json_file(paths["themes"])
theme_cache = _theme_cache_disk.get("codes", {}) if isinstance(_theme_cache_disk, dict) else {}
# 缓存净化：历史缓存里可能混入“昨日涨停/昨日连板”等统计口径字段，需过滤掉避免污染题材强度
if not isinstance(theme_cache, dict):
    theme_cache = {}
else:
    for k, v in list(theme_cache.items()):
        if not isinstance(v, list):
            theme_cache[k] = []
            continue
        theme_cache[k] = [t for t in v if t and t not in EXCLUDE_THEME_NAMES and t not in NOISE_THEMES]

def normalize_stock_code(dm: str) -> str:
    """
    纯函数：把接口返回的股票代码统一为 6 位数字。

    必盈接口有时返回 `sz000657` / `sh600519`，而 hszg/zg 文档参数示例为 `000001`。
    这里统一取末尾 6 位，提升兼容性。
    """
    if not dm:
        return ""
    digits = "".join([c for c in str(dm) if c.isdigit()])
    return digits[-6:] if len(digits) >= 6 else digits

def fetch_stock_themes(code6: str):
    """
    有副作用函数：请求 API 获取股票的概念/行业/指数归因，并做噪音过滤。
    返回：清洗后的题材列表（去前缀后的短名称）
    """
    if not code6:
        return []
    if code6 in theme_cache:
        return theme_cache[code6]
    try:
        url = f"{BASE}/hszg/zg/{code6}/{TOKEN}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        result = []
        if isinstance(data, list):
            for item in data:
                t = clean_theme(item.get("name", ""))
                if t and t not in NOISE_THEMES:
                    result.append(t)
        # 去重但保持顺序
        seen = set()
        uniq = []
        for t in result:
            if t in seen:
                continue
            seen.add(t)
            uniq.append(t)
        theme_cache[code6] = uniq
        return uniq
    except Exception:
        theme_cache[code6] = []
        return []

def query_themes(stock_list, target_dict):
    """批量查询股票题材（带缓存 + 代码归一化）"""
    print(f"   准备查询 {len(stock_list)} 只股票题材...")
    for i, s in enumerate(stock_list):
        raw_code = s.get("dm", "")
        code6 = normalize_stock_code(raw_code)
        name = s.get("mc", code6 or raw_code)
        try:
            themes = fetch_stock_themes(code6)
            for t in themes:
                target_dict[t] = target_dict.get(t, 0) + 1
                # 确保存储的是名称而非代码
                if name not in theme_stocks.get(t, []):
                    theme_stocks.setdefault(t, []).append(name)
            if (i + 1) % 10 == 0:
                print(f"   已处理 {i+1}/{len(stock_list)}...")
            time.sleep(0.01)
        except Exception:
            # print(f"   查询 {code} 失败: {e}")
            pass

def query_themes_with_store(stock_list, target_count, target_stocks):
    """
    批量查询题材（用于炸板/强势等不同来源），与 query_themes 类似但写入独立的 stocks 容器。
    """
    print(f"   准备查询 {len(stock_list)} 只股票题材...")
    for i, s in enumerate(stock_list):
        raw_code = s.get("dm", "")
        code6 = normalize_stock_code(raw_code)
        name = s.get("mc", code6 or raw_code)
        try:
            themes = fetch_stock_themes(code6)
            for t in themes:
                target_count[t] = target_count.get(t, 0) + 1
                if name not in target_stocks.get(t, []):
                    target_stocks.setdefault(t, []).append(name)
            if (i + 1) % 10 == 0:
                print(f"   已处理 {i+1}/{len(stock_list)}...")
            time.sleep(0.01)
        except Exception:
            pass

# 查询涨停股题材
query_themes(zt_all, theme_count)

# 查询炸板股题材
if zb_all:
    print(f"   准备查询 {len(zb_all)} 只炸板股题材...")
    query_themes_with_store(zb_all, zb_theme_count, zb_theme_stocks)

# 查询跌停股题材（跌停通常数量不大，且对“主线风险”判断有价值）
if dt_all:
    print(f"   准备查询 {len(dt_all)} 只跌停股题材...")
    query_themes_with_store(dt_all, dt_theme_count, dt_theme_stocks)

# 过滤掉噪音题材和"昨日涨停"
real_themes = [item for item in theme_count.items() if item[0] != "昨日涨停"]
real_themes = sorted(real_themes, key=lambda x: -x[1])
themes_fetch_at = now_report().strftime("%H:%M:%S")
print(f"   有效题材: {len(real_themes)} 个")
for t, c in real_themes[:10]:
    print(f"   · {t}: {c}只 ({', '.join(theme_stocks.get(t, [])[:4])})")

def build_theme_top_list(theme_counts, theme_names, theme_stocks_map, topn=3):
    """
    纯函数：根据题材计数构建 TopN（用于 Vue 渲染）。
    """
    pairs = [(k, theme_counts.get(k, 0)) for k in theme_names]
    pairs = [p for p in pairs if p[1] > 0]
    pairs.sort(key=lambda x: -x[1])
    result = []
    for name, cnt in pairs[:topn]:
        examples = "·".join(theme_stocks_map.get(name, [])[:3])
        result.append({"name": name, "count": cnt, "examples": examples})
    return result

def topk_theme_names(theme_counts, k=5):
    """
    纯函数：拿到计数 TopK 的题材名列表。
    """
    return [name for name, _ in sorted(theme_counts.items(), key=lambda x: -x[1])[:k]]

def build_theme_strength_rows(zt_cnt: dict, zb_cnt: dict, dt_cnt: dict, topn: int = 12):
    """
    纯函数：构建“分三列（涨停/炸板/跌停）+ 净强度”的题材强度表。

    评分模型（可后续再调参）：
    net = zt*1.0 - zb*0.7 - dt*1.2
    """
    names = set(zt_cnt.keys()) | set(zb_cnt.keys()) | set(dt_cnt.keys())
    rows = []
    for name in names:
        zt = int(zt_cnt.get(name, 0) or 0)
        zb = int(zb_cnt.get(name, 0) or 0)
        dt = int(dt_cnt.get(name, 0) or 0)
        net = zt * 1.0 - zb * 0.7 - dt * 1.2
        risk = zb * 0.7 + dt * 1.2
        rows.append({
            "name": name,
            "zt": zt,
            "zb": zb,
            "dt": dt,
            "net": round(net, 1),
            "risk": round(risk, 1),
            "netClass": "red-text" if net >= 3 else ("orange-text" if net >= 1 else "green-text"),
            "riskClass": "red-text" if risk >= 3 else ("orange-text" if risk >= 1 else "green-text"),
        })
    rows.sort(key=lambda r: (-r["net"], -r["zt"], r["risk"]))
    return rows[:topn]

# 题材归因面板（涨停/炸板/强势三视角 + 重叠度）
zt_top_names = topk_theme_names(theme_count, k=8)
zb_top_names = topk_theme_names(zb_theme_count, k=8)
dt_top_names = topk_theme_names(dt_theme_count, k=8)

zt_top3 = build_theme_top_list(theme_count, zt_top_names, theme_stocks, topn=3)
zb_top3 = build_theme_top_list(zb_theme_count, zb_top_names, zb_theme_stocks, topn=3)
dt_top3 = build_theme_top_list(dt_theme_count, dt_top_names, dt_theme_stocks, topn=3)

overlap = list(set(topk_theme_names(theme_count, 5)) & set(topk_theme_names(zb_theme_count, 5)))
overlap_score = safe_rate(len(overlap), 5)
theme_strength_rows = build_theme_strength_rows(theme_count, zb_theme_count, dt_theme_count, topn=12)
theme_panels_json = json.dumps(
    {
        "ztTop": zt_top3,
        "zbTop": zb_top3,
        "dtTop": dt_top3,
        "strengthRows": theme_strength_rows,
        "overlap": {
            "themes": overlap[:5],
            "score": f"{overlap_score:.0f}%",
            "note": "涨停主线与炸板主杀题材的重叠度（越高越提示主线在分歧/退潮）",
        },
    },
    ensure_ascii=False,
)

# 写回题材缓存（跨天复用）
write_json_file(paths["themes"], {"version": 1, "codes": theme_cache})

# ══════════════════════════
# ⑦ 大面股 / 核按钮 (跌停池)
# ══════════════════════════
print("\n[7/12] 大面股分析...")
big_face = []  # -5%以下的大面股
for s in dt_all:
    zf = s.get('zf', 0)
    if zf <= -9.5 or zf <= -5:
        big_face.append({
            'name': s.get('mc', ''), 'code': s.get('dm', ''),
            'zf': zf, 'p': s.get('p', 0)
        })

# 从强势股池找大面(-5%以下)
big_face_from_qs = []
if qs_all:
    for s in qs_all:
        zf = s.get('zf', 0)
        if zf <= -5:
            big_face_from_qs.append({
                'name': s.get('mc', ''), 'code': s.get('dm', ''),
                'zf': zf, 'p': s.get('p', 0)
            })

all_big_faces = big_face + big_face_from_qs
print(f"   大面股(-5%↓): {len(all_big_faces)}只")
for b in all_big_faces[:5]:
    print(f"   · {b['name']} {b['zf']:.2f}%")

# ══════════════════════════
# ⑧ 成交额TOP10 (全市场)
# ══════════════════════════
print("\n[8/12] 成交额TOP10...")

# 合并涨停池和强势股池取TOP10
all_stocks_for_top10 = []
for s in zt_all:
    all_stocks_for_top10.append({
        'mc': s.get('mc', ''), 'dm': s.get('dm', ''),
        'zf': s.get('zf', 0), 'cje': s.get('cje', 0),
        'source': 'zt'
    })
if qs_all:
    for s in qs_all:
        all_stocks_for_top10.append({
            'mc': s.get('mc', ''), 'dm': s.get('dm', ''),
            'zf': s.get('zf', 0), 'cje': s.get('cje', 0),
            'source': 'qs'
        })

# 去重(优先用zt)
seen = set()
unique_stocks = []
for s in all_stocks_for_top10:
    if s['dm'] not in seen:
        seen.add(s['dm'])
        unique_stocks.append(s)

unique_stocks.sort(key=lambda x: x.get('cje', 0), reverse=True)
top10 = unique_stocks[:10]

print(f"   TOP1: {top10[0]['mc']} {top10[0]['cje']/1e8:.0f}亿")
top10_total = sum(t['cje'] for t in top10) / 1e8

# 为TOP10查板块
print("   查询TOP10题材...")
top10_with_theme = []
for t in top10:
    themes_for_this = []
    try:
        # 复用题材缓存 + 代码归一化（避免每次全量都重复打 10 次接口）
        code6 = normalize_stock_code(t.get("dm", ""))
        themes_for_this = fetch_stock_themes(code6)
        time.sleep(0.003)
    except Exception:
        pass
    top10_with_theme.append({
        **t,
        'sector': themes_for_this[0] if themes_for_this else '未知'
    })

for t in top10_with_theme[:5]:
    print(f"   {t['mc']} {t['zf']:+.2f}% {t['cje']/1e8:.0f}亿 [{t['sector']}]")

# ══════════════════════════
# ⑨ 昨日涨停今表现(qsgc)
# ══════════════════════════
print("\n[9/12] 昨日涨停今表现...")
# qsgc是今日强势股池，里面包含昨日涨停今涨幅分布
avg_zf_qs = 0.0
best_qs = []
worst_qs = []
if qs_all:
    zs = [(s.get('zf', 0), s.get('mc', '')) for s in qs_all]
    zs.sort(key=lambda x: x[0], reverse=True)
    avg_zf_qs = float(sum(z[0] for z in zs) / len(zs)) if zs else 0.0
    best_qs = zs[:5]
    worst_qs = zs[-5:] if len(zs) >= 5 else zs
    print(f"   强势股均涨: {avg_zf_qs:+.2f}%")
    print(f"   最佳: {best_qs[0][1]} {best_qs[0][0]:+.2f}%")
    print(f"   最差: {worst_qs[0][1]} {worst_qs[0][0]:+.2f}%")

best_qs_text = f"{best_qs[0][1]} {best_qs[0][0]:+.2f}%" if best_qs else '暂无'
worst_qs_text = f"{worst_qs[0][1]} {worst_qs[0][0]:+.2f}%" if worst_qs else '暂无'

# 昨日强势股四象限反馈
qs_extreme_up = [s for s in qs_all if s.get('zf', 0) >= 5] if qs_all else []
qs_positive = [s for s in qs_all if 0 <= s.get('zf', 0) < 5] if qs_all else []
qs_negative = [s for s in qs_all if -5 < s.get('zf', 0) < 0] if qs_all else []
qs_extreme_down = [s for s in qs_all if s.get('zf', 0) <= -5] if qs_all else []

# ══════════════════════════
# ⑩ 综合判断计算
# ══════════════════════════
print("\n[10/12] 计算综合判断...")

# 赚钱效应四维
first_board = len([s for s in zt_all if s.get('lbc', 1) == 1])
link_board = len([s for s in zt_all if s.get('lbc', 1) >= 2])
ratio_fb = first_board / link_board if link_board > 0 else first_board

effect_ratio_val = f"{int(jj_1b_rate)}%"
effect_ratio_detail = f"(昨日首板{len(yest_1b_codes)}只→今晋级{len(jinwei_from_1b)}只)"
effect_prop_val = f"{first_board}:{link_board}" if link_board > 0 else f"{first_board}:0"
effect_prop_detail = f"(首板{first_board},连板{link_board})"

# 梯队完整度
lb_levels = sorted(by_lbc.keys(), reverse=True)
ladder_str = '→'.join(str(lb) for lb in lb_levels[:4]) if len(lb_levels) >= 2 else str(max_lb)
effect_ladder_val = ladder_str
effect_ladder_detail = f"(最高{max_lb}板)"

limit_ratio = f"{zt_count}:{dt_count}" if dt_count > 0 else str(zt_count)
limit_ratio_detail = f"({zt_count/dt_count:.1f}:1)" if dt_count > 0 else "(无跌停)"

# verdict
if zt_count >= 70 and fb_rate >= 75 and jj_rate >= 40:
    effect_verdict_type = "good"
    effect_verdict_title = "📋 综合判断：大涨高潮日，赚钱效应极好。"
    up_cnt = sum(1 for i in indices_data if i.get("pct", 0) >= 0)
    effect_verdict_detail = (
        f"四大指数 {up_cnt}红{4-up_cnt}绿{'（创业板最强）' if any(i['name']=='创业板指' and i['pct']>2 for i in indices_data) else ''}，"
        f"封板率{fb_rate:.1f}%创近期高点，晋级率{jj_rate:.1f}%。当前是出手时机，但注意高潮次日分化风险。"
    )
elif zt_count >= 50 and fb_rate >= 65:
    effect_verdict_type = "warn"
    effect_verdict_title = "📋 综合判断：冰点修复期，赚钱效应偏弱但结构性机会存在。"
    effect_verdict_detail = (
        f"今日连板梯队完整度尚可（{max_lb}板龙头存活），但高位股断板率高，分歧较大。操作上以低位首板为主，高位接力需谨慎。"
    )
else:
    effect_verdict_type = "fire"
    effect_verdict_title = "📋 综合判断：情绪冰点期，亏钱效应明显。"
    effect_verdict_detail = (
        f"涨停数不足{zt_count}只，封板率仅{fb_rate:.1f}%，建议空仓观望或极轻仓试错。"
    )

market_tone = "bull" if effect_verdict_type == "good" else ("mixed" if effect_verdict_type == "warn" else "bear")
chart_palette = (
    ['#ef4444', '#f97316', '#f59e0b', '#fb7185']
    if market_tone == 'bull' else
    (['#f59e0b', '#fb7185', '#2563eb', '#10b981']
     if market_tone == 'mixed' else
     ['#10b981', '#0ea5e9', '#14b8a6', '#64748b'])
)

# 恐惧指标评级
bf_count = len(all_big_faces)  # typo fix below
if bf_count <= 2 and dt_count <= 2:
    fear_risk = "极低"
    fear_risk_note = "亏钱效应极小"
    risk_color = "green-text"
elif bf_count <= 5 and dt_count <= 5:
    fear_risk = "偏低"
    fear_risk_note = "少量大面股，整体可控"
    risk_color = "blue-text"
elif bf_count <= 10:
    fear_risk = "偏高"
    fear_risk_note = "大面股数量偏多，注意回避高位"
    risk_color = "orange-text"
else:
    fear_risk = "高"
    fear_risk_note = "大面横飞，建议观望"
    risk_color = "red-text"

# 昨涨停表现评级
if not qs_all:
    # 你已要求关闭强势股池（qsgc），这里不再用“强势池涨幅分布”评估昨日反馈，避免误导。
    yesterday_perf = "未计算"
    yesterday_note = "强势股池已关闭（减少接口），如需昨日反馈可再开启或改为“昨日涨停票今日涨幅分布”方案"
elif avg_zf_qs >= 3:
    yesterday_perf = "良好"
    yesterday_note = "昨日涨停多数盈利"
elif avg_zf_qs >= 0:
    yesterday_perf = "中等"
    yesterday_note = "部分分化"
elif avg_zf_qs >= -2:
    yesterday_perf = "偏弱"
    yesterday_note = "多数断板分化"
else:
    yesterday_perf = "差"
    yesterday_note = "大面积回落"

print(f"   效应verdict: {effect_verdict_type}")
print(f"   恐惧风险: {fear_risk}")

# ══════════════════════════
# ⑪ 动态热点板块解读生成
# ══════════════════════════
print("\n[11/12] 生成热点解读...")

hot_topics = []
topic_tags = ['fire', 'fire', 'good', 'caution', 'good', 'caution']
tag_texts = ['最强主线', '持续 ✅', '关注', '活跃', '活跃', '活跃']

# 取TOP6题材生成解读
emojis = ['🔥', '🔋', '📡', '⚡', '🤖', '💻']
for idx, (t_name, t_cnt) in enumerate(real_themes[:6]):
    stocks_in_theme = theme_stocks.get(t_name, [])[:5]
    # 找该题材下涨幅最大的代表股
    reps = []
    for s in zt_all:
        if s['mc'] in stocks_in_theme:
            reps.append(f"{s['mc']}({s.get('zf',0):+.1f}%)")
    
    tag_idx = min(idx, len(tag_texts)-1)
    emoji = emojis[min(idx, len(emojis)-1)]
    
    # 动态生成描述
    desc_parts = []
    if reps:
        desc_parts.append('、'.join(reps[:3]))
    desc_parts.append(f"共{t_cnt}只涨停")
    
    # 根据题材特点加描述
    if '锂' in t_name or '电池' in t_name:
        topic_desc = f"新能源方向活跃，{desc_parts[0] if desc_parts else t_name}领涨。"
    elif 'AI' in t_name or '算力' in t_name or '机器人' in t_name:
        topic_desc = f"科技主线延续，{desc_parts[0] if desc_parts else t_name}表现突出。"
    elif '华为' in t_name:
        topic_desc = f"华为产业链联动，{desc_parts[0] if desc_parts else t_name}封板坚决。"
    elif 'IDC' in t_name or '数据中心' in t_name or '东数西算' in t_name:
        topic_desc = f"数字经济方向资金涌入，{desc_parts[0] if desc_parts else t_name}走强。"
    elif '光伏' in t_name or '新能源' in t_name:
        topic_desc = f"赛道股反弹，{desc_parts[0] if desc_parts else t_name}异动。"
    elif '军工' in t_name or '航空' in t_name:
        topic_desc = f"国防军工活跃，{desc_parts[0] if desc_parts else t_name}带动板块。"
    else:
        topic_desc = f"{t_name}方向{t_cnt}只涨停，资金关注度提升。{' '.join(reps[:2]) if reps else ''}"

    hot_topics.append({
        'emoji': emoji,
        'title': f"{t_name}",
        'desc': topic_desc,
        'type': topic_tags[tag_idx],
        'tag': tag_texts[tag_idx],
        'count': t_cnt
    })

for h in hot_topics:
    print(f"   [{h['tag']}] {h['emoji']} {h['title']} — {h['count']}只")

# 主线/支线/轮动线分层
theme_layers = []
layer_labels = ['主线', '支线', '轮动']
layer_ranges = [(0, 1), (1, 3), (3, 6)]
for idx, (start, end) in enumerate(layer_ranges):
    layer_themes = real_themes[start:end]
    layer_names = [item[0] for item in layer_themes]
    layer_count = sum(item[1] for item in layer_themes)
    layer_stocks = []
    for theme_name in layer_names:
        for stock_name in theme_stocks.get(theme_name, []):
            if stock_name not in layer_stocks:
                layer_stocks.append(stock_name)
            if len(layer_stocks) >= 3:
                break
        if len(layer_stocks) >= 3:
            break
    theme_layers.append({
        'label': layer_labels[idx],
        'names': ' / '.join(layer_names) if layer_names else '暂无',
        'count': layer_count,
        'stocks': '·'.join(layer_stocks) if layer_stocks else '暂无代表股'
    })

# 主线题材持续性（近5个交易日）
# 优化策略：
# 1) 只统计 2 连板及以上（减少当日需要查询题材的股票数量）
# 2) 按日期缓存最近 5 个交易日的“题材计数 map”，5 天之外自动丢弃
def get_theme_daily_count_map(trade_date, cache_days_keep):
    """
    返回：{题材名: 连板(>=2)涨停家数}
    """
    # 读缓存
    try:
        paths = cache_paths()
        trend_cache = read_json_file(paths["theme_trend"])
        by_day = trend_cache.get("by_day", {}) if isinstance(trend_cache, dict) else {}
        if isinstance(by_day, dict) and trade_date in by_day and isinstance(by_day[trade_date], dict):
            return by_day[trade_date]
    except Exception:
        pass

    # 计算：只取 2 连板及以上
    day_zt_all = fetch_pool_data("ztgc", trade_date, use_cache_first=True, cache=pool_cache)
    day_counts = {}
    for stock in day_zt_all:
        try:
            lbc = int(stock.get("lbc", 1) or 1)
        except Exception:
            lbc = 1
        if lbc < 2:
            continue
        code6 = normalize_stock_code(stock.get('dm', ''))
        if not code6:
            continue
        try:
            themes = fetch_stock_themes(code6)
            for t in themes:
                day_counts[t] = day_counts.get(t, 0) + 1
            time.sleep(0.002)
        except Exception:
            continue

    # 写缓存并裁剪到最近 5 个交易日
    try:
        paths = cache_paths()
        trend_cache = read_json_file(paths["theme_trend"])
        if not isinstance(trend_cache, dict):
            trend_cache = {}
        by_day = trend_cache.get("by_day", {})
        if not isinstance(by_day, dict):
            by_day = {}
        by_day[trade_date] = day_counts
        # prune
        keep = set(cache_days_keep or [])
        by_day = {d: v for d, v in by_day.items() if d in keep}
        trend_cache.update({"version": 1, "as_of": DATE, "by_day": by_day})
        write_json_file(paths["theme_trend"], trend_cache)
    except Exception:
        pass

    return day_counts

theme_trend_days = get_trading_days_from_volume_k(5) or [DATE]
# 实时盯盘：把 DATE 纳入近5日（否则盘中会停留在上一个交易日）
if DATE not in theme_trend_days:
    theme_trend_days = theme_trend_days + [DATE]
# 去重并只保留最后5个
theme_trend_days = sorted(set(theme_trend_days))[-5:]
focus_theme_names = [item[0] for item in real_themes[:3]]
theme_trend = {'dates': [d[5:] for d in theme_trend_days], 'series': []}

if focus_theme_names:
    print("\n[附加分析] 统计主线题材持续性...")
    theme_history_map = {theme: [] for theme in focus_theme_names}
    for trade_date in theme_trend_days:
        day_map = get_theme_daily_count_map(trade_date, theme_trend_days)
        day_counts = {theme: int(day_map.get(theme, 0) or 0) for theme in focus_theme_names}
        print(f"   {trade_date[5:]}: " + " | ".join([f"{theme}{day_counts.get(theme, 0)}只" for theme in focus_theme_names]))
        for theme in focus_theme_names:
            theme_history_map[theme].append(day_counts.get(theme, 0))

    for theme in focus_theme_names:
        counts = theme_history_map[theme]
        delta = counts[-1] - counts[-2] if len(counts) >= 2 else 0
        theme_trend['series'].append({
            'name': theme,
            'counts': counts,
            'delta': delta,
        })

# ══════════════════════════
# ⑫ 板块强度TOP5
# ══════════════════════════
print("\n[12/12] 板块强度排名...")
sector_top5 = []
sector_evals = ['最强', '爆发', '活跃', '活跃', '活跃']
for idx, (t_name, t_cnt) in enumerate(real_themes[:5]):
    eval_word = sector_evals[idx] if idx < len(sector_evals) else '一般'
    stocks_str = '·'.join(theme_stocks.get(t_name, [])[:3])
    sector_top5.append({
        'rank': idx + 1,
        'name': t_name,
        'count': int(t_cnt),
        'detail': stocks_str,
        'eval': eval_word,
        'eval_color': ['red-text', 'success', 'primary', 'warning', 'text-muted'][min(idx, 4)]
    })

# ══════════════════════════
# 增强维度：情绪 / 接力 / 抱团 / 主线集中度
# ══════════════════════════
def clamp(value, low, high):
    """将数值限制在给定区间内。"""
    return max(low, min(value, high))

def get_board_rate_class(rate):
    """根据封板率返回对应的暖冷色类名。"""
    if rate >= 75:
        return 'red-text'
    if rate >= 60:
        return 'orange-text'
    return 'green-text'

def describe_volume_shift(volume_diff, volume_change_pct):
    """根据量能变化生成放量/缩量与大/小幅文案。"""
    magnitude_text = '大幅' if abs(volume_change_pct) >= 5 else '小幅'
    direction_text = '放量' if volume_diff >= 0 else '缩量'
    if volume_diff >= 0:
        tone_text = '增量资金回流明显。' if abs(volume_change_pct) >= 5 else '增量资金有回流，但力度相对温和。'
    else:
        tone_text = '资金明显收缩，追涨意愿下降。' if abs(volume_change_pct) >= 5 else '资金小幅收缩，更多偏存量博弈。'
    return {
        'tag': f"{magnitude_text}{direction_text}",
        'detail': f"{magnitude_text}{direction_text} {abs(volume_diff):.2f}亿",
        'tone': tone_text,
    }


def class_for_good_rate(rate, hi=60, mid=40):
    """
    纯函数：给“越高越好”的成功率/健康度分配颜色类名。
    - 高：红（偏强）
    - 中：橙（中性）
    - 低：绿（偏弱）
    """
    if rate >= hi:
        return "red-text"
    if rate >= mid:
        return "orange-text"
    return "green-text"

def class_for_bad_rate(rate, hi=30, mid=15):
    """
    纯函数：给“越高越糟”的风险率分配颜色类名（反向）。
    - 高：红（危险）
    - 中：橙（注意）
    - 低：绿（可控）
    """
    if rate >= hi:
        return "red-text"
    if rate >= mid:
        return "orange-text"
    return "green-text"

def median(values):
    """
    纯函数：计算中位数（空列表返回 0）。
    """
    xs = sorted([v for v in values if v is not None])
    n = len(xs)
    if n == 0:
        return 0
    mid = n // 2
    if n % 2 == 1:
        return xs[mid]
    return (xs[mid - 1] + xs[mid]) / 2

def is_hms_leq(hms: str, threshold_hms: str) -> bool:
    """
    纯函数：判断 HH:mm:ss 是否早于等于阈值时间。
    说明：HMS 固定格式下，字符串比较即可满足时序比较。
    """
    if not hms:
        return False
    return hms <= threshold_hms

def get_heat_level(score):
    """将热度分数映射为 1~5 级，用于热力图区块着色。"""
    return int(clamp(round(score), 1, 5))

top1_theme_name = real_themes[0][0] if real_themes else '暂无主线'
top1_theme_count = real_themes[0][1] if real_themes else 0
top3_theme_count = sum(item[1] for item in real_themes[:3])
top3_theme_ratio = top3_theme_count / zt_count * 100 if zt_count else 0
theme_focus_level = (
    '高度集中' if top3_theme_ratio >= 60 else
    ('较集中' if top3_theme_ratio >= 45 else '偏分散')
)
theme_focus_note = (
    f"TOP1 题材为 {top1_theme_name}，贡献 {top1_theme_count} 只涨停；"
    f"TOP3 题材合计覆盖 {top3_theme_count} 只涨停。"
)

sentiment_score = round(clamp(
    fb_rate * 0.35 +
    jj_rate * 0.25 +
    min(zt_count, 90) * 0.35 -
    dt_count * 2.2 -
    bf_count * 1.4,
    0,
    100
))

# ───────────────────────────────
# 市场全景双线评分：热度 vs 风险（更贴合短线盘感）
# ───────────────────────────────
# 热度：越高越好（封板/晋级/涨停广度/早盘一致性）
zt_breadth_score = clamp(min(zt_count, 90) / 90 * 100, 0, 100) if zt_count else 0
heat_score = round(clamp(
    fb_rate * 0.35 +
    jj_rate * 0.25 +
    zt_breadth_score * 0.25 +
    zt_early_ratio * 0.15,
    0, 100
))

# 风险：越高越危险（炸板/跌停/大面/高位炸板/断板）
dt_score = clamp(min(dt_count, 20) / 20 * 100, 0, 100) if dt_count else 0
bf_score = clamp(min(bf_count, 20) / 20 * 100, 0, 100) if bf_count else 0
risk_score = round(clamp(
    zb_rate * 0.25 +
    dt_score * 0.20 +
    bf_score * 0.20 +
    zb_high_ratio * 0.20 +
    broken_lb_rate * 0.15,
    0, 100
))

# 情绪总分：用“热度(高) + (100-风险)(高)”合成，保留 0~100 的直观刻度
sentiment_score = round(clamp(heat_score * 0.65 + (100 - risk_score) * 0.35, 0, 100))
sentiment_phase = (
    '高潮' if sentiment_score >= 82 else
    ('强修复' if sentiment_score >= 68 else
     ('分歧' if sentiment_score >= 52 else
      ('弱修复' if sentiment_score >= 38 else '冰点')))
)
sentiment_note = (
    f"热度 {heat_score} / 风险 {risk_score}；"
    f"封板率 {fb_rate:.1f}% 、晋级率 {jj_rate:.1f}% 、炸板率 {zb_rate:.1f}% 、跌停 {dt_count} 只。"
)

# 开发/模块化复用：情绪模块输入（用于 partial 重算 mood/moodStage/moodCards）
mood_inputs = {
    # scoring
    "fb_rate": fb_rate,
    "jj_rate": jj_rate,
    "jj_rate_adj": jj_rate_adj,
    "zt_count": zt_count,
    "zt_early_ratio": zt_early_ratio,
    "zb_rate": zb_rate,
    "dt_count": dt_count,
    "bf_count": bf_count,
    "zb_high_ratio": zb_high_ratio,
    "broken_lb_rate": broken_lb_rate,
    "broken_lb_rate_adj": broken_lb_rate_adj,
    # stage extra
    "rate_2to3": rate_2to3,
    "rate_2to3_adj": rate_2to3_adj,
    "rate_3to4": rate_3to4,
    "rate_3to4_adj": rate_3to4_adj,
    "height_gap": height_gap,
    # cards
    "zt_early_count": zt_early_count,
    "avg_seal_fund_yi": avg_seal_fund_yi,
    "top_seal_names": top_seal_names,
    "hs_median": hs_median,
    "hs_ge15_ratio": hs_ge15_ratio,
    "yest_2b_count": len(yest_2b_codes),
    "succ_2to3": succ_2to3,
    "yest_3b_count": len(yest_3b_codes),
    "succ_3to4": succ_3to4,
    "max_lb": max_lb,
    "second_lb": second_lb,
    "zb_high_count": zb_high_count,
    "zb_count": zb_count,
    "zb_high_names": zb_high_names,
    "avg_zt_zbc": avg_zt_zbc,
    "zt_zbc_ge3_ratio": zt_zbc_ge3_ratio,
    "smallcap_ratio": smallcap_ratio,
    "smallcap_cnt": smallcap_cnt,
    "yest_lb_count": len(yest_lb_stocks),
    "duanban_count": len(duanban_list),
    # 首板晋级（用于“情绪流”辅助观察：更多体现“试错能否转强”）
    "jj_1b_rate": jj_1b_rate,
    "jj_1b_rate_adj": jj_1b_rate_adj,
    # 高位断板提示（用于明日指南：观察断板龙头对次高板/梯队的反馈影响）
    "top_duanban_name": top_duanban_name,
    "top_duanban_lb": top_duanban_lb,
    "top_duanban_is_high": 1 if top_duanban_is_high else 0,
    # 与“赚钱效应综合判断”对齐（用于修正情绪阶段割裂感）
    "effect_verdict_type": effect_verdict_type,
    # 强势股池（qsgc）派生：昨日涨停今表现（用于热力图“赚钱效应”）
    "qs_avg_zf": avg_zf_qs,
    "qs_best_name": (best_qs[0][1] if best_qs else ""),
    "qs_best_zf": (float(best_qs[0][0]) if best_qs else 0.0),
    "qs_worst_name": (worst_qs[0][1] if worst_qs else ""),
    "qs_worst_zf": (float(worst_qs[0][0]) if worst_qs else 0.0),
}

top10_concentration = top10_total / today_total_vol * 100 if today_total_vol else 0
limitup_absorb_ratio = zt_total_cje / today_total_vol * 100 if today_total_vol else 0
capital_style = (
    '抱团明显' if top10_concentration >= 18 else
    ('局部抱团' if top10_concentration >= 12 else '分散轮动')
)
capital_note = (
    f"成交额 TOP10 占两市 {top10_concentration:.1f}% ，"
    f"涨停池吸金占比 {limitup_absorb_ratio:.1f}% 。"
)

relay_grade = (
    '顺畅' if jj_rate >= 55 and avg_zf_qs >= 2 else
    ('一般' if jj_rate >= 35 and avg_zf_qs >= 0 else '承压')
)
yesterday_feedback_text = f"{avg_zf_qs:+.2f}%"
yesterday_feedback_class = (
    'red-text' if avg_zf_qs > 0 else
    ('green-text' if avg_zf_qs < 0 else 'blue-text')
)

rotation_style = (
    '高低切' if first_board_count >= max(link_board * 2, 1) else
    ('高位抱团' if five_plus_count >= 4 else '均衡轮动')
)
rotation_note = (
    f"首板 {first_board_count} 只 / 连板 {link_board} 只 / 5板+ {five_plus_count} 只，"
    f"当前更偏 {rotation_style}。"
)

# 题材内部梯队画像
def pick_theme_leader(theme_name):
    """从涨停池中找题材最高板龙头。"""
    theme_names = set(theme_stocks.get(theme_name, []))
    candidates = [s for s in zt_all if s.get('mc', '') in theme_names]
    if not candidates:
        return '暂无'
    candidates.sort(key=lambda x: (x.get('lbc', 1), x.get('zf', 0)), reverse=True)
    leader = candidates[0]
    return f"{leader.get('mc', '')}({leader.get('lbc', 1)}板)"

def pick_theme_center(theme_name):
    """从成交额核心中找题材中军。"""
    candidates = [s for s in unique_stocks if s.get('mc', '') in set(theme_stocks.get(theme_name, []))]
    if not candidates:
        return '暂无'
    candidates.sort(key=lambda x: x.get('cje', 0), reverse=True)
    centers = candidates[:2]
    return ' / '.join(
        f"{center.get('mc', '')}({center.get('cje', 0)/1e8:.0f}亿)"
        for center in centers
    )

def pick_theme_elastic(theme_name):
    """从 20cm / 科创方向中找弹性票。"""
    theme_names = set(theme_stocks.get(theme_name, []))
    candidates = [
        s for s in zt_all
        if s.get('mc', '') in theme_names and (
            s.get('dm', '').startswith('300') or s.get('dm', '').startswith('688')
        )
    ]
    if not candidates:
        return '暂无'
    candidates.sort(key=lambda x: (x.get('zf', 0), x.get('cje', 0)), reverse=True)
    elastic = candidates[0]
    return f"{elastic.get('mc', '')}({elastic.get('zf', 0):+.1f}%)"

theme_profiles = []
for theme_name, theme_count in real_themes[:3]:
    theme_profiles.append({
        'name': theme_name,
        'count': theme_count,
        'leader': pick_theme_leader(theme_name),
        'center': pick_theme_center(theme_name),
        'elastic': pick_theme_elastic(theme_name),
    })

# 风格雷达（拆分：强度计算逻辑迁移到 daily_review.metrics.style_radar）
from daily_review.metrics.style_radar import calc_style_strengths
gem_today_count = len([s for s in zt_all if str(s.get('dm', '')).startswith('300')])
gem_height = height_trend["gem"][-1] if height_trend.get("gem") else 0
style_inputs = {
    "jj_rate": jj_rate,
    "first_board_count": first_board_count,
    "zt_count": zt_count,
    "gem_today_count": gem_today_count,
    "gem_height": gem_height,
    "top3_theme_ratio": top3_theme_ratio,
    "top10_concentration": top10_concentration,
    "high_level_ratio": high_level_ratio,
    "max_lb": max_lb,
}
style_strengths = calc_style_strengths(style_inputs)
relay_strength = style_strengths["relay_strength"]
low_trial_strength = style_strengths["low_trial_strength"]
elastic_strength = style_strengths["elastic_strength"]
theme_focus_strength = style_strengths["theme_focus_strength"]
capital_focus_strength = style_strengths["capital_focus_strength"]
high_game_strength = style_strengths["high_game_strength"]

# ══════════════════════════
# 输出汇总
# ══════════════════════════
print("\n" + "=" * 50)
print("✅ 数据采集完成!")
print("=" * 50)

# ───────────────────────────────
# HTML生成
# ───────────────────────────────
print("\n正在生成HTML...")

# ───────────────────────────────
# 输出文件策略（加分秒 + 清理历史）
# ───────────────────────────────
OUTPUT_DIR = "html"
KEEP_ONLY_LATEST_PER_DATE = True

def build_report_filename(date_str: str, now: datetime.datetime) -> str:
    """
    纯函数：构建报告文件名（包含分秒）。

    示例：复盘日记-20260417-153012.html
    """
    date_compact = date_str.replace("-", "")
    hms = now.strftime("%H%M%S")
    return f"复盘日记-{date_compact}-{hms}.html"

def cleanup_old_reports(output_dir: str, date_str: str, keep: int = 1) -> None:
    """
    有副作用函数：清理同一天的历史报告，只保留最新 keep 份。

    说明：
    - 只匹配：复盘日记-YYYYMMDD-*.html
    - keep=1：每次生成新报告前，自动删掉旧版本，避免 html 目录堆积
    """
    if keep < 0:
        return
    date_compact = date_str.replace("-", "")
    folder = Path(output_dir)
    if not folder.exists():
        return
    candidates = sorted(
        folder.glob(f"复盘日记-{date_compact}-*.html"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in candidates[keep:]:
        try:
            p.unlink()
        except Exception:
            # 清理失败不影响主流程
            pass

def up_down_class(val):
    if val > 0: return 'up'
    elif val < 0: return 'down'
    return 'flat'

def pct_class(val):
    if val > 0: return 'red-text'
    elif val < 0: return 'green-text'
    return ''

def render_metric_cards(cards):
    """复用现有 fear-card 风格渲染增强指标卡片。"""
    return ''.join(
        f"""
          <div class="fear-card">
            <div class="fear-val {card.get('value_class', '')}">{card['value']}</div>
            <div class="fear-label">{card['label']}</div>
            <div class="fear-note">{card['note']}</div>
          </div>"""
        for card in cards
    )

def render_heatmap_cells(cells):
    """渲染更接近热力图视觉语义的热区单元。"""
    return ''.join(
        f"""
        <div class="heatmap-cell level-{cell['level']}">
          <div class="heatmap-rank">热度 L{cell['level']}</div>
          <div class="heatmap-title">{cell['title']}</div>
          <div class="heatmap-value">{cell['value']}</div>
          <div class="heatmap-note">{cell['note']}</div>
        </div>"""
        for cell in cells
    )

def render_ladder_steps(groups):
    """将连板数据渲染为阶梯式天梯布局。"""
    if not groups:
        return '<div class="tier-card">暂无 2 板及以上连板股</div>'

    max_badge = max(group['badge'] for group in groups)

    def render_stock(stock):
        status_cls = 'green-text' if stock['status'] == '晋级' else 'blue-text'
        note_html = f'<span class="ladder-chip-note">{stock["note"]}</span>' if stock['note'] else ''
        return f"""
            <div class="ladder-stock-card">
              <div class="ladder-stock-name">{stock['name']}</div>
              <div class="ladder-stock-meta">
                <span class="ladder-chip {status_cls}">{stock['status']}</span>
                {note_html}
              </div>
            </div>"""

    return ''.join(
        f"""
        <div class="ladder-step" style="--step-offset: {(max_badge - group['badge']) * 28}px;">
          <div class="ladder-step-header">
            <span class="ladder-badge {'badge-' + str(group['badge']) if group['badge'] <= 6 else 'badge-1'}">{group['badge']}板</span>
            <span class="ladder-step-count">{len(group['stocks'])}只</span>
          </div>
          <div class="ladder-stock-list">
            {''.join(render_stock(stock) for stock in group['stocks'])}
          </div>
        </div>"""
        for group in groups
    )

# 说明：
# 1) 过去这里会用 Python 拼接 idx_cards_html / panorama_html 等片段；
# 2) 现在改为在最终 HTML 中使用 Vue3（CDN）来渲染这些列表/数字，便于后续维护迭代；
# 3) Python 侧只负责产出结构化数据（marketData）与静态样式。

# 量能
vol_dates_str = ','.join(v['date'] for v in vol_history)
vol_values_str = ','.join(str(round(v['vol'], 2)) for v in vol_history)
volume_shift = describe_volume_shift(vol_diff, vol_chg_pct)

summary_text = f"""📊 涨停<span class="summary-highlight">{zt_count}家</span>、封板率<span class="summary-highlight">{fb_rate:.1f}%</span>显示短线情绪<span class="summary-highlight">{'良好' if fb_rate>=70 else '一般'}</span>。<br />量能<span class="summary-highlight">{volume_shift['tag']}{abs(vol_diff):.0f}亿({vol_chg_pct:+.2f}%)</span>，{volume_shift['tone']}"""

sentiment_html = f"""
        <div class="insight-banner">
          <div class="insight-score">
            <span class="insight-score-num">{heat_score}</span>
            <span class="insight-score-unit">热度</span>
          </div>
          <div class="insight-main">
            <div class="insight-title">情绪温度 · {sentiment_phase}</div>
            <div class="insight-desc">{sentiment_note}</div>
          </div>
          <div class="insight-side">
            <div class="insight-chip">风险 {risk_score}</div>
            <div class="insight-side-note">{theme_focus_level} · 主线集中度</div>
          </div>
          <div style="grid-column: 1 / -1;">
            <div style="display:grid; gap:8px;">
              <div>
                <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--text-muted); margin-bottom:4px;">
                  <span>热度</span><span>{heat_score}</span>
                </div>
                <div class="insight-meter">
                  <div class="insight-meter-fill" style="width: {heat_score}%;"></div>
                </div>
              </div>
              <div>
                <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--text-muted); margin-bottom:4px;">
                  <span>风险</span><span>{risk_score}</span>
                </div>
                <div class="insight-meter" style="background: rgba(239, 68, 68, 0.12);">
                  <div class="insight-meter-fill" style="width: {risk_score}%; background: linear-gradient(90deg, rgba(34,197,94,0.6) 0%, rgba(249,115,22,0.85) 45%, rgba(239,68,68,0.95) 100%);"></div>
                </div>
              </div>
            </div>
          </div>
        </div>"""

# 结构拆解
structure_grid_html = f"""
          <div class="fear-card">
            <div class="fear-val red-text">{first_board_count}只</div>
            <div class="fear-label">首板</div>
            <div class="fear-note">低位试错主战场</div>
          </div>
          <div class="fear-card">
            <div class="fear-val orange-text">{second_board_count}只</div>
            <div class="fear-label">2板</div>
            <div class="fear-note">次日接力核心池</div>
          </div>
          <div class="fear-card">
            <div class="fear-val blue-text">{third_board_count}只</div>
            <div class="fear-label">3板</div>
            <div class="fear-note">分歧后核心验证</div>
          </div>
          <div class="fear-card">
            <div class="fear-val purple-text">{four_plus_count}只</div>
            <div class="fear-label">4板+</div>
            <div class="fear-note">高位抱团观察区</div>
          </div>"""

risk_grid_html = f"""
          <div class="fear-card">
            <div class="fear-val red-text">{five_plus_count}只</div>
            <div class="fear-label">5板及以上</div>
            <div class="fear-note">{high_level_note}</div>
          </div>
          <div class="fear-card">
            <div class="fear-val blue-text">{jj_rate:.1f}%</div>
            <div class="fear-label">连板晋级率</div>
            <div class="fear-note">昨日连板 {len(yest_lb_stocks)} → 今存活 {len(jinwei_list)}</div>
          </div>
          <div class="fear-card">
            <div class="fear-val {'green-text' if high_level_risk == '可控' else ('orange-text' if high_level_risk == '偏高' else 'red-text')}">{high_level_risk}</div>
            <div class="fear-label">高位风险</div>
            <div class="fear-note">结合空间高度与断板数量综合判断</div>
          </div>"""

rotation_grid_html = render_metric_cards([
    {
        'value': rotation_style,
        'label': '风格偏好',
        'note': rotation_note,
        'value_class': 'purple-text',
    },
    {
        'value': f"{first_board_count}:{link_board}",
        'label': '低位/连板比',
        'note': '首板试错与接力博弈的相对强弱',
        'value_class': 'blue-text',
    },
    {
        'value': f"{high_level_ratio:.1f}%",
        'label': '高位占比',
        'note': '5板及以上在涨停池中的占比',
        'value_class': 'orange-text' if high_level_ratio < 8 else 'red-text',
    },
])

tier_cards_html = ""
for layer in theme_layers:
    tier_cards_html += f"""
        <div class="tier-card">
          <div class="tier-label">{layer['label']}</div>
          <div class="tier-title">{layer['names']}</div>
          <div class="tier-desc">{layer['count']}只涨停 · {layer['stocks']}</div>
        </div>"""

# 赚钱效应四维
effect_grid_html = f"""
          <div class="effect-item yellow-bg">
            <div class="effect-val orange-text" id="effectRatio">{effect_ratio_val}</div>
            <div class="effect-label">
              首板晋级率<br />
              <span style="color: var(--text-muted); font-size: 10px" id="effectRatioDetail">{effect_ratio_detail}</span>
            </div>
          </div>
          <div class="effect-item blue-bg">
            <div class="effect-val blue-text" id="effectProp">{effect_prop_val}</div>
            <div class="effect-label">
              首:连板比<br />
              <span style="color: var(--text-muted); font-size: 10px" id="effectPropDetail">{effect_prop_detail}</span>
            </div>
          </div>
          <div class="effect-item green-bg">
            <div class="effect-val green-text" id="effectLadder">{effect_ladder_val}</div>
            <div class="effect-label">
              梯队完整度<br />
              <span style="color: var(--text-muted); font-size: 10px" id="effectLadderDetail">{effect_ladder_detail}</span>
            </div>
          </div>
          <div class="effect-item red-bg">
            <div class="effect-val red-text" id="effectLimit">{limit_ratio}</div>
            <div class="effect-label">
              涨跌停比<br />
              <span style="color: var(--text-muted); font-size: 10px" id="effectLimitDetail">{limit_ratio_detail}</span>
            </div>
          </div>"""

# 恐惧指标 - 大面股组
bf_names = ', '.join([b['name'] for b in all_big_faces[:3]]) if all_big_faces else '无'
dt_names = ', '.join([f"{s.get('mc','')}{s.get('zf',0):.1f}%" for s in dt_all[:2]]) if dt_all else '—'

fear_grid1 = f"""
          <div class="fear-card">
            <div class="fear-val red-text" id="fearBigFace">{bf_count}只</div>
            <div class="fear-label">大面股(-5%↓)</div>
            <div class="fear-note" id="fearBigFaceNote">{bf_names if bf_names else '无'}</div>
          </div>
          <div class="fear-card">
            <div class="fear-val green-text" id="fearLimitDown">{dt_count}只</div>
            <div class="fear-label">非ST跌停</div>
            <div class="fear-note" id="fearLimitDownNote">{dt_names}</div>
          </div>
          <div class="fear-card">
            <div class="fear-val {risk_color}" id="fearRisk">{fear_risk}</div>
            <div class="fear-label">亏钱效应</div>
            <div class="fear-note">{fear_risk_note}</div>
          </div>"""

# 恐惧指标 - 炸板&昨表现组
seal_rate_class = get_board_rate_class(fb_rate)
fear_grid2 = f"""
          <div class="fear-card">
            <div class="fear-val orange-text" id="fearBroken">{zb_rate:.1f}%</div>
            <div class="fear-label">今日炸板率</div>
            <div class="fear-note" id="fearBrokenNote">{zb_count}/({zt_count}+{zb_count}) = {zb_rate:.1f}% | {'高于' if zb_rate>25 else '低于'}均值</div>
          </div>
          <div class="fear-card">
            <div class="fear-val {seal_rate_class}" id="fearSuccess">{fb_rate:.1f}%</div>
            <div class="fear-label">封板成功率</div>
            <div class="fear-note">封板质量{'极高' if fb_rate>=80 else ('尚可' if fb_rate>=70 else '偏低')}</div>
          </div>
          <div class="fear-card">
            <div class="fear-val blue-text" id="fearYesterday">{yesterday_perf}</div>
            <div class="fear-label">昨涨停今表现</div>
            <div class="fear-note">{yesterday_note}</div>
          </div>"""

capital_grid_html = render_metric_cards([
    {
        'value': f"{top10_concentration:.1f}%",
        'label': 'TOP10 成交集中度',
        'note': '成交额前十占两市总成交比例',
        'value_class': 'blue-text',
    },
    {
        'value': f"{limitup_absorb_ratio:.1f}%",
        'label': '涨停池吸金占比',
        'note': '涨停股成交额占两市总成交比例',
        'value_class': 'red-text',
    },
    {
        'value': capital_style,
        'label': '资金风格',
        'note': capital_note,
        'value_class': 'purple-text',
    },
])

relay_grid_html = render_metric_cards([
    {
        'value': f"{jj_rate:.1f}%",
        'label': '连板承接',
        'note': f'昨日连板 {len(yest_lb_stocks)} 只，今日晋级 {len(jinwei_list)} 只',
        'value_class': 'blue-text',
    },
    {
        'value': f"{jj_1b_rate:.0f}%",
        'label': '首板转二板',
        'note': f'昨日首板 {len(yest_1b_codes)} 只，今日晋级 {len(jinwei_from_1b)} 只',
        'value_class': 'orange-text',
    },
    {
        'value': yesterday_feedback_text,
        'label': '昨日强势反馈',
        'note': f'接力质量判断：{relay_grade}',
        'value_class': yesterday_feedback_class,
    },
])

yesterday_review_grid_html = render_metric_cards([
    {
        'value': yesterday_feedback_text,
        'label': '强势股均涨',
        'note': '昨日涨停 / 强势股的次日整体反馈',
        'value_class': yesterday_feedback_class,
    },
    {
        'value': best_qs_text,
        'label': '最佳反馈',
        'note': '最强延续样本',
        'value_class': 'red-text',
    },
    {
        'value': worst_qs_text,
        'label': '最弱反馈',
        'note': '次日负反馈样本',
        'value_class': 'green-text',
    },
])

broken_structure_grid_html = render_metric_cards([
    {
        'value': f"{zb_low_count}只",
        'label': '首板炸板',
        'note': '低位试错失败，隔日修复价值一般',
        'value_class': 'orange-text',
    },
    {
        'value': f"{zb_mid_count}只",
        'label': '中位炸板',
        'note': '2-3板分歧区，最影响接力信心',
        'value_class': 'blue-text',
    },
    {
        'value': f"{zb_high_count}只",
        'label': '高位炸板',
        'note': f'高位风险样本：{zb_high_names}',
        'value_class': 'red-text',
    },
])

# 热点板块解读
topics_html = ""
for h in hot_topics:
    topics_html += f"""
        <div class="hot-topic {h['type']}">
          <div class="topic-title">
            {h['emoji']} {h['title']}
            <span class="topic-tag tag-{h['type'].replace('good','sustained').replace('caution','caution').replace('fire','fire')}">{h['tag']}</span>
          </div>
          <div class="topic-desc">{h['desc']}</div>
        </div>"""

theme_focus_grid_html = render_metric_cards([
    {
        'value': top1_theme_name,
        'label': '最强主线',
        'note': f'贡献 {top1_theme_count} 只涨停',
        'value_class': 'red-text',
    },
    {
        'value': f"{top3_theme_ratio:.1f}%",
        'label': 'TOP3 覆盖率',
        'note': f'TOP3 题材合计 {top3_theme_count} 只涨停',
        'value_class': 'blue-text',
    },
    {
        'value': theme_focus_level,
        'label': '主线集中度',
        'note': theme_focus_note,
        'value_class': 'purple-text',
    },
])

theme_profile_cards_html = ""
for profile in theme_profiles:
    theme_profile_cards_html += f"""
        <div class="tier-card">
          <div class="tier-label">{profile['name']} · {profile['count']}只</div>
          <div class="tier-title">龙头：{profile['leader']}</div>
          <div class="tier-desc">中军：{profile['center']}</div>
          <div class="tier-desc">弹性：{profile['elastic']}</div>
        </div>"""

theme_trend_cards_html = ""
for idx, item in enumerate(theme_trend['series']):
    delta = item['delta']
    delta_cls = 'red-text' if delta > 0 else ('green-text' if delta < 0 else 'blue-text')
    trend_text = " → ".join(str(v) for v in item['counts'])
    theme_trend_cards_html += f"""
        <div class="tier-card">
          <div class="tier-label">近5日持续性 · {theme_trend['dates'][0] if theme_trend['dates'] else ''} ~ {theme_trend['dates'][-1] if theme_trend['dates'] else ''}</div>
          <div class="tier-title">{item['name']}</div>
          <div class="tier-desc">涨停家数：{trend_text}</div>
          <div class="tier-desc {delta_cls}">最新变化：{delta:+d} 只</div>
        </div>"""

quadrant_feedback_html = render_metric_cards([
    {
        'value': f"{len(qs_extreme_up)}只",
        'label': '强延续',
        'note': '昨日强势股中今日涨幅 >= 5%',
        'value_class': 'red-text',
    },
    {
        'value': f"{len(qs_positive)}只",
        'label': '温和盈利',
        'note': '昨日强势股中今日收红但未大涨',
        'value_class': 'orange-text',
    },
    {
        'value': f"{len(qs_negative)}只",
        'label': '小幅负反馈',
        'note': '昨日强势股中今日小幅回落',
        'value_class': 'blue-text',
    },
    {
        'value': f"{len(qs_extreme_down)}只",
        'label': '大面 / 核按钮',
        'note': '昨日强势股中今日跌幅 <= -5%',
        'value_class': 'green-text',
    },
])

heatmap_cells = [
    {
        'title': '接力热区',
        'value': f"{len(qs_extreme_up) + len(qs_positive)}只",
        'note': '昨日强势股中继续给到正反馈的样本数量。',
        'level': get_heat_level((len(qs_extreme_up) * 1.3 + len(qs_positive) * 0.7) / max(qs_count, 1) * 5),
    },
    {
        'title': '主线拥挤度',
        'value': f"{top3_theme_ratio:.1f}%",
        'note': 'TOP3 题材覆盖率越高，资金越集中在主线。',
        'level': get_heat_level(top3_theme_ratio / 20),
    },
    {
        'title': '亏钱扩散',
        'value': f"{bf_count + dt_count}只",
        'note': '大面股与跌停数量越多，亏钱效应越容易扩散。',
        'level': get_heat_level((bf_count + dt_count) / 3),
    },
    {
        'title': '高位压力',
        'value': f"{five_plus_count} / {zb_high_count}",
        'note': '5板+家数与高位炸板数量共同反映高位博弈压力。',
        'level': get_heat_level((five_plus_count * 1.5 + zb_high_count) / 2),
    },
]
heatmap_cells_html = render_heatmap_cells(heatmap_cells)

# 高度趋势数据
ht_dates_str = ','.join(height_trend['dates'])
ht_main_str = ','.join(str(x) for x in height_trend['main'])
ht_sub_str = ','.join(str(x) for x in height_trend['sub'])
ht_gem_str = ','.join(str(x) for x in height_trend['gem'])
ht_labels_main = ','.join(height_trend['labels_main'])
ht_labels_sub = ','.join(height_trend['labels_sub'])

# 连板天梯
ladder_groups = [
    {
        'badge': badge,
        'stocks': [row for row in ladder_rows if row['badge'] == badge]
    }
    for badge in sorted({row['badge'] for row in ladder_rows}, reverse=True)
]
ladder_steps_html = render_ladder_steps(ladder_groups)

# 断板列表
broken_text = ' / '.join([f"{s['mc']}({s['lbc']}板)" for s in duanban_list[:8]])
if broken_text:
    broken_text = f"❌ 昨日断板：{broken_text}"
else:
    broken_text = "✅ 昨日无断板"

# ───────────────────────────────
# Vue 渲染所需数据（结构化 JSON）
# ───────────────────────────────
def build_top10_rows(rows):
    """
    纯函数：把成交额 TOP10 的原始字段，整理为前端易渲染的行数据。
    说明：这里直接产出显示用字符串（如 +x.xx% / xx亿），确保渲染结果与旧版 HTML 一致。
    """
    result = []
    for i, t in enumerate(rows):
        weight = 900 if i == 0 else (800 if i <= 2 else 700)
        result.append({
            'rank': i + 1,
            'mc': t['mc'],
            'zf_str': f"{t['zf']:+.2f}%",
            'pct_class': pct_class(t['zf']),
            'cje_yi': f"{t['cje']/1e8:.0f}亿",
            'weight': weight,
            'sector': t['sector'],
        })
    return result

def build_action_guide(key_watch1, key_watch2, hot_topics, top1_theme_name, rotation_style, zt_count, effect_verdict_type):
    """
    纯函数：生成“明日行动指南”的结构化数据（Vue v-for 渲染）。
    """
    watch3 = hot_topics[1]['title'] if len(hot_topics) > 1 else '主流板块'
    mainline_focus = (
        '低位换手首板 / 2板确认'
        if rotation_style == '高低切'
        else '高位核心分歧承接'
    )
    risk_prefix = '高潮次日分化风险！' if zt_count >= 70 else '注意情绪变化'
    risk_level = '近期峰值' if zt_count >= 70 else '正常水平'
    risk_action = '不追涨' if zt_count >= 70 else '控制仓位'

    if effect_verdict_type == 'good':
        suggest = '持仓观察'
        suggest_detail = '— 四维度向好，但今天高潮，只持仓不追涨。'
    elif effect_verdict_type == 'warn':
        suggest = '轻仓试错'
        suggest_detail = '— 有结构性机会，以低位首板为主。'
    else:
        suggest = '空仓观望'
        suggest_detail = '— 等待情绪修复再入场。'

    return [
        {'dot_class': 'dot-key', 'strong_text': '关键看点①：', 'text': key_watch1, 'style': ''},
        {'dot_class': 'dot-key', 'strong_text': '关键看点②：', 'text': key_watch2, 'style': ''},
        {'dot_class': 'dot-watch', 'strong_text': '观察：', 'text': f"{watch3}是否分化。", 'style': ''},
        {
            'dot_class': 'dot-watch',
            'strong_text': '主线应对：',
            'text': f"围绕{top1_theme_name}做核心辨识度，当前风格偏{rotation_style}，优先看{mainline_focus}。",
            'style': '',
        },
        {
            'dot_class': 'dot-risk',
            'strong_text': '风险提示：',
            'text': f"{risk_prefix}今日涨停{zt_count}只是{risk_level}，{risk_action}。",
            'style': '',
        },
        {
            'dot_class': 'dot-safe',
            'strong_text': f"策略建议：{suggest}",
            'text': suggest_detail,
            'style': 'color: var(--theme-positive)',
        },
    ]

# 板块强度TOP5 / 成交额TOP10 / 行动指南（改为 Vue 渲染）
sectors_json = json.dumps(sector_top5, ensure_ascii=False)
top10_rows_json = json.dumps(build_top10_rows(top10_with_theme), ensure_ascii=False)
top10_summary_json = json.dumps(
    {
        'top5_sum_yi': f"{sum(t['cje'] for t in top10_with_theme[:5]) / 1e8:.0f}亿",
        'top5_sectors': ', '.join([t['sector'] for t in top10_with_theme[:5]]),
    },
    ensure_ascii=False
)

# 行动指南：关键看点
key_watch1 = f"{ladder_rows[0]['name'].replace('👑 ','')}{max_lb}→{max_lb+1}板能否晋级？决定空间是否打开。" if ladder_rows else ""
key_watch2 = f"{hot_topics[0]['title']}持续性！" if hot_topics else ""
action_guide_json = json.dumps(
    build_action_guide(
        key_watch1=key_watch1,
        key_watch2=key_watch2,
        hot_topics=hot_topics,
        top1_theme_name=top1_theme_name,
        rotation_style=rotation_style,
        zt_count=zt_count,
        effect_verdict_type=effect_verdict_type,
    ),
    ensure_ascii=False
)

# ───────────────────────────────
# 情绪阶段（更细维度的规则判定）
# ───────────────────────────────
def calc_mood_stage(
    *,
    heat_score: float,
    risk_score: float,
    fb_rate: float,
    zb_rate: float,
    dt_count: int,
    rate_2to3: float,
    rate_3to4: float,
    height_gap: int,
    broken_lb_rate: float,
    zb_high_ratio: float,
    zt_early_ratio: float,
    max_lb: int,
) -> dict:
    """
    纯函数：根据多维指标给出“情绪阶段”与原因说明。

    返回：
    - title: 阶段名称（高潮/强修复/分歧/弱修复/退潮/冰点）
    - type: good|warn|fire（用于前端配色）
    - detail: 一句话结论
    """
    # 风险/退潮信号
    risk_hits = 0
    risk_hits += 1 if dt_count >= 10 else 0
    risk_hits += 1 if broken_lb_rate >= 35 else 0
    risk_hits += 1 if zb_high_ratio >= 20 else 0
    risk_hits += 1 if zb_rate >= 28 else 0
    risk_hits += 1 if height_gap >= 4 else 0
    risk_hits += 1 if risk_score >= 60 else 0

    # 强势/一致信号
    strong_hits = 0
    strong_hits += 1 if fb_rate >= 78 else 0
    strong_hits += 1 if rate_2to3 >= 55 else 0
    strong_hits += 1 if rate_3to4 >= 35 else 0
    strong_hits += 1 if zt_early_ratio >= 55 else 0
    strong_hits += 1 if heat_score >= 75 else 0
    # 短线高度突破：提高强势判定权重（6板及以上视为“空间打开”）
    strong_hits += 1 if max_lb >= 6 else 0

    # 阶段判定（优先识别极端）
    if heat_score <= 35 or (fb_rate < 55 and dt_count >= 15) or risk_score >= 80:
        return {"title": "冰点", "type": "fire", "detail": "跌停与断板压力大，短线生态偏弱，等待情绪修复信号。"}

    if risk_hits >= 3 and strong_hits <= 1:
        return {"title": "退潮", "type": "fire", "detail": "高位/连板承接走弱，风险信号集中，优先防守，少做接力。"}

    if strong_hits >= 4 and risk_hits <= 1:
        # 高分段再区分“高潮”
        if heat_score >= 85 and (risk_score >= 45 or height_gap >= 3 or zb_rate >= 22):
            return {"title": "高潮", "type": "good", "detail": "一致性强但易分化，注意高潮次日回撤与高位炸板风险。"}
        return {"title": "强修复", "type": "good", "detail": "封板与晋级偏强，短线生态健康，低位与核心接力都有机会。"}

    # 中间态：分歧/弱修复
    if risk_hits >= 2 and strong_hits >= 2:
        return {"title": "分歧", "type": "warn", "detail": "强弱并存，轮动加快，控制仓位，优先做确定性更高的方向。"}

    return {"title": "弱修复", "type": "warn", "detail": "有修复但承接一般，适合轻仓试错，重点观察2进3/3进4能否走强。"}

mood_stage_json = json.dumps(
    # 统一口径：使用 daily_review/metrics/mood.py 的阶段判定（避免“正常复盘”和“只重算mood”输出不一致）
    calc_mood_stage_unified(
        heat_score=heat_score,
        risk_score=risk_score,
        inputs=mood_inputs,
    ),
    ensure_ascii=False,
)

# 情绪生态补充指标卡片（Vue v-for 渲染）
mood_cards_json = json.dumps(
    [
        {
            "value": f"{zt_early_ratio:.0f}%",
            "label": "早盘封板占比",
            "note": f"10点前首封 {zt_early_count} / 涨停 {zt_count}",
            "valueClass": class_for_good_rate(zt_early_ratio, hi=55, mid=35),
        },
        {
            "value": f"{avg_seal_fund_yi:.1f}亿",
            "label": "平均封板资金",
            "note": f"TOP3：{top_seal_names}",
            "valueClass": ("red-text" if avg_seal_fund_yi >= 2.0 else ("orange-text" if avg_seal_fund_yi >= 1.0 else "green-text")),
        },
        {
            "value": f"{hs_median:.1f}%",
            "label": "涨停换手(中位)",
            "note": f"高换手(≥15%) {hs_ge15_ratio:.0f}%",
            "valueClass": ("red-text" if hs_median >= 10 else ("orange-text" if hs_median >= 6 else "green-text")),
        },
        {
            "value": f"{rate_2to3:.0f}%",
            "label": "2进3成功率",
            "note": f"昨日2板 {len(yest_2b_codes)} → 今3板+ {succ_2to3}",
            "valueClass": class_for_good_rate(rate_2to3, hi=55, mid=35),
        },
        {
            "value": f"{rate_3to4:.0f}%",
            "label": "3进4成功率",
            "note": f"昨日3板 {len(yest_3b_codes)} → 今4板+ {succ_3to4}",
            "valueClass": class_for_good_rate(rate_3to4, hi=45, mid=25),
        },
        {
            "value": f"{height_gap}",
            "label": "高度差",
            "note": f"最高{max_lb}板 / 次高{second_lb}板",
            "valueClass": ("orange-text" if height_gap >= 3 else ("blue-text" if height_gap == 2 else "green-text")),
        },
        {
            "value": f"{zb_high_ratio:.1f}%",
            "label": "高位炸板占比(4板+)",
            "note": f"高位炸板 {zb_high_count} / 炸板 {zb_count}（{zb_high_names if zb_high_names else '无'}）",
            "valueClass": class_for_bad_rate(zb_high_ratio, hi=20, mid=8),
        },
        {
            "value": f"{avg_zt_zbc:.1f}",
            "label": "涨停炸板次数(均)",
            "note": f"高炸板(≥3次) {zt_zbc_ge3_ratio:.0f}%",
            "valueClass": class_for_bad_rate(zt_zbc_ge3_ratio, hi=18, mid=8),
        },
        {
            "value": f"{smallcap_ratio:.0f}%",
            "label": "小票活跃度(<50亿)",
            "note": f"小票 {smallcap_cnt} / 涨停 {zt_count}",
            "valueClass": class_for_good_rate(smallcap_ratio, hi=55, mid=35),
        },
        {
            "value": f"{broken_lb_rate:.0f}%",
            "label": "连板断板率",
            "note": f"昨日连板 {len(yest_lb_stocks)} → 断板 {len(duanban_list)}",
            "valueClass": class_for_bad_rate(broken_lb_rate, hi=35, mid=20),
        },
    ],
    ensure_ascii=False,
)

# 题材趋势序列（避免在 f-string 内部嵌套三引号，降低语法风险）
theme_trend_series_js = ','.join(
    f'''
            {{
              name: "{item['name']}",
              values: [{','.join(str(v) for v in item['counts'])}]
            }}'''.rstrip()
    for item in theme_trend['series']
)

# 连板天梯 JS 数组行（避免在 f-string 表达式里出现 \n 反斜杠）
ladder_rows_js = ', '.join(
    f'''
          {{ badge: {r["badge"]}, name: "{r["name"]}", status: "{r["status"]}", note: "{r["note"]}" }}'''.rstrip()
    for r in ladder_rows
)

# ───────────────────────────────
# 最终HTML组装
# ───────────────────────────────
html = f'''<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>A股收盘简报 | {DATE}</title>
    <script src="{ECHARTS_SRC}"></script>
    <script src="{VUE_SRC}"></script>
    <style>
      [v-cloak] {{ display: none; }}
      :root {{
        --primary: #2563eb;
        --success: #10b981;
        --danger: #ef4444;
        --warning: #f59e0b;
        --purple: #8b5cf6;
        --pink: #ec4899;
        --theme-accent: #2563eb;
        --theme-accent-2: #60a5fa;
        --theme-soft: rgba(37, 99, 235, 0.12);
        --hero-start: #1e3a8a;
        --hero-mid: #2563eb;
        --hero-end: #60a5fa;
        --theme-glow: rgba(37, 99, 235, 0.18);
        --theme-chip-bg: rgba(37, 99, 235, 0.12);
        --theme-chip-text: #1d4ed8;
        --theme-positive: #2563eb;
        --theme-heat-hot: rgba(239,68,68,0.12);
        --theme-heat-warm: rgba(245,158,11,0.12);
        --theme-heat-cool: rgba(37,99,235,0.10);
        --theme-heat-cold: rgba(16,185,129,0.10);

        /* 亮色主题 */
        --bg-base: #f4f7fa;
        --bg-card: #ffffff;
        --bg-elevated: #f8fafc;
        --border: rgba(0, 0, 0, 0.06);
        --text-primary: #1e293b;
        --text-secondary: #475569;
        --text-muted: #94a3b8;

        --radius-lg: 18px;
        --radius-md: 12px;
        --radius-sm: 8px;
        --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.04);
        --shadow-md: 0 4px 20px rgba(0, 0, 0, 0.05);
        --shadow-lg: 0 10px 40px rgba(0, 0, 0, 0.08);
      }}

      [data-theme="dark"] {{
        --bg-base: #0f172a;
        --bg-card: #1e293b;
        --bg-elevated: #334155;
        --border: rgba(255, 255, 255, 0.08);
        --text-primary: #f1f5f9;
        --text-secondary: #cbd5e1;
        --text-muted: #64748b;
        --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.3);
        --shadow-md: 0 4px 20px rgba(0, 0, 0, 0.4);
      }}

      body[data-market-tone="bull"] {{
        --primary: #ea580c;
        --theme-accent: #ef4444;
        --theme-accent-2: #f97316;
        --theme-soft: rgba(239, 68, 68, 0.14);
        --hero-start: #7f1d1d;
        --hero-mid: #dc2626;
        --hero-end: #f97316;
        --theme-glow: rgba(239, 68, 68, 0.24);
        --theme-chip-bg: rgba(249, 115, 22, 0.16);
        --theme-chip-text: #c2410c;
        --theme-positive: #dc2626;
        --theme-heat-hot: rgba(239,68,68,0.18);
        --theme-heat-warm: rgba(249,115,22,0.16);
        --theme-heat-cool: rgba(251,191,36,0.14);
        --theme-heat-cold: rgba(253,186,116,0.12);
      }}

      body[data-market-tone="mixed"] {{
        --primary: #d97706;
        --theme-accent: #f59e0b;
        --theme-accent-2: #fb7185;
        --theme-soft: rgba(245, 158, 11, 0.14);
        --hero-start: #78350f;
        --hero-mid: #d97706;
        --hero-end: #fb7185;
        --theme-glow: rgba(245, 158, 11, 0.20);
        --theme-chip-bg: rgba(245, 158, 11, 0.14);
        --theme-chip-text: #b45309;
        --theme-positive: #ea580c;
        --theme-heat-hot: rgba(251,146,60,0.16);
        --theme-heat-warm: rgba(245,158,11,0.16);
        --theme-heat-cool: rgba(59,130,246,0.10);
        --theme-heat-cold: rgba(16,185,129,0.10);
      }}

      body[data-market-tone="bear"] {{
        --primary: #0f766e;
        --theme-accent: #10b981;
        --theme-accent-2: #38bdf8;
        --theme-soft: rgba(16, 185, 129, 0.14);
        --hero-start: #0f172a;
        --hero-mid: #0f766e;
        --hero-end: #0ea5e9;
        --theme-glow: rgba(16, 185, 129, 0.20);
        --theme-chip-bg: rgba(16, 185, 129, 0.14);
        --theme-chip-text: #0f766e;
        --theme-positive: #0ea5e9;
        --theme-heat-hot: rgba(14,165,233,0.14);
        --theme-heat-warm: rgba(56,189,248,0.12);
        --theme-heat-cool: rgba(16,185,129,0.12);
        --theme-heat-cold: rgba(15,118,110,0.16);
      }}

      * {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
      }}

      body {{
        font-family: -apple-system, "SF Pro Text", "Helvetica Neue", "PingFang SC", "Microsoft YaHei", sans-serif;
        background: var(--bg-base);
        color: var(--text-primary);
        line-height: 1.6;
        padding: 24px 12px 60px;
        transition:
          background 0.3s,
          color 0.3s;
      }}
      .container {{
        max-width: 860px;
        margin: 0 auto;
      }}

      /* Hero */
      .hero {{
        background: linear-gradient(135deg, var(--hero-start) 0%, var(--hero-mid) 58%, var(--hero-end) 100%);
        border-radius: var(--radius-lg);
        padding: 32px 28px;
        color: #fff;
        margin-bottom: 20px;
        position: relative;
        overflow: hidden;
        box-shadow: var(--shadow-lg);
      }}
      .hero::before {{
        content: "";
        position: absolute;
        top: -30%;
        right: -15%;
        width: 320px;
        height: 320px;
        background: rgba(255, 255, 255, 0.06);
        border-radius: 50%;
        animation: float 6s ease-in-out infinite;
      }}
      .hero::after {{
        content: "";
        position: absolute;
        bottom: -40%;
        left: -10%;
        width: 200px;
        height: 200px;
        background: rgba(255, 255, 255, 0.04);
        border-radius: 50%;
        animation: float 8s ease-in-out infinite reverse;
      }}
      @keyframes float {{
        0%, 100% {{ transform: translateY(0) scale(1); }}
        50% {{ transform: translateY(-20px) scale(1.05); }}
      }}
      .hero-top {{ position: relative; z-index: 1; }}
      .hero-controls {{
        position: absolute;
        top: 20px;
        right: 20px;
        display: flex;
        gap: 8px;
        z-index: 2;
      }}
      .theme-toggle {{
        background: rgba(255, 255, 255, 0.15);
        border: 1px solid rgba(255, 255, 255, 0.2);
        color: #fff;
        border-radius: 20px;
        padding: 6px 14px;
        font-size: 12px;
        cursor: pointer;
        transition: all 0.2s;
        backdrop-filter: blur(10px);
        font-weight: 700;
        letter-spacing: 0.2px;
      }}
      .theme-toggle:hover {{ background: rgba(255, 255, 255, 0.25); }}
      .cycle-tag {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: rgba(255, 255, 255, 0.18);
        backdrop-filter: blur(10px);
        padding: 6px 16px;
        border-radius: 30px;
        font-size: 13px;
        font-weight: 600;
        margin-bottom: 12px;
      }}
      .cycle-dot {{
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--success);
        animation: pulse 2s infinite;
      }}
      @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}
      .hero-date {{ font-size: 26px; font-weight: 800; letter-spacing: 0.5px; }}
      .hero-subtitle {{ opacity: 0.8; font-size: 13px; margin-top: 6px; font-weight: 500; }}

      .index-row {{ display: flex; gap: 12px; margin-top: 24px; position: relative; z-index: 1; flex-wrap: wrap; }}
      .index-card {{
        flex: 1; min-width: 120px;
        background: rgba(255, 255, 255, 0.1);
        border-radius: var(--radius-md);
        padding: 16px 12px;
        text-align: center;
        backdrop-filter: blur(8px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        transition: transform 0.2s, background 0.2s;
      }}
      .index-card:hover {{ transform: translateY(-3px); background: rgba(255, 255, 255, 0.18); }}
      .index-card.highlight {{ background: rgba(239, 68, 68, 0.25); border-color: rgba(239, 68, 68, 0.4); box-shadow: 0 0 30px rgba(239, 68, 68, 0.2); }}
      body[data-market-tone="bull"] .index-card.highlight {{ background: rgba(239, 68, 68, 0.26); border-color: rgba(249, 115, 22, 0.48); box-shadow: 0 0 34px rgba(239, 68, 68, 0.26); }}
      body[data-market-tone="mixed"] .index-card.highlight {{ background: rgba(245, 158, 11, 0.24); border-color: rgba(251, 146, 60, 0.44); box-shadow: 0 0 30px rgba(245, 158, 11, 0.22); }}
      body[data-market-tone="bear"] .index-card.highlight {{ background: rgba(14, 165, 233, 0.20); border-color: rgba(16, 185, 129, 0.38); box-shadow: 0 0 30px rgba(14, 165, 233, 0.18); }}
      .index-name {{ font-size: 12px; opacity: 0.85; margin-bottom: 6px; font-weight: 600; }}
      .index-val {{ font-size: 20px; font-weight: 800; margin-bottom: 2px; }}
      .index-pct {{ font-size: 13px; font-weight: 700; }}
      .up {{ color: #fecaca !important; }}
      .down {{ color: #bbf7d0 !important; }}
      .flat {{ color: #fef08a !important; }}

      /* Card */
      .card {{
        background: var(--bg-card);
        border-radius: var(--radius-lg);
        padding: 24px;
        margin-bottom: 18px;
        box-shadow: var(--shadow-md);
        border: 1px solid var(--border);
        transition: background 0.3s, border-color 0.3s;
      }}
      .card-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }}
      .card-title {{
        display: flex; align-items: center; gap: 10px;
        font-size: 17px; font-weight: 800; color: var(--text-primary);
        margin-bottom: 10px;
      }}
      .card-title::before {{
        content: ""; display: inline-block;
        width: 4px; height: 20px;
        background: var(--primary); border-radius: 2px;
      }}
      .card-badge {{ font-size: 11px; padding: 4px 10px; border-radius: 20px; font-weight: 700; background: var(--bg-elevated); color: var(--text-muted); }}

      /* Panorama */
      .panorama-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }}
      @media (max-width: 500px) {{ .panorama-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
      .panorama-box {{ text-align: center; padding: 18px 10px; border-radius: var(--radius-md); background: var(--bg-elevated); transition: all 0.2s; border: 1px solid transparent; }}
      .panorama-box:hover {{ transform: translateY(-2px); border-color: var(--primary); box-shadow: 0 4px 14px var(--theme-glow); }}
      .panorama-box.pulse {{ animation: boxPulse 2s ease-in-out; }}
      @keyframes boxPulse {{ 0%, 100% {{ box-shadow: none; }} 50% {{ box-shadow: 0 0 22px var(--theme-glow); }} }}
      .panorama-num {{ font-size: 30px; font-weight: 900; line-height: 1.1; margin-bottom: 6px; }}
      .panorama-label {{ font-size: 12px; color: var(--text-muted); font-weight: 600; }}

      /* Volume */
      .volume-info-box {{ background: var(--bg-elevated); border-radius: var(--radius-md); padding: 20px; display: flex; align-items: center; gap: 20px; margin-bottom: 20px; border: 1px solid var(--border); }}
      .volume-icon-circle {{ width: 48px; height: 48px; background: var(--bg-card); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 22px; box-shadow: var(--shadow-sm); flex-shrink: 0; }}
      .volume-main-val {{ flex: 1; }}
      .volume-label-row {{ display: flex; gap: 12px; font-size: 13px; color: var(--text-muted); margin-bottom: 4px; font-weight: 600; }}
      .volume-data-row {{ display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }}
      .volume-total {{ font-size: 26px; font-weight: 900; color: var(--text-primary); }}
      .volume-change {{ font-size: 16px; font-weight: 800; }}
      .volume-increase {{ font-size: 14px; font-weight: 600; }}
      .insight-banner {{ display: grid; grid-template-columns: 120px 1fr auto; gap: 18px; align-items: center; padding: 16px 18px; border-radius: var(--radius-md); background: linear-gradient(135deg, var(--theme-soft), rgba(255,255,255,0.02)); border: 1px solid var(--theme-glow); margin-top: 16px; }}
      .insight-score {{ display: flex; align-items: baseline; justify-content: center; gap: 4px; }}
      .insight-score-num {{ font-size: 34px; line-height: 1; font-weight: 900; color: var(--primary); }}
      .insight-score-unit {{ font-size: 12px; font-weight: 700; color: var(--text-muted); }}
      .insight-title {{ font-size: 15px; font-weight: 800; color: var(--text-primary); }}
      .insight-desc {{ margin-top: 4px; font-size: 12px; color: var(--text-secondary); line-height: 1.7; }}
      .insight-side {{ text-align: right; }}
      .insight-chip {{ display: inline-flex; align-items: center; padding: 6px 12px; border-radius: 999px; font-size: 11px; font-weight: 800; background: var(--theme-chip-bg); color: var(--theme-chip-text); border: 1px solid var(--theme-glow); }}
      .insight-side-note {{ margin-top: 8px; font-size: 11px; color: var(--text-muted); font-weight: 700; }}
      .insight-meter {{ margin-top: 12px; height: 10px; border-radius: 999px; background: rgba(148, 163, 184, 0.16); overflow: hidden; }}
      .insight-meter-fill {{ height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--theme-accent-2) 0%, var(--theme-accent) 100%); }}
      .heatmap-shell {{ margin-top: 16px; }}
      .heatmap-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
      .heatmap-cell {{
        position: relative;
        min-height: 148px;
        border-radius: var(--radius-md);
        padding: 18px;
        border: 1px solid var(--border);
        overflow: hidden;
        display: flex;
        flex-direction: column;
        justify-content: flex-end;
        background: var(--bg-elevated);
        isolation: isolate;
      }}
      .heatmap-cell::before {{
        content: "";
        position: absolute;
        inset: 0;
        background:
          radial-gradient(circle at top right, rgba(255,255,255,0.35), transparent 34%),
          linear-gradient(135deg, rgba(255,255,255,0.18), transparent 55%);
        z-index: -1;
      }}
      .heatmap-cell.level-1 {{ background: linear-gradient(135deg, rgba(224, 242, 254, 0.88), rgba(248, 250, 252, 0.98)); }}
      .heatmap-cell.level-2 {{ background: linear-gradient(135deg, rgba(186, 230, 253, 0.92), rgba(240, 249, 255, 0.98)); }}
      .heatmap-cell.level-3 {{ background: linear-gradient(135deg, rgba(254, 240, 138, 0.82), rgba(255, 247, 237, 0.98)); }}
      .heatmap-cell.level-4 {{ background: linear-gradient(135deg, rgba(253, 186, 116, 0.86), rgba(255, 237, 213, 0.98)); }}
      .heatmap-cell.level-5 {{ background: linear-gradient(135deg, rgba(252, 165, 165, 0.9), rgba(254, 226, 226, 0.98)); }}
      [data-theme="dark"] .heatmap-cell.level-1 {{ background: linear-gradient(135deg, rgba(14, 116, 144, 0.55), rgba(15, 23, 42, 0.92)); }}
      [data-theme="dark"] .heatmap-cell.level-2 {{ background: linear-gradient(135deg, rgba(3, 105, 161, 0.6), rgba(15, 23, 42, 0.92)); }}
      [data-theme="dark"] .heatmap-cell.level-3 {{ background: linear-gradient(135deg, rgba(161, 98, 7, 0.62), rgba(30, 41, 59, 0.94)); }}
      [data-theme="dark"] .heatmap-cell.level-4 {{ background: linear-gradient(135deg, rgba(194, 65, 12, 0.68), rgba(51, 65, 85, 0.94)); }}
      [data-theme="dark"] .heatmap-cell.level-5 {{ background: linear-gradient(135deg, rgba(185, 28, 28, 0.72), rgba(69, 10, 10, 0.92)); }}
      .heatmap-rank {{ position: absolute; top: 14px; right: 14px; font-size: 11px; font-weight: 800; color: rgba(15, 23, 42, 0.62); }}
      [data-theme="dark"] .heatmap-rank {{ color: rgba(241, 245, 249, 0.78); }}
      .heatmap-title {{ font-size: 12px; font-weight: 800; color: var(--text-muted); margin-bottom: 8px; }}
      .heatmap-value {{ font-size: 30px; line-height: 1.1; font-weight: 900; color: var(--text-primary); }}
      .heatmap-note {{ margin-top: 8px; font-size: 11px; line-height: 1.6; color: var(--text-secondary); max-width: 88%; }}
      .heatmap-legend {{
        display: flex;
        align-items: center;
        gap: 12px;
        margin-top: 12px;
        font-size: 11px;
        color: var(--text-muted);
        font-weight: 700;
      }}
      .heatmap-legend-bar {{
        flex: 1;
        height: 10px;
        border-radius: 999px;
        background: linear-gradient(90deg, #bae6fd 0%, #fef08a 50%, #fca5a5 100%);
        border: 1px solid rgba(148, 163, 184, 0.18);
      }}

      /* Effect Grid */
      .effect-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }}
      @media (max-width: 600px) {{ .effect-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
      .effect-item {{ padding: 16px 12px; border-radius: var(--radius-md); text-align: center; border: 1px solid transparent; transition: all 0.2s; }}
      .effect-item:hover {{ transform: translateY(-2px); box-shadow: var(--shadow-md); }}
      .effect-item.yellow-bg {{ background: linear-gradient(135deg, #fffbeb, #fef3c7); }}
      .effect-item.blue-bg {{ background: linear-gradient(135deg, #eff6ff, #dbeafe); }}
      .effect-item.green-bg {{ background: linear-gradient(135deg, #ecfdf5, #d1fae5); }}
      .effect-item.red-bg {{ background: linear-gradient(135deg, #fef2f2, #fee2e2); }}
      body[data-market-tone="bull"] .effect-item.yellow-bg,
      body[data-market-tone="bull"] .effect-item.red-bg {{ background: linear-gradient(135deg, rgba(254, 226, 226, 0.96), rgba(253, 186, 116, 0.86)); border-color: rgba(239, 68, 68, 0.18); }}
      body[data-market-tone="bull"] .effect-item.blue-bg,
      body[data-market-tone="bull"] .effect-item.green-bg {{ background: linear-gradient(135deg, rgba(255, 237, 213, 0.92), rgba(254, 249, 195, 0.86)); border-color: rgba(249, 115, 22, 0.16); }}
      body[data-market-tone="bear"] .effect-item.yellow-bg,
      body[data-market-tone="bear"] .effect-item.red-bg {{ background: linear-gradient(135deg, rgba(220, 252, 231, 0.92), rgba(186, 230, 253, 0.84)); border-color: rgba(16, 185, 129, 0.18); }}
      body[data-market-tone="bear"] .effect-item.blue-bg,
      body[data-market-tone="bear"] .effect-item.green-bg {{ background: linear-gradient(135deg, rgba(224, 242, 254, 0.92), rgba(204, 251, 241, 0.84)); border-color: rgba(14, 165, 233, 0.16); }}
      [data-theme="dark"] .effect-item.yellow-bg {{ background: rgba(245, 158, 11, 0.15); }}
      [data-theme="dark"] .effect-item.blue-bg {{ background: rgba(37, 99, 235, 0.15); }}
      [data-theme="dark"] .effect-item.green-bg {{ background: rgba(16, 185, 129, 0.15); }}
      [data-theme="dark"] .effect-item.red-bg {{ background: rgba(239, 68, 68, 0.15); }}
      .effect-val {{ font-size: 22px; font-weight: 900; margin-bottom: 4px; }}
      .effect-label {{ font-size: 11px; color: var(--text-secondary); line-height: 1.4; font-weight: 600; }}

      /* Fear Grid */
      .fear-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 16px; }}
      @media (max-width: 500px) {{ .fear-grid {{ grid-template-columns: 1fr; }} }}
      .fear-card {{ background: var(--bg-elevated); border-radius: var(--radius-md); padding: 14px 10px; text-align: center; border: 1px solid var(--border); transition: all 0.2s; }}
      .fear-card:hover {{ border-color: var(--primary); transform: translateY(-1px); }}
      body[data-market-tone="bull"] .fear-card {{ box-shadow: inset 0 1px 0 rgba(255,255,255,0.25), 0 0 0 1px rgba(249, 115, 22, 0.05); }}
      body[data-market-tone="bear"] .fear-card {{ box-shadow: inset 0 1px 0 rgba(255,255,255,0.18), 0 0 0 1px rgba(14, 165, 233, 0.05); }}
      .fear-val {{ font-size: 20px; font-weight: 800; margin-bottom: 4px; }}
      .fear-label {{ font-size: 11px; color: var(--text-muted); font-weight: 700; }}
      .fear-note {{ font-size: 10px; color: var(--text-muted); margin-top: 4px; line-height: 1.3; }}

      /* Ladder Table */
      .ladder-table {{ width: 100%; border-collapse: separate; border-spacing: 0 6px; font-size: 13.5px; }}
      .ladder-table th {{ padding: 10px 12px; text-align: center; font-weight: 700; color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}
      .ladder-table td {{ padding: 12px 12px; background: var(--bg-elevated); text-align: center; vertical-align: middle; transition: background 0.2s; }}
      .ladder-table tr:hover td {{ background: var(--bg-card); }}
      .ladder-table tr td:first-child {{ border-radius: var(--radius-sm) 0 0 var(--radius-sm); }}
      .ladder-table tr td:last-child {{ border-radius: 0 var(--radius-sm) var(--radius-sm) 0; }}
      .ladder-badge {{ display: inline-block; padding: 4px 12px; border-radius: 8px; font-size: 12px; font-weight: 800; min-width: 45px; }}
      .badge-6 {{ background: linear-gradient(135deg, #fee2e2, #fecaca); color: #b91c1c; }}
      .badge-5 {{ background: linear-gradient(135deg, #fee2e2, #fecaca); color: #dc2626; }}
      .badge-4 {{ background: linear-gradient(135deg, #ffedd5, #fed7aa); color: #9a3412; }}
      .badge-3 {{ background: linear-gradient(135deg, #dcfce7, #bbf7d0); color: #15803d; }}
      .badge-2 {{ background: linear-gradient(135deg, #dbeafe, #bfdbfe); color: #1d4ed8; }}
      .badge-1 {{ background: var(--bg-elevated); color: var(--text-muted); }}
      [data-theme="dark"] .badge-6 {{ background: rgba(239, 68, 68, 0.2); color: #fca5a5; }}
      [data-theme="dark"] .badge-5 {{ background: rgba(239, 68, 68, 0.2); color: #fca5a5; }}
      [data-theme="dark"] .badge-4 {{ background: rgba(245, 158, 11, 0.2); color: #fcd34d; }}
      [data-theme="dark"] .badge-3 {{ background: rgba(16, 185, 129, 0.2); color: #86efac; }}
      [data-theme="dark"] .badge-2 {{ background: rgba(37, 99, 235, 0.2); color: #93c5fd; }}
      [data-theme="dark"] .badge-1 {{ background: rgba(148, 163, 184, 0.2); color: #94a3b8; }}
      .stock-name-cell {{ font-weight: 700; color: var(--text-primary); }}
      .ladder-steps {{ display: flex; flex-direction: column; gap: 12px; }}
      .ladder-step {{
        margin-left: var(--step-offset);
        background: linear-gradient(135deg, var(--bg-elevated), rgba(255,255,255,0.04));
        border: 1px solid var(--border);
        border-radius: var(--radius-md);
        padding: 14px 16px;
        box-shadow: var(--shadow-sm);
      }}
      .ladder-step-header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }}
      .ladder-step-count {{ font-size: 11px; color: var(--text-muted); font-weight: 800; }}
      .ladder-stock-list {{ display: flex; flex-wrap: wrap; gap: 10px; }}
      .ladder-stock-card {{
        min-width: 150px;
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 10px 12px;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.3);
      }}
      .ladder-stock-name {{ font-size: 13px; font-weight: 800; color: var(--text-primary); }}
      .ladder-stock-meta {{ display: flex; align-items: center; gap: 8px; margin-top: 6px; flex-wrap: wrap; }}
      .ladder-chip {{
        display: inline-flex;
        align-items: center;
        border-radius: 999px;
        font-size: 10px;
        font-weight: 800;
        background: rgba(148, 163, 184, 0.12);
        padding: 2px 8px;
      }}
      .ladder-chip-note {{ font-size: 10px; color: var(--text-muted); }}

      /* Hot Topic */
      .hot-topic {{ padding: 16px; border-radius: var(--radius-md); margin-bottom: 12px; border-left: 4px solid; transition: all 0.2s; }}
      .hot-topic:hover {{ transform: translateX(4px); }}
      .hot-topic.good {{ background: linear-gradient(135deg, var(--theme-soft), var(--bg-elevated)); border-color: var(--theme-accent); }}
      .hot-topic.caution {{ background: var(--bg-elevated); border-color: var(--warning); }}
      .hot-topic.fire {{ background: linear-gradient(135deg, var(--theme-soft), var(--bg-elevated)); border-color: var(--theme-accent-2); }}
      .topic-title {{ font-weight: 800; font-size: 14px; margin-bottom: 6px; display: flex; align-items: center; gap: 8px; color: var(--text-primary); }}
      .topic-desc {{ font-size: 13px; color: var(--text-secondary); line-height: 1.65; }}
      .topic-tag {{ display: inline-block; font-size: 10px; padding: 2px 10px; border-radius: 20px; font-weight: 800; margin-left: auto; }}
      .tag-sustained {{ background: #dcfce7; color: #166534; }}
      .tag-caution {{ background: #fef3c7; color: #92400e; }}
      .tag-fire {{ background: #fee2e2; color: #b91c1c; }}
      [data-theme="dark"] .tag-sustained {{ background: rgba(16, 185, 129, 0.2); color: #86efac; }}
      [data-theme="dark"] .tag-caution {{ background: rgba(245, 158, 11, 0.2); color: #fcd34d; }}
      [data-theme="dark"] .tag-fire {{ background: rgba(239, 68, 68, 0.2); color: #fca5a5; }}

      /* Sector List */
      .sector-list {{ list-style: none; }}
      .sector-item {{ display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-radius: var(--radius-md); margin-bottom: 8px; background: var(--bg-elevated); border: 1px solid transparent; transition: all 0.2s; }}
      .sector-item:hover {{ background: var(--bg-card); border-color: var(--primary); transform: translateX(4px); }}
      .sector-rank {{ width: 28px; height: 28px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 900; color: #fff; flex-shrink: 0; }}
      .rank-1 {{ background: linear-gradient(135deg, #fbbf24, #f59e0b); }}
      .rank-2 {{ background: linear-gradient(135deg, #94a3b8, #64748b); }}
      .rank-3 {{ background: linear-gradient(135deg, #d97706, #b45309); }}
      .rank-n {{ background: var(--bg-card); color: var(--text-muted); }}
      [data-theme="dark"] .rank-n {{ background: rgba(148, 163, 184, 0.2); }}
      .sector-info {{ flex: 1; margin-left: 14px; }}
      .sector-name {{ font-weight: 700; font-size: 14px; color: var(--text-primary); }}
      .sector-detail {{ font-size: 11px; color: var(--text-muted); margin-top: 2px; font-weight: 500; }}
      .sector-pct {{ font-size: 15px; font-weight: 800; min-width: 55px; text-align: right; }}

      /* Action List */
      .action-list {{ list-style: none; }}
      .action-item {{ display: flex; gap: 14px; padding: 14px 0; border-bottom: 1px solid var(--border); }}
      .action-item:last-child {{ border: none; }}
      .action-dot {{ width: 10px; height: 10px; border-radius: 50%; margin-top: 6px; flex-shrink: 0; }}
      .dot-key {{ background: var(--primary); box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15); }}
      .dot-risk {{ background: var(--danger); box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.15); }}
      .dot-watch {{ background: var(--warning); box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.15); }}
      .dot-safe {{ background: var(--success); box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.15); }}
      .action-text {{ font-size: 13.5px; color: var(--text-secondary); line-height: 1.65; font-weight: 500; }}

      /* Chart */
      .chart-container {{ width: 100%; height: 220px; margin-bottom: 16px; position: relative; }}
      .chart-legend {{ display: none; }} /* ECharts has its own legend or we use custom one */
      .radar-chart-container {{ width: 100%; height: 300px; }}
      .theme-trend-chart-container {{ width: 100%; height: 280px; margin-top: 12px; }}

      /* Verdict Box */
      .verdict-box {{ border-radius: var(--radius-md); padding: 18px; font-size: 13.5px; line-height: 1.75; margin-top: 14px; }}
      .verdict-warn {{ background: linear-gradient(135deg, #fffbeb, #fef3c7); color: #92400e; border: 1px solid #fde68a; }}
      .verdict-good {{ background: linear-gradient(135deg, #ecfdf5, #d1fae5); color: #166534; border: 1px solid #a7f3d0; }}
      .verdict-fire {{ background: linear-gradient(135deg, #fef2f2, #fee2e2); color: #b91c1c; border: 1px solid #fecaca; }}
      body[data-market-tone="bull"] .verdict-good {{ background: linear-gradient(135deg, rgba(254, 226, 226, 0.96), rgba(253, 186, 116, 0.92)); color: #9a3412; border-color: rgba(249, 115, 22, 0.30); }}
      body[data-market-tone="mixed"] .verdict-warn {{ background: linear-gradient(135deg, rgba(255, 247, 237, 0.96), rgba(254, 215, 170, 0.88)); color: #9a3412; border-color: rgba(245, 158, 11, 0.30); }}
      body[data-market-tone="bear"] .verdict-fire {{ background: linear-gradient(135deg, rgba(220, 252, 231, 0.94), rgba(186, 230, 253, 0.88)); color: #0f766e; border-color: rgba(14, 165, 233, 0.28); }}
      [data-theme="dark"] .verdict-warn {{ background: rgba(245, 158, 11, 0.15); border-color: rgba(245, 158, 11, 0.3); }}
      [data-theme="dark"] .verdict-good {{ background: rgba(16, 185, 129, 0.15); border-color: rgba(16, 185, 129, 0.3); }}
      [data-theme="dark"] .verdict-fire {{ background: rgba(239, 68, 68, 0.15); border-color: rgba(239, 68, 68, 0.3); }}
      .verdict-box strong {{ font-size: 14px; display: block; margin-bottom: 4px; }}

      /* Summary Box */
      .summary-box {{ 
        background: var(--bg-elevated); 
        border-radius: var(--radius-md); 
        padding: 18px 20px; 
        border-left: 5px solid var(--theme-accent); 
        margin-top: 16px; 
        box-shadow: inset 0 0 10px rgba(0,0,0,0.02);
      }}
      .summary-text {{ 
        font-size: 14.5px; 
        color: var(--text-primary); 
        line-height: 1.85; 
        font-weight: 500; 
      }}
      .summary-highlight {{ 
        color: var(--theme-accent); 
        font-weight: 800; 
        padding: 0 2px;
      }}
      .summary-footer {{ 
        display: flex; 
        justify-content: flex-end; 
        align-items: center; 
        gap: 8px; 
        margin-top: 12px; 
        opacity: 0.45; 
        font-size: 11px; 
        font-weight: 700;
        color: var(--text-secondary);
      }}

      /* Section Header */
      .section-header {{ font-size: 12px; font-weight: 800; color: var(--text-muted); margin: 16px 0 10px; padding-left: 10px; border-left: 3px solid var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }}
      .hero-note {{ margin-top: 8px; font-size: 12px; color: rgba(255,255,255,0.86); font-weight: 600; }}
      .tier-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
      .tier-card {{ background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 14px 16px; }}
      .tier-label {{ font-size: 11px; font-weight: 800; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 8px; }}
      .tier-title {{ font-size: 14px; font-weight: 800; color: var(--text-primary); line-height: 1.5; }}
      .tier-desc {{ margin-top: 6px; font-size: 12px; color: var(--text-secondary); line-height: 1.6; }}
      .red-text {{ color: var(--danger); }}
      .green-text {{ color: var(--success); }}
      .orange-text {{ color: var(--warning); }}
      .blue-text {{ color: var(--primary); }}
      .purple-text {{ color: var(--purple); }}

      /* Footer */
      .footer {{ text-align: center; padding: 32px 20px; color: var(--text-muted); font-size: 12px; font-weight: 500; }}
      .footer p {{ margin-bottom: 4px; }}

      @media (max-width: 600px) {{
        .hero {{ padding: 24px 20px; }}
        .hero-date {{ font-size: 22px; }}
        .card {{ padding: 18px 16px; }}
        .volume-info-box {{ flex-direction: column; text-align: center; }}
        .insight-banner {{ grid-template-columns: 1fr; text-align: center; }}
        .insight-side {{ text-align: center; }}
        .heatmap-grid {{ grid-template-columns: 1fr; }}
        .index-card {{ min-width: 100px; }}
        .index-val {{ font-size: 18px; }}
        .ladder-step {{ margin-left: 0 !important; }}
        .ladder-stock-card {{ min-width: 100%; }}
      }}

      @media print {{ .theme-toggle {{ display: none; }} body {{ background: #fff; color: #000; }} .card {{ box-shadow: none; border: 1px solid #e2e8f0; }} }}
    </style>
  </head>
  <body data-market-tone="{market_tone}">
    <div class="container" id="app" v-cloak>
      <!-- Hero -->
      <div class="hero">
        <div class="hero-controls">
          <button class="theme-toggle" id="themeToggleBtn" onclick="toggleTheme()">🌙 深色</button>
        </div>
        <div class="hero-top">
          <div class="cycle-tag"><span class="cycle-dot"></span>短线复盘 · 情绪监控</div>
          <div class="hero-date">{DATE.replace('-', '年', 1).replace('-', '月', 1)}收盘简报</div>
          <div class="hero-subtitle">数据来源：实时API | 自动生成报告</div>
          {'<div class="hero-note">⚠️ ' + DATE_NOTE + '</div>' if DATE_NOTE else ''}
        </div>
        <div class="index-row">
          <div v-for="(idx, i) in marketData.indices" :key="i" :class="idx.highlight ? 'index-card highlight' : 'index-card'">
            <div class="index-name">{{{{ idx.name }}}}</div>
            <div class="index-val">{{{{ idx.val }}}}</div>
            <div class="index-pct" :class="indexChgClass(idx.chg)">{{{{ indexChgIcon(idx.chg) }}}} {{{{ idx.chg }}}}</div>
          </div>
        </div>
      </div>

      <!-- 市场全景 -->
      <div class="card">
        <div class="card-header"><div class="card-title">市场全景</div><div class="card-badge">非ST股</div></div>
        <div class="panorama-grid">
          <div class="panorama-box pulse">
            <div class="panorama-num red-text">{{{{ marketData.panorama.limitUp }}}}</div>
            <div class="panorama-label">涨停</div>
          </div>
          <div class="panorama-box">
            <div class="panorama-num orange-text">{{{{ marketData.panorama.broken }}}}</div>
            <div class="panorama-label">炸板</div>
          </div>
          <div class="panorama-box">
            <div class="panorama-num green-text">{{{{ marketData.panorama.limitDown }}}}</div>
            <div class="panorama-label">跌停</div>
          </div>
          <div class="panorama-box">
            <div class="panorama-num" :class="boardRateClass(marketData.panorama.ratio)">{{{{ marketData.panorama.ratio }}}}</div>
            <div class="panorama-label">封板率</div>
          </div>
        </div>
{sentiment_html}
        <div class="section-header">情绪生态指标</div>
        <div class="verdict-box" :class="'verdict-' + marketData.moodStage.type" style="margin-bottom: 14px;">
          <strong>🧭 情绪阶段：{{{{ marketData.moodStage.title }}}}</strong>
          {{{{ marketData.moodStage.detail }}}}
        </div>
        <div class="fear-grid">
          <div class="fear-card" v-for="(card, idx) in marketData.moodCards" :key="'mood-'+idx">
            <div class="fear-val" :class="card.valueClass">{{{{ card.value }}}}</div>
            <div class="fear-label">{{{{ card.label }}}}</div>
            <div class="fear-note">{{{{ card.note }}}}</div>
          </div>
        </div>
      </div>

      <!-- 短线结构拆解 -->
      <div class="card">
        <div class="card-title">短线结构拆解</div>
        <div class="section-header">涨停结构</div>
        <div class="fear-grid">
{structure_grid_html}
        </div>
        <div class="section-header">高位风险</div>
        <div class="fear-grid">
{risk_grid_html}
        </div>
        <div class="section-header">高低切换偏好</div>
        <div class="fear-grid">
{rotation_grid_html}
        </div>
        <div class="section-header">主线 / 支线 / 轮动线</div>
        <div class="tier-grid">
{tier_cards_html}
        </div>
      </div>

      <!-- 市场量能 -->
      <div class="card">
        <div class="card-header"><div class="card-title">市场量能</div></div>
        <div class="volume-info-box">
          <div class="volume-icon-circle">⇄</div>
          <div class="volume-main-val">
            <div class="volume-label-row"><span>沪深合计 · 实际量能</span><span>较昨日</span></div>
            <div class="volume-data-row">
              <span class="volume-total" id="volTotal">{today_total_vol:.2f}亿</span>
              <span class="volume-change {pct_class(vol_chg_pct)}" id="volChange">{vol_chg_pct:+.2f}%</span>
              <span class="volume-increase orange-text" id="volIncrease">{volume_shift['detail']}</span>
            </div>
          </div>
        </div>

        <div class="chart-container">
          <div id="volume-trend-echart" style="width: 100%; height: 100%;"></div>
        </div>

        <div class="section-header">资金抱团度</div>
        <div class="fear-grid">
{capital_grid_html}
        </div>

        <div class="summary-box">
          <div class="summary-text" id="summaryText">{summary_text}</div>
          
        </div>
      </div>

      <!-- 赚钱效应四维判断 -->
      <div class="card">
        <div class="card-title">赚钱效应综合判断</div>
        <div class="verdict-box verdict-{effect_verdict_type}" id="effectVerdict">
          <strong>{effect_verdict_title}</strong>
          {effect_verdict_detail}
        </div>
        <div class="section-header">接力承接质量</div>
        <div class="fear-grid">
{relay_grid_html}
        </div>
        <div class="section-header">昨日强势股反馈</div>
        <div class="fear-grid">
{yesterday_review_grid_html}
        </div>
        <div class="section-header">昨日强势股四象限反馈</div>
        <div class="fear-grid">
{quadrant_feedback_html}
        </div>
        <div class="section-header">情绪热力图</div>
        <div class="heatmap-shell">
          <div class="heatmap-grid">
{heatmap_cells_html}
          </div>
          <div class="heatmap-legend">
            <span>低热度</span>
            <div class="heatmap-legend-bar"></div>
            <span>高热度</span>
          </div>
        </div>
      </div>

      <!-- 恐惧指标 -->
      <div class="card">
        <div class="card-title">恐惧指标 & 赚钱效应量化</div>

        <div class="section-header">大面股 / 核按钮</div>
        <div class="fear-grid">
{fear_grid1}
        </div>

        <div class="section-header">炸板率 & 昨涨停表现</div>
        <div class="fear-grid">
{fear_grid2}
        </div>
        <div class="section-header">炸板结构拆解</div>
        <div class="fear-grid">
{broken_structure_grid_html}
        </div>
      </div>

      <!-- 今日热点板块解读 -->
      <div class="card">
        <div class="card-title">今日热点板块解读</div>
{topics_html}
        <div class="section-header">主线集中度</div>
        <div class="fear-grid">
{theme_focus_grid_html}
        </div>
        <div class="section-header">板块内部梯队</div>
        <div class="tier-grid">
{theme_profile_cards_html}
        </div>
        <div class="section-header">主线题材近5日持续性</div>
        <div class="tier-grid">
{theme_trend_cards_html}
        </div>
        <div class="theme-trend-chart-container">
          <div id="theme-trend-echart" style="width: 100%; height: 100%;"></div>
        </div>
      </div>

      <!-- 风格雷达图 -->
      <div class="card">
        <div class="card-title">市场风格雷达</div>
        <div class="radar-chart-container">
          <div id="style-radar-echart" style="width: 100%; height: 100%;"></div>
        </div>
      </div>

      <!-- 近7日高度趋势 -->
      <div class="card">
        <div class="card-title">近7日高度趋势</div>
        <div class="chart-container" style="height: 260px;">
          <div id="height-trend-echart" style="width: 100%; height: 100%;"></div>
        </div>
      </div>

      <!-- 连板天梯 -->
      <div class="card">
        <div class="card-header"><div class="card-title">连板天梯</div><div class="card-badge">非ST</div></div>
        <div class="ladder-steps" id="ladderBody">
{ladder_steps_html}
        </div>
        <div style="margin-top: 12px; padding: 10px 14px; background: rgba(239, 68, 68, 0.08); border-radius: var(--radius-sm); font-size: 12px; color: var(--danger); font-weight: 600" id="brokenList">
          {broken_text}
        </div>
      </div>

      <!-- 板块强度TOP5 -->
      <div class="card">
        <div class="card-title">板块强度 TOP5</div>
        <ul class="sector-list">
          <li class="sector-item" v-for="sec in marketData.sectors" :key="sec.rank">
            <span :class="sec.rank <= 3 ? ('sector-rank rank-' + sec.rank) : 'sector-rank rank-n'">{{{{ sec.rank }}}}</span>
            <div class="sector-info">
              <div class="sector-name">{{{{ sec.name }}}}</div>
              <div class="sector-detail">{{{{ sec.detail }}}}</div>
            </div>
            <div class="sector-pct" :style="'color: var(--' + sec.eval_color + ')'">{{{{ sec.eval }}}}</div>
          </li>
        </ul>
      </div>

      <!-- 题材归因（涨停/炸板/强势 三视角） -->
      <div class="card">
        <div class="card-title">题材归因</div>
        <div class="tier-grid">
          <div class="tier-card">
            <div class="tier-label">涨停主线 TOP3</div>
            <div v-for="(t, i) in marketData.themePanels.ztTop" :key="'zt-'+i" style="margin-top:8px;">
              <div class="tier-title">{{{{ t.name }}}} <span style="color:var(--text-muted);font-size:12px;">({{{{ t.count }}}}只)</span></div>
              <div class="tier-desc">{{{{ t.examples }}}}</div>
            </div>
          </div>
          <div class="tier-card">
            <div class="tier-label">炸板主杀 TOP3</div>
            <div v-for="(t, i) in marketData.themePanels.zbTop" :key="'zb-'+i" style="margin-top:8px;">
              <div class="tier-title">{{{{ t.name }}}} <span style="color:var(--text-muted);font-size:12px;">({{{{ t.count }}}}只)</span></div>
              <div class="tier-desc">{{{{ t.examples }}}}</div>
            </div>
          </div>
          <div class="tier-card">
            <div class="tier-label">跌停风险 TOP3</div>
            <div v-for="(t, i) in marketData.themePanels.dtTop" :key="'dt-'+i" style="margin-top:8px;">
              <div class="tier-title">{{{{ t.name }}}} <span style="color:var(--text-muted);font-size:12px;">({{{{ t.count }}}}只)</span></div>
              <div class="tier-desc">{{{{ t.examples }}}}</div>
            </div>
          </div>
        </div>
        <div style="margin-top:12px;">
          <div style="font-weight:800; margin-bottom:8px;">题材强度（涨停/炸板/跌停 + 净强度）</div>
          <table class="ladder-table">
            <thead>
              <tr>
                <th>题材</th>
                <th>涨停</th>
                <th>炸板</th>
                <th>跌停</th>
                <th>净强度</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, idx) in marketData.themePanels.strengthRows" :key="'ts-'+idx">
                <td class="stock-name-cell">{{{{ r.name }}}}</td>
                <td>{{{{ r.zt }}}}</td>
                <td>{{{{ r.zb }}}}</td>
                <td>{{{{ r.dt }}}}</td>
                <td :class="r.netClass">{{{{ r.net }}}}</td>
              </tr>
            </tbody>
          </table>
          <div style="margin-top:8px; font-size:12px; color: var(--text-muted);">
            说明：净强度 = 涨停*1.0 - 炸板*0.7 - 跌停*1.2（参数可后续迭代）。
          </div>
        </div>
        <div class="summary-box" style="margin-top: 12px;">
          <div class="summary-text">
            🔎 主线/杀跌重叠度：<span class="summary-highlight">{{{{ marketData.themePanels.overlap.score }}}}</span>
            <span style="color:var(--text-muted);font-size:12px;">（{{{{ marketData.themePanels.overlap.themes.join('、') || '无' }}}}）</span>
            <div style="margin-top:6px;color:var(--text-muted);font-size:12px;">{{{{ marketData.themePanels.overlap.note }}}}</div>
          </div>
        </div>
      </div>

      <!-- 成交额TOP10 -->
      <div class="card">
        <div class="card-title">成交额 TOP10</div>
        <table class="ladder-table">
          <thead><tr><th>#</th><th>个股</th><th>涨幅</th><th>成交额</th><th>板块</th></tr></thead>
          <tbody>
            <tr v-for="row in marketData.top10" :key="row.rank">
              <td><span :style="'color: var(--danger); font-weight: ' + row.weight">{{{{ row.rank }}}}</span></td>
              <td class="stock-name-cell">{{{{ row.mc }}}}</td>
              <td :class="row.pct_class">{{{{ row.zf_str }}}}</td>
              <td :style="'font-weight: ' + row.weight">{{{{ row.cje_yi }}}}</td>
              <td>{{{{ row.sector }}}}</td>
            </tr>
          </tbody>
        </table>
        <div style="margin-top: 10px; font-size: 12px; color: var(--text-muted)">
          TOP5合计：<strong style="color: var(--text-primary)">{{{{ marketData.top10Summary.top5_sum_yi }}}}</strong>
          | {{{{ marketData.top10Summary.top5_sectors }}}}
        </div>
      </div>

      <!-- 明日行动指南 -->
      <div class="card">
        <div class="card-title">明日行动指南</div>
        <ul class="action-list">
          <li class="action-item" v-for="(item, idx) in marketData.actionGuide" :key="idx">
            <span class="action-dot" :class="item.dot_class"></span>
            <span class="action-text" :style="item.style">
              <strong>{{{{ item.strong_text }}}}</strong>
              {{{{ item.text }}}}
            </span>
          </li>
        </ul>
      </div>

      <div class="footer">
        <p>📊 生成时间：{DATE} 收盘{' · 自动回退交易日' if DATE_NOTE else ''}</p>
        <p>数据来源：风中一刀的主升浪丨</p>
        <p>K线为王 · 数据即事实 · 零ST · 不编造不猜测</p>
      </div>
    </div>

    <script>
      // 核心数据对象
      const marketData = {{
        date: "{DATE}",
        dateNote: "{DATE_NOTE}",
        indices: [
          {{ name: "{indices_data[0]['name']}", val: "{indices_data[0]['close']:.2f}", chg: "{indices_data[0]['pct']:+.2f}%", up: {"true" if indices_data[0]["pct"] >= 0 else "false"} }},
          {{ name: "{indices_data[1]['name']}", val: "{indices_data[1]['close']:.2f}", chg: "{indices_data[1]['pct']:+.2f}%", up: {"true" if indices_data[1]["pct"] >= 0 else "false"} }},
          {{ name: "{indices_data[2]['name']}", val: "{indices_data[2]['close']:.2f}", chg: "{indices_data[2]['pct']:+.2f}%", up: {"true" if indices_data[2]["pct"] >= 0 else "false"}, highlight: {"true" if indices_data[2]["pct"] > 2 else "false"} }},
        ],
        panorama: {{ limitUp: {zt_count}, broken: {zb_count}, limitDown: {dt_count}, ratio: "{fb_rate:.1f}%" }},
        mood: {{ heat: {heat_score}, risk: {risk_score}, score: {sentiment_score} }},
        volume: {{
          total: "{today_total_vol:.2f}亿",
          change: "{vol_chg_pct:+.2f}%",
          increase: "{volume_shift['detail']}",
          dates: [{','.join(['"'+v['date']+'"' for v in vol_history])}],
          values: [{','.join([str(round(v['vol'],2)) for v in vol_history])}],
        }},
        effect: {{
          ratio: "{effect_ratio_val}",
          ratioDetail: "{effect_ratio_detail}",
          prop: "{effect_prop_val}",
          propDetail: "{effect_prop_detail}",
          ladder: "{effect_ladder_val}",
          ladderDetail: "{effect_ladder_detail}",
          limit: "{limit_ratio}",
          limitDetail: "{limit_ratio_detail}",
          verdict: "{effect_verdict_title}",
          verdictDetail: "{effect_verdict_detail}",
          verdictType: "{effect_verdict_type}",
        }},
        fear: {{
          bigFace: "{bf_count}只",
          bigFaceNote: "{bf_names}",
          limitDown: "{dt_count}只",
          limitDownNote: "{dt_names}",
          risk: "{fear_risk}",
          broken: "{zb_rate:.1f}%",
          brokenNote: "{zb_count}/({zt_count}+{zb_count})={zb_rate:.1f}%",
          success: "{fb_rate:.1f}%",
          successNote: "封板质量{'极高' if fb_rate>=80 else ('尚可' if fb_rate>=70 else '偏低')}",
          yesterday: "{yesterday_perf}",
        }},
        styleRadar: {{
          indicators: ["连板接力", "低位试错", "20cm弹性", "题材集中", "资金抱团", "高位博弈"],
          values: [{relay_strength}, {low_trial_strength}, {elastic_strength}, {theme_focus_strength}, {capital_focus_strength}, {high_game_strength}],
          palette: [{','.join(['"'+c+'"' for c in chart_palette])}],
        }},
        themeTrend: {{
          dates: [{','.join(['"'+d+'"' for d in theme_trend['dates']])}],
          palette: [{','.join(['"'+c+'"' for c in chart_palette])}],
          series: [
{theme_trend_series_js}
          ]
        }},
        heightTrend: {{
          dates: [{','.join(['"'+d+'"' for d in height_trend['dates']])}],
          main: [{','.join(str(x) for x in height_trend['main'])}],
          sub: [{','.join(str(x) for x in height_trend['sub'])}],
          gem: [{','.join(str(x) for x in height_trend['gem'])}],
          palette: [{','.join(['"'+c+'"' for c in chart_palette])}],
          labels: {{
            main: [{','.join(['"'+l+'"' for l in height_trend['labels_main']])}],
            sub: [{','.join(['"'+l+'"' for l in height_trend['labels_sub']])}],
            gem: [{','.join(['"'+l+'"' for l in height_trend['labels_gem']])}],
          }},
        }},
        ladder: [
{ladder_rows_js}
        ],
        broken: "{broken_text.replace('❌ 昨日断板：','').replace('✅ 昨日无断板','')}",
        sectors: {sectors_json},
        top10: {top10_rows_json},
        top10Summary: {top10_summary_json},
        actionGuide: {action_guide_json},
        moodStage: {mood_stage_json},
        moodCards: {mood_cards_json},
        themePanels: {theme_panels_json},
      }};

      /**
       * Vue 应用：只负责把 marketData 渲染到 DOM（列表 / 表格 / 行动指南）
       * 说明：图表仍由原有 ECharts 函数渲染，避免一次性改动过大。
       */
      const mountVueApp = () => {{
        if (!window.Vue) return;
        const {{ createApp }} = window.Vue;

        createApp({{
          data() {{
            return {{ marketData }};
          }},
          methods: {{
            /**
             * 纯函数：根据涨跌幅字符串（如 +1.23%）返回样式类名
             */
            indexChgClass(chgStr) {{
              const v = Number(String(chgStr).replace('%', ''));
              if (v > 0) return 'up';
              if (v < 0) return 'down';
              return 'flat';
            }},
            /**
             * 纯函数：根据涨跌幅字符串返回箭头图标
             */
            indexChgIcon(chgStr) {{
              const v = Number(String(chgStr).replace('%', ''));
              if (v > 0) return '📈';
              if (v < 0) return '📉';
              return '⏺';
            }},
            /**
             * 纯函数：根据封板率（如 78.0%）返回对应色彩类名（与 Python get_board_rate_class 保持一致）
             */
            boardRateClass(rateStr) {{
              const v = Number(String(rateStr).replace('%', ''));
              if (v >= 75) return 'red-text';
              if (v >= 60) return 'orange-text';
              return 'green-text';
            }},
          }},
        }}).mount('#app');
      }};

      // 核心图表实例
      let volumeChart, heightChart, styleChart, themeTrendChart;

      /**
       * 渲染量能趋势图 (ECharts 实现)
       * @param {{Object}} data 量能数据
       */
      const renderVolumeTrend = (data) => {{
        const chartDom = document.getElementById('volume-trend-echart');
        if (!chartDom) return;
        if (volumeChart) volumeChart.dispose();
        volumeChart = echarts.init(chartDom, document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : null);
        
        const vals = data.values.map(v => Number(v));
        const isUp = (i) => i === 0 || vals[i] >= vals[i-1];
        const themeTone = document.body.getAttribute('data-market-tone') || 'mixed';
        const trendColor = themeTone === 'bull' ? '#ef4444' : (themeTone === 'bear' ? '#0ea5e9' : '#f59e0b');
        
        const option = {{
          backgroundColor: 'transparent',
          tooltip: {{ 
            trigger: 'axis', 
            axisPointer: {{ type: 'shadow' }},
            formatter: (params) => {{
              let res = `<div style="font-weight:800;margin-bottom:4px">${{params[0].name}}</div>`;
              params.forEach(p => {{
                res += `<div style="display:flex;justify-content:space-between;gap:12px;font-size:12px">
                  <span>${{p.seriesName}}</span>
                  <span style="font-weight:800;color:${{p.color}}">${{p.value.toFixed(0)}}亿</span>
                </div>`;
              }});
              return res;
            }}
          }},
          grid: {{ top: '15%', left: '3%', right: '3%', bottom: '15%', containLabel: true }},
          xAxis: {{
            type: 'category',
            data: data.dates,
            axisLine: {{ lineStyle: {{ color: 'var(--text-muted)' }} }},
            axisLabel: {{ color: 'var(--text-muted)', fontWeight: 700, fontSize: 10 }}
          }},
          yAxis: {{
            type: 'value',
            max: 40000,
            splitLine: {{ lineStyle: {{ type: 'dashed', color: 'var(--border)' }} }},
            axisLabel: {{ 
              color: 'var(--text-muted)', 
              fontWeight: 700, 
              fontSize: 10,
              formatter: (v) => v.toFixed(0)
            }}
          }},
          series: [
            {{
              name: '两市成交额',
              type: 'bar',
              label: {{
                show: true,
                position: 'top',
                formatter: (params) => params.value.toFixed(0),
                color: 'var(--text-muted)',
                fontWeight: 800,
                fontSize: 10
              }},
              data: vals.map((v, i) => ({{
                value: v,
                itemStyle: {{ color: isUp(i) ? '#ef4444' : '#10b981', borderRadius: [4, 4, 0, 0] }}
              }})),
              barWidth: '45%'
            }},
            {{
              name: '成交趋势',
              type: 'line',
              data: vals,
              smooth: true,
              showSymbol: false,
              lineStyle: {{ width: 3, color: trendColor }},
              areaStyle: {{
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                  {{ offset: 0, color: echarts.color.modifyAlpha(trendColor, 0.22) }},
                  {{ offset: 1, color: echarts.color.modifyAlpha(trendColor, 0.02) }}
                ])
              }}
            }}
          ]
        }};
        volumeChart.setOption(option);
      }};

      /**
       * 渲染高度趋势图 (ECharts 实现)
       * @param {{Object}} data 高度趋势数据
       */
      const renderHeightTrend = (data) => {{
        const chartDom = document.getElementById('height-trend-echart');
        if (!chartDom) return;
        if (heightChart) heightChart.dispose();
        heightChart = echarts.init(chartDom, document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : null);
        const colors = data.palette?.length ? data.palette : ['#ef4444', '#f59e0b', '#94a3b8'];

        const option = {{
          backgroundColor: 'transparent',
          tooltip: {{ trigger: 'axis' }},
          legend: {{
            data: ['最高板', '次高板', '创业板'],
            bottom: 0,
            textStyle: {{ color: 'var(--text-muted)', fontWeight: 600, fontSize: 11 }},
            icon: 'circle'
          }},
          grid: {{ top: '15%', left: '3%', right: '5%', bottom: '20%', containLabel: true }},
          xAxis: {{
            type: 'category',
            data: data.dates,
            boundaryGap: false,
            axisLine: {{ lineStyle: {{ color: 'var(--text-muted)' }} }},
            axisLabel: {{ color: 'var(--text-muted)', fontWeight: 700, fontSize: 10 }}
          }},
          yAxis: {{
            type: 'value',
            min: 0,
            max: 8,
            interval: 1,
            splitLine: {{ lineStyle: {{ type: 'dashed', color: 'var(--border)' }} }},
            axisLabel: {{ color: 'var(--text-muted)', fontWeight: 700, fontSize: 10 }}
          }},
          series: [
            {{
              name: '最高板',
              type: 'line',
              data: data.main,
              smooth: true,
              lineStyle: {{ width: 4, color: colors[0] }},
              itemStyle: {{ color: colors[0] }},
              areaStyle: {{
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                  {{ offset: 0, color: echarts.color.modifyAlpha(colors[0], 0.16) }},
                  {{ offset: 1, color: echarts.color.modifyAlpha(colors[0], 0.02) }}
                ])
              }},
              symbolSize: 8,
              label: {{
                show: true,
                position: 'top',
                formatter: (params) => data.labels.main[params.dataIndex] || '',
                color: colors[0],
                fontWeight: 800,
                fontSize: 10,
                backgroundColor: echarts.color.modifyAlpha(colors[0], 0.12),
                padding: [2, 4],
                borderRadius: 4,
                borderColor: colors[0],
                borderWidth: 0.5
              }}
            }},
            {{
              name: '次高板',
              type: 'line',
              data: data.sub,
              smooth: true,
              lineStyle: {{ width: 3, color: colors[1], type: 'dashed' }},
              itemStyle: {{ color: colors[1] }},
              symbolSize: 6,
              label: {{
                show: true,
                position: 'top',
                formatter: (params) => data.labels.sub[params.dataIndex] || '',
                color: colors[1],
                fontWeight: 800,
                fontSize: 10
              }}
            }},
            {{
              name: '创业板',
              type: 'line',
              data: data.gem,
              smooth: true,
              lineStyle: {{ width: 2, color: colors[2] }},
              itemStyle: {{ color: colors[2] }},
              symbolSize: 4,
              label: {{
                show: true,
                position: 'top',
                formatter: (params) => data.labels.gem[params.dataIndex] || '',
                color: colors[2],
                fontWeight: 800,
                fontSize: 10
              }}
            }}
          ]
        }};
        heightChart.setOption(option);
      }};

      /**
       * 渲染市场风格雷达图
       * @param {{Object}} data 风格数据
       */
      const renderStyleRadar = (data) => {{
        const chartDom = document.getElementById('style-radar-echart');
        if (!chartDom) return;
        if (styleChart) styleChart.dispose();
        styleChart = echarts.init(chartDom, document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : null);
        const colors = data.palette?.length ? data.palette : ['#2563eb', '#60a5fa'];

        const option = {{
          backgroundColor: 'transparent',
          tooltip: {{ trigger: 'item' }},
          radar: {{
            radius: '62%',
            splitNumber: 5,
            indicator: data.indicators.map(name => ({{ name, max: 100 }})),
            axisName: {{
              color: 'var(--text-primary)',
              fontSize: 12,
              fontWeight: 700
            }},
            splitArea: {{
              areaStyle: {{
                color: ['rgba(37, 99, 235, 0.03)', 'rgba(37, 99, 235, 0.06)']
              }}
            }},
            splitLine: {{ lineStyle: {{ color: 'rgba(148, 163, 184, 0.28)' }} }},
            axisLine: {{ lineStyle: {{ color: 'rgba(148, 163, 184, 0.28)' }} }}
          }},
          series: [
            {{
              name: '市场风格',
              type: 'radar',
              data: [
                {{
                  value: data.values,
                  areaStyle: {{ color: echarts.color.modifyAlpha(colors[0], 0.22) }},
                  lineStyle: {{ color: colors[0], width: 2.5 }},
                  itemStyle: {{ color: colors[0] }},
                  symbolSize: 6
                }}
              ]
            }}
          ]
        }};
        styleChart.setOption(option);
      }};

      /**
       * 渲染主线题材持续性图
       * @param {{Object}} data 题材趋势数据
       */
      const renderThemeTrend = (data) => {{
        const chartDom = document.getElementById('theme-trend-echart');
        if (!chartDom || !data?.series?.length) return;
        if (themeTrendChart) themeTrendChart.dispose();
        themeTrendChart = echarts.init(chartDom, document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : null);

        const colors = data.palette?.length ? data.palette : ['#ef4444', '#f59e0b', '#2563eb'];
        const option = {{
          backgroundColor: 'transparent',
          tooltip: {{ trigger: 'axis' }},
          legend: {{
            bottom: 0,
            textStyle: {{ color: 'var(--text-muted)', fontWeight: 700, fontSize: 11 }}
          }},
          grid: {{ top: '14%', left: '3%', right: '4%', bottom: '18%', containLabel: true }},
          xAxis: {{
            type: 'category',
            data: data.dates,
            axisLine: {{ lineStyle: {{ color: 'var(--text-muted)' }} }},
            axisLabel: {{ color: 'var(--text-muted)', fontWeight: 700, fontSize: 10 }}
          }},
          yAxis: {{
            type: 'value',
            minInterval: 1,
            splitLine: {{ lineStyle: {{ type: 'dashed', color: 'var(--border)' }} }},
            axisLabel: {{ color: 'var(--text-muted)', fontWeight: 700, fontSize: 10 }}
          }},
          series: data.series.map((item, index) => ({{
            name: item.name,
            type: 'line',
            data: item.values,
            smooth: true,
            symbolSize: 7,
            lineStyle: {{ width: 3, color: colors[index % colors.length] }},
            itemStyle: {{ color: colors[index % colors.length] }},
            areaStyle: index === 0 ? {{
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                {{ offset: 0, color: echarts.color.modifyAlpha(colors[index % colors.length], 0.18) }},
                {{ offset: 1, color: echarts.color.modifyAlpha(colors[index % colors.length], 0.02) }}
              ])
            }} : undefined
          }}))
        }};
        themeTrendChart.setOption(option);
      }};

      const updateThemeToggleLabel = () => {{
        const btn = document.getElementById("themeToggleBtn");
        if (!btn) return;
        const isDark = document.documentElement.getAttribute("data-theme") === "dark";
        const marketTone = document.body.getAttribute("data-market-tone") || "mixed";
        const toneText = marketTone === "bull" ? "强市暖色" : (marketTone === "bear" ? "弱市冷色" : "混合主题");
        btn.textContent = `${{isDark ? '☀️ 浅色' : '🌙 深色'}} · ${{toneText}}`;
      }};

      /**
       * 渲染连板天梯
       * @param {{Array}} data 天梯数据
       */
      const renderLadder = (data) => {{
        const container = document.getElementById("ladderBody");
        if (!container) return;

        const groups = [...data.reduce((acc, row) => {{
          const next = new Map(acc);
          const group = next.get(row.badge) || [];
          group.push(row);
          next.set(row.badge, group);
          return next;
        }}, new Map()).entries()].sort((a, b) => b[0] - a[0]);

        const maxBadge = groups.length ? groups[0][0] : 2;
        container.innerHTML = groups.map(([badge, rows]) => `
          <div class="ladder-step" style="--step-offset:${{(maxBadge - badge) * 28}}px;">
            <div class="ladder-step-header">
              <span class="ladder-badge ${{badge <= 6 ? `badge-${{badge}}` : 'badge-1'}}">${{badge}}板</span>
              <span class="ladder-step-count">${{rows.length}}只</span>
            </div>
            <div class="ladder-stock-list">
              ${{
                rows.map(row => `
                  <div class="ladder-stock-card">
                    <div class="ladder-stock-name">${{row.name}}</div>
                    <div class="ladder-stock-meta">
                      <span class="ladder-chip ${{row.status === "晋级" ? "green-text" : "blue-text"}}">${{row.status}}</span>
                      ${{row.note ? `<span class="ladder-chip-note">${{row.note}}</span>` : ''}}
                    </div>
                  </div>
                `).join('')
              }}
            </div>
          </div>
        `).join("");
      }};

      /**
       * 切换主题 (支持 ECharts 重新渲染)
       */
      const toggleTheme = () => {{
        const html = document.documentElement;
        const isDark = html.getAttribute("data-theme") === "dark";
        isDark ? html.removeAttribute("data-theme") : html.setAttribute("data-theme", "dark");
        updateThemeToggleLabel();
        
        // 重新初始化图表以适配主题
        renderVolumeTrend(marketData.volume);
        renderHeightTrend(marketData.heightTrend);
        renderStyleRadar(marketData.styleRadar);
        renderThemeTrend(marketData.themeTrend);
      }};

      document.addEventListener("DOMContentLoaded", () => {{
        mountVueApp();
        renderVolumeTrend(marketData.volume);
        renderHeightTrend(marketData.heightTrend);
        renderStyleRadar(marketData.styleRadar);
        renderThemeTrend(marketData.themeTrend);
        renderLadder(marketData.ladder);
        updateThemeToggleLabel();
        
        // 响应式处理
        window.addEventListener('resize', () => {{
          volumeChart && volumeChart.resize();
          heightChart && heightChart.resize();
          styleChart && styleChart.resize();
          themeTrendChart && themeTrendChart.resize();
        }});
      }});

    </script>
  </body>
</html>'''

os.makedirs(OUTPUT_DIR, exist_ok=True)
if KEEP_ONLY_LATEST_PER_DATE:
    cleanup_old_reports(OUTPUT_DIR, DATE, keep=0)

now = now_report()
output_filename = build_report_filename(DATE, now)
output_path = os.path.join(OUTPUT_DIR, output_filename)

# A 方案（模板外置）：优先用模板注入 marketData 生成最终 HTML，保证页面结构/样式不被业务代码污染
try:
    from pathlib import Path as _Path
    from daily_review.render.render_html import render_html_template

    template_path = _Path(__file__).resolve().parent / "templates" / "report_template.html"
    if not template_path.exists():
        raise FileNotFoundError(f"模板不存在: {template_path}")

    # 将各类 JSON 字符串恢复为 Python 对象，便于统一注入
    mood_stage = json.loads(mood_stage_json)
    mood_cards = json.loads(mood_cards_json)
    theme_panels = json.loads(theme_panels_json)
    sectors = json.loads(sectors_json)
    top10_rows = json.loads(top10_rows_json)
    top10_summary = json.loads(top10_summary_json)
    action_guide = json.loads(action_guide_json)

    # 在所有当日指标都计算完成后，再生成“昨日对比Δ”（避免前置计算时变量未定义）
    if prev_metrics:
        day_delta = {
            "date": prev_metrics.get("date"),
            "zt": zt_count - int(prev_metrics.get("zt", 0) or 0),
            "zb": zb_count - int(prev_metrics.get("zb", 0) or 0),
            "dt": dt_count - int(prev_metrics.get("dt", 0) or 0),
            "fb_rate": round(fb_rate - float(prev_metrics.get("fb_rate", 0) or 0), 1),
            "jj_rate": (round(jj_rate - float(prev_metrics.get("jj_rate", 0) or 0), 1) if "jj_rate" in prev_metrics else None),
            "zb_rate": round(zb_rate - float(prev_metrics.get("zb_rate", 0) or 0), 1),
            "zt_early_ratio": round(zt_early_ratio - float(prev_metrics.get("zt_early_ratio", 0) or 0), 1),
            "loss": ((bf_count + dt_count) - (int(prev_metrics.get("bf_count", 0) or 0) + int(prev_metrics.get("dt", 0) or 0)) if "bf_count" in prev_metrics else None),
            "top3_theme_ratio": round(top3_theme_ratio - float(prev_metrics.get("top3_theme_ratio", 0) or 0), 1) if "top3_theme_ratio" in prev_metrics else None,
            "max_lb": max_lb - int(prev_metrics.get("max_lb", 0) or 0) if "max_lb" in prev_metrics else None,
            "heat": round(heat_score - float(prev_metrics.get("heat", 0) or 0), 0) if "heat" in prev_metrics else None,
            "risk": round(risk_score - float(prev_metrics.get("risk", 0) or 0), 0) if "risk" in prev_metrics else None,
        }

    # 激进方案：把“趋势Δ”注入 mood_inputs，给情绪阶段提供“流”的信息（修复/转弱更早确认）
    # 说明：delta 来源于上一交易日缓存（market_data-YYYYMMDD.json），缺失则为 0/None
    mood_inputs.setdefault("mood_mode", _env("MOOD_MODE", "aggressive"))
    mood_inputs["delta_heat"] = float(day_delta.get("heat") or 0) if isinstance(day_delta, dict) else 0
    mood_inputs["delta_risk"] = float(day_delta.get("risk") or 0) if isinstance(day_delta, dict) else 0
    mood_inputs["delta_jj_rate"] = float(day_delta.get("jj_rate") or 0) if isinstance(day_delta, dict) else 0
    mood_inputs["delta_fb_rate"] = float(day_delta.get("fb_rate") or 0) if isinstance(day_delta, dict) else 0
    mood_inputs["delta_zt"] = int(day_delta.get("zt") or 0) if isinstance(day_delta, dict) else 0
    mood_inputs["delta_loss"] = float(day_delta.get("loss") or 0) if isinstance(day_delta, dict) else 0

    # 激进方案（增强）：引入最近 5~7 日“情绪流”趋势（上升/下降）
    # 你定义的核心：连板高度↑ + 封板成功率(fb_rate)↑ + 晋级承接(jj_rate)↑ ⇒ 上升周期
    try:
        hist_n = int(_env("MOOD_HIST_DAYS", "5") or "5")
    except Exception:
        hist_n = 5
    hist_n = max(3, min(hist_n, 10))

    def _snap_mood_style(date_str: str) -> dict:
        """
        纯函数（IO 读取除外）：从缓存 market_data 中抽取情绪关键指标。
        返回：{date, max_lb, fb_rate, jj_rate, broken_lb_rate}
        """
        if date_str == DATE:
            return {
                "date": DATE,
                "max_lb": int(max_lb or 0),
                "fb_rate": float(fb_rate or 0),
                "jj_rate": float(jj_rate_adj or jj_rate or 0),
                "broken_lb_rate": float(broken_lb_rate_adj or broken_lb_rate or 0),
            }
        snap = try_load_cached_market_data(date_str)
        if not snap:
            return {}
        fin = (snap.get("features") or {})
        mi = (fin.get("mood_inputs") or {})
        si = (fin.get("style_inputs") or {})
        return {
            "date": str(snap.get("date") or date_str),
            "max_lb": int(si.get("max_lb", 0) or 0),
            "fb_rate": float(mi.get("fb_rate", 0) or 0),
            "jj_rate": float(mi.get("jj_rate_adj", mi.get("jj_rate", 0)) or 0),
            "broken_lb_rate": float(mi.get("broken_lb_rate_adj", mi.get("broken_lb_rate", 0)) or 0),
        }

    # 用 keep_days（最近交易日）作为候选，确保日期序列是交易日序
    hist_days = [d for d in (keep_days or []) if isinstance(d, str)]
    if DATE not in hist_days:
        hist_days.append(DATE)
    hist_days = hist_days[-hist_n:]

    hist_rows = [r for r in (_snap_mood_style(d) for d in hist_days) if r]
    if len(hist_rows) >= 2:
        first, last = hist_rows[0], hist_rows[-1]
        trend_max_lb = float(last.get("max_lb", 0)) - float(first.get("max_lb", 0))
        trend_fb = float(last.get("fb_rate", 0)) - float(first.get("fb_rate", 0))
        trend_jj = float(last.get("jj_rate", 0)) - float(first.get("jj_rate", 0))
        trend_broken = float(last.get("broken_lb_rate", 0)) - float(first.get("broken_lb_rate", 0))
    else:
        trend_max_lb = trend_fb = trend_jj = trend_broken = 0.0

    mood_inputs["hist_days"] = [r.get("date") for r in hist_rows]
    mood_inputs["hist_max_lb"] = [int(r.get("max_lb", 0) or 0) for r in hist_rows]
    mood_inputs["hist_fb_rate"] = [round(float(r.get("fb_rate", 0) or 0), 1) for r in hist_rows]
    mood_inputs["hist_jj_rate"] = [round(float(r.get("jj_rate", 0) or 0), 1) for r in hist_rows]
    mood_inputs["hist_broken_lb_rate"] = [round(float(r.get("broken_lb_rate", 0) or 0), 1) for r in hist_rows]
    mood_inputs["trend_max_lb"] = round(trend_max_lb, 2)
    mood_inputs["trend_fb_rate"] = round(trend_fb, 2)
    mood_inputs["trend_jj_rate"] = round(trend_jj, 2)
    mood_inputs["trend_broken_lb_rate"] = round(trend_broken, 2)

    market_data = {
        "meta": {
            "generatedAt": now.strftime("%Y-%m-%d %H:%M:%S"),
            "asOf": {
                "indices": indices_fetch_at,
                "pools": pools_fetch_at if "pools_fetch_at" in globals() else "",
                "themes": themes_fetch_at if "themes_fetch_at" in globals() else "",
            },
            "source": {
                "indices": "hsindex/real/time",
                "pools": "ztgc/zbgc/dtgc/qsgc",
                "themes": "hszg/zg（题材归因，含本地缓存）",
            },
        },
        "date": DATE,
        "dateNote": DATE_NOTE,
        # 开发/模块化复用：存放各模块可复用的“中间特征”，用于部分更新（只重算某个模块）
        "features": {
            "chart_palette": chart_palette,
            "style_inputs": style_inputs,
            "mood_inputs": mood_inputs,
            "style_strengths": {
                **style_strengths
            },
        },
        "indices": [
            {
                "name": i["name"],
                "val": f'{i["close"]:.2f}',
                "chg": f'{i["pct"]:+.2f}%',
                "up": True,
                "highlight": (i.get("name") == "创业板指" and i.get("pct", 0) > 2),
            }
            for i in indices_data
        ],
        # 涨停池明细（用于“涨停个股数据分析”前端算法；只保留必要字段，避免文件过大）
        "ztgc": [
            {
                "dm": s.get("dm", ""),
                "mc": s.get("mc", ""),
                # 价格（元）
                "p": float(s.get("p", 0) or 0),
                "lbc": int(s.get("lbc", 1) or 1),
                "zf": float(s.get("zf", 0) or 0),
                # 成交额（元）
                "cje": float(s.get("cje", 0) or 0),
                # 流通市值/总市值（元）：用于“封单强度 = 封板资金 / 流通市值”一类算法
                "lt": float(s.get("lt", 0) or 0),
                "zsz": float(s.get("zsz", 0) or 0),
                "zj": float(s.get("zj", 0) or 0),
                "zbc": int(s.get("zbc", 0) or 0),
                "hs": float(s.get("hs", 0) or 0),
                # 首/末封板时间（HHmmss 或 HH:mm:ss）：用于识别“一字/强封/带动扩散”
                "fbt": s.get("fbt", ""),
                "lbt": s.get("lbt", ""),
                # 文本统计：x天y板（可选，用于展示/调试）
                "tj": s.get("tj", ""),
                "hy": s.get("hy", ""),
            }
            for s in (zt_all or [])
        ],
        # 个股->题材映射（key 使用涨停池原始 dm，便于前端直接匹配）
        "zt_code_themes": {
            str(s.get("dm", "")): fetch_stock_themes(normalize_stock_code(s.get("dm", "")))
            for s in (zt_all or [])
            if str(s.get("dm", "")).strip()
        },
        "panorama": {"limitUp": zt_count, "broken": zb_count, "limitDown": dt_count, "ratio": f"{fb_rate:.1f}%"},
        "mood": {"heat": heat_score, "risk": risk_score, "score": sentiment_score},
        "volume": {
            "total": f"{today_total_vol:.2f}亿",
            "change": f"{vol_chg_pct:+.2f}%",
            "increase": volume_shift["detail"],
            "dates": [v["date"] for v in vol_history],
            "values": [round(v["vol"], 2) for v in vol_history],
        },
        "effect": {
            "ratio": effect_ratio_val,
            "ratioDetail": effect_ratio_detail,
            "prop": effect_prop_val,
            "propDetail": effect_prop_detail,
            "ladder": effect_ladder_val,
            "ladderDetail": effect_ladder_detail,
            "limit": limit_ratio,
            "limitDetail": limit_ratio_detail,
            "verdict": effect_verdict_title,
            "verdictDetail": effect_verdict_detail,
            "verdictType": effect_verdict_type,
        },
        "fear": {
            "bigFace": f"{bf_count}只",
            "bigFaceNote": bf_names if bf_names else "无大面股",
            "limitDown": f"{dt_count}只",
            "limitDownNote": dt_names,
            "risk": fear_risk,
            "broken": f"{zb_rate:.1f}%",
            "brokenNote": f"{zb_count}/({zt_count}+{zb_count})={zb_rate:.1f}%",
            "success": f"{fb_rate:.1f}%",
            "successNote": f"封板质量{'极高' if fb_rate>=80 else ('尚可' if fb_rate>=70 else '偏低')}",
            "yesterday": yesterday_perf,
        },
        # 风格/轮动（用于页面“风格偏好/主线支线轮动线”动态渲染，避免写死）
        "rotation": {
            "style": rotation_style,
            "note": rotation_note,
            "highLevelRatio": round(high_level_ratio, 1),
        },
        # 主线/支线/轮动线分层（来自当日题材统计）
        "themeLayers": theme_layers,
        "styleRadar": {
            "indicators": ["连板接力", "低位试错", "20cm弹性", "题材集中", "资金抱团", "高位博弈"],
            "values": [relay_strength, low_trial_strength, elastic_strength, theme_focus_strength, capital_focus_strength, high_game_strength],
            "palette": chart_palette,
        },
        "themeTrend": {
            "dates": theme_trend["dates"],
            "palette": chart_palette,
            "series": [{"name": it["name"], "values": it["counts"]} for it in theme_trend.get("series", [])],
        },
        "heightTrend": {
            "dates": height_trend["dates"],
            "main": height_trend["main"],
            "sub": height_trend["sub"],
            "gem": height_trend["gem"],
            "palette": chart_palette,
            "labels": {"main": height_trend["labels_main"], "sub": height_trend["labels_sub"], "gem": height_trend["labels_gem"]},
        },
        "ladder": ladder_rows,
        "broken": broken_text.replace("❌ 昨日断板：", "").replace("✅ 昨日无断板", ""),
        "sectors": sectors,
        "top10": top10_rows,
        "top10Summary": top10_summary,
        "actionGuide": action_guide,
        "moodStage": mood_stage,
        "moodCards": mood_cards,
        "themePanels": theme_panels,
        "prev": prev_metrics,
        "delta": day_delta,
    }

    # 增强：为“龙头识别”补齐更强特征（严格一字识别）
    # 说明：
    # - 只对“候选池”做少量请求，避免 50+ 涨停股逐个拉日线导致请求爆炸
    # - 候选池筛选：封板资金(zj)更大 + 封板更早
    try:
        zt_rows = market_data.get("ztgc") or []

        def _key(s: dict) -> tuple:
            # 封板越早越优先；资金越大越优先
            fbt = str(s.get("fbt") or "235959")
            return (fbt, -float(s.get("zj") or 0))

        candidates = sorted(zt_rows, key=_key)[:15]
        ohlc_by_code = {}
        for s in candidates:
            code = str(s.get("dm") or "").strip()
            if not code:
                continue
            ohlc_by_code[code] = fetch_latest_daily_bar(code)

        market_data["features"].setdefault("leader_inputs", {})
        market_data["features"]["leader_inputs"]["ohlc_by_code"] = ohlc_by_code
    except Exception:
        market_data["features"].setdefault("leader_inputs", {})
        market_data["features"]["leader_inputs"].setdefault("ohlc_by_code", {})

    # 增强：龙头识别（大单一字点火 + 带动板块爆发）
    # 说明：输出写入 marketData.leaders，供模板/前端展示；算法实现见 daily_review/metrics/leader.py
    try:
        from daily_review.modules.leader import rebuild_leaders

        market_data.update(rebuild_leaders(market_data))
    except Exception:
        market_data.setdefault("leaders", [])

    render_html_template(
        template_path=template_path,
        output_path=_Path(output_path),
        market_data=market_data,
        report_date=DATE,
        date_note=DATE_NOTE,
    )

    # 产物缓存：给“部分更新”复用（不需要重跑全量抓取）
    cache_dir = _Path(__file__).resolve().parent / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    date_compact = DATE.replace("-", "")
    (_Path(cache_dir) / f"market_data-{date_compact}.json").write_text(
        json.dumps(market_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 缓存裁剪：market_data-*.json 只保留最近 CACHE_DAYS 个交易日（避免本地无限增长）
    try:
        keep_set = {str(d).replace("-", "") for d in (keep_days or [])}
        for fp in _Path(cache_dir).glob("market_data-*.json"):
            # market_data-YYYYMMDD.json
            stem = fp.stem
            parts = stem.split("-")
            if len(parts) >= 2:
                d8 = parts[-1]
                if d8 not in keep_set:
                    fp.unlink(missing_ok=True)
    except Exception:
        pass
except Exception as e:
    # 模板渲染失败则回退到旧逻辑（确保可用性）
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"⚠️ 模板渲染失败，已回退旧HTML拼接方式：{e}")

print(f"\n✅ HTML已生成: {os.path.abspath(output_path) if 'os' in globals() else output_path}")
print(f"\n--- 报告摘要 ---")
print(f"日期: {DATE}")
print("指数: " + " ".join([f'{i["name"]}{i["close"]:.2f}({i["pct"]:+.2f}%)' for i in indices_data]))
print(f"全景: 涨停{zt_count} 炸板{zb_count} 跌停{dt_count} 封板{fb_rate:.1f}%")
print(f"量能: {today_total_vol:.0f}亿 ({vol_chg_pct:+.2f}%)")
print(f"赚钱效应: {effect_verdict_title}")
print(f"天梯: 最高{max_lb}板, {len(ladder_rows)}只连板, 晋级率{jj_rate:.1f}%")
print(f"题材TOP3: {', '.join([f'{t[0]}({t[1]}只)' for t in real_themes[:3]])}")
print(f"恐惧: 大面{bf_count}只, 亏钱{fear_risk}")
print(f"成交额TOP1: {top10_with_theme[0]['mc']} {top10_with_theme[0]['cje']/1e8:.0f}亿")
