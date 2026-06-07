#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
features.sector_resolver：板块/题材归一化与个股多板块归属

职责（纯逻辑，仅 read_json，不发起网络 I/O）：
- 读取 cache_online 中的 4 路缓存（选股宝异动/选股宝板块/东财主题/东财主题成份股）
- 维护板块名 ALIAS_MAP + 产业链 CHAIN_MAP
- 输出：
  · stock_to_sectors:  {code6: [(sector, confidence, sources)]}
  · sector_to_info:    {sector: SectorInfo(rank/zt/hot/event_count/...)}
  · chain_groups:      {"半导体": ["先进封装", ...]}

输入约定（cache_online/）：
- xuangubao_abnormal-YYYYMMDD.json     → save_abnormal_snapshot 落盘
- xuangubao_surge_plates-YYYYMMDD.json → save_surge_plates_snapshot 落盘
- eastmoney_tomorrow_themes-YYYYMMDD.json  → save_tomorrow_snapshot 落盘
- eastmoney_theme_stocks-YYYYMMDD.json     → 同上

非职责：
- 不做评分（M4 ladder_builder）
- 不做主线判定（M4）
- 不做候选池筛选（后续 watch 流程）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from daily_review.data.xuangubao import (
    load_latest_abnormal,
    load_latest_surge_plates,
)
from daily_review.data.eastmoney_theme import (
    load_latest_tomorrow_themes,
    load_latest_theme_stocks,
)


# ---------------------------------------------------------------------------
# 常量：板块同义映射 + 产业链分组
# ---------------------------------------------------------------------------

#
# 板块名归一化映射：alias → canonical
# - 维护原则：当观察到跨源（选股宝/东财/必盈）对同一题材给出不同命名时补一条
# - 单向映射：alias → canonical；canonical 自身不入表
#
ALIAS_MAP: dict[str, str] = {
    # 半导体链
    "高端封装": "先进封装",
    "Chiplet": "先进封装",
    "半导体封测": "先进封装",
    "存储芯片": "存储",
    "国产芯片": "半导体",
    "芯片": "半导体",
    "MLCC": "被动元件",
    "光刻机": "光刻机",
    "光刻胶": "光刻胶",
    "ASML": "光刻机",
    # 算力 / AI / 通信
    "光通信": "光模块",
    "CPO": "光模块",
    "云计算数据中心": "数据中心",
    "数据中心": "算力",
    "液冷服务器": "液冷",
    "算力租赁": "算力",
    "AI算力": "算力",
    "AI大模型": "AI应用",
    "人工智能": "AI应用",
    "AIGC": "AI应用",
    "ChatGPT": "AI应用",
    "多模态AI": "AI应用",
    "Sora概念": "AI应用",
    "英伟达": "英伟达",
    "NVIDIA": "英伟达",
    # 新能源
    "锂电池": "锂电",
    "动力电池": "锂电",
    "光伏发电": "光伏",
    "HJT电池": "光伏",
    "BC电池": "光伏",
    "TOPCon电池": "光伏",
    "固态电池": "固态电池",
    "新能源汽车": "新能源车",
    "智能电网": "电力",
    "电力改革": "电力",
    "电力行业": "电力",
    "绿色电力": "电力",
    "绿电": "电力",
    "清洁能源": "电力",
    "数字能源": "电力",
    "火电": "电力",
    "水电": "电力",
    "风电": "电力",
    "风能": "电力",
    "海上风电": "电力",
    "核电": "电力",
    "虚拟电厂": "电力",
    "特高压": "电力",
    # 煤炭
    "动力煤": "煤炭",
    "焦煤": "煤炭",
    "焦炭": "煤炭",
    "煤炭开采": "煤炭",
    "煤电": "煤炭",
    # 机器人
    "人形机器人": "机器人",
    "具身智能": "机器人",
    "机器视觉": "机器人",
    "减速器": "机器人",
    # 低空经济 / 航天
    "飞行汽车": "低空经济",
    "eVTOL": "低空经济",
    "空管": "低空经济",
    "卫星互联网": "商业航天",
    "卫星导航": "商业航天",
    "千帆星座": "商业航天",
    "商业航天": "商业航天",
    # 东财/本地板块推测里偶尔会带行业后缀，统一并回商业航天主线。
    "商业航天（航天航空）": "商业航天",
    # 华为 / 智驾
    "华为产业链": "华为",
    "华为手机": "华为",
    "赛力斯": "华为汽车",
    "华为汽车": "华为汽车",
    "无人驾驶": "智能驾驶",
    "车联网": "智能驾驶",
    "智驾": "智能驾驶",
    "萝卜快跑": "智能驾驶",
    # 医药
    "创新药": "生物医药",
    "减肥药": "生物医药",
    "CRO": "生物医药",
    "GLP-1": "生物医药",
    # 软件 / 信创 / 金融
    "互联网金融": "金融科技",
    "移动支付": "金融科技",
    "跨境支付": "金融科技",
    "网络安全": "信息安全",
    "数据安全": "信息安全",
    "国产软件": "软件",
    "计算机软件": "软件",
    "基础软件": "信创",
    "财税数字化": "软件",
    "电子证照": "软件",
    "智慧政务": "软件",
    "数字经济": "软件",
    "智慧灯杆": "新型基建",
    "车路云": "智能驾驶",
    "路侧单元": "智能驾驶",
    "V2X": "智能驾驶",
    # 其他
    "国企改革": "国企改革",
    "央企改革": "国企改革",
    "中字头": "国企改革",
}

