#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
龙头识别（短线复盘）

目标（对应你的描述）：
- 当天出现“强封/一字”的点火源
- 并且能够带动题材/板块爆发（万马齐鸣）
- 认定为“龙头”（领涨性、一马当先）

实现约束：
- 尽量函数式：核心计算为纯函数
- 数据缺失要可容错（毕竟接口字段不一定齐）
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


def _to_float(v: Any, default: float = 0.0) -> float:
    """纯函数：安全转 float。"""
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _to_int(v: Any, default: int = 0) -> int:
    """纯函数：安全转 int。"""
    try:
        if v is None:
            return default
        return int(float(v))
    except Exception:
        return default

def _safe_div(a: float, b: float) -> float:
    """纯函数：安全除法。"""
    if b == 0:
        return 0.0
    return a / b


def _time_hhmmss_to_sec(t: str | None) -> int:
    """
    纯函数：把 "HHMMSS" / "HH:MM:SS" 转成秒。
    - 缺失或异常 -> 视为很晚（24h）
    """
    if not t:
        return 24 * 3600
    s = str(t).strip()
    if not s:
        return 24 * 3600
    try:
        if ":" in s:
            hh, mm, ss = s.split(":")
        else:
            s = s.zfill(6)
            hh, mm, ss = s[0:2], s[2:4], s[4:6]
        return int(hh) * 3600 + int(mm) * 60 + int(ss)
    except Exception:
        return 24 * 3600


def _clamp(x: float, lo: float, hi: float) -> float:
    """纯函数：截断到区间。"""
    return max(lo, min(x, hi))


def _log_norm(x: float, x_max: float) -> float:
    """
    纯函数：对数归一化（0~1）。
    - 用于“封单金额”等长尾分布特征，避免极端值一票定乾坤
    """
    if x <= 0 or x_max <= 0:
        return 0.0
    return _clamp(math.log1p(x) / math.log1p(x_max), 0.0, 1.0)

