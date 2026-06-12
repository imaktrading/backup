"""variant 抽出 (Phase 1f) — title keyword から rarity variant 識別子を取得.

KEY2 (= variant code) の役割: KEY1 (= card_id / 型番 / URL) が同じでも
別 variant (= 例 Alt Art / Secret Rare) は別商品として **物理除外しない**。
(KEY1, KEY2) tuple 完全一致のみ「真の重複」 = false positive ゼロ化.

fail-closed: keyword hit せず → "" (= 通常版扱い)、 推測で variant 付けない。
"""

from __future__ import annotations

import re
from typing import Tuple

# 抽出優先順 (= rarity 価値順、 複数 hit 時は最も rare な variant を採用)
VARIANT_PRIORITY: Tuple[str, ...] = ("sec", "alt", "par", "pro", "spc", "fa")

# (pattern, code) - title 内 keyword の正規表現
_PATTERNS: Tuple[Tuple[re.Pattern, str], ...] = (
    # Secret (Rare) = sec
    (re.compile(r"\bSecret(?:\s+Rare)?\b", re.IGNORECASE), "sec"),
    # Alt(ernate) Art / Alt Art = alt
    (re.compile(r"\bAlt(?:ernate)?\s+Art\b", re.IGNORECASE), "alt"),
    # Alternative Art (= eBay Features aspect 表記)
    (re.compile(r"\bAlternative\s+Art\b", re.IGNORECASE), "alt"),
    # Parallel = par
    (re.compile(r"\bParallel\b", re.IGNORECASE), "par"),
    # Promo = pro
    (re.compile(r"\bPromo(?:tional)?\b", re.IGNORECASE), "pro"),
    # Special = spc
    (re.compile(r"\bSpecial\b", re.IGNORECASE), "spc"),
    # Full Art = fa
    (re.compile(r"\bFull\s+Art\b", re.IGNORECASE), "fa"),
)


def extract_variant(text: str) -> str:
    """text (= title or aspect 値) から variant code を抽出.

    複数 hit 時は VARIANT_PRIORITY 順で最も rare な code を返す。
    hit 無し / empty input → "" (= 通常版)。
    """
    if not text:
        return ""
    found = set()
    for pat, code in _PATTERNS:
        if pat.search(text):
            found.add(code)
    if not found:
        return ""
    for code in VARIANT_PRIORITY:
        if code in found:
            return code
    return ""