#
# 产业链分组：用于 spec 里 "TOP3 板块产业链联动 → 合并主线" 的判定
# - canonical 必须是 ALIAS_MAP 归一化后的名字
#
CHAIN_MAP: dict[str, list[str]] = {
    "半导体": [
        "半导体", "先进封装", "PCB板", "光模块", "存储", "被动元件",
        "科特估", "玻璃基板", "CPO", "PCB", "大基金", "光刻机", "光刻胶",
    ],
    "新能源": [
        "锂电", "光伏", "储能", "充电桩", "固态电池", "新能源车", "锂电池",
        "钠电池", "风电", "氢能", "虚拟电厂",
    ],
    "机器人": [
        "机器人", "减速器", "传感器", "PEEK材料", "机器视觉", "伺服电机", "丝杠",
    ],
    "AI算力": [
        "算力", "光模块", "液冷", "云计算", "AI应用", "光通信", "液冷服务器",
        "数据中心", "算力租赁", "交换机", "服务器",
    ],
    "低空经济": [
        "低空经济", "飞行汽车", "无人机", "eVTOL", "空管", "航空发动机",
        "螺旋桨", "碳纤维", "机场基建",
    ],
    "商业航天": [
        "商业航天", "商业航天（航天航空）", "卫星互联网", "卫星导航", "运载火箭", "卫星制造", "测控",
        "地面站", "千帆星座", "星网",
    ],
    "华为产业链": [
        "华为", "华为鸿蒙", "华为昇腾", "华为鲲鹏", "华为欧拉", "华为海思",
        "华为汽车", "赛力斯", "鸿蒙", "引望",
    ],
    "汽车/智驾": [
        "汽车整车", "无人驾驶", "智能驾驶", "车联网", "激光雷达", "高精地图",
        "域控制器", "智能座舱", "线控底盘", "智驾", "萝卜快跑",
    ],
    "消费电子": [
        "消费电子", "苹果概念", "智能穿戴", "折叠屏", "钛合金", "AI手机",
        "AI PC", "VR/AR", "MR", "混合现实",
    ],
    "软件/信创": [
        "软件", "信创", "信息安全", "金融科技", "云计算", "大数据",
        "操作系统", "数据库", "中间件", "办公软件", "网络安全", "数据安全",
        "财税数字化", "电子证照", "智慧政务", "ERP", "SaaS", "数字经济",
    ],
    "电力": [
        "电力", "电力改革", "电力行业", "绿色电力", "清洁能源", "数字能源",
        "电网设备", "虚拟电厂", "智能电网", "特高压", "配电网", "绿电",
        "抽水蓄能",
    ],
    "煤炭": [
        "煤炭", "动力煤", "焦煤", "焦炭", "煤炭开采", "煤电",
    ],
    "生物医药": [
        "生物医药", "创新药", "CRO", "减肥药", "医疗器械", "中药",
        "细胞免疫治疗", "仿制药",
    ],
    "国企改革": [
        "国企改革", "央企改革", "中字头", "地方国资改革", "上海国企改革",
    ],
}