def _quantile(xs: Sequence[float], q: float, default: float = 0.0) -> float:
    """
    纯函数：分位数（q in [0,1]）。
    - xs 为空返回 default
    - 简单线性插值
    """
    if not xs:
        return default
    ys = sorted(xs)
    q = _clamp(q, 0.0, 1.0)
    pos = (len(ys) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ys[lo]
    w = pos - lo
    return ys[lo] * (1.0 - w) + ys[hi] * w

def infer_limit_pct(*, code: str, zf: float) -> float:
    """
    纯函数：推断涨跌停幅度（0.1 / 0.2）。

    说明：
    - 这里用启发式：20cm 常见于 300/301/688；且涨幅往往接近 20
    - ST/北交所等特殊规则暂不覆盖（后续可按需增强）
    """
    code = str(code or "").strip()
    if code.startswith(("300", "301", "688")) or abs(zf) >= 15:
        return 0.2
    return 0.1


def score_space(*, lbc: int, limit_pct: float) -> tuple[float, dict[str, Any]]:
    """
    纯函数：空间高度得分（0~8）

    目的：
    - 给“龙头空间”一个轻权重加成（你要求“叠加一定的空间高度”）
    - 但避免简单地“高度=龙头”：因此分值上限不高、且只作为加分项

    经验阈值（可按你的历史分布再调）：
    - 10cm：2/3/4/6 板分别是关键分段
    - 20cm：1/2/3 板的“空间含金量”更高，因此阈值更低
    """
    lb = max(0, int(lbc or 0))
    if lb <= 1:
        return (0.0, {"lbc": lb, "limitPct": limit_pct})

    if limit_pct >= 0.2:
        # 20cm：2板已具备一定空间辨识度
        if lb >= 3:
            s = 8.0
        elif lb == 2:
            s = 6.0
        else:
            s = 3.0
    else:
        # 10cm：空间需要更高板数才体现“龙头属性”
        if lb >= 6:
            s = 8.0
        elif lb >= 4:
            s = 6.0
        elif lb == 3:
            s = 4.0
        else:  # lb == 2
            s = 2.0

    return (s, {"lbc": lb, "limitPct": limit_pct})


def is_one_word_limitup_by_ohlc(
    *,
    ohlc: Mapping[str, Any] | None,
    code: str,
    zf: float,
    eps_ratio: float = 0.003,
) -> bool:
    """
    纯函数：用日线 OHLC 严格判断“一字板”（更强方案）。

    判定：
    - O==H==L==C（全天几乎没有波动）
    - 且 C 接近涨停价（由 pc * (1+limit_pct) 推断）
    """
    if not ohlc:
        return False
    o = _to_float(ohlc.get("o"), None)  # type: ignore[arg-type]
    h = _to_float(ohlc.get("h"), None)  # type: ignore[arg-type]
    l = _to_float(ohlc.get("l"), None)  # type: ignore[arg-type]
    c = _to_float(ohlc.get("c"), None)  # type: ignore[arg-type]
    pc = _to_float(ohlc.get("pc"), None)  # type: ignore[arg-type]
    if None in (o, h, l, c, pc) or pc <= 0:
        return False
    if not (abs(o - h) < 1e-9 and abs(o - l) < 1e-9 and abs(o - c) < 1e-9):
        return False

    limit_pct = infer_limit_pct(code=code, zf=zf)
    limit_price = pc * (1.0 + limit_pct)
    return abs(c - limit_price) / limit_price <= eps_ratio


def is_one_word_limitup(*, hs: float, zbc: int, fbt: str | None, hs_p10: float = 1.2) -> bool:
    """
    纯函数：用现有字段近似识别“一字板”。

    说明：
    - 你当前数据没有开盘价/最高/最低，因此只能用启发式：
      - 换手极低 + 开板次数为 0 + 首封时间非常早
    - 阈值建议后续用你的历史数据分布校准
    """
    early = _time_hhmmss_to_sec(fbt) <= _time_hhmmss_to_sec("093000")
    # hs_p10：用当日涨停池的“低换手分位数”作为动态阈值，比写死 1.2 更稳
    return (hs <= max(0.1, hs_p10)) and (zbc == 0) and early


def pick_primary_theme(
    *,
    code: str,
    code2themes: Mapping[str, list[str]],
    hot_sectors: list[dict[str, Any]],
    fallback_industry: str,
) -> str:
    """
    纯函数：为个股挑“主归因题材”（用于聚合计算）。

    规则：
    1) 优先命中当日热点板块（marketData.sectors）中排名更靠前的题材
    2) 否则回退到题材映射的第一个
    3) 再兜底用行业 hy
    """
    themes = code2themes.get(code) or []
    # 加权：如果该股命中 CPO/光模块，优先用它作为“主归因题材”
    pri = _pick_priority_theme_from_list([str(x) for x in themes if x])
    if pri:
        return pri
    hot_names = [str(s.get("name") or "") for s in (hot_sectors or []) if str(s.get("name") or "").strip()]
    for name in hot_names:
        if name in themes:
            return name
    if themes:
        return str(themes[0])
    return fallback_industry or "其他"

def _theme_priority(name: str) -> int:
    """
    纯函数：题材权重/优先级定义（数值越小优先级越高）。

    用户规则：
    - 一级：光模块、商业航天、锂电池、储能
    - 其他：二级
    """
    s = str(name or "").strip()
    if not s:
        return 999
    up = s.upper()
    # 1) 一级：光模块（含 CPO/光通信/高速互联 等常见别名）
    if ("光模块" in s) or ("光通信" in s) or ("高速互联" in s) or ("CPO" in up):
        return 1
    # 2) 一级：商业航天
    if ("商业航天" in s) or ("航天" in s and "商业" in s):
        return 2
    # 3) 一级：锂电池
    if ("锂电" in s) or ("锂电池" in s) or ("动力电池" in s):
        return 3
    # 4) 一级：储能
    if ("储能" in s):
        return 4
    # 二级：其他
    return 100


def _is_tier1_theme(name: str) -> bool:
    """纯函数：是否一级题材。"""
    return _theme_priority(name) <= 4


def _pick_priority_theme_from_list(themes: list[str]) -> str | None:
    """
    纯函数：在多题材里优先挑“一级题材”（用户指定加权）。
    优先级顺序：光模块 > 商业航天 > 锂电池 > 储能。
    """
    cand = [( _theme_priority(t), t) for t in themes if t]
    cand.sort(key=lambda x: x[0])
    if cand and cand[0][0] <= 4:
        return cand[0][1]
    return None


def score_ignition(
    *,
    code: str,
    hs: float,
    zbc: int,
    fbt: str | None,
    lbt: str | None,
    zf: float,
    lbc: int,
    seal_amt: float,
    seal_amt_max: float,
    lt_mktcap: float,
    cje: float,
    ohlc: Mapping[str, Any] | None,
    hs_p10: float,
) -> tuple[float, dict[str, Any]]:
    """
    纯函数：点火源得分（0~40）
    - 一字/强封（低换手、不开板、早封）更像“点火”
    - 封单金额越大越强（用 log 归一化）
    """
    # 一字识别：优先用 OHLC 严格判断；缺失则回退到启发式
    strict_one_word = is_one_word_limitup_by_ohlc(ohlc=ohlc, code=code, zf=zf)
    weak_one_word = is_one_word_limitup(hs=hs, zbc=zbc, fbt=fbt, hs_p10=hs_p10)
    one_word = strict_one_word or weak_one_word

    # 强方案：严格一字权重更高
    one_word_score = 24.0 if strict_one_word else (14.0 if weak_one_word else 0.0)

    # 早封：09:30 越接近越高；10:30 以后基本不给分
    t = _time_hhmmss_to_sec(fbt)
    early_score = _clamp(((_time_hhmmss_to_sec("103000") - t) / (60 * 60)) * 8.0, 0.0, 8.0)

    # 封单金额：长尾，用 log 归一化（绝对强度）
    seal_score = _log_norm(seal_amt, seal_amt_max) * 20.0

    # 封单强度（相对强度）：封板资金/流通市值、封板资金/成交额
    # 注：lt/cje 可能缺失，保持可容错
    seal_vs_lt = _safe_div(seal_amt, lt_mktcap)
    seal_vs_cje = _safe_div(seal_amt, cje)
    # 两个比值都长尾，做温和缩放；上限避免过拟合
    rel_score = _clamp((math.log1p(seal_vs_lt * 1e4) + math.log1p(seal_vs_cje * 50)) * 3.2, 0.0, 12.0)

    # 封板稳定性：末封 - 首封（越久越强），一字往往贯穿全天
    dur_min = max(0.0, (_time_hhmmss_to_sec(lbt) - _time_hhmmss_to_sec(fbt)) / 60.0)
    dur_score = _clamp(dur_min / 60.0 * 6.0, 0.0, 6.0)  # 封住 60min 给 6 分

    # 空间高度：轻权重加成（避免“高度=龙头”的误判）
    limit_pct = infer_limit_pct(code=code, zf=zf)
    space_score, space_r = score_space(lbc=lbc, limit_pct=limit_pct)

    # 开板惩罚：zbc 越多越扣分（上限防炸）
    open_penalty = _clamp(zbc, 0, 10) * 1.4

    raw = one_word_score + early_score + seal_score + rel_score + dur_score + space_score - open_penalty
    return (
        _clamp(raw, 0.0, 40.0),
        {
            "oneWord": one_word,
            "strictOneWord": strict_one_word,
            "oneWordScore": round(one_word_score, 2),
            "earlyScore": round(early_score, 2),
            "sealScore": round(seal_score, 2),
            "relScore": round(rel_score, 2),
            "durMin": round(dur_min, 1),
            "durScore": round(dur_score, 2),
            "spaceScore": round(space_score, 2),
            "space": space_r,
            "openPenalty": round(open_penalty, 2),
        },
    )


def _build_theme_stats(
    *,
    rows: Sequence[Mapping[str, Any]],
    theme_of: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """
    纯函数：从涨停池直接统计“万马齐鸣”的扩散强度（不依赖 sectors.eval）。

    输出：
    - theme -> {count, times_sec(sorted), first_fbt_sec, last_fbt_sec, max_count}
    """
    times_by_theme: dict[str, list[int]] = {}
    for s in rows:
        code = str(s.get("dm") or "").strip()
        if not code:
            continue
        theme = theme_of.get(code) or "其他"
        t = _time_hhmmss_to_sec(str(s.get("fbt") or "").strip() or None)
        times_by_theme.setdefault(theme, []).append(t)

    max_cnt = max([len(v) for v in times_by_theme.values()] or [0])
    out: dict[str, dict[str, Any]] = {}
    for theme, ts in times_by_theme.items():
        ts_sorted = sorted(ts)
        out[theme] = {
            "count": len(ts_sorted),
            "times_sec": ts_sorted,
            "first_fbt_sec": ts_sorted[0] if ts_sorted else 24 * 3600,
            "last_fbt_sec": ts_sorted[-1] if ts_sorted else 24 * 3600,
            "max_count": max_cnt,
        }
    return out


def score_explosion(
    *,
    theme: str,
    theme_stats: Mapping[str, Any],
    leader_fbt: str | None,
) -> tuple[float, dict[str, Any]]:
    """
    纯函数：板块爆发得分（0~40）

    强方案（更贴近“带动板块爆发”）：
    - 直接基于涨停池统计该题材的涨停规模
    - 并计算“在龙头封板后”跟随涨停的数量（follow_count）
    """
    if not theme:
        return (0.0, {"theme": theme, "hit": False})
    st = (theme_stats or {}).get(theme) if isinstance(theme_stats, dict) else None
    if not isinstance(st, dict):
        return (6.0, {"theme": theme, "hit": False, "count": 0, "follow": 0})

    cnt = _to_int(st.get("count"), 0)
    max_cnt = _to_int(st.get("max_count"), 0)
    cnt_norm = (cnt / max_cnt) if max_cnt > 0 else 0.0

    times_sec: list[int] = list(st.get("times_sec") or [])
    t0 = _time_hhmmss_to_sec(leader_fbt)
    # 跟随：排除“同一分钟同步封板”的噪声，默认 >=60s 认为是被带动
    follow = len([t for t in times_sec if (t - t0) >= 60])
    follow_ratio = follow / max(cnt - 1, 1)

    # 扩散持续性：题材内封板时间跨度（越长越像“万马齐鸣”）
    spread_min = max(0.0, (_to_int(st.get("last_fbt_sec"), 0) - _to_int(st.get("first_fbt_sec"), 0)) / 60.0)
    spread_score = _clamp(spread_min / 240.0, 0.0, 1.0)  # 4小时打满

    score = 40.0 * _clamp(cnt_norm * 0.55 + follow_ratio * 0.30 + spread_score * 0.15, 0.0, 1.0)
    # 题材加权：一级题材轻微放大（避免过拟合）
    if _is_tier1_theme(theme):
        score = min(40.0, score * 1.10)
    return (
        round(score, 2),
        {
            "theme": theme,
            "hit": True,
            "count": cnt,
            "follow": follow,
            "followRatio": round(follow_ratio, 3),
            "spreadMin": round(spread_min, 1),
            "boost": "一级题材" if _is_tier1_theme(theme) else "",
        },
    )


def score_leadership(*, fbt: str | None, theme_first_fbt: str | None) -> tuple[float, dict[str, Any]]:
    """
    纯函数：先发性（0~20）
    - 同题材内越早封板越像“带队”
    """
    t = _time_hhmmss_to_sec(fbt)
    t0 = _time_hhmmss_to_sec(theme_first_fbt)
    lag_sec = t - t0  # 越小越好

    # 领先/同步：满分；落后越多越扣，30分钟后趋近 0
    score = _clamp(20.0 - (lag_sec / 60.0) * (20.0 / 30.0), 0.0, 20.0)
    return (round(score, 2), {"lagSec": int(lag_sec), "themeFirst": theme_first_fbt or ""})


@dataclass(frozen=True)
class LeaderPick:
    code: str
    name: str
    theme: str
    score: float
    reason: dict[str, Any]


def pick_leaders(
    *,
    ztgc: Iterable[Mapping[str, Any]],
    code2themes: Mapping[str, list[str]],
    hot_sectors: list[dict[str, Any]],
    ohlc_by_code: Mapping[str, Mapping[str, Any]] | None = None,
    topk: int = 5,
) -> list[LeaderPick]:
    """
    纯函数：从涨停池中挑“龙头候选”并排序返回。

    输入：
    - ztgc: marketData.ztgc（涨停池）
    - code2themes: marketData.zt_code_themes（涨停股->题材）
    - hot_sectors: marketData.sectors（今日热点题材Top）
    """
    rows = list(ztgc or [])
    seal_amt_max = max([_to_float(s.get("zj"), 0.0) for s in rows] or [0.0])
    hs_p10 = _quantile([_to_float(s.get("hs"), 0.0) for s in rows if _to_float(s.get("hs"), 0.0) > 0], 0.10, 1.2)

    # 先为每个票分配主题材，并算出“该题材最早封板时间”
    theme_of: dict[str, str] = {}
    theme_first_fbt: dict[str, str] = {}
    for s in rows:
        code = str(s.get("dm") or "").strip()
        if not code:
            continue
        theme = pick_primary_theme(
            code=code,
            code2themes=code2themes,
            hot_sectors=hot_sectors,
            fallback_industry=str(s.get("hy") or ""),
        )
        theme_of[code] = theme
        fbt = str(s.get("fbt") or "").strip()
        if not fbt:
            continue
        prev = theme_first_fbt.get(theme)
        if (prev is None) or (_time_hhmmss_to_sec(fbt) < _time_hhmmss_to_sec(prev)):
            theme_first_fbt[theme] = fbt

    theme_stats = _build_theme_stats(rows=rows, theme_of=theme_of)

    picks: list[LeaderPick] = []
    for s in rows:
        code = str(s.get("dm") or "").strip()
        name = str(s.get("mc") or "").strip()
        if not code or not name:
            continue

        hs = _to_float(s.get("hs"), 0.0)
        zbc = _to_int(s.get("zbc"), 0)
        fbt = str(s.get("fbt") or "").strip() or None
        lbt = str(s.get("lbt") or "").strip() or None
        seal_amt = _to_float(s.get("zj"), 0.0)  # 以 zj 近似“封单资金/大单强度”
        zf = _to_float(s.get("zf"), 0.0)
        lbc = _to_int(s.get("lbc"), 1)
        lt_mktcap = _to_float(s.get("lt"), 0.0)
        cje = _to_float(s.get("cje"), 0.0)
        ohlc = (ohlc_by_code or {}).get(code) if ohlc_by_code else None

        theme = theme_of.get(code) or "其他"

        ign, ign_r = score_ignition(
            code=code,
            hs=hs,
            zbc=zbc,
            fbt=fbt,
            lbt=lbt,
            zf=zf,
            lbc=lbc,
            seal_amt=seal_amt,
            seal_amt_max=seal_amt_max,
            lt_mktcap=lt_mktcap,
            cje=cje,
            ohlc=ohlc,
            hs_p10=hs_p10,
        )
        exp, exp_r = score_explosion(theme=theme, theme_stats=theme_stats, leader_fbt=fbt)
        lead, lead_r = score_leadership(fbt=fbt, theme_first_fbt=theme_first_fbt.get(theme))

        # 题材偏好加分：一级题材更容易顶出来（光模块优先级最高）
        pr = _theme_priority(theme)
        if pr == 1:
            theme_bonus = 4.0
        elif pr <= 4:
            theme_bonus = 2.5
        else:
            theme_bonus = 0.0
        score = ign + exp + lead + theme_bonus
        tags: list[str] = []
        if ign_r.get("strictOneWord"):
            tags.append("一字板")
        elif ign_r.get("oneWord"):
            tags.append("强封")
        if exp_r.get("hit") and _to_int(exp_r.get("follow"), 0) >= 2:
            tags.append("带动板块")
        if lead >= 15:
            tags.append("先发")
        if _to_float(ign_r.get("spaceScore"), 0.0) >= 6:
            tags.append("空间")
        if theme_bonus > 0:
            tags.append("一级题材")
            if pr == 1:
                tags.append("光模块优先")

        picks.append(
            LeaderPick(
                code=code,
                name=name,
                theme=theme,
                score=round(score, 2),
                reason={
                    "ignition": ign_r,
                    "explosion": exp_r,
                    "lead": lead_r,
                    "tags": tags,
                    "themeBonus": theme_bonus,
                    "themeTier": 1 if pr <= 4 else 2,
                },
            )
        )

    # 强约束：每个题材只保留最强的 1 只（更贴近“龙头唯一性”）
    best_by_theme: dict[str, LeaderPick] = {}
    for p in picks:
        cur = best_by_theme.get(p.theme)
        if (cur is None) or (p.score > cur.score):
            best_by_theme[p.theme] = p

    uniq = list(best_by_theme.values())
    return sorted(uniq, key=lambda x: x.score, reverse=True)[: max(1, topk)]
