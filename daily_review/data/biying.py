#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
data.biying：外部数据源访问（不做业务判断）

覆盖：
- 指数实时：hsindex/real/time
- 指数日K：hsindex/latest/history（用于交易日与量能）
- 三池：hslt/{pool}/{date}
- 个股题材：hszg/zg/{code6}
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional, Sequence, Tuple

from daily_review.http import HttpClient


def _extract_trade_dates(items: Any) -> list[str]:
    """
    从指数K线条目提取“真实交易日”列表。
    过滤规则：
    - sf=1：占位/停牌/未收盘
    - a<=0 或 v<=0：无成交的占位数据
    """
    out: list[str] = []
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        t = it.get("t", "")
        if not (isinstance(t, str) and len(t) >= 10):
            continue
        sf = int(it.get("sf", 0) or 0)
        a = float(it.get("a", 0) or 0)
        v = float(it.get("v", 0) or 0)
        if sf == 1:
            continue
        if a <= 0 or v <= 0:
            continue
        out.append(t[:10])
    return out


def get_recent_trade_dates(client: HttpClient, *, n: int = 15) -> list[str]:
    """
    从指数日K提取最近交易日列表，用于非交易日回退。
    """
    def _unwrap(resp: Any) -> Any:
        """
        必盈接口偶发会返回 dict 包裹结构（如 data/items/result/list），此处做轻量兼容。
        """
        if isinstance(resp, list):
            return resp
        if not isinstance(resp, dict):
            return resp
        for k in ("data", "items", "list", "result", "rows", "klines", "kline", "resultObj"):
            v = resp.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict) and isinstance(v.get("items"), list):
                return v.get("items")
        # 兜底：找第一个 list 值
        for v in resp.values():
            if isinstance(v, list):
                return v
        return resp

    # 兼容：指数代码备用（某些环境 000001.SH 可能权限/路径异常）
    codes = ("000001.SH", "399001.SZ", "399006.SZ")
    for code in codes:
        try:
            url = f"{client.base_url}/hsindex/latest/{code}/d/{client.token}?lt={max(n, 12)}"
            data = client.get_json(url)
            items = _unwrap(data)
            uniq = sorted(set(_extract_trade_dates(items)))
            if uniq:
                return uniq[-n:] if len(uniq) >= n else uniq
        except Exception:
            continue
    return []


def resolve_trade_date(client: HttpClient, requested_date: str | None) -> tuple[str, str]:
    """
    将非交易日请求自动回退到最近交易日。
    返回：(date, date_note)
    """
    if not requested_date:
        # 默认用今天；若非交易日则回退
        requested_date = _dt.datetime.now().strftime("%Y-%m-%d")
    note = ""
    try:
        _dt.datetime.strptime(requested_date, "%Y-%m-%d")
    except Exception:
        return requested_date, ""

    dates = get_recent_trade_dates(client, n=20)
    if not dates:
        return requested_date, ""
    if requested_date in dates:
        return requested_date, ""
    # 回退：取 <= requested_date 的最近一个
    past = [d for d in dates if d <= requested_date]
    if past:
        actual = past[-1]
        note = f"非交易日自动回退到最近交易日：{actual}"
        return actual, note
    return requested_date, ""


def resolve_trade_date_intraday(client: HttpClient, requested_date: str | None) -> tuple[str, str]:
    """
    盘中模式的日期解析：
    - 目标是“尽量渲染当天盘中数据”，避免因为指数日K存在 sf=1 占位而把当天回退成昨日。

    规则：
    1) requested_date 为空 → 取今天（按运行环境 TZ）
    2) 如果 requested_date 本身就是最近交易日列表中的一天 → 直接使用
    3) 如果 requested_date == 今天 且 今天 > 最近交易日列表最后一天（通常代表“今日尚未收盘/指数日K占位被过滤”）
       → 仍然使用今天，并返回注释说明（盘中数据）
    4) 其他情况 → 沿用 resolve_trade_date 的回退逻辑
    """
    if not requested_date:
        requested_date = _dt.datetime.now().strftime("%Y-%m-%d")
    try:
        _dt.datetime.strptime(requested_date, "%Y-%m-%d")
    except Exception:
        return requested_date, ""

    today = _dt.datetime.now().strftime("%Y-%m-%d")
    dates = get_recent_trade_dates(client, n=20)
    if not dates:
        return requested_date, ""

    if requested_date in dates:
        return requested_date, ""

    # 盘中兜底：允许使用“今天”（即使指数日K占位被过滤）
    if requested_date == today and today > dates[-1]:
        return requested_date, f"盘中模式：使用当日盘中数据（指数日K可能尚未收盘，忽略回退：{dates[-1]}）"

    return resolve_trade_date(client, requested_date)


