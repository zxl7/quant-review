#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时盯盘（AkShare + 必盈兜底）

输出盘中盯盘快照，供本地构建链路写入缓存并嵌入报告页。

原则：
- 只取"盯盘必要字段"，避免请求过多导致被限流
- 容错：单个数据源失败不影响整体输出
- 输出字段尽量稳定（前端只依赖少量 key）
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from daily_review.utils.stock import filter_non_st_stocks


BJ_TZ = timezone(timedelta(hours=8))


def _now_bj() -> datetime:
    return datetime.now(BJ_TZ)


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


def _to_int_or_none(x: Any) -> int | None:
    """
    纯函数：安全转 int；失败返回 None（用于可选字段）。
    """
    try:
        if x is None or x == "":
            return None
        if isinstance(x, bool):
            return None
        return int(float(str(x).strip()))
    except Exception:
        return None

@dataclass
class LiveSnapshot:
    source: str
    ts_bj: str
    date: str
    market: Dict[str, Any]
    concepts: List[Dict[str, Any]]
    alerts: List[Dict[str, Any]]
    indices: List[Dict[str, Any]] | None = None
    indices_as_of: str = ""
    health: Dict[str, Any] | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "ts_bj": self.ts_bj,
            "date": self.date,
            "market": self.market,
            "concepts": self.concepts,
            "alerts": self.alerts,
            "indices": self.indices or [],
            "asOf": {"indices": self.indices_as_of},
            "health": self.health or {},
        }


def _concepts_from_biying(date10: str) -> List[Dict[str, Any]]:
    """
    必盈兜底：用涨停池的题材字段(gn/hy)粗略构建"主线板块TOP"。
    - 这是一个"盯盘可用"的 proxy，不追求严格等同东方财富概念涨跌幅。
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
                "chg_pct": None,          # 必盈兜底无法给出"板块涨跌幅"，前端会展示为 -
                "inflow": None,
                "outflow": None,
                "net": None,
                "companies": None,
                "lead": v.get("lead") or "-",
                "lead_chg_pct": None,
                "up": int(v.get("count", 0) or 0),  # 用"涨停样本数"近似梯队热度
                "down": 0,
            }
        )
    return out


def _read_local_cache(date8: str) -> Dict[str, Any] | None:
    """
    尝试读取本地缓存 market_data-YYYYMMDD.json。
    """
    from pathlib import Path
    try:
        # 假设 cache 目录在 daily_review 的上两级
        root = Path(__file__).resolve().parent.parent
        cache_file = root / "cache" / f"market_data-{date8}.json"
        if cache_file.exists():
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _market_from_local(cache_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    从本地缓存中提取市场状态。
    """
    if not cache_data:
        return {}
    try:
        features = cache_data.get("features") or {}
        mood_inputs = features.get("mood_inputs") or {}
        volume_data = cache_data.get("volume") or {}
        return {
            "zt": _to_int(mood_inputs.get("zt_count"), 0),
            "dt": _to_int(mood_inputs.get("dt_count"), 0),
            "zab": _to_int(mood_inputs.get("zb_count"), 0),
            "zab_rate": _to_float(mood_inputs.get("zb_rate"), 0.0),
            "lianban": _to_int(mood_inputs.get("lianban_count"), 0),
            "max_lianban": _to_int(mood_inputs.get("max_lb"), 0),
            "amount": str(volume_data.get("total", "")),
        }
    except Exception:
        return {}


