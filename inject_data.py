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

ROOT = Path(__file__).resolve().parent


def inject(date8: str) -> Path:
    """注入数据并返回输出路径"""
    # 读取市场数据
    data_path = ROOT / "cache" / f"market_data-{date8}.json"
    if not data_path.exists():
        raise FileNotFoundError(f"数据缓存不存在: {data_path}")

    md = json.loads(data_path.read_text(encoding="utf-8"))
    # 清理前端不需要的大字段
    md.pop("raw", None)

    # 读取 Vite 构建产物
    built = ROOT / "web" / "dist" / "index.html"
    if not built.exists():
        raise FileNotFoundError(f"Vite 构建产物不存在: {built}\n请先执行: cd web && npm run build")

    html = built.read_text(encoding="utf-8")

    # 注入 window.__MARKET_DATA__ 到 </head> 前
    data_script = f"<script>window.__MARKET_DATA__={json.dumps(md, ensure_ascii=False)};</script>"
    if "</head>" in html:
        html = html.replace("</head>", f"{data_script}\n  </head>")
    else:
        html = data_script + "\n" + html

    # 替换标题为日期格式
    report_date = md.get("date", date8)
    html = html.replace("<title>A股简报</title>", f"<title>{report_date} A股简报</title>")
    # 清理旧模板残留的 title 标签
    html = html.replace("<title>A股收盘简报 | __REPORT_DATE__</title>", "")
    html = html.replace("<title><!-- legacy template --></title>", "")

    # 写入输出
    out_dir = ROOT / "html"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"复盘日记-{date8}-tab-v1.html"
    out_path.write_text(html, encoding="utf-8")

    # 同时写 index.html 用于本地预览
    index_path = out_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")

    return out_path


def refresh_dev_data(date8: str) -> None:
    """刷新 web/public 数据文件（供 Vite dev 和 dist 直开使用）"""
    data_path = ROOT / "cache" / f"market_data-{date8}.json"
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
    import sys

    # --dev-only：仅刷新 web/public/__data.js，不构建
    if len(sys.argv) > 1 and sys.argv[1] == "--dev-only":
        files = sorted((ROOT / "cache").glob("market_data-2026*.json"))
        if not files:
            print("错误: cache/ 中没有 market_data-*.json", file=sys.stderr)
            sys.exit(1)
        date8 = files[-1].name.replace("market_data-", "").replace(".json", "")
        refresh_dev_data(date8)
        sys.exit(0)

    date8 = sys.argv[1] if len(sys.argv) > 1 else None
    if not date8:
        # 自动取最新缓存
        files = sorted((ROOT / "cache").glob("market_data-2026*.json"))
        if not files:
            print("错误: cache/ 中没有 market_data-*.json", file=sys.stderr)
            sys.exit(1)
        date8 = files[-1].name.replace("market_data-", "").replace(".json", "")

    out = inject(date8)
    print(f"✅ 数据已注入: {out}")
    print(f"   数据来源: cache/market_data-{date8}.json")
    print(f"   模板来源: web/dist/index.html")

    # 同时刷新 dev 数据
    refresh_dev_data(date8)