# ---------------------------------------------------------------------------
# 输出 dataclass
# ---------------------------------------------------------------------------


@dataclass
class SectorVote:
    sector: str          # 归一化后的板块名
    source: str          # xgb_event / xgb_plate / em_theme / em_static / biying_static
    raw_name: str        # 原始名，便于追溯 alias
    weight: float        # 单源权重 0.3~0.6


@dataclass
class StockSectors:
    code: str
    sectors: list[tuple[str, float, list[str]]] = field(default_factory=list)
    # ↑ (sector_canonical, confidence ∈ [0,1], sources_list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "sectors": [
                {"sector": s, "confidence": round(c, 3), "sources": src}
                for (s, c, src) in self.sectors
            ],
        }


@dataclass
class SectorInfo:
    name: str                        # 归一化后名
    aliases: list[str] = field(default_factory=list)
    stocks: list[str] = field(default_factory=list)  # 6位代码
    # 东财明日主题信号
    em_theme_code: str = ""
    em_rank: int | None = None       # sortNum，越小越靠前
    em_zt_count: int = 0             # fex3
    em_cumulate_gain: float = 0.0    # cumulateF3
    em_is_hot: bool = False
    em_title: str = ""
    em_summary: str = ""
    # 选股宝信号
    xgb_plate_id: str = ""
    xgb_description: str = ""        # 当日热点描述（即时叙事）
    event_count: int = 0             # 异动事件中被提及次数

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "aliases": self.aliases,
            "stocks": self.stocks,
            "em_theme_code": self.em_theme_code,
            "em_rank": self.em_rank,
            "em_zt_count": self.em_zt_count,
            "em_cumulate_gain": round(self.em_cumulate_gain, 2),
            "em_is_hot": self.em_is_hot,
            "em_title": self.em_title,
            "em_summary": self.em_summary,
            "xgb_plate_id": self.xgb_plate_id,
            "xgb_description": self.xgb_description,
            "event_count": self.event_count,
        }


@dataclass
class SectorResolution:
    date: str
    stock_to_sectors: dict[str, StockSectors] = field(default_factory=dict)
    sector_to_info: dict[str, SectorInfo] = field(default_factory=dict)
    chain_groups: dict[str, list[str]] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "stock_to_sectors": {k: v.to_dict() for k, v in self.stock_to_sectors.items()},
            "sector_to_info": {k: v.to_dict() for k, v in self.sector_to_info.items()},
            "chain_groups": self.chain_groups,
            "diagnostics": self.diagnostics,
        }


# ---------------------------------------------------------------------------
# 归一化辅助
# ---------------------------------------------------------------------------


_CODE_DIGITS_RE = re.compile(r"\d+")


def normalize_code(raw: Any) -> str:
    """统一为 6 位数字代码。接受 '603398.SS'、'sh603398'、'603398' 等。"""
    s = str(raw or "")
    digits = "".join(_CODE_DIGITS_RE.findall(s))
    return digits[-6:] if len(digits) >= 6 else digits


# 噪音板块名：这些不是真正的"题材"，是市场状态分类标签，应直接过滤
# 与 daily_review/config.py 的 noise_themes 保持一致但拷贝在此（避免循环 import）
NOISE_SECTORS: frozenset[str] = frozenset({
    "破净股", "ST股", "低价股", "强势人气股", "微盘股", "次新股",
    "退市风险", "退市概念", "风险警示", "小盘", "中盘", "大盘",
    "融资融券", "QFII持股", "基金重仓", "深股通", "沪股通",
    "年度强势", "富时罗素", "昨日涨停", "昨日连板", "昨日首板",
})

# 题材名称清理正则：去除常见的前缀和后缀
_SECTOR_CLEAN_RE = re.compile(
    r"^(A股-|概念板块-|行业-|主题-|概念-)|(板块|概念|题材|指数|[-]?概念板块)$"
)


