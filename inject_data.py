"""
Vue3 数据注入脚本（inject_data.py）

将 cache/market_data-YYYYMMDD.json 转换为 web 可直接消费的数据文件。
当前只维护 web 路径：web/public 用于 dev，web/dist 用于构建产物预览/部署。

架构位置：Layer 2（数据加工）→ Layer 3（渲染）的桥梁
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent


def _build_theme_alias_map(md: dict, watchlist: Optional[dict] = None) -> dict:
    """
    汇总今日题材别名映射：canonical_name → 出现过的原始名集合。

    归一化责任已经下沉到后端算法层（tide / core_tide / zt_analysis），
    本函数只做“收集 + 分组”：
    - 后端已带 canonical 字段的来源（tide/core_tide/zt_analysis）：
      用算法层吐出来的 canonical 作为分组 key，把同行的 raw name 一并塞进桶里。
    - 上游没带 canonical 的来源（plateRankTop10/sectors/leaders/zt_code_themes/watchlist）：
      用 raw name 自身作为分组 key，等同于“透传”。

    这样前端拿到的 alias_map 直接反映后端的判定结果，不需要在 inject_data 里
    再跑一遍 normalize_sector。
    """
    alias_map: dict[str, set[str]] = {}

    def push(name: object, canonical: object = None) -> None:
        raw = str(name or "").strip()
        canon = str(canonical or "").strip()
        # 没 canonical → 用 raw 自己做 key（透传，前端按 raw 匹配）
        key = canon or raw
        if not key:
            return
        bucket = alias_map.setdefault(key, set())
        bucket.add(key)
        if raw:
            bucket.add(raw)

    # ---- 上游：未带 canonical，按 raw 透传 ----
    for row in md.get("plateRankTop10") or []:
        if isinstance(row, dict):
            push(row.get("name"))
    for row in md.get("sectors") or []:
        if isinstance(row, dict):
            push(row.get("name"))
    theme_panels = md.get("themePanels") if isinstance(md.get("themePanels"), dict) else {}
    for key in ("strengthRows", "ztTop", "zbTop", "dtTop"):
        for row in theme_panels.get(key) or []:
            if isinstance(row, dict):
                push(row.get("name"))
    for row in md.get("leaders") or []:
        if isinstance(row, dict):
            push(row.get("theme"))
    code_themes = md.get("zt_code_themes") if isinstance(md.get("zt_code_themes"), dict) else {}
    for themes in code_themes.values():
        for theme in themes or []:
            push(theme)

    # ---- 算法层：直接读 canonical_name / predThemeCanonical / plateNameCanonical ----
    for signal_key in ("tideSignal", "coreTideSignal"):
        signal = md.get(signal_key) if isinstance(md.get(signal_key), dict) else {}
        for row in signal.get("themes") or []:
            if isinstance(row, dict):
                push(row.get("name"), row.get("canonical_name"))
    zt_analysis = md.get("ztAnalysis") if isinstance(md.get("ztAnalysis"), dict) else {}
    for bucket_key in ("relay", "watch"):
        for row in zt_analysis.get(bucket_key) or []:
            if not isinstance(row, dict):
                continue
            push(row.get("predTheme"), row.get("predThemeCanonical"))
            push(row.get("plateName"), row.get("plateNameCanonical"))

    # ---- watchlist：未带 canonical，按 raw 透传 ----
    if isinstance(watchlist, dict):
        ladder = watchlist.get("ladder") if isinstance(watchlist.get("ladder"), dict) else {}
        for row in ladder.get("main_lines") or []:
            if not isinstance(row, dict):
                continue
            push(row.get("name"))
            for theme in row.get("constituents") or []:
                push(theme)
        picks = watchlist.get("picks_advisor") if isinstance(watchlist.get("picks_advisor"), dict) else {}
        for row in picks.get("main_line_picks") or []:
            if not isinstance(row, dict):
                continue
            push(row.get("main_line"))
            for theme in row.get("constituents") or []:
                push(theme)
        sector_resolution = watchlist.get("sector_resolution") if isinstance(watchlist.get("sector_resolution"), dict) else {}
        stock_to_sectors = sector_resolution.get("stock_to_sectors") if isinstance(sector_resolution.get("stock_to_sectors"), dict) else {}
        for info in stock_to_sectors.values():
            sectors = info.get("sectors") if isinstance(info, dict) else []
            for sector in sectors or []:
                if isinstance(sector, dict):
                    push(sector.get("sector"))

    return {key: sorted(values) for key, values in alias_map.items() if key and values}


def _prune_plan_text_fields(md: dict) -> None:
    """移除明日行动指南已下线的聚焦/底部文案字段。"""
    if not isinstance(md, dict):
        return
    md.pop("actionGuideV2", None)
    md.pop("summary3", None)


def _ensure_stock_research_backtest(md: dict) -> None:
    """
    为 web 数据补齐个股回测。

    说明：
    - 优先保留 cache/market_data 已经写入的 stockResearchBacktest；
    - 若旧缓存里还没有，则在 inject 阶段现场补算，保证 web 新 tab 有数据可读；
    - 失败时静默跳过，前端会展示空态说明。
    """
    if not isinstance(md, dict):
        return
    existing = md.get("stockResearchBacktest")
    if isinstance(existing, dict) and existing.get("summary"):
        return
    try:
        from scripts.build_stock_research_backtest import build_stock_research_backtest_payload

        md["stockResearchBacktest"] = build_stock_research_backtest_payload()
    except Exception:
        return


def _resolve_data_path(date8: str, source: Optional[str] = None) -> Path:
    """解析数据源路径；优先使用显式 source，其次回退到标准收盘缓存。"""
    if source:
        data_path = Path(source)
        if not data_path.is_absolute():
            data_path = ROOT / data_path
        return data_path
    return ROOT / "cache" / f"market_data-{date8}.json"


def _resolve_eastmoney_tomorrow_path() -> Path:
    path = ROOT / "web" / "public" / "eastmoney_tomorrow.json"
    fallback = ROOT / "web" / "dist" / "eastmoney_tomorrow.json"
    if path.exists():
        return path
    return fallback


def _resolve_intraday_resonance_path(date8: str) -> Path:
    """盘中共振数据，从 cache_online 读取（由 cli intraday 模式产出）"""
    path = ROOT / "cache_online" / f"intraday_resonance-{date8}.json"
    if path.exists():
        return path
    # 兜底：web/public 下的 dev 文件
    fallback = ROOT / "web" / "public" / "intraday_resonance.json"
    return fallback


def _resolve_watchlist_path(date8: str) -> Path:
    """
    watchlist_cache 由 tools/fetch_watchlist.py 产出，保存在 cache_online/。

    注意：watchlist 的"数据日期"通常是接口当天（YYYY-MM-DD），可能与涨停池
    数据日期（pools_date）不一致。这里先按 date8 找；若不存在，回退到最新一份。
    """
    direct = ROOT / "cache_online" / f"watchlist_cache-{date8}.json"
    if direct.exists():
        return direct
    files = sorted((ROOT / "cache_online").glob("watchlist_cache-*.json"))
    return files[-1] if files else direct


def _build_watchlist_stock_index(watchlist: dict) -> dict:
    """
    反向索引：code → {primary_sector, primary_confidence, all_sectors,
                       main_line, main_line_confidence}

    前端可 O(1) 查询，避免每个 zt-item 都遍历 stock_to_sectors。
    """
    out: dict = {}
    sec = watchlist.get("sector_resolution") or {}
    sts = sec.get("stock_to_sectors") or {}
    if not isinstance(sts, dict):
        return out

    # 先建 sector → main_line 反查（主线优先）
    main_lines = (watchlist.get("ladder") or {}).get("main_lines") or []
    sector_to_main: dict[str, tuple[str, float]] = {}
    for ml in main_lines:
        if not isinstance(ml, dict):
            continue
        ml_name = str(ml.get("name") or "")
        ml_conf = float(ml.get("confidence") or 0.0)
        if not ml_name:
            continue
        for s in (ml.get("constituents") or []):
            if isinstance(s, str) and s:
                # 高置信度主线优先（同一 sector 被多个主线覆盖时取 confidence 最高的）
                prev = sector_to_main.get(s)
                if prev is None or ml_conf > prev[1]:
                    sector_to_main[s] = (ml_name, ml_conf)

    for code, info in sts.items():
        if not isinstance(info, dict):
            continue
        sectors = info.get("sectors") or []
        if not isinstance(sectors, list) or not sectors:
            continue
        # confidence 降序
        sorted_sectors = sorted(
            ((str(s.get("sector") or ""), float(s.get("confidence") or 0.0))
             for s in sectors if isinstance(s, dict) and s.get("sector")),
            key=lambda kv: kv[1],
            reverse=True,
        )
        if not sorted_sectors:
            continue
        primary_sector, primary_conf = sorted_sectors[0]
        # 在该股票所有板块中找最强主线（取该股板块在 sector_to_main 中能匹配到、且主线 conf 最高的）
        best_main: tuple[str, float] | None = None
        for sec_name, _sc in sorted_sectors:
            cand = sector_to_main.get(sec_name)
            if cand and (best_main is None or cand[1] > best_main[1]):
                best_main = cand
        out[str(code)] = {
            "primary_sector": primary_sector,
            "primary_confidence": round(primary_conf, 3),
            "all_sectors": [[s, round(c, 3)] for s, c in sorted_sectors[:5]],
            "main_line": best_main[0] if best_main else "",
            "main_line_confidence": round(best_main[1], 3) if best_main else 0.0,
        }
    return out


def _enhance_with_watchlist(md: dict, watchlist: dict) -> None:
    """
    用 watchlist 多源融合结果就地增强 md：
    1. 重写 zt_code_themes（watchlist 在前，原列表兜底）
    2. 让 watchlist 最强主线占据 themePanels.ztTop[0]
    3. 透传 watchlist 整包 + 反向索引

    所有改动都是 idempotent + graceful：watchlist 为空时直接返回。
    """
    if not isinstance(watchlist, dict) or not watchlist:
        return

    sec = watchlist.get("sector_resolution") or {}
    sts = sec.get("stock_to_sectors") or {}

    # ---- 1. zt_code_themes 增强 ----
    if isinstance(sts, dict) and sts:
        old_map = dict(md.get("zt_code_themes") or {})
        new_map: dict = {}
        for code, info in sts.items():
            sectors = info.get("sectors") if isinstance(info, dict) else None
            if not isinstance(sectors, list):
                continue
            # watchlist 已按 confidence 降序
            themes = [
                str(s.get("sector") or "").strip()
                for s in sectors
                if isinstance(s, dict) and s.get("sector")
            ]
            themes = [t for t in themes if t]
            origin = old_map.get(str(code)) or []
            for t in origin:
                t_s = str(t or "").strip()
                if t_s and t_s not in themes:
                    themes.append(t_s)
            if themes:
                new_map[str(code)] = themes
        # 未被 watchlist 覆盖的 code 保留原数据
        for code, themes in old_map.items():
            if str(code) not in new_map:
                new_map[str(code)] = themes
        md["zt_code_themes"] = new_map

    # ---- 2. themePanels.ztTop 主线高亮 ----
    main_lines = (watchlist.get("ladder") or {}).get("main_lines") or []
    if main_lines and isinstance(main_lines[0], dict):
        top_name = str(main_lines[0].get("name") or "").strip()
        if top_name and isinstance(md.get("themePanels"), dict):
            zt_top = list(md["themePanels"].get("ztTop") or [])
            existing_idx = next(
                (i for i, x in enumerate(zt_top)
                 if isinstance(x, dict) and str(x.get("name") or "") == top_name),
                -1,
            )
            if existing_idx > 0:
                zt_top.insert(0, zt_top.pop(existing_idx))
            elif existing_idx < 0:
                zt_top.insert(0, {"name": top_name, "source": "watchlist"})
            md["themePanels"]["ztTop"] = zt_top

    # ---- 3. 透传 + 反向索引 ----
    md["watchlist"] = watchlist
    md["watchlist_stock_index"] = _build_watchlist_stock_index(watchlist)

    # ---- 4. picks_advisor 提级到顶层（前端直接消费） ----
    picks = watchlist.get("picks_advisor")
    if isinstance(picks, dict) and picks.get("main_line_picks"):
        md["picks_advisor"] = picks

    # ---- 5. tide_signal 提级到顶层（watchlist 口径优先） ----
    tide = watchlist.get("tide_signal")
    if isinstance(tide, dict):
        md["tideSignal"] = tide

    # ---- 6. core_tide_signal 提级到顶层（推荐线与展示共用同一口径） ----
    core_tide = watchlist.get("core_tide_signal")
    if isinstance(core_tide, dict):
        md["coreTideSignal"] = core_tide

    # ---- 7. 当日题材别名映射（统一由 Python 出数，前端只读） ----
    md["theme_alias_map"] = _build_theme_alias_map(md, watchlist)


def build_web_data(date8: str, source: Optional[str] = None) -> Path:
    """生成 web/dist 旁路数据文件并返回 dist 目录。"""
    # 读取市场数据
    data_path = _resolve_data_path(date8, source)
    if not data_path.exists():
        raise FileNotFoundError(f"数据缓存不存在: {data_path}")

    md = json.loads(data_path.read_text(encoding="utf-8"))
    # 清理前端不需要的大字段
    md.pop("raw", None)
    _prune_plan_text_fields(md)
    _ensure_stock_research_backtest(md)
    try:
        from daily_review.render.render_html import build_market_overview_7d, build_mood_trend_7d

        md["marketOverview7d"] = build_market_overview_7d(market_data=md)
        md["moodTrend7d"] = build_mood_trend_7d(market_data=md)
    except Exception as e:
        print(f"⚠ 7日情绪衍生字段重算失败（跳过）: {e}", file=sys.stderr)

    # watchlist 增强：让现有前端自动消费更准的板块归属 + 主线（前端 UI 零改动）
    wl_path = _resolve_watchlist_path(date8)
    if wl_path.exists():
        try:
            watchlist = json.loads(wl_path.read_text(encoding="utf-8"))
            _enhance_with_watchlist(md, watchlist)
        except Exception as e:
            print(f"⚠ watchlist 增强失败（跳过）: {e}", file=sys.stderr)
    if "theme_alias_map" not in md:
        md["theme_alias_map"] = _build_theme_alias_map(md)

    payload = json.dumps(md, ensure_ascii=False)
    # 明日策略池
    tp_path = ROOT / "web" / "public" / "tomorrow_picks.json"
    tp_payload = "{}"
    if tp_path.exists():
        tp_payload = tp_path.read_text(encoding="utf-8")
    else:
        tp_fallback = ROOT / "web" / "dist" / "tomorrow_picks.json"
        if tp_fallback.exists():
            tp_payload = tp_fallback.read_text(encoding="utf-8")

    # 东方财富明日主题数据
    em_path = _resolve_eastmoney_tomorrow_path()
    em_payload = "{}"
    if em_path.exists():
        em_payload = em_path.read_text(encoding="utf-8")

    # 盘中共振事件数据
    res_path = _resolve_intraday_resonance_path(date8)
    resonance_payload = "[]"
    if res_path.exists():
        resonance_payload = res_path.read_text(encoding="utf-8")

    # 同步 dist 旁路数据文件，支持通过 web/dist/index.html 加载同目录数据。
    dist_dir = ROOT / "web" / "dist"
    if not (dist_dir / "index.html").exists():
        raise FileNotFoundError(f"Vite 构建产物不存在: {dist_dir / 'index.html'}\n请先执行: cd web && npm run build")
    (dist_dir / "market_data.json").write_text(payload, encoding="utf-8")
    (dist_dir / "market_data.js").write_text(f"window.__MARKET_DATA__={payload};", encoding="utf-8")
    if tp_payload != "{}":
        (dist_dir / "tomorrow_picks.json").write_text(tp_payload, encoding="utf-8")
    if em_payload != "{}":
        (dist_dir / "eastmoney_tomorrow.json").write_text(em_payload, encoding="utf-8")
    if resonance_payload != "[]":
        (dist_dir / "intraday_resonance.json").write_text(resonance_payload, encoding="utf-8")

    return dist_dir


def inject(date8: str, source: Optional[str] = None) -> Path:
    """兼容旧调用名：只生成 web 数据，不再生成 html/复盘日记。"""
    return build_web_data(date8, source)


def refresh_dev_data(date8: str, source: Optional[str] = None) -> None:
    """刷新 web/public 数据文件（供 Vite dev 和 dist 直开使用）"""
    data_path = _resolve_data_path(date8, source)
    if not data_path.exists():
        return
    md = json.loads(data_path.read_text(encoding="utf-8"))
    md.pop("raw", None)
    _prune_plan_text_fields(md)
    _ensure_stock_research_backtest(md)
    try:
        from daily_review.render.render_html import build_market_overview_7d, build_mood_trend_7d

        md["marketOverview7d"] = build_market_overview_7d(market_data=md)
        md["moodTrend7d"] = build_mood_trend_7d(market_data=md)
    except Exception as e:
        print(f"⚠ 7日情绪衍生字段重算失败（dev 跳过）: {e}", file=sys.stderr)
    # watchlist 增强：dev 路径保持与 inject() 一致
    wl_path = _resolve_watchlist_path(date8)
    if wl_path.exists():
        try:
            watchlist = json.loads(wl_path.read_text(encoding="utf-8"))
            _enhance_with_watchlist(md, watchlist)
        except Exception as e:
            print(f"⚠ watchlist 增强失败（dev 跳过）: {e}", file=sys.stderr)
    if "theme_alias_map" not in md:
        md["theme_alias_map"] = _build_theme_alias_map(md)
    payload = json.dumps(md, ensure_ascii=False)
    dev_file = ROOT / "web" / "public" / "market_data.json"
    dev_script = ROOT / "web" / "public" / "market_data.js"
    dev_file.parent.mkdir(parents=True, exist_ok=True)
    dev_file.write_text(payload, encoding="utf-8")
    dev_script.write_text(f"window.__MARKET_DATA__={payload};", encoding="utf-8")
    # 同步盘中共振数据
    res_file = _resolve_intraday_resonance_path(date8)
    if res_file.exists():
        import shutil
        target_res_file = ROOT / "web" / "public" / "intraday_resonance.json"
        if res_file.resolve() != target_res_file.resolve():
            shutil.copy2(res_file, target_res_file)
            print(f"  盘中共振 dev 数据已同步")
    print(f"  dev 数据已刷新: {dev_file}")
    print(f"  dev 脚本已刷新: {dev_script}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="将 market_data 写入 web/public 与 web/dist 数据文件")
    ap.add_argument("date8", nargs="?", help="交易日，格式 YYYYMMDD；不传则自动取最新缓存")
    ap.add_argument("--dev-only", action="store_true", help="仅刷新 web/public 下的数据文件")
    ap.add_argument("--source", help="显式指定数据源 JSON 路径，可用于 intraday 缓存")
    args = ap.parse_args()

    if args.dev_only:
        if args.date8:
            date8 = args.date8
        else:
            files = sorted((ROOT / "cache").glob("market_data-2026*.json"))
            if not files:
                print("错误: cache/ 中没有 market_data-*.json", file=sys.stderr)
                sys.exit(1)
            date8 = files[-1].name.replace("market_data-", "").replace(".json", "")
        refresh_dev_data(date8, args.source)
        sys.exit(0)

    date8 = args.date8
    if not date8:
        # 自动取最新缓存
        files = sorted((ROOT / "cache").glob("market_data-2026*.json"))
        if not files:
            print("错误: cache/ 中没有 market_data-*.json", file=sys.stderr)
            sys.exit(1)
        date8 = files[-1].name.replace("market_data-", "").replace(".json", "")

    out = inject(date8, args.source)
    print(f"✅ web 数据已生成: {out}")
    source_path = _resolve_data_path(date8, args.source)
    print(f"   数据来源: {source_path.relative_to(ROOT) if source_path.is_relative_to(ROOT) else source_path}")
    print(f"   Web 入口: web/dist/index.html")

    # 同时刷新 dev 数据
    refresh_dev_data(date8, args.source)
