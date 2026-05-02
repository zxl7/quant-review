#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
短线提醒 / 语录加载器

职责：
- 仅从工作区 `心法.md` 读取候选
- 优先读取“标准调用池”，按 `ICE / START / FERMENT / CLIMAX` 精准分层
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
    cycle_code = str(mood_stage.get("cycle") or "").strip().upper()

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

    def _bucket_key(title: str, current_mode: str = "", current_bucket: str = "common") -> tuple[str, str, bool]:
        """
        解析标题 → (mode, bucket, primary_only)
        mode: tip / quote
        bucket:
        - common
        - ICE / START / FERMENT / CLIMAX
        - good / warn / fire（兼容老写法）
        primary_only: 是否处于“标准调用池”优先区域
        """
        t = title.strip().replace(" ", "")
        mode = current_mode
        bucket = current_bucket
        primary_only = any(k in t for k in ("标准调用池", "日报优先", "标准分层"))

        if any(k in t for k in ("短线提醒", "提醒")):
            mode = "tip"
        elif any(k in t for k in ("语录", "心法", "口诀", "摘录", "OCR")):
            mode = "quote"

        # 显式 cycle code 优先
        m = re.search(r"\b(ICE|START|FERMENT|CLIMAX)\b", title, flags=re.I)
        if m:
            bucket = m.group(1).upper()
            return mode, bucket, primary_only

        if "通用" in t:
            bucket = "common"
        elif any(k in t for k in ("冰点", "退潮")):
            bucket = "ICE"
        elif any(k in t for k in ("启动", "试错")):
            bucket = "START"
        elif any(k in t for k in ("修复", "发酵")):
            bucket = "FERMENT"
        elif any(k in t for k in ("高潮", "亢奋")):
            bucket = "CLIMAX"
        elif any(k in t for k in ("强势", "进攻")):
            bucket = "good"
        elif any(k in t for k in ("分歧", "震荡", "中性")):
            bucket = "warn"
        elif any(k in t for k in ("防守", "危险")):
            bucket = "fire"
        return mode, bucket, primary_only

    def _parse_md_buckets() -> tuple[dict[str, list[tuple[str, str]]], bool]:
        """
        统一解析心法.md。
        若存在“标准调用池”，优先只使用该区域条目；
        否则回退全文件语义解析。
        """
        workspace_root = cache_dir.parent
        md_path = workspace_root / "心法.md"
        if not md_path.exists():
            return ({}, False)

        raw = md_path.read_text(encoding="utf-8", errors="ignore")
        lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
        entries: list[tuple[str, str, str, bool]] = []
        mode = ""
        bucket = "common"
        in_primary = False

        def _append(mode_key: str, bucket_key: str, text: str, primary_flag: bool) -> None:
            s = _norm_line(text)
            s = re.sub(r"\s+", "", s)
            if len(s) < 10 or len(s) > 60:
                return
            entries.append((mode_key, bucket_key, s, primary_flag))

        for ln in lines:
            s0 = ln.strip()
            if s0.startswith("#"):
                sharp_count = len(s0) - len(s0.lstrip("#"))
                title = s0.lstrip("#").strip()
                mode, bucket, primary_hit = _bucket_key(title, mode, bucket)
                # 仅把“标准调用池”所在的大段作为 primary 区域
                if sharp_count <= 2:
                    in_primary = primary_hit
                continue
            s0 = re.sub(r"^\s*[-*+]\s*", "", s0).strip().strip("“”\"'").strip()
            if not s0:
                continue
            if mode == "tip":
                _append("tip", bucket, s0, in_primary)
            elif mode == "quote":
                for p in _split_sentences(s0):
                    _append("quote", bucket, p, in_primary)

        # 如果存在标准调用池，只用它；否则用全量
        use_primary = any(primary for _, _, _, primary in entries)
        buckets: dict[str, list[tuple[str, str]]] = {}
        seen_by_key: dict[str, set[str]] = {}
        for mode_key, bucket_key, text, primary_flag in entries:
            if use_primary and not primary_flag:
                continue
            key = f"{mode_key}:{bucket_key}"
            seen = seen_by_key.setdefault(key, set())
            if text in seen:
                continue
            seen.add(text)
            _id = "u" + hashlib.md5(f"{key}:{text}".encode("utf-8")).hexdigest()[:8]
            buckets.setdefault(key, []).append((_id, text))
        return (buckets, use_primary)

    buckets, using_primary_pool = _parse_md_buckets()

    def _merge_keys(mode_key: str, keys: list[str]) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        seen_ids: set[str] = set()
        for k in keys:
            for _id, txt in buckets.get(f"{mode_key}:{k}", []):
                if _id in seen_ids:
                    continue
                seen_ids.add(_id)
                out.append((_id, txt))
        return out

    # 精准调用顺序：cycle 优先，type 次级，common 兜底
    tip_keys: list[str]
    quote_keys: list[str]
    if cycle_code == "ICE":
        tip_keys = ["ICE", "fire", "warn", "common"]
        quote_keys = ["ICE", "fire", "warn", "common"]
    elif cycle_code == "START":
        tip_keys = ["START", "warn", "common"]
        quote_keys = ["START", "warn", "common"]
    elif cycle_code == "FERMENT":
        tip_keys = ["FERMENT", "good", "warn", "common"]
        quote_keys = ["FERMENT", "good", "warn", "common"]
    elif cycle_code == "CLIMAX":
        tip_keys = ["CLIMAX", "good", "warn", "common"]
        quote_keys = ["CLIMAX", "good", "warn", "common"]
    elif stage_type == "good":
        tip_keys = ["good", "warn", "common"]
        quote_keys = ["good", "warn", "common"]
    elif stage_type == "fire":
        tip_keys = ["fire", "warn", "common"]
        quote_keys = ["fire", "warn", "common"]
    else:
        tip_keys = ["warn", "common"]
        quote_keys = ["warn", "common"]

    tip_pool = _merge_keys("tip", tip_keys)
    quote_pool = _merge_keys("quote", quote_keys)

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

    tip_id, tip_txt = pick_one(tip_pool, tip_used, f"{date}:{cycle_code or stage_type}:tip:1")
    tip_id2, tip_txt2 = pick_one(tip_pool, tip_used | ({tip_id} if tip_id else set()), f"{date}:{cycle_code or stage_type}:tip:2")
    quote_id, quote_txt = pick_one(quote_pool, quote_used, f"{date}:{cycle_code or stage_type}:quote")

    tips: list[str] = []
    for txt in [tip_txt, tip_txt2]:
        if txt and txt not in tips:
            tips.append(txt)
    tips = tips[:2]

    try:
        if history.get("last_date") != date:
            new_tip_ids = [x for x in [tip_id, tip_id2] if x]
            history["tip_ids"] = new_tip_ids + list(history.get("tip_ids") or [])
            history["quote_ids"] = [quote_id] + list(history.get("quote_ids") or [])
            history["tip_ids"] = (history["tip_ids"] or [])[:7]
            history["quote_ids"] = (history["quote_ids"] or [])[:7]
            history["last_date"] = date
            history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return {
        "tips": tips,
        "quotes": [quote_txt] if quote_txt else [],
        "meta": {
            "cycle": cycle_code or "-",
            "stageType": stage_type or "-",
            "tipKeys": tip_keys,
            "quoteKeys": quote_keys,
            "source": "心法标准调用池" if using_primary_pool else "心法素材库",
        },
    }