def normalize_sector(raw_name: str) -> str:
    """
    板块名归一化：
    1. strip + 去空格
    2. 正则清理前缀/后缀（如 "A股-芯片概念" -> "芯片"）
    3. 别名表 ALIAS_MAP 映射
    4. 噪音过滤
    """
    if not raw_name:
        return ""

    # 1. 基础清理
    s = str(raw_name).strip().replace(" ", "")
    if not s:
        return ""

    # 2. 移除前缀后缀 (如 A股-概念板块-芯片 -> 芯片)
    cleaned = _SECTOR_CLEAN_RE.sub("", s)
    if not cleaned:
        cleaned = s

    # 3. 别名映射 (优先用清理后的名字找，找不到用原始名字找)
    canonical = ALIAS_MAP.get(cleaned, ALIAS_MAP.get(s, cleaned))

    # 4. 噪音过滤
    if canonical in NOISE_SECTORS:
        return ""

    return canonical


# ---------------------------------------------------------------------------
# 来源权重（4 路）
# ---------------------------------------------------------------------------

# 来源权重设计思路：
# - 选股宝异动是"即时叙事"——板块异动事件 weight 最高（最实时、明确板块归因）
# - 东财主题是"明日预热排行"——含明确成份股 + 排名
# - 必盈静态题材是"长期标签"——置信度低，仅用于补充
SOURCE_WEIGHTS: dict[str, float] = {
    "xgb_plate_event": 0.55,   # 板块异动事件里 related_stocks 命中
    "xgb_stock_event": 0.40,   # 个股异动事件里 related_plates 命中
    "em_theme": 0.55,          # 东财主题成份股命中
    "biying_static": 0.25,     # 必盈静态题材兜底
}


def _combine_confidence(votes: list[SectorVote]) -> tuple[float, list[str]]:
    """
    多源投票 → 最终 confidence。
    - 累计权重，配合"多源加成"：>=2源时再 ×1.15，>=3 源时 ×1.30
    - 上限 1.0
    """
    if not votes:
        return 0.0, []
    weight_sum = sum(v.weight for v in votes)
    unique_sources = sorted({v.source for v in votes})
    multi_bonus = 1.0
    if len(unique_sources) >= 3:
        multi_bonus = 1.30
    elif len(unique_sources) >= 2:
        multi_bonus = 1.15
    confidence = min(1.0, weight_sum * multi_bonus)
    return confidence, unique_sources


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def resolve(
    *,
    root: Path,
    date: str,
    pools_cache: dict[str, Any] | None = None,
    min_confidence: float = 0.30,
) -> SectorResolution:
    """
    主入口：从 cache_online 读取 4 路数据 + 可选 pools_cache，输出 SectorResolution。

    参数：
        root:           workspace 根目录
        date:           交易日 YYYY-MM-DD
        pools_cache:    可选传入已加载的必盈 pools_cache（含静态板块标签）；
                        若为 None，则不使用 biying_static 来源
        min_confidence: 个股板块归属的最小置信度阈值，过滤噪音

    返回：SectorResolution
    """
    abnormal = load_latest_abnormal(root, date)
    surge_plates = load_latest_surge_plates(root, date)
    tomorrow_themes = load_latest_tomorrow_themes(root, date)
    theme_stocks = load_latest_theme_stocks(root, date)

    sector_to_info: dict[str, SectorInfo] = {}
    # votes_by_stock_sector: code -> sector -> list[SectorVote]
    votes_by: dict[str, dict[str, list[SectorVote]]] = {}
    raw_alias_of: dict[str, set[str]] = {}   # canonical → 见过的原始名集合

    def _add_vote(code: str, raw_sector: str, source: str, weight: float) -> None:
        canonical = normalize_sector(raw_sector)
        if not code or not canonical:
            return
        raw_alias_of.setdefault(canonical, set()).add(raw_sector)
        bucket = votes_by.setdefault(code, {}).setdefault(canonical, [])
        bucket.append(SectorVote(sector=canonical, source=source, raw_name=raw_sector, weight=weight))

    def _ensure_info(canonical: str) -> SectorInfo:
        return sector_to_info.setdefault(canonical, SectorInfo(name=canonical))

    # ---- 1) 选股宝异动事件：双向映射 ----
    _ingest_xgb_events(abnormal, _add_vote, _ensure_info)

    # ---- 2) 选股宝当日热点板块：补充 description + plate_id ----
    _ingest_xgb_surge_plates(surge_plates, _ensure_info)

    # ---- 3) 东财明日主题：rank / zt_count / is_hot + stockList ----
    #    同时构建 theme_code → theme_name 映射，给 step4 使用
    theme_code_to_name = _ingest_em_themes(tomorrow_themes, _add_vote, _ensure_info)

    # ---- 4) 东财主题成份股：补充该主题更全的成份股 ----
    _ingest_em_theme_stocks(theme_stocks, theme_code_to_name, _add_vote)

    # ---- 5) 必盈静态题材（可选兜底） ----
    if pools_cache is not None:
        _ingest_biying_static(pools_cache, _add_vote)

    # ---- 6) 聚合 confidence ----
    stock_to_sectors: dict[str, StockSectors] = {}
    for code, sector_map in votes_by.items():
        items: list[tuple[str, float, list[str]]] = []
        for sector, votes in sector_map.items():
            conf, sources = _combine_confidence(votes)
            if conf >= min_confidence:
                items.append((sector, conf, sources))
        items.sort(key=lambda x: x[1], reverse=True)
        if items:
            stock_to_sectors[code] = StockSectors(code=code, sectors=items)

    # ---- 7) 回填 SectorInfo.stocks（通过过滤后的 stock_to_sectors） ----
    for code, ss in stock_to_sectors.items():
        for sector, _conf, _src in ss.sectors:
            info = _ensure_info(sector)
            if code not in info.stocks:
                info.stocks.append(code)

    # ---- 8) 回填 aliases ----
    for canonical, raw_set in raw_alias_of.items():
        info = sector_to_info.get(canonical)
        if not info:
            continue
        info.aliases = sorted(a for a in raw_set if a != canonical)

    # ---- 9) 产业链聚合 ----
    chain_groups: dict[str, list[str]] = {}
    for chain, members in CHAIN_MAP.items():
        hit = [m for m in members if m in sector_to_info]
        if hit:
            chain_groups[chain] = hit

    diagnostics = {
        "abnormal_events": _count_events(abnormal),
        "surge_plates": _count_surge_plates(surge_plates),
        "em_themes": _count_em_themes(tomorrow_themes),
        "em_theme_stocks": _count_em_theme_stocks(theme_stocks),
        "stock_count": len(stock_to_sectors),
        "sector_count": len(sector_to_info),
        "min_confidence": min_confidence,
    }

    return SectorResolution(
        date=date,
        stock_to_sectors=stock_to_sectors,
        sector_to_info=sector_to_info,
        chain_groups=chain_groups,
        diagnostics=diagnostics,
    )


