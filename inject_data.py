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


def inject(date8: str, source: Optional[str] = None) -> Path:
    """注入数据并返回输出路径"""
    # 读取市场数据
    data_path = _resolve_data_path(date8, source)
    if not data_path.exists():
        raise FileNotFoundError(f"数据缓存不存在: {data_path}")

    md = json.loads(data_path.read_text(encoding="utf-8"))
    # 清理前端不需要的大字段
    md.pop("raw", None)
    payload = json.dumps(md, ensure_ascii=False)

    # 读取 Vite 构建产物
    built = ROOT / "web" / "dist" / "index.html"
    if not built.exists():
        raise FileNotFoundError(f"Vite 构建产物不存在: {built}\n请先执行: cd web && npm run build")

    html = built.read_text(encoding="utf-8")

    # 注入 window.__MARKET_DATA__ 到 </head> 前
    data_script = f"<script>window.__MARKET_DATA__={payload};</script>"
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

    # 注入明日策略池数据（如果已预取）
    tp_path = ROOT / "web" / "dist" / "tomorrow_picks.json"
    if tp_path.exists():
        tp_data = tp_path.read_text(encoding="utf-8")
        tp_script = f"<script>window.__TOMORROW_PICKS__={tp_data};</script>"
        if "</head>" in html:
            html = html.replace("</head>", f"{tp_script}\n  </head>")
        else:
            html = html + "\n" + tp_script

    # 同步 dist 旁路数据文件，支持直接打开 web/dist/index.html
    dist_dir = ROOT / "web" / "dist"
    (dist_dir / "market_data.json").write_text(payload, encoding="utf-8")
    (dist_dir / "market_data.js").write_text(f"window.__MARKET_DATA__={payload};", encoding="utf-8")

    return out_path


def refresh_dev_data(date8: str, source: Optional[str] = None) -> None:
    """刷新 web/public 数据文件（供 Vite dev 和 dist 直开使用）"""
    data_path = _resolve_data_path(date8, source)
    if not data_path.exists():
        return
    md = json.loads(data_path.read_text(encoding="utf-8"))
    md.pop("raw", None)
    payload = json.dumps(md, ensure_ascii=False)
    dev_file = ROOT / "web" / "public" / "market_data.json"
    dev_script = ROOT / "web" / "public" / "market_data.js"
    dev_file.parent.mkdir(parents=True, exist_ok=True)
    dev_file.write_text(payload, encoding="utf-8")
    dev_script.write_text(f"window.__MARKET_DATA__={payload};", encoding="utf-8")
    print(f"  dev 数据已刷新: {dev_file}")
    print(f"  dev 脚本已刷新: {dev_script}")


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
