#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时盯盘（AkShare + 必盈兜底）

输出一个轻量 JSON（latest_intraday.json），供 GitHub Pages 静态页在“实时盯盘”Tab 拉取并自动刷新。

原则：
- 只取“盯盘必要字段”，避免请求过多导致被限流
- 容错：单个数据源失败不影响整体输出
- 输出字段尽量稳定（前端只依赖少量 key）
"""

from __future__ import annotations

import argparse
import json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List


BJ_TZ = timezone(timedelta(hours=8))


def _now_bj() -> datetime:
    return datetime.now(BJ_TZ)


def _sleep_jitter(lo: float = 0.8, hi: float = 1.8) -> None:
    time.sleep(random.uniform(lo, hi))


def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip().replace("%", "")
        return float(s)
    except Exception:
        return default


def _to_int(x: Any, default: int = 0) -> int:
    try:
        if x is None:
            return default
        if isinstance(x, bool):
            return default
        return int(float(str(x).strip()))
    except Exception:
        return default


def _safe_df_to_records(df, cols: List[str], limit: int = 10) -> List[Dict[str, Any]]:
    if df is None:
        return []
    try:
        sub = df
        # 尽量只取需要列
        keep = [c for c in cols if c in sub.columns]
        if keep:
            sub = sub[keep]
        # 去掉 NaN
        sub = sub.fillna("")
        recs = sub.to_dict(orient="records")
        return recs[:limit]
    except Exception:
        return []


@dataclass
class LiveSnapshot:
    source: str
    ts_bj: str
    date: str
    market: Dict[str, Any]
    concepts: List[Dict[str, Any]]
    alerts: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "ts_bj": self.ts_bj,
            "date": self.date,
            "market": self.market,
            "concepts": self.concepts,
            "alerts": self.alerts,
        }


def _concepts_from_biying(date10: str) -> List[Dict[str, Any]]:
    """
    必盈兜底：用涨停池的题材字段(gn/hy)粗略构建“主线板块TOP”。
    - 这是一个“盯盘可用”的 proxy，不追求严格等同东方财富概念涨跌幅。
    """
    try:
        from daily_review.config import load_config_from_env, DEFAULT_CONFIG
        from daily_review.http import HttpClient
        from daily_review.data.biying import fetch_pool
    except Exception:
        return []

    try:
        cfg = load_config_from_env()
        if not cfg.token:
            return []
        client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=25)
        zt = fetch_pool(client, pool_name="ztgc", date=date10) or []
        if not isinstance(zt, list) or not zt:
            return []
    except Exception:
        return []

    # theme -> {count, leader_name, leader_score}
    agg: Dict[str, Dict[str, Any]] = {}

    def norm_themes(s: str) -> List[str]:
        s = str(s or "").strip()
        if not s:
            return []
        # 常见分隔符：中点/顿号/分号/逗号/空格
        for sep in ["·", "、", ";", "；", ",", "，", "|", "/"]:
            s = s.replace(sep, " ")
        parts = [p.strip() for p in s.split() if p.strip()]
        # 过滤噪声题材（沿用配置的 noise_themes）
        parts = [p for p in parts if p not in (DEFAULT_CONFIG.noise_themes or set())]
        return parts[:6]

    for x in zt:
        if not isinstance(x, dict):
            continue
        name = str(x.get("mc") or x.get("name") or "")
        lbc = _to_int(x.get("lbc"), 1)
        cje = _to_float(x.get("cje"), 0.0)
        leader_score = lbc * 1e12 + cje  # 先看高度再看成交额

        themes = []
        themes.extend(norm_themes(x.get("gn")))
        themes.extend(norm_themes(x.get("hy")))
        # 去重但保序
        seen = set()
        themes2 = []
        for t in themes:
            if t not in seen:
                themes2.append(t)
                seen.add(t)
        themes = themes2[:6]

        for t in themes:
            slot = agg.setdefault(t, {"count": 0, "lead": "", "leader_score": -1})
            slot["count"] += 1
            if leader_score > float(slot.get("leader_score", -1)):
                slot["leader_score"] = leader_score
                slot["lead"] = name

    rows = sorted(agg.items(), key=lambda kv: (kv[1].get("count", 0), kv[1].get("leader_score", 0)), reverse=True)
    out: List[Dict[str, Any]] = []
    for t, v in rows[:12]:
        out.append(
            {
                "name": t,
                "chg_pct": None,          # 必盈兜底无法给出“板块涨跌幅”，前端会展示为 -
                "lead": v.get("lead") or "-",
                "lead_chg_pct": None,
                "up": int(v.get("count", 0) or 0),  # 用“涨停样本数”近似梯队热度
                "down": 0,
            }
        )
    return out


def _market_from_biying(date10: str) -> Dict[str, Any]:
    """
    必盈兜底：用三池统计市场状态（涨停/炸板/跌停/连板高度）。
    """
    try:
        from daily_review.config import load_config_from_env
        from daily_review.http import HttpClient
        from daily_review.data.biying import fetch_pool
    except Exception:
        return {}

    try:
        cfg = load_config_from_env()
        if not cfg.token:
            return {}
        client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=25)
        zt = fetch_pool(client, pool_name="ztgc", date=date10) or []
        zb = fetch_pool(client, pool_name="zbgc", date=date10) or []
        dt = fetch_pool(client, pool_name="dtgc", date=date10) or []
    except Exception:
        return {}

    zt_cnt = len(zt) if isinstance(zt, list) else 0
    zab_cnt = len(zb) if isinstance(zb, list) else 0
    dt_cnt = len(dt) if isinstance(dt, list) else 0

    lianban_cnt = 0
    max_lianban = 0
    if isinstance(zt, list):
        lbs = [_to_int(x.get("lbc"), 1) for x in zt if isinstance(x, dict)]
        lianban_cnt = sum(1 for lb in lbs if lb >= 2)
        max_lianban = max(lbs) if lbs else 0

    try_total = zt_cnt + zab_cnt
    zab_rate = (zab_cnt / try_total * 100.0) if try_total > 0 else 0.0
    return {
        "zt": zt_cnt,
        "dt": dt_cnt,
        "zab": zab_cnt,
        "zab_rate": round(zab_rate, 1),
        "lianban": lianban_cnt,
        "max_lianban": max_lianban,
    }


def build_live_snapshot(date8: str | None = None) -> LiveSnapshot:
    """
    生成实时盯盘快照。
    date8: YYYYMMDD；为空则取北京时间“今天”。
    """
    now = _now_bj()
    date8 = date8 or now.strftime("%Y%m%d")
    date10 = f"{date8[:4]}-{date8[4:6]}-{date8[6:8]}"

    sources: List[str] = []
    alerts: List[Dict[str, Any]] = []
    market: Dict[str, Any] = {}
    concepts: List[Dict[str, Any]] = []

    # 先尝试 AkShare
    ak = None
    try:
        import akshare as ak  # type: ignore
    except Exception as e:
        alerts.append({"level": "warn", "text": f"AkShare 不可用，启用必盈兜底（{e}）"})
        ak = None

    # --- 1) 涨跌停/炸板/连板（轻量） ---
    zt_cnt = dt_cnt = zab_cnt = lianban_cnt = max_lianban = 0
    if ak is not None:
        sources.append("AkShare")
        try:
            _sleep_jitter()
            zt_df = ak.stock_zt_pool_em(date=date8)  # 今日涨停池
            # 过滤 ST（尽量）
            if zt_df is not None and "名称" in zt_df.columns:
                zt_df = zt_df[~zt_df["名称"].astype(str).str.contains("ST", na=False)]
            zt_cnt = int(len(zt_df)) if zt_df is not None else 0
        except Exception:
            pass

        try:
            _sleep_jitter()
            dt_df = ak.stock_zt_pool_dtgc_em(date=date8)  # 跌停池
            if dt_df is not None and "名称" in dt_df.columns:
                dt_df = dt_df[~dt_df["名称"].astype(str).str.contains("ST", na=False)]
            dt_cnt = int(len(dt_df)) if dt_df is not None else 0
        except Exception:
            pass

        try:
            _sleep_jitter()
            zb_df = ak.stock_zt_pool_zbgc_em(date=date8)  # 炸板池
            if zb_df is not None and "名称" in zb_df.columns:
                zb_df = zb_df[~zb_df["名称"].astype(str).str.contains("ST", na=False)]
            zab_cnt = int(len(zb_df)) if zb_df is not None else 0
        except Exception:
            pass

        try:
            _sleep_jitter()
            strong_df = ak.stock_zt_pool_strong_em(date=date8)  # 连板池/强势池
            # 常见列：连板数/连续涨停天数 等；尽量容错
            if strong_df is not None:
                # 统计连板数>=2
                lb_col = None
                for c in ["连板数", "连续涨停天数", "连板", "连续涨停"]:
                    if c in strong_df.columns:
                        lb_col = c
                        break
                if lb_col:
                    lbs = strong_df[lb_col].apply(lambda x: _to_int(x, 0))
                    lianban_cnt = int((lbs >= 2).sum())
                    max_lianban = int(lbs.max()) if len(lbs) else 0
        except Exception:
            pass

    try_total = zt_cnt + zab_cnt
    zab_rate = (zab_cnt / try_total * 100.0) if try_total > 0 else 0.0

    # --- 2) 板块主线（概念涨跌幅 TOP） ---
    if ak is not None:
        try:
            _sleep_jitter()
            cdf = ak.stock_board_concept_spot_em()  # 概念板块实时
            if cdf is not None:
                # 常见：板块名称, 涨跌幅, 领涨股票, 领涨股票-涨跌幅
                if "涨跌幅" in cdf.columns:
                    cdf = cdf.sort_values(by="涨跌幅", ascending=False)
                for _, r in cdf.head(12).iterrows():
                    name = str(r.get("板块名称") or r.get("板块") or r.get("名称") or "")
                    chg = _to_float(r.get("涨跌幅"), 0.0)
                    lead = str(r.get("领涨股票") or r.get("领涨股") or "")
                    lead_chg = _to_float(r.get("领涨股票-涨跌幅") or r.get("领涨股-涨跌幅"), 0.0)
                    up = _to_int(r.get("上涨家数"), 0)
                    dn = _to_int(r.get("下跌家数"), 0)
                    if name:
                        concepts.append(
                            {
                                "name": name,
                                "chg_pct": round(chg, 2),
                                "lead": lead,
                                "lead_chg_pct": round(lead_chg, 2),
                                "up": up,
                                "down": dn,
                            }
                        )
        except Exception:
            pass

    # 必盈兜底：当 AkShare 概念榜为空时，用涨停池题材统计补齐
    if not concepts:
        c2 = _concepts_from_biying(date10)
        if c2:
            concepts = c2
            sources.append("必盈")
        else:
            alerts.append({"level": "warn", "text": "板块数据获取失败或为空（稍后重试）"})

    # 必盈兜底：当 AkShare 市场统计拿不到时，用三池补齐
    if (zt_cnt == 0 and dt_cnt == 0 and zab_cnt == 0) or ak is None:
        m2 = _market_from_biying(date10)
        if m2:
            zt_cnt = int(m2.get("zt", 0) or 0)
            dt_cnt = int(m2.get("dt", 0) or 0)
            zab_cnt = int(m2.get("zab", 0) or 0)
            zab_rate = float(m2.get("zab_rate", 0.0) or 0.0)
            lianban_cnt = int(m2.get("lianban", 0) or 0)
            max_lianban = int(m2.get("max_lianban", 0) or 0)
            if "必盈" not in sources:
                sources.append("必盈")
    # 负反馈：跌停/炸板过多
    if dt_cnt >= 20:
        alerts.append({"level": "danger", "text": f"跌停偏多（{dt_cnt}）→ 亏钱扩散风险上升"})
    elif dt_cnt >= 10:
        alerts.append({"level": "warn", "text": f"跌停偏多（{dt_cnt}）→ 控制追高"})

    if zab_rate >= 35:
        alerts.append({"level": "danger", "text": f"炸板率高（{zab_rate:.1f}%）→ 分歧偏强，谨慎接力"})
    elif zab_rate >= 25:
        alerts.append({"level": "warn", "text": f"炸板率偏高（{zab_rate:.1f}%）→ 注意回封质量"})

    if max_lianban >= 6 and zab_rate >= 25:
        alerts.append({"level": "warn", "text": f"高度{max_lianban}板 + 分歧不低 → 高位兑现/炸板风险"})

    # 主线不明：仅在 AkShare 有涨跌幅时判断
    if concepts and (concepts[0].get("chg_pct") is not None):
        top = concepts[0]
        if _to_float(top.get("chg_pct"), 0.0) < 1.0:
            alerts.append({"level": "warn", "text": "主线偏弱：板块涨幅不突出，先看资金回流方向"})

    market = {
        "source": "+".join(sources) if sources else "unknown",
        "zt": zt_cnt,
        "dt": dt_cnt,
        "zab": zab_cnt,
        "zab_rate": round(zab_rate, 1),
        "lianban": lianban_cnt,
        "max_lianban": max_lianban,
    }

    return LiveSnapshot(
        source=market["source"],
        ts_bj=now.strftime("%Y-%m-%d %H:%M:%S"),
        date=date10,
        market=market,
        concepts=concepts,
        alerts=alerts,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="YYYYMMDD；为空取北京时间今天")
    ap.add_argument("--out", required=True, help="输出 JSON 文件路径")
    args = ap.parse_args()

    snap = build_live_snapshot(args.date.strip() or None)
    out_path = args.out
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snap.to_dict(), f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
