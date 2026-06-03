"""normalize.py - 比較前 format normalize (= 必須、format ズレ防止).

V8 出力 と eBay 側 source の format ズレで全件不一致判定にならないように
比較前に必ず通す normalize 関数群。

依頼書 (2026-05-22_revise_trigger_simplification.md) 4.5. 必須実装。
"""
from __future__ import annotations

import re
from typing import Optional


_POLICY_RE = re.compile(r"^DDP-([ABC])-P(\d+)$")


def normalize_policy_name(name) -> str:
    """Policy 名 normalize.

    例:
      "DDP-A-P9"  → "DDP-A-P09"   (= tier 部 0 埋め 2 桁統一)
      "DDP-A-P09" → "DDP-A-P09"   (= 変化なし)
      "Free"      → "Free"        (= legacy 名はそのまま)
      "100-200 Copy" → "100-200 Copy"
      " DDP-A-P5 " → "DDP-A-P05"  (= whitespace trim)
      None        → ""

    Returns: normalized 文字列 (= "" / 元値 / "DDP-X-PXX")
    """
    if name is None:
        return ""
    s = str(name).strip()
    if not s:
        return ""
    m = _POLICY_RE.match(s)
    if not m:
        return s
    return f"DDP-{m.group(1)}-P{int(m.group(2)):02d}"


def normalize_usd(price) -> Optional[float]:
    """USD price normalize.

    例:
      "$397.98"  → 397.98
      "397.98"   → 397.98
      "1,234.56" → 1234.56
      397.98     → 397.98
      None / "" / "abc" → None

    Returns: round 2 桁 float or None
    """
    if price is None:
        return None
    if isinstance(price, (int, float)):
        return round(float(price), 2)
    s = str(price).replace("$", "").replace(",", "").strip()
    if not s:
        return None
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def normalize_url(url) -> Optional[str]:
    """URL normalize (= 空欄判定統一).

    例:
      "https://..." → "https://..."
      "   " → None
      "" → None
      None → None
    """
    if url is None:
        return None
    s = str(url).strip()
    return s if s else None


# D 列 SOLD マーカー (全 format 網羅)
SOLD_MARKERS = {"○", "✓", "Sold", "SOLD", "sold", "TRUE", "true", "1", "YES", "yes"}


def is_sold(d_col_val) -> bool:
    """D 列の SOLD マーカー判定.

    例:
      "○"     → True
      "✓"     → True
      "SOLD"  → True
      " "     → False
      ""      → False
      None    → False
    """
    if d_col_val is None:
        return False
    return str(d_col_val).strip() in SOLD_MARKERS