# ---------------------------------------------------------------------------
# 各数据源的 ingest（每个函数只负责"读 + 投票"，不计算 confidence）
# ---------------------------------------------------------------------------


def _iter_abnormal_events(abnormal: dict[str, Any]) -> list[dict[str, Any]]:
    """
    从 save_abnormal_snapshot 落盘结构中合并最新一次 run 的事件列表。
    优先使用 combined（全类型）；回退到 latest.combined。
    """
    if not isinstance(abnormal, dict):
        return []
    latest = abnormal.get("latest") if isinstance(abnormal.get("latest"), dict) else {}
    combined = latest.get("combined") if isinstance(latest.get("combined"), dict) else {}
    raw = combined.get("data") if isinstance(combined.get("data"), dict) else {}
    events = raw.get("data") if isinstance(raw.get("data"), list) else []
    return [e for e in events if isinstance(e, dict)]


def _ingest_xgb_events(
    abnormal: dict[str, Any],
    add_vote,
    ensure_info,
) -> None:
    events = _iter_abnormal_events(abnormal)
    for ev in events:
        # 板块异动：plate_abnormal_event_data.related_stocks
        plate_ev = ev.get("plate_abnormal_event_data") or {}
        if isinstance(plate_ev, dict) and plate_ev.get("plate_name"):
            plate_name = str(plate_ev.get("plate_name") or "")
            plate_id = str(plate_ev.get("plate_id") or "")
            related = plate_ev.get("related_stocks") or []
            canonical = normalize_sector(plate_name)
            if canonical:
                info = ensure_info(canonical)
                info.event_count += 1
                if plate_id and not info.xgb_plate_id:
                    info.xgb_plate_id = plate_id
            for s in related:
                if not isinstance(s, dict):
                    continue
                code = normalize_code(s.get("symbol") or s.get("code") or "")
                if code:
                    add_vote(code, plate_name, "xgb_plate_event", SOURCE_WEIGHTS["xgb_plate_event"])

        # 个股异动：stock_abnormal_event_data.related_plates
        stock_ev = ev.get("stock_abnormal_event_data") or {}
        if isinstance(stock_ev, dict) and stock_ev.get("symbol"):
            code = normalize_code(stock_ev.get("symbol"))
            related_plates = stock_ev.get("related_plates") or []
            if not isinstance(related_plates, list):
                continue
            for p in related_plates:
                if not isinstance(p, dict):
                    continue
                plate_name = str(p.get("plate_name") or "")
                if code and plate_name:
                    add_vote(code, plate_name, "xgb_stock_event", SOURCE_WEIGHTS["xgb_stock_event"])


