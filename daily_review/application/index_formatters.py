from __future__ import annotations


def display_float(v, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        if isinstance(v, str):
            return float(v.replace("%", "").replace("亿", "").replace(",", "").strip())
        return float(v)
    except Exception:
        return default


def format_index_pct(v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return ""
        if s.endswith("%"):
            return f"{display_float(s):+.2f}%"
        try:
            return f"{float(s):+.2f}%"
        except Exception:
            return s
    return f"{display_float(v):+.2f}%"


def format_index_val(v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return ""
        try:
            return f"{float(s):.2f}"
        except Exception:
            return s
    return f"{display_float(v):.2f}"