def _concepts_from_local(cache_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    从本地缓存中提取板块概念。
    优先尝试从 plateRankTop10 或 conceptFundFlowTop 中读取。
    """
    if not cache_data:
        return []
    try:
        # 优先使用处理好的强榜
        concepts = cache_data.get("plateRankTop10") or cache_data.get("conceptFundFlowTop") or []
        out = []
        for c in concepts[:12]:
            out.append({
                "name": c.get("name") or "",
                "chg_pct": _to_float(c.get("chg_pct"), None),
                "inflow": _to_float(c.get("inflow"), None),
                "outflow": _to_float(c.get("outflow"), None),
                "net": _to_float(c.get("net"), None),
                "companies": _to_int_or_none(c.get("companies")),
                "lead": c.get("lead") or "-",
                "lead_chg_pct": _to_float(c.get("lead_chg_pct"), None),
            })
        return out
    except Exception:
        return []



def _fetch_index_amount(client, code: str) -> float:
    """
    有副作用函数：获取指数实时成交额（元）。
    使用 hsindex/real/time/{code} 端点，返回 cje 字段。
    """
    try:
        resp = client.api(f"hsindex/real/time/{code}")
        if isinstance(resp, dict):
            val = resp.get("cje", 0)
            if val:
                return float(val)
    except Exception:
        pass
    return 0.0


def _fetch_indices_from_api(client) -> tuple[List[Dict[str, Any]], str]:
    """实时指数备用读取，避免单个 URL 形态异常阻塞已验证的盘中市场快照。"""
    rows: List[Dict[str, Any]] = []
    as_of = ""
    for code, name in (("000001.SH", "上证指数"), ("399001.SZ", "深证成指"), ("399006.SZ", "创业板指")):
        try:
            raw = client.api(f"hsindex/real/time/{code}")
        except Exception:
            raw = None
        if not isinstance(raw, dict):
            continue
        price = _to_float(raw.get("p"), 0.0)
        prev_close = _to_float(raw.get("yc"), 0.0)
        if price <= 0:
            continue
        chg = ((price - prev_close) / prev_close * 100.0) if prev_close > 0 else _to_float(raw.get("pc"), 0.0)
        stamp = str(raw.get("t") or "").strip()
        if stamp:
            as_of = stamp[11:19] if len(stamp) >= 19 else stamp
        rows.append({"name": name, "code": code, "val": price, "chg": chg, "cje": _to_float(raw.get("cje"), 0.0), "t": stamp})
    return rows, as_of



def _market_from_biying(date10: str) -> Dict[str, Any]:
    """
    必盈兜底：用三池统计市场状态（涨停/炸板/跌停/连板高度）。
    成交额：直接获取上证(000001.SH) + 深证(399001.SZ) 实时成交额，相加得两市总额。
    """
    try:
        from daily_review.config import load_config_from_env
        from daily_review.http import HttpClient
        from daily_review.data.biying import fetch_pool_result, fetch_indices_realtime
    except Exception:
        return {}

    try:
        cfg = load_config_from_env()
        if not cfg.token:
            return {}
        # 盘中槽位外层已有整轮重试；单请求必须短超时且三池并行，避免一次上游故障拖过十分钟。
        client = HttpClient(base_url=cfg.base_url, token=cfg.token, timeout=6, retries=0)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                name: executor.submit(fetch_pool_result, client, pool_name=name, date=date10)
                for name in ("ztgc", "zbgc", "dtgc")
            }
            pool_results = {name: future.result() for name, future in futures.items()}
        zt = pool_results["ztgc"]["rows"]
        zb = pool_results["zbgc"]["rows"]
        dt = pool_results["dtgc"]["rows"]
        pool_status = {key: value["status"] for key, value in pool_results.items()}
        valid_status = {"valid", "valid_empty"}
        if not any(status in valid_status for status in pool_status.values()):
            return {
                "zt": None, "dt": None, "zab": None, "zab_rate": None,
                "lianban": None, "max_lianban": None, "amount": "",
                "quality": "partial", "pool_status": pool_status,
                "pool_errors": {key: value["error"] for key, value in pool_results.items() if value.get("error")},
                "indices": [], "indices_as_of": "",
            }
        indices, indices_as_of = fetch_indices_realtime(
            client,
            [("000001.SH", "上证指数"), ("399001.SZ", "深证成指"), ("399006.SZ", "创业板指")],
        )
        if len(indices) != 3 or not all(_to_float(x.get("val"), 0) > 0 for x in indices):
            indices, indices_as_of = _fetch_indices_from_api(client)
    except Exception:
        return {"quality": "failed", "pool_status": {}, "indices": [], "indices_as_of": ""}

    pool_status = {key: value["status"] for key, value in pool_results.items()}
    pool_valid = {key: status in {"valid", "valid_empty"} for key, status in pool_status.items()}
    zt_cnt = len(zt) if pool_valid["ztgc"] and isinstance(zt, list) else None
    zab_cnt = len(zb) if pool_valid["zbgc"] and isinstance(zb, list) else None
    # 盘中风控统一看非 ST 跌停，避免 ST 把风险预警抬高。
    dt_cnt = len(filter_non_st_stocks(dt)) if pool_valid["dtgc"] and isinstance(dt, list) else None

    lianban_cnt = None
    max_lianban = None
    if pool_valid["ztgc"] and isinstance(zt, list):
        lbs = [_to_int(x.get("lbc"), 1) for x in zt if isinstance(x, dict)]
        lianban_cnt = sum(1 for lb in lbs if lb >= 2)
        max_lianban = max(lbs) if lbs else 0

    try_total = (zt_cnt or 0) + (zab_cnt or 0)
    zab_rate = (zab_cnt / try_total * 100.0) if zab_cnt is not None and zt_cnt is not None and try_total > 0 else None

    # 成交额：直接获取上证(000001.SH) + 深证(399001.SZ) 实时成交额
    amount_val = 0.0
    amount_val += _fetch_index_amount(client, "000001.SH")
    amount_val += _fetch_index_amount(client, "399001.SZ")
    
    if amount_val > 0:
        amount_str = f"{amount_val/1e8:.1f}亿"
    else:
        amount_str = ""

    return {
        "zt": zt_cnt,
        "dt": dt_cnt,
        "zab": zab_cnt,
        "zab_rate": round(zab_rate, 1) if zab_rate is not None else None,
        "lianban": lianban_cnt,
        "max_lianban": max_lianban,
        "amount": amount_str,
        "quality": "valid" if all(pool_valid.values()) else "partial",
        "pool_status": pool_status,
        "pool_errors": {key: value["error"] for key, value in pool_results.items() if value.get("error")},
        "indices": indices if len(indices) == 3 and all(_to_float(x.get("val"), 0) > 0 for x in indices) else [],
        "indices_as_of": indices_as_of if len(indices) == 3 else "",
    }

def build_live_snapshot(date8: str | None = None, *, intraday: bool = True) -> "LiveSnapshot":
    """
    生成实时盯盘快照。

    - intraday=True（默认）：强制拉取实时数据，缓存仅作兜底。
    - intraday=False：允许使用本地缓存（用于离线渲染测试）。
    """
    now = _now_bj()
    date8 = date8 or now.strftime("%Y%m%d")
    date10 = f"{date8[:4]}-{date8[4:6]}-{date8[6:8]}"

    sources: List[str] = []
    alerts: List[Dict[str, Any]] = []
    market: Dict[str, Any] = {}
    concepts: List[Dict[str, Any]] = []
    amount: str = ""
    indices: List[Dict[str, Any]] = []
    indices_as_of = ""
    health: Dict[str, Any] = {"status": "fallback", "pool_status": {}, "pool_errors": {}}

    # 始终尝试读取本地缓存（用于获取 amount 等补充字段）
    cache_data = _read_local_cache(date8)

    zt_cnt = dt_cnt = zab_cnt = lianban_cnt = max_lianban = 0
    zab_rate = 0.0

    if cache_data:
        sources.append("本地缓存")
        m_local = _market_from_local(cache_data)
        if m_local:
            zt_cnt = int(m_local.get("zt") or 0)
            dt_cnt = int(m_local.get("dt") or 0)
            zab_cnt = int(m_local.get("zab") or 0)
            zab_rate = float(m_local.get("zab_rate") or 0.0)
            lianban_cnt = int(m_local.get("lianban") or 0)
            max_lianban = int(m_local.get("max_lianban") or 0)
            amount = str(m_local.get("amount")) or ""

        c_local = _concepts_from_local(cache_data)
        if c_local:
            concepts = c_local

    # 2) 如果缓存没拿到数据，或者数据缺失，使用必盈实时拉取
    #    盘中模式（intraday=True）强制走此分支
    if intraday or not cache_data or (zt_cnt == 0 and dt_cnt == 0 and zab_cnt == 0):
        if cache_data and "本地缓存" in sources:
            sources.remove("本地缓存")
            alerts.append({"level": "warn", "text": "本地缓存数据不完整，启用必盈实时拉取"})
        elif intraday and not cache_data:
            alerts.append({"level": "info", "text": "盘中模式：强制实时拉取"})

        m2 = _market_from_biying(date10)
        if m2 and m2.get("quality") == "valid":
            zt_cnt = int(m2.get("zt", 0) or 0)
            dt_cnt = int(m2.get("dt", 0) or 0)
            zab_cnt = int(m2.get("zab", 0) or 0)
            zab_rate = float(m2.get("zab_rate", 0.0) or 0.0)
            lianban_cnt = int(m2.get("lianban", 0) or 0)
            max_lianban = int(m2.get("max_lianban", 0) or 0)
            # 必盈没有 amount，尝试使用缓存中的 amount
            amount_from_biying = str(m2.get("amount", "") or "")
            if not amount_from_biying and cache_data:
                m_local = _market_from_local(cache_data)
                amount_from_biying = str(m_local.get("amount")) or ""
            amount = amount_from_biying
            if "必盈" not in sources:
                sources.append("必盈(实时)")
            indices = m2.get("indices") if isinstance(m2.get("indices"), list) else []
            indices_as_of = str(m2.get("indices_as_of") or "")
            health = {"status": "valid", "pool_status": m2.get("pool_status") or {}, "pool_errors": {}}
        elif m2:
            # 三池可独立降级：哪个池成功就保留哪个字段，失败字段保持 None，绝不伪造为 0。
            pool_status = m2.get("pool_status") or {}
            valid_status = {"valid", "valid_empty"}
            if pool_status.get("ztgc") in valid_status:
                zt_cnt = m2.get("zt")
                lianban_cnt = m2.get("lianban")
                max_lianban = m2.get("max_lianban")
            else:
                zt_cnt = None
                lianban_cnt = None
                max_lianban = None
            if pool_status.get("dtgc") in valid_status:
                dt_cnt = m2.get("dt")
            else:
                dt_cnt = None
            if pool_status.get("zbgc") in valid_status:
                zab_cnt = m2.get("zab")
                zab_rate = m2.get("zab_rate")
            else:
                zab_cnt = None
                zab_rate = None
            indices = m2.get("indices") if isinstance(m2.get("indices"), list) else []
            indices_as_of = str(m2.get("indices_as_of") or "")
            health = {
                "status": "partial",
                "pool_status": pool_status,
                "pool_errors": m2.get("pool_errors") or {},
            }
            alerts.append({"level": "warn", "text": "盘中三池响应不完整，保留最近有效数据"})
        elif cache_data:
            # API 也失败了，回退到缓存
            sources.append("必盈(失败，使用缓存兜底)")
        else:
            alerts.append({"level": "danger", "text": "数据拉取失败，请稍后重试"})
                
    pool_states = health.get("pool_status") if isinstance(health.get("pool_status"), dict) else {}
    all_pools_failed = bool(pool_states) and not any(str(state or "") in {"valid", "valid_empty"} for state in pool_states.values())
    if (not concepts or intraday) and not (intraday and all_pools_failed):
        c2 = _concepts_from_biying(date10)
        if c2:
            concepts = c2
            if "必盈" not in sources:
                sources.append("必盈(实时)")
        elif not concepts:
            alerts.append({"level": "warn", "text": "板块数据获取失败或为空（稍后重试）"})
    elif intraday and all_pools_failed:
        alerts.append({"level": "warn", "text": "三池请求均超时，本槽位跳过板块补抓并等待下一节点"})

    # 负反馈：跌停/炸板过多
    if dt_cnt is not None and dt_cnt >= 20:
        alerts.append({"level": "danger", "text": f"跌停偏多（{dt_cnt}）→ 亏钱扩散风险上升"})
    elif dt_cnt is not None and dt_cnt >= 10:
        alerts.append({"level": "warn", "text": f"跌停偏多（{dt_cnt}）→ 控制追高"})

    if zab_rate is not None and zab_rate >= 35:
        alerts.append({"level": "danger", "text": f"炸板率高（{zab_rate:.1f}%）→ 分歧偏强，谨慎接力"})
    elif zab_rate is not None and zab_rate >= 25:
        alerts.append({"level": "warn", "text": f"炸板率偏高（{zab_rate:.1f}%）→ 注意回封质量"})

    if max_lianban is not None and zab_rate is not None and max_lianban >= 6 and zab_rate >= 25:
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
        # 辅助炸板池失败时保留 None，避免既伪造 0 又因 round(None) 中断整帧。
        "zab_rate": round(zab_rate, 1) if zab_rate is not None else None,
        "lianban": lianban_cnt,
        "max_lianban": max_lianban,
        "amount": str(amount) if amount else "",
    }

    return LiveSnapshot(
        source=market["source"],
        ts_bj=now.strftime("%Y-%m-%d %H:%M:%S"),
        date=date10,
        market=market,
        concepts=concepts,
        alerts=alerts,
        indices=indices,
        indices_as_of=indices_as_of,
        health=health,
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