def _ingest_xgb_surge_plates(
    surge_plates: dict[str, Any],
    ensure_info,
) -> None:
    """
    嵌套路径：cache_file["raw"]["data"]["data"]["items"] → list[{id,name,description}]
    """
    if not isinstance(surge_plates, dict):
        return
    layer1 = surge_plates.get("raw")
    if not isinstance(layer1, dict):
        return
    inner = layer1.get("data")
    if not isinstance(inner, dict):
        return
    payload = inner.get("data") if isinstance(inner.get("data"), dict) else inner
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        # 兜底：递归查找含 name+id 的节点（防止接口结构变化）
        items = []

        def collect(node: Any) -> None:
            if isinstance(node, list):
                for it in node:
                    collect(it)
            elif isinstance(node, dict):
                if node.get("name") and node.get("id") is not None:
                    items.append(node)
                for v in node.values():
                    collect(v)

        collect(payload)

    for it in items:
        if not isinstance(it, dict):
            continue
        plate_name = str(it.get("name") or "")
        plate_id = str(it.get("id") or "")
        desc = str(it.get("description") or "")
        canonical = normalize_sector(plate_name)
        if not canonical:
            continue
        info = ensure_info(canonical)
        if plate_id and not info.xgb_plate_id:
            info.xgb_plate_id = plate_id
        if desc and not info.xgb_description:
            info.xgb_description = desc


def _ingest_em_themes(
    tomorrow_themes: dict[str, Any],
    add_vote,
    ensure_info,
) -> dict[str, str]:
    """
    解析东财明日主题缓存（save_tomorrow_snapshot 落盘结构）。

    嵌套路径：cache_file["raw"]["raw"]["data"] → list[theme]

    返回：theme_code → theme_name 映射，给 _ingest_em_theme_stocks 使用
    """
    out: dict[str, str] = {}
    if not isinstance(tomorrow_themes, dict):
        return out
    layer1 = tomorrow_themes.get("raw")
    if not isinstance(layer1, dict):
        return out
    inner = layer1.get("raw")
    if not isinstance(inner, dict):
        return out
    data = inner.get("data")
    items: list[Any] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        keys = sorted((k for k in data.keys() if str(k).isdigit()), key=lambda k: int(k))
        items = [data[k] for k in keys]

    for it in items:
        if not isinstance(it, dict):
            continue
        theme_name = str(it.get("themeName") or "")
        theme_code = str(it.get("themeCode") or "")
        canonical = normalize_sector(theme_name)
        if not canonical:
            continue
        if theme_code:
            out[theme_code] = theme_name

        info = ensure_info(canonical)
        info.em_theme_code = theme_code
        try:
            sn = int(it.get("sortNum") or 0)
            if sn > 0 and (info.em_rank is None or sn < info.em_rank):
                info.em_rank = sn
        except Exception:
            pass
        try:
            info.em_zt_count = max(info.em_zt_count, int(it.get("fex3") or 0))
        except Exception:
            pass
        try:
            info.em_cumulate_gain = max(info.em_cumulate_gain, float(it.get("cumulateF3") or 0.0))
        except Exception:
            pass
        is_hot_v = it.get("isHot")
        if (is_hot_v == 1) or (str(is_hot_v) == "1"):
            info.em_is_hot = True
        if not info.em_title:
            info.em_title = str(it.get("title") or "")[:200]
        if not info.em_summary:
            info.em_summary = str(it.get("summary") or "")[:400]

        # 主题预览股票（stockList 是部分成份股）
        for s in it.get("stockList") or []:
            if not isinstance(s, dict):
                continue
            code = normalize_code(s.get("code") or "")
            if code:
                add_vote(code, theme_name, "em_theme", SOURCE_WEIGHTS["em_theme"])

    return out


