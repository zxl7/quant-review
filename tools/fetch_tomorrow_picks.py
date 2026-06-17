#!/usr/bin/env python3
"""
fetch_tomorrow_picks.py — 从 market_data 缓存提取明日策略池，输出 JSON。

用于 CI 中生成 dev 版本的明日策略池数据。
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def main():
    output = sys.argv[1] if len(sys.argv) > 1 else "web/public/tomorrow_picks.json"
    output_path = Path(output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path

    # 取最新的 market_data
    cache_dir = ROOT / "cache"
    files = sorted(cache_dir.glob("market_data-*.json"))
    if not files:
        print("⚠ No market_data cache found, writing empty")
        output_path.write_text("{}", encoding="utf-8")
        return 0

    latest = files[-1]
    data = json.loads(latest.read_text(encoding="utf-8"))

    # 提取 ztAnalysis 中的 relay 和 watch
    za = data.get("ztAnalysis") or {}
    relay = za.get("relay") or []
    watch = za.get("watch") or []

    picks = {
        "date": data.get("date", ""),
        "generatedAt": data.get("meta", {}).get("generatedAt", ""),
        "relay": relay[:15],
        "watch": watch[:15],
        "relaySelectionMode": za.get("meta", {}).get("relaySelectionMode", ""),
        "relayDiagnostics": za.get("meta", {}).get("relayDiagnostics", {}),
        "watchGroups": [str(row.get("watchGroup") or "").strip() for row in watch[:15] if isinstance(row, dict) and str(row.get("watchGroup") or "").strip()],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(picks, ensure_ascii=False), encoding="utf-8")
    print(f"✅ 明日策略池已写入: {output_path} ({len(relay)} relay / {len(watch)} watch)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