def fetch_indices_realtime(client: HttpClient, codes: Sequence[tuple[str, str]]) -> tuple[list[dict[str, Any]], str]:
    """
    获取主要指数实时数据。
    返回：(indices, as_of_time)
    """
    out: list[dict[str, Any]] = []
    as_of = ""
    for code, name in codes:
        url = f"{client.base_url}/hsindex/real/time/{code}/{client.token}"
        rt = client.get_json(url) or {}
        t = str(rt.get("t", "") or "")
        if t:
            as_of = t

        # 兼容口径：部分接口字段含义容易混淆
        # - p: 当前价
        # - yc: 昨收
        # - ud: 涨跌额
        # - pc: 涨跌幅（有些数据源也可能返回 0/缺失）
        p = float(rt.get("p", 0) or 0)
        yc = float(rt.get("yc", 0) or 0)
        ud = float(rt.get("ud", 0) or 0)
        pc = rt.get("pc", None)
        try:
            pc = float(pc) if pc is not None else None
        except Exception:
            pc = None
        chg_pct = ((p - yc) / yc * 100.0) if yc > 0 else (pc if pc is not None else (ud / p * 100.0 if p else 0.0))
        out.append(
            {
                "name": name,
                "code": code,
                "val": p,
                "chg": chg_pct,  # %
                "cje": float(rt.get("cje", 0) or 0),  # 元
                "t": t,
            }
        )
    # as_of 只展示 HH:MM:SS
    as_of_short = as_of[11:19] if len(as_of) >= 19 else as_of
    return out, (as_of_short or _dt.datetime.now().strftime("%H:%M:%S"))


def fetch_pool(client: HttpClient, *, pool_name: str, date: str) -> list[dict[str, Any]]:
    """
    三池/强势池：hslt/{pool}/{date}
    """
    path = f"hslt/{pool_name}/{date}"
    data = client.api(path, exit_on_404=False, quiet_404=True)
    return data if isinstance(data, list) else []


def fetch_index_latest_k(client: HttpClient, *, code: str, lt: int = 5) -> list[dict[str, Any]]:
    url = f"{client.base_url}/hsindex/latest/{code}/d/{client.token}?lt={max(lt, 5)}"
    data = client.get_json(url)
    return data if isinstance(data, list) else []


def fetch_index_history_k(client: HttpClient, *, code: str, st: str, et: str) -> list[dict[str, Any]]:
    url = f"{client.base_url}/hsindex/history/{code}/d/{client.token}?st={st}&et={et}"
    data = client.get_json(url)
    return data if isinstance(data, list) else []


def get_trading_days_from_index_k(client: HttpClient, *, date: str, n: int = 7) -> list[str]:
    """
    用指数日K确定最近 n 个交易日（参考 gen_report_v4 的策略）。
    """
    if n <= 5:
        sh = fetch_index_latest_k(client, code="000001.SH", lt=n)
        sz = fetch_index_latest_k(client, code="399001.SZ", lt=n)
        uniq = sorted(set(_extract_trade_dates(sh) + _extract_trade_dates(sz)))
        return uniq[-n:] if len(uniq) >= n else uniq

    et = date.replace("-", "")
    st_dt = (_dt.datetime.strptime(date, "%Y-%m-%d") - _dt.timedelta(days=40)).strftime("%Y%m%d")
    sh = fetch_index_history_k(client, code="000001.SH", st=st_dt, et=et)
    sz = fetch_index_history_k(client, code="399001.SZ", st=st_dt, et=et)
    uniq = sorted(set(_extract_trade_dates(sh) + _extract_trade_dates(sz)))
    uniq = [d for d in uniq if d <= date]
    return uniq[-n:] if len(uniq) >= n else uniq


