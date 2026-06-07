from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class MarketDataAsOf(TypedDict, total=False):
    indices: str
    pools: str
    themes: str
    quotes: str
    plate_rotate: str


class MarketDataMeta(TypedDict, total=False):
    asOf: MarketDataAsOf
    version: str
    generatedAt: str
    mode: str
    snapshotTime: str
    preservedFromDate: str
    preserveReason: str
    rendered_at_bj: str


class MarketDataRaw(TypedDict, total=False):
    pools: dict[str, Any]
    themes: dict[str, Any]
    index_klines: dict[str, Any]
    indices_realtime: dict[str, Any]
    theme_trend_cache: dict[str, Any]
    quotes: dict[str, Any]


class MarketDataFeatures(TypedDict, total=False):
    mood_inputs: dict[str, Any]
    chart_palette: Any


class MarketData(TypedDict, total=False):
    date: str
    dateNote: str
    meta: MarketDataMeta
    raw: MarketDataRaw
    features: MarketDataFeatures
    indices: list[dict[str, Any]]
    panorama: dict[str, Any]
    volume: dict[str, Any]
    sectors: list[dict[str, Any]]
    themePanels: dict[str, Any]
    themeTrend: dict[str, Any]
    heightTrend: dict[str, Any]
    ladder: list[dict[str, Any]]
    top10: list[dict[str, Any]]
    top10Summary: dict[str, Any]
    mood: dict[str, Any]
    moodStage: dict[str, Any]
    moodCards: list[dict[str, Any]]
    learningNotes: dict[str, Any]
    leaders: list[dict[str, Any]]
    ztgc: list[dict[str, Any]]
    zt_code_themes: dict[str, Any]
    ladderDecision: dict[str, Any]
    sentimentDecision: dict[str, Any]
    planDecision: dict[str, Any]
    shortlineDecision: dict[str, Any]
    preservedResearch: dict[str, Any]
    stockResearchBacktest: dict[str, Any]
    intradaySnapshots: dict[str, Any]
    delta: dict[str, Any]
    prev: dict[str, Any]


class PreservedResearchSnapshot(TypedDict, total=False):
    marketData: MarketData
    preservedFromDate: str
    preserveReason: str


class IntradaySnapshot(TypedDict, total=False):
    time: str
    ts_bj: str
    date: str
    source: str
    headline: str
    heat: float | int
    risk: float | int
    fb: float | int
    jj: float | int
    zt: int
    lianban: int
    zab: int
    zb: float | int
    dt: float | int
    bf: float | int
    max_lb: int
    amount: str
    loss: float | int
    hm2: float | int
    pos: list[Any]
    riskSignals: list[Any]
    shift_score: int
    shift_label: str
