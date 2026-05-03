from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class PlateRotateFetcher:
    """
    短线侠板块轮动抓取器（开盘啦口径）
    - 抓 TOP 表格（含多日期）
    - 抓每个板块对应的领涨龙头（按日期列）
    - 抓每个板块 20 日强度/量能序列
    """

    base_url: str = "https://www.duanxianxia.com"
    timeout: int = 25

    def _session(self) -> Any:
        try:
            import requests  # type: ignore
        except Exception as e:
            raise RuntimeError("缺少 requests 依赖，无法在线抓取板块轮动；请改用本地 plate_rotate_cache.json") from e
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
                )
            }
        )
        # 预热 cookie / session
        s.get(f"{self.base_url}/web/platerotat", timeout=self.timeout)
        return s

    @staticmethod
    def _extract_dates(header_html: str) -> List[str]:
        return re.findall(r">(20\d{2}-\d{2}-\d{2})<", header_html)

    @staticmethod
    def _parse_cell(cell_html: str) -> Dict[str, Any]:
        code_m = re.search(r"code='(\d+)'", cell_html)
        name_m = re.search(r"name='([^']+)'", cell_html)
        # 强度数值可能带红色 span
        nums = re.findall(r">(-?\d+(?:\.\d+)?)<", cell_html)
        strength = None
        if nums:
            try:
                strength = float(nums[-1])
            except Exception:
                strength = None
        return {
            "code": code_m.group(1) if code_m else "",
            "name": name_m.group(1) if name_m else "",
            "strength": strength,
        }

    @staticmethod
    def _split_rows(html: str) -> List[str]:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S)
        return rows

    @staticmethod
    def _split_tds(row_html: str) -> List[str]:
        return re.findall(r"<td[^>]*>.*?</td>", row_html, flags=re.S)

    @staticmethod
    def _strip_tag_text(s: str) -> str:
        x = re.sub(r"<[^>]+>", "", s)
        return re.sub(r"\\s+", " ", x).strip()

    @staticmethod
    def _parse_long_cell(cell_html: str) -> List[Dict[str, str]]:
        # <div class='kline' code='688531'><span>龙一</span>日联科技</div>
        out: List[Dict[str, str]] = []
        for m in re.finditer(
            r"<div\s+class='kline'\s+code='(\d+)'[^>]*>\s*<span>([^<]+)</span>\s*([^<]+)</div>",
            cell_html,
            flags=re.S,
        ):
            out.append({"rank": m.group(2).strip(), "name": m.group(3).strip(), "code": m.group(1).strip()})
        if not out and "当日无领涨" in cell_html:
            out.append({"rank": "", "name": "当日无领涨", "code": ""})
        return out

    def fetch_kaipan_days(self, *, days: int = 20) -> Dict[str, Any]:
        s = self._session()
        api = f"{self.base_url}/api"
        # 1) 获取板块轮动表格
        rot = s.post(
            f"{api}/getPlateRotatData",
            data={"from": "kaipan", "days": str(days), "dates": "0"},
            timeout=self.timeout,
        ).json()
        html = str(rot.get("html") or "")
        rows = self._split_rows(html)
        if not rows:
            return {"dates": [], "by_day": {}}

        header_tds = self._split_tds(rows[0])
        dates: List[str] = []
        for td in header_tds[1:]:
            t = self._strip_tag_text(td)
            if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", t):
                dates.append(t)
        # 10 个排名行：rows[1:11]
        rank_rows = rows[1:11]
        # by_day[date] = rows(list)
        by_day: Dict[str, Dict[str, Any]] = {d: {"rows": [], "leaders": []} for d in dates}

        # 先收集每个日期的 top10（含 code/name/strength）
        for rr in rank_rows:
            tds = self._split_tds(rr)
            if len(tds) < 2:
                continue
            rank_text = self._strip_tag_text(tds[0])
            try:
                rank_no = int(re.findall(r"\d+", rank_text)[0])
            except Exception:
                continue
            for idx, d in enumerate(dates, start=1):
                if idx >= len(tds):
                    continue
                cell = self._parse_cell(tds[idx])
                row_obj = {
                    "rank": rank_no,
                    "name": cell.get("name") or "",
                    "code": cell.get("code") or "",
                    "strength": cell.get("strength"),
                }
                by_day[d]["rows"].append(row_obj)

        # 2) 收集全窗口出现过的板块 code，逐个补领涨 + 量能/强度序列
        unique_codes = sorted(
            {
                str(row.get("code") or "")
                for d in dates
                for row in (by_day.get(d, {}).get("rows") or [])
                if str(row.get("code") or "")
            }
        )
        detail_map: Dict[str, Dict[str, Any]] = {}
        mmdd_to_full = {d[5:]: d for d in dates if len(d) >= 10}

        for code in unique_codes:
            # 领涨龙头（按日期列）
            try:
                ljs = s.post(
                    f"{api}/getLongByPlate",
                    data={"platecode": code, "days": str(days), "dates": "0"},
                    timeout=self.timeout,
                ).json()
            except Exception:
                ljs = {}
            long_html = str(ljs.get("html") or "")
            long_tds = self._split_tds(long_html)
            leaders_by_date: Dict[str, List[Dict[str, str]]] = {}
            for i, d in enumerate(dates, start=1):
                if i >= len(long_tds):
                    continue
                leaders_by_date[d] = self._parse_long_cell(long_tds[i])

            # 强度/量能（日序列）
            try:
                djs = s.post(
                    f"{api}/getPlateDayChart",
                    data={"platecode": code, "days": str(days), "dates": "0"},
                    timeout=self.timeout,
                ).json()
            except Exception:
                djs = {}
            strength_by_date: Dict[str, Any] = {}
            volume_by_date: Dict[str, Any] = {}
            chart_dates = djs.get("date") or []
            series1 = djs.get("series1") or []
            series2 = djs.get("series2") or []
            for idx, mmdd in enumerate(chart_dates):
                full_date = mmdd_to_full.get(str(mmdd))
                if not full_date:
                    continue
                if idx < len(series1):
                    strength_by_date[full_date] = series1[idx]
                if idx < len(series2):
                    volume_by_date[full_date] = series2[idx]

            detail_map[code] = {
                "legend": djs.get("legend"),
                "date": chart_dates,
                "strengthSeries": series1,
                "volumeSeries": series2,
                "leadersByDate": leaders_by_date,
                "strengthByDate": strength_by_date,
                "volumeByDate": volume_by_date,
            }

        # 3) 回填到每个日期的 top10 行
        for d in dates:
            rows_d = by_day.get(d, {}).get("rows") or []
            for row in rows_d:
                code = str(row.get("code") or "")
                detail = detail_map.get(code) or {}
                leaders = ((detail.get("leadersByDate") or {}).get(d) or [])
                row["leaders"] = leaders
                row["lead"] = leaders[0]["name"] if leaders else ""
                row["leadCode"] = leaders[0]["code"] if leaders and leaders[0].get("code") else ""
                row["volume"] = ((detail.get("volumeByDate") or {}).get(d))
                row["strengthByDate"] = ((detail.get("strengthByDate") or {}).get(d))
            by_day[d]["detailByCode"] = {
                str(row.get("code") or ""): detail_map.get(str(row.get("code") or ""), {})
                for row in rows_d
                if str(row.get("code") or "")
            }

        return {"dates": dates, "by_day": by_day, "source": f"{self.base_url}/web/platerotat"}