def normalize_stock_code(code: str) -> str:
    """
    统一 code 为 6 位数字。
    """
    digits = "".join([c for c in str(code or "") if c.isdigit()])
    return digits[-6:] if len(digits) >= 6 else digits


def fetch_stock_themes(client: HttpClient, *, code6: str) -> list[dict[str, Any]]:
    """
    获取个股题材原始列表（不做过滤）。
    """
    url = f"{client.base_url}/hszg/zg/{code6}/{client.token}"
    data = client.get_json(url)
    return data if isinstance(data, list) else []


# === 个股行情（v3扩展）===

def fetch_stock_realtime(client: HttpClient, code6: str) -> dict | None:
    """获取个股实时行情。

    Args:
        client: HTTP客户端
        code6: 6位股票代码，如 600519

    Returns:
        行情dict或None
    端点: hsrl/ssjy/{code}/{token}
    """
    try:
        path = f"hsrl/ssjy/{code6}/{client.token}"
        data = client.api(path)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None


def fetch_stocks_realtime(client: HttpClient, stock_codes: str) -> list:
    """获取多只股票实时批量行情。

    Args:
        client: HTTP客户端
        stock_codes: 逗号分隔的股票代码字符串，如 "600519,000858"

    Returns:
        行情列表
    端点: hsrl/ssjy_more/{token}?stock_codes={codes}
    """
    try:
        url = f"{client.base_url}/hsrl/ssjy_more/{client.token}?stock_codes={stock_codes}"
        data = client.get_json(url)
        # 兼容：部分返回为 {"data":[...]} 或 {"list":[...]}
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for k in ("data", "list", "items", "result"):
                v = data.get(k)
                if isinstance(v, list):
                    return v
        return []
    except Exception:
        return []


# === K线数据（v3扩展）===

def fetch_stock_latest_k(
    client: HttpClient,
    *,
    code: str,          # 如 "600519.SH"
    period: str = "d",  # d/w/m
    adjust: str = "f",  # f前复权/n不复权
    lt: int = 30,       # 最近N根
) -> list:
    """获取个股日K线数据。

    Args:
        client: HTTP客户端
        code: 股票代码含市场后缀，如 "600519.SH"
        period: 周期 d=日 w=周 m=月
        adjust: 复权方式 f=前复权 n=不复权
        lt: 返回最近N根K线

    Returns:
        K线数据列表
    端点: hsstock/latest/{code}.{market}/{period}/{adjust}/{token}?lt=N
    """
    try:
        url = f"{client.base_url}/hsstock/latest/{code}/{period}/{adjust}/{client.token}?lt={max(lt, 1)}"
        data = client.get_json(url)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def fetch_stock_history_k(
    client: HttpClient,
    *,
    code: str,
    period: str = "d",
    adjust: str = "f",
    st: str = "",   # YYYYMMDD
    et: str = "",   # YYYYMMDD
) -> list:
    """获取个股历史日K线数据。

    Args:
        client: HTTP客户端
        code: 股票代码如 "600519.SH"
        period: 周期 d/w/m
        adjust: 复权方式 f/n
        st: 起始日期 YYYYMMDD
        et: 结束日期 YYYYMMDD

    Returns:
        K线数据列表
    端点: hsstock/history/{code}/{period}/{adjust}/{token}?st=&et=
    """
    try:
        base_url = f"{client.base_url}/hsstock/history/{code}/{period}/{adjust}/{client.token}"
        params = []
        if st:
            params.append(f"st={st}")
        if et:
            params.append(f"et={et}")
        url = f"{base_url}?{'&'.join(params)}"
        data = client.get_json(url)
        return data if isinstance(data, list) else []
    except Exception:
        return []


# === 技术指标（v3扩展）===