def _ingest_em_theme_stocks(
    theme_stocks: dict[str, Any],
    theme_code_to_name: dict[str, str],
    add_vote,
) -> None:
    """
    解析东财主题成份股缓存（save_tomorrow_snapshot 第二阶段落盘）。

    嵌套路径：cache_file["by_theme"][themeCode]["raw"]["data"]["stockList"] → list[stock]
    依赖 theme_code_to_name 把 themeCode 反查成 themeName 再走 add_vote。
    """
    if not isinstance(theme_stocks, dict) or not theme_code_to_name:
        return
    by_theme = theme_stocks.get("by_theme") if isinstance(theme_stocks.get("by_theme"), dict) else {}
    for tc, resp in by_theme.items():
        theme_name = theme_code_to_name.get(str(tc) or "")
        if not theme_name or not isinstance(resp, dict):
            continue
        raw = resp.get("raw") if isinstance(resp.get("raw"), dict) else None
        d = raw.get("data") if isinstance(raw, dict) else None
        stocks = d.get("stockList") if isinstance(d, dict) else []
        if not isinstance(stocks, list):
            continue
        for s in stocks:
            if not isinstance(s, dict):
                continue
            code = normalize_code(s.get("securityCode") or s.get("codeSuffix") or "")
            if code:
                add_vote(code, theme_name, "em_theme", SOURCE_WEIGHTS["em_theme"])


def _ingest_biying_static(
    pools_cache: dict[str, Any],
    add_vote,
) -> None:
    """
    必盈 pools_cache 中个股的静态板块标签。
    pools_cache 结构通常为 {date: {pool_name: [stock_records]}} 或 {pool_name: [...]}，
    每个 record 含 mc/lbc/cje/plate 等字段。
    这里只在 record 含 plate 字段时投票。
    """

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for it in node:
                walk(it)
        elif isinstance(node, dict):
            code = node.get("mc") or node.get("code") or node.get("symbol")
            plate = node.get("plate") or node.get("sector") or node.get("hy")
            if code and plate:
                c = normalize_code(code)
                if isinstance(plate, str):
                    add_vote(c, plate, "biying_static", SOURCE_WEIGHTS["biying_static"])
                elif isinstance(plate, list):
                    for p in plate:
                        if isinstance(p, str) and p:
                            add_vote(c, p, "biying_static", SOURCE_WEIGHTS["biying_static"])
            # 继续递归（pools_cache 嵌套较深）
            for v in node.values():
                walk(v)

    walk(pools_cache)


# ---------------------------------------------------------------------------
# 诊断计数
# ---------------------------------------------------------------------------


def _count_events(abnormal: dict[str, Any]) -> int:
    return len(_iter_abnormal_events(abnormal))


def _count_surge_plates(surge_plates: dict[str, Any]) -> int:
    if not isinstance(surge_plates, dict):
        return 0
    layer1 = surge_plates.get("raw")
    if not isinstance(layer1, dict):
        return 0
    inner = layer1.get("data")
    if not isinstance(inner, dict):
        return 0
    payload = inner.get("data") if isinstance(inner.get("data"), dict) else inner
    items = payload.get("items") if isinstance(payload, dict) else None
    return len(items) if isinstance(items, list) else 0


def _count_em_themes(tomorrow_themes: dict[str, Any]) -> int:
    if not isinstance(tomorrow_themes, dict):
        return 0
    raw = tomorrow_themes.get("raw")
    if not isinstance(raw, dict):
        return 0
    inner = raw.get("raw") if isinstance(raw.get("raw"), dict) else raw
    d = inner.get("data") if isinstance(inner, dict) else None
    if isinstance(d, list):
        return len(d)
    if isinstance(d, dict):
        return sum(1 for k in d.keys() if str(k).isdigit())
    return 0


def _count_em_theme_stocks(theme_stocks: dict[str, Any]) -> int:
    if not isinstance(theme_stocks, dict):
        return 0
    by = theme_stocks.get("by_theme") or {}
    return len(by) if isinstance(by, dict) else 0
