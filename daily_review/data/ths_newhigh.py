#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
data.ths_newhigh：同花顺创新高数据源（不做业务判断）

职责：
- 抓取同花顺创新高榜单页面
- 解析 创月/半年/一年/历史新高 的个股列表
- 落盘到 cache_online/ths_newhigh-YYYYMMDD.json

设计约定：
- 仅负责数据抓取与轻量结构化，不在这里做推荐判断
- 抓取失败时保留 error 字段，调用方决定是否回退上一次缓存
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import urllib.error
import urllib.request
from html import unescape
from pathlib import Path
from typing import Any

from daily_review.cache_io import read_json, write_json


BASE_URL = "https://data.10jqka.com.cn/rank/cxg/"

_UA_DESKTOP = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)

_BOARD_TO_LABEL = {
    1: "创月新高",
    2: "半年新高",
    3: "一年新高",
    4: "历史新高",
}


def _now_bj_str() -> str:
    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def _http_get_text(url: str, *, timeout: int = 20) -> str:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _UA_DESKTOP)
    req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
    req.add_header("Referer", BASE_URL)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _clean_text(text: Any) -> str:
    return re.sub(r"\s+", " ", unescape(str(text or ""))).strip()


def _clean_code(text: Any) -> str:
    digits = re.sub(r"\D", "", str(text or ""))
    return digits[-6:] if len(digits) >= 6 else digits


def _extract_tbody(html: str) -> str:
    m = re.search(r"<tbody[^>]*>(.*?)</tbody>", html, flags=re.I | re.S)
    return m.group(1) if m else ""


def _strip_tags(html: str) -> str:
    return _clean_text(re.sub(r"<[^>]+>", " ", str(html or "")))


def _extract_cell_htmls(tr_html: str) -> list[str]:
    return re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr_html, flags=re.I | re.S)


def _extract_href_code(cell_html: str) -> str:
    href_match = re.search(r"/stock/([0-9A-Za-z]+)\.html", cell_html, flags=re.I)
    return _clean_code(href_match.group(1)) if href_match else ""


def _parse_board_rows(html: str, *, board: int) -> list[dict[str, Any]]:
    tbody = _extract_tbody(html)
    if not tbody:
        return []
    rows: list[dict[str, Any]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody, flags=re.I | re.S):
        cells = _extract_cell_htmls(tr)
        if len(cells) < 5:
            continue
        code = _extract_href_code(cells[1]) or _clean_code(_strip_tags(cells[1]))
        name = _strip_tags(cells[2])
        if not code or not name:
            continue
        rows.append(
            {
                "board": board,
                "boardLabel": _BOARD_TO_LABEL.get(board, ""),
                "code": code,
                "name": name,
                "latest": _strip_tags(cells[3]) if len(cells) > 3 else "",
                "preHigh": _strip_tags(cells[4]) if len(cells) > 4 else "",
                "preHighDate": _strip_tags(cells[5]) if len(cells) > 5 else "",
                "intervalDays": _strip_tags(cells[6]) if len(cells) > 6 else "",
            }
        )
    return rows


def fetch_newhigh_board(*, board: int, page: int = 1, timeout: int = 20) -> dict[str, Any]:
    board_id = int(board)
    page_no = max(1, int(page or 1))
    url = BASE_URL if board_id == 1 and page_no == 1 else f"{BASE_URL}board/{board_id}/page/{page_no}/"
    try:
        html = _http_get_text(url, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"url": url, "ok": False, "error": str(e), "rows": []}
    rows = _parse_board_rows(html, board=board_id)
    return {"url": url, "ok": bool(rows), "rows": rows, "html_length": len(html)}


def cache_path_newhigh(root: Path, date: str) -> Path:
    d8 = str(date or "").replace("-", "")
    return root / "cache_online" / f"ths_newhigh-{d8}.json"


def save_newhigh_snapshot(
    *,
    root: Path,
    date: str,
    mode: str = "eod",
    note: str = "",
    boards: list[int] | tuple[int, ...] = (1, 2, 3, 4),
) -> Path:
    now_bj = _now_bj_str()
    by_board: dict[str, Any] = {}
    all_rows: list[dict[str, Any]] = []
    for board in boards:
        resp = fetch_newhigh_board(board=int(board))
        by_board[str(board)] = {
            "board": int(board),
            "label": _BOARD_TO_LABEL.get(int(board), ""),
            "url": resp.get("url"),
            "ok": bool(resp.get("ok")),
            "error": resp.get("error") or "",
            "count": len(resp.get("rows") or []),
        }
        all_rows.extend(resp.get("rows") or [])

    payload = {
        "schema": "ths_newhigh_v1",
        "date": date,
        "updated_at_bj": now_bj,
        "mode": mode,
        "note": note,
        "source": "ths_cxg_page",
        "boards": by_board,
        "rows": all_rows,
    }
    path = cache_path_newhigh(root, date)
    write_json(path, payload)
    return path


def load_latest_newhigh(root: Path, date: str) -> dict[str, Any]:
    return read_json(cache_path_newhigh(root, date), default={})