def fetch_stock_indicator(
    client: HttpClient,
    *,
    code: str,
    indicator: str,      # macd / ma / boll / kdj
    period: str = "d",
    adjust: str = "f",
    lt: int = 100,
) -> list:
    """获取技术指标数据。

    Args:
        client: HTTP客户端
        code: 股票代码如 "600519.SH"
        indicator: 指标类型 macd/ma/boll/kdj
        period: 周期 d/w/m
        adjust: 复权方式
        lt: 返回最近N个数据点

    Returns:
        指标数据列表
    端点: hsstock/history/{indicator}/{code}/{period}/{adjust}/{token}?lt=N
    """
    try:
        valid_indicators = {"macd", "ma", "boll", "kdj"}
        if indicator not in valid_indicators:
            raise ValueError(f"不支持的indicator: {indicator}，可选 {valid_indicators}")
        url = (
            f"{client.base_url}/hsstock/history/{indicator}/{code}"
            f"/{period}/{adjust}/{client.token}?lt={max(lt, 1)}"
        )
        data = client.get_json(url)
        return data if isinstance(data, list) else []
    except Exception:
        return []


# === 资金流向（v3扩展）===

def fetch_stock_money_flow(
    client: HttpClient,
    *,
    code: str,
    st: str = "",
    et: str = "",
) -> dict | None:
    """获取个股资金流向（大单动向）数据。

    Args:
        client: HTTP客户端
        code: 股票代码如 "600519.SH"
        st: 起始日期 YYYYMMDD
        et: 结束日期 YYYYMMDD

    Returns:
        资金流向字典或None
    端点: hsstock/history/transaction/{code}/...
    """
    try:
        base_url = f"{client.base_url}/hsstock/history/transaction/{code}/{client.token}"
        params = []
        if st:
            params.append(f"st={st}")
        if et:
            params.append(f"et={et}")
        url = f"{base_url}?{'&'.join(params)}"
        data = client.get_json(url)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


# === 财务数据（v3扩展）===

def fetch_financial_indicators(client: HttpClient, *, code6: str) -> dict | None:
    """获取财务指标100+项(ROE/PE/PB等)。

    Args:
        client: HTTP客户端
        code6: 6位股票代码，如 600519

    Returns:
        财务指标字典或None
    端点: hscp/cwzb/{code6}/{token}
    """
    try:
        path = f"hscp/cwzb/{code6}/{client.token}"
        data = client.api(path)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None


def fetch_income_statement(client: HttpClient, *, code6: str) -> list | None:
    """获取季度利润表。

    Args:
        client: HTTP客户端
        code6: 6位股票代码

    Returns:
        利润表列表或None
    端点: hscp/jdlr/{code6}/{token}
    """
    try:
        path = f"hscp/jdlr/{code6}/{client.token}"
        data = client.api(path)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return None


def fetch_top_shareholders(client: HttpClient, *, code6: str) -> list | None:
    """获取十大股东信息。

    Args:
        client: HTTP客户端
        code6: 6位股票代码

    Returns:
        十大股东列表或None
    端点: hscp/sdgd/{code6}/{token}
    """
    try:
        path = f"hscp/sdgd/{code6}/{client.token}"
        data = client.api(path)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return None


def fetch_float_shareholders(client: HttpClient, *, code6: str) -> list | None:
    """获取十大流通股东信息。

    Args:
        client: HTTP客户端
        code6: 6位股票代码

    Returns:
        十大流通股东列表或None
    端点: hscp/ltgd/{code6}/{token}
    """
    try:
        path = f"hscp/ltgd/{code6}/{client.token}"
        data = client.api(path)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return None


# === 五档盘口（v3扩展）===

def fetch_five_level(client: HttpClient, *, code: str, market: str) -> dict | None:
    """获取五档买卖盘口数据。

    Args:
        client: HTTP客户端
        code: 股票代码如 "600519"
        market: 市场代码如 "SH"

    Returns:
        五档盘口字典或None
    端点: hsstock/real/five/{code}.{market}/...
    """
    try:
        url = f"{client.base_url}/hsstock/real/five/{code}.{market}/{client.token}"
        data = client.get_json(url)
        return data if isinstance(data, dict) else None
    except Exception:
        return None
