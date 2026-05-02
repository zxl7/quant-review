#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
短线提醒 / 语录加载器

职责：
- 仅从工作区 `心法.md` 读取候选
- 按标题语义粗分阶段：good / warn / fire
- 基于历史做近 7 日去重轮播
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict


def build_learning_notes(*, market_data: Dict[str, Any], cache_dir: Path) -> Dict[str, Any]:
    """
    学习短线的注意事项 + 1 句语录（偏复盘语气）。
    取数逻辑：完全来自工作区 `心法.md`
    """
    date = str(market_data.get("date") or "").strip() or "unknown-date"
    mood_stage = (market_data.get("moodStage") or {})
    stage_type = (mood_stage.get("type") or "warn").strip()

    def _norm_line(s: str) -> str:
        s = s.strip()
        s = re.sub(r"^\s*[（(]?\s*\d+\s*[）)]\s*", "", s)
        s = re.sub(r"^\s*\d+\s*[\.、]\s*", "", s)
        s = re.sub(r"^\s*[一二三四五六七八九十]+\s*[、.．]\s*", "", s)
        s = s.replace("—", "—").strip()
        return s

    def _split_sentences(text: str) -> list[str]:
        parts = re.split(r"[。！？!?\n]+", text)
        out: list[str] = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            out.extend([x.strip() for x in re.split(r"[；;]+", p) if x.strip()])
        return out

    def _load_user_pool() -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, str]]]:
        """
        从工作区的 `心法.md` 提炼候选（语录 + 短线提醒）：
        - 返回 (tips_add, quotes_add, fire_quotes_add)
        """
        workspace_root = cache_dir.parent
        md_path = workspace_root / "心法.md"
        if not md_path.exists():
            return ([], [], [])

        raw = md_path.read_text(encoding="utf-8", errors="ignore")
        lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
        sentences: list[str] = []
        section = ""
        for ln in lines:
            s0 = ln.strip()
            if s0.startswith("#"):
                if "短线提醒" in s0:
                    section = "tip"
                elif "语录" in s0:
                    section = "quote"
                elif any(k in s0 for k in ("退潮", "防守", "冰点")):
                    section = "fire"
                continue

            s0 = re.sub(r"^\s*[-*+]\s*", "", s0)
            s0 = s0.strip().strip("“”\"'").strip()
            s0 = _norm_line(s0)
            if not s0:
                continue
            if section == "tip":
                sentences.append(s0)
            else:
                sentences.extend(_split_sentences(s0))

        seen: set[str] = set()
        cand: list[str] = []
        for s in sentences:
            s = _norm_line(s)
            s = re.sub(r"\s+", "", s)
            if len(s) < 10 or len(s) > 60:
                continue
            if s in seen:
                continue
            seen.add(s)
            cand.append(s)

        tips_add: list[tuple[str, str]] = []
        quotes_add: list[tuple[str, str]] = []
        fire_quotes_add: list[tuple[str, str]] = []
        for s in cand:
            _id = "u" + hashlib.md5(s.encode("utf-8")).hexdigest()[:8]
            if len(s) <= 26:
                if any(k in s for k in ["止损", "亏损", "认赔", "危险", "躲开", "不摊", "不平摊", "保命"]):
                    fire_quotes_add.append((_id, s))
                else:
                    quotes_add.append((_id, s))
            else:
                tips_add.append((_id, s))

        return (tips_add, quotes_add, fire_quotes_add)

    def _load_user_pool_by_stage() -> tuple[
        list[tuple[str, str]],
        list[tuple[str, str]],
        list[tuple[str, str]],
        list[tuple[str, str]],
        list[tuple[str, str]],
        list[tuple[str, str]],
    ]:
        """
        从心法.md 进一步提炼：
        - tips_good / tips_warn / tips_fire
        - quotes_good / quotes_warn / quotes_fire
        """
        workspace_root = cache_dir.parent
        md_path = workspace_root / "心法.md"
        if not md_path.exists():
            return ([], [], [], [], [], [])

        raw = md_path.read_text(encoding="utf-8", errors="ignore")
        lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]

        mode = ""
        stage = "warn"
        tips_good: list[tuple[str, str]] = []
        tips_warn: list[tuple[str, str]] = []
        tips_fire: list[tuple[str, str]] = []
        quotes_good: list[tuple[str, str]] = []
        quotes_warn: list[tuple[str, str]] = []
        quotes_fire: list[tuple[str, str]] = []

        def _pick_stage(title: str, current_mode: str, current_stage: str) -> tuple[str, str]:
            t = title.strip().replace(" ", "")
            next_mode = current_mode
            next_stage = current_stage

            if "短线提醒" in t:
                next_mode = "tip"
            elif any(k in t for k in ("语录", "心法", "口诀", "OCR", "识别整理", "原始摘录")):
                next_mode = "quote"

            if any(k in t for k in ("强势", "高潮", "进攻")):
                next_stage = "good"
            elif any(k in t for k in ("退潮", "防守", "冰点")):
                next_stage = "fire"
            elif any(k in t for k in ("分歧", "震荡", "中性", "通用", "耐心", "顺势", "少操作", "联动", "消息", "亏损处理")):
                next_stage = "warn"
            return next_mode, next_stage

        def _append(mode_key: str, stage_key: str, text: str) -> None:
            s = _norm_line(text)
            s = re.sub(r"\s+", "", s)
            if len(s) < 10 or len(s) > 60:
                return
            _id = "u" + hashlib.md5(f"{mode_key}:{stage_key}:{s}".encode("utf-8")).hexdigest()[:8]
            if mode_key == "tip":
                if stage_key == "good":
                    tips_good.append((_id, s))
                elif stage_key == "fire":
                    tips_fire.append((_id, s))
                else:
                    tips_warn.append((_id, s))
            elif mode_key == "quote":
                if stage_key == "good":
                    quotes_good.append((_id, s))
                elif stage_key == "fire":
                    quotes_fire.append((_id, s))
                else:
                    quotes_warn.append((_id, s))

        for ln in lines:
            s0 = ln.strip()
            if s0.startswith("#"):
                mode, stage = _pick_stage(s0.lstrip("#").strip(), mode, stage)
                continue
            s0 = re.sub(r"^\s*[-*+]\s*", "", s0).strip().strip("“”\"'").strip()
            if not s0:
                continue
            if mode == "tip":
                _append("tip", stage, s0)
            elif mode == "quote":
                for p in _split_sentences(s0):
                    _append("quote", stage, p)

        return (tips_good, tips_warn, tips_fire, quotes_good, quotes_warn, quotes_fire)

    user_tips_add, user_quotes_add, user_fire_quotes_add = _load_user_pool()
    tips_good, tips_warn, tips_fire, quotes_good, quotes_warn, quotes_fire = _load_user_pool_by_stage()

    if user_tips_add:
        tips_warn = user_tips_add + tips_warn
    if user_quotes_add:
        quotes_warn = user_quotes_add + quotes_warn
    if user_fire_quotes_add:
        quotes_fire = user_fire_quotes_add + quotes_fire

    if stage_type == "good":
        tip_pool = tips_good + tips_warn
        quote_pool = quotes_good + quotes_warn
    elif stage_type == "fire":
        tip_pool = tips_fire + tips_warn
        quote_pool = quotes_fire + quotes_warn
    else:
        tip_pool = tips_warn
        quote_pool = quotes_warn

    history_path = cache_dir / "learning_notes_history.json"
    history = {"tip_ids": [], "quote_ids": [], "last_date": ""}
    try:
        if history_path.exists():
            history = json.loads(history_path.read_text(encoding="utf-8")) or history
    except Exception:
        history = {"tip_ids": [], "quote_ids": [], "last_date": ""}

    tip_used = set((history.get("tip_ids") or [])[:7])
    quote_used = set((history.get("quote_ids") or [])[:7])

    def pick_one(pool: list[tuple[str, str]], used: set[str], seed_key: str) -> tuple[str, str]:
        if not pool:
            return ("", "")
        seed = int(hashlib.md5(seed_key.encode("utf-8")).hexdigest(), 16)
        start = seed % len(pool)
        for i in range(len(pool)):
            _id, _txt = pool[(start + i) % len(pool)]
            if _id not in used:
                return (_id, _txt)
        return pool[start]

    tip_id, tip_txt = pick_one(tip_pool, tip_used, f"{date}:{stage_type}:tip")
    quote_id, quote_txt = pick_one(quote_pool, quote_used, f"{date}:{stage_type}:quote")

    tips: list[str] = []
    if tip_txt and tip_txt not in tips:
        tips.append(tip_txt)
    tips = tips[:3]

    try:
        if history.get("last_date") != date:
            history["tip_ids"] = [tip_id] + list(history.get("tip_ids") or [])
            history["quote_ids"] = [quote_id] + list(history.get("quote_ids") or [])
            history["tip_ids"] = (history["tip_ids"] or [])[:7]
            history["quote_ids"] = (history["quote_ids"] or [])[:7]
            history["last_date"] = date
            history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return {"tips": tips, "quotes": [quote_txt] if quote_txt else []}
