"""
Vue3 数据注入脚本（inject_data.py）

将 cache/market_data-YYYYMMDD.json 注入到 Vite 构建产物 web/dist/index.html，
产出最终单文件 HTML 报告。

架构位置：Layer 2（数据加工）→ Layer 3（渲染）的桥梁
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent


def _resolve_data_path(date8: str, source: Optional[str] = None) -> Path:
    """解析数据源路径；优先使用显式 source，其次回退到标准收盘缓存。"""
    if source:
        data_path = Path(source)
        if not data_path.is_absolute():
            data_path = ROOT / data_path
        return data_path
    return ROOT / "cache" / f"market_data-{date8}.json"


def _resolve_dragon_tiger_path(date8: str) -> Path:
    # 优先用 cache 目录的当日缓存（fetch 流程产出），兜底 web/public（dev 场景）
    cached = ROOT / "cache" / f"dragon_tiger-{date8}.json"
    if cached.exists():
        return cached
    return ROOT / "web" / "public" / "dragon_tiger_data.json"


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


def inject(date8: str, source: Optional[str] = None) -> Path:
    """注入数据并返回输出路径"""
    # 读取市场数据
    data_path = _resolve_data_path(date8, source)
    if not data_path.exists():
        raise FileNotFoundError(f"数据缓存不存在: {data_path}")

    md = json.loads(data_path.read_text(encoding="utf-8"))
    # 清理前端不需要的大字段
    md.pop("raw", None)

    # watchlist 增强：让现有前端自动消费更准的板块归属 + 主线（前端 UI 零改动）
    wl_path = _resolve_watchlist_path(date8)
    if wl_path.exists():
        try:
            watchlist = json.loads(wl_path.read_text(encoding="utf-8"))
            _enhance_with_watchlist(md, watchlist)
        except Exception as e:
            print(f"⚠ watchlist 增强失败（跳过）: {e}", file=sys.stderr)

    payload = json.dumps(md, ensure_ascii=False)
    dragon_payload = "{}"
    dragon_path = _resolve_dragon_tiger_path(date8)
    if dragon_path.exists():
        dragon_data = json.loads(dragon_path.read_text(encoding="utf-8"))
        dragon_payload = json.dumps(dragon_data, ensure_ascii=False)
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

    # 读取 Vite 构建产物
    built = ROOT / "web" / "dist" / "index.html"
    if not built.exists():
        raise FileNotFoundError(f"Vite 构建产物不存在: {built}\n请先执行: cd web && npm run build")

    html = built.read_text(encoding="utf-8")

    # 注入 window.__MARKET_DATA__ 到 </head> 前
    data_script = f"<script>window.__MARKET_DATA__={payload};window.__DRAGON_TIGER_DATA__={dragon_payload};window.__TOMORROW_PICKS__={tp_payload};window.__EASTMONEY_TOMORROW_DATA__={em_payload};window.__INTRADAY_RESONANCE__={resonance_payload};</script>"
    if "</head>" in html:
        html = html.replace("</head>", f"{data_script}\n  </head>")
    else:
        html = data_script + "\n" + html

    # 写入输出
    out_dir = ROOT / "html"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"复盘日记-{date8}-tab-v1.html"
    out_path.write_text(html, encoding="utf-8")

    # 同时写 index.html 用于本地预览
    index_path = out_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")

    # 同步 dist 旁路数据文件，支持直接打开 web/dist/index.html
    dist_dir = ROOT / "web" / "dist"
    (dist_dir / "market_data.json").write_text(payload, encoding="utf-8")
    (dist_dir / "market_data.js").write_text(f"window.__MARKET_DATA__={payload};", encoding="utf-8")
    (dist_dir / "dragon_tiger_data.json").write_text(dragon_payload, encoding="utf-8")
    (dist_dir / "dragon_tiger_data.js").write_text(f"window.__DRAGON_TIGER_DATA__={dragon_payload};", encoding="utf-8")
    if tp_payload != "{}":
        (dist_dir / "tomorrow_picks.json").write_text(tp_payload, encoding="utf-8")
    if em_payload != "{}":
        (dist_dir / "eastmoney_tomorrow.json").write_text(em_payload, encoding="utf-8")
    if resonance_payload != "[]":
        (dist_dir / "intraday_resonance.json").write_text(resonance_payload, encoding="utf-8")

    return out_path


def refresh_dev_data(date8: str, source: Optional[str] = None) -> None:
    """刷新 web/public 数据文件（供 Vite dev 和 dist 直开使用）"""
    data_path = _resolve_data_path(date8, source)
    if not data_path.exists():
        return
    md = json.loads(data_path.read_text(encoding="utf-8"))
    md.pop("raw", None)
    # watchlist 增强：dev 路径保持与 inject() 一致
    wl_path = _resolve_watchlist_path(date8)
    if wl_path.exists():
        try:
            watchlist = json.loads(wl_path.read_text(encoding="utf-8"))
            _enhance_with_watchlist(md, watchlist)
        except Exception as e:
            print(f"⚠ watchlist 增强失败（dev 跳过）: {e}", file=sys.stderr)
    payload = json.dumps(md, ensure_ascii=False)
    dragon_payload = "{}"
    dragon_path = _resolve_dragon_tiger_path(date8)
    if dragon_path.exists():
        dragon_data = json.loads(dragon_path.read_text(encoding="utf-8"))
        dragon_payload = json.dumps(dragon_data, ensure_ascii=False)
    dev_file = ROOT / "web" / "public" / "market_data.json"
    dev_script = ROOT / "web" / "public" / "market_data.js"
    dev_dragon_file = ROOT / "web" / "public" / "dragon_tiger_data.json"
    dev_dragon_script = ROOT / "web" / "public" / "dragon_tiger_data.js"
    dev_file.parent.mkdir(parents=True, exist_ok=True)
    dev_file.write_text(payload, encoding="utf-8")
    dev_script.write_text(f"window.__MARKET_DATA__={payload};", encoding="utf-8")
    dev_dragon_file.write_text(dragon_payload, encoding="utf-8")
    dev_dragon_script.write_text(f"window.__DRAGON_TIGER_DATA__={dragon_payload};", encoding="utf-8")
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
    print(f"  龙虎榜 dev 数据已刷新: {dev_dragon_file}")
    print(f"  龙虎榜 dev 脚本已刷新: {dev_dragon_script}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="将 market_data 注入到 V3 构建产物中")
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
    print(f"✅ 数据已注入: {out}")
    source_path = _resolve_data_path(date8, args.source)
    print(f"   数据来源: {source_path.relative_to(ROOT) if source_path.is_relative_to(ROOT) else source_path}")
    print(f"   渲染来源: web/dist/index.html")

    # 同时刷新 dev 数据
    refresh_dev_data(date8, args.source)
