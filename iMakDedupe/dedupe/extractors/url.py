"""mercari URL から item_id / shops product_id 抽出.

mercari URL パターン:
- 通常出品: `https://jp.mercari.com/item/m12345678901`
- Shops:    `https://jp.mercari.com/shops/product/abc123-def`

fail-closed: pattern hit せず取れなければ None。
"""

from __future__ import annotations

import re
from typing import Optional

_MERCARI_ITEM_RE = re.compile(r"/item/(m\d+)")
_MERCARI_SHOPS_RE = re.compile(r"/shops/product/([\w-]+)")


def extract_mercari_item_id(url: str) -> Optional[str]:
    """通常メルカリ item_id (= m12345678901)."""
    if not url:
        return None
    m = _MERCARI_ITEM_RE.search(url)
    return m.group(1) if m else None


def extract_mercari_shops_id(url: str) -> Optional[str]:
    """Mercari Shops product_id."""
    if not url:
        return None
    m = _MERCARI_SHOPS_RE.search(url)
    return m.group(1) if m else None


def extract_mercari_url_key(url: str) -> Optional[str]:
    """URL 突合 key. 通常 / Shops どちらか hit すれば返す.

    通常 / Shops は path namespace が異なるため id 値衝突しない前提だが、
    呼出側で混在管理しやすいよう prefix 付き string を返す:
    - `item:m12345` / `shops:abc-def`
    """
    if not url:
        return None
    item = extract_mercari_item_id(url)
    if item:
        return f"item:{item}"
    shop = extract_mercari_shops_id(url)
    if shop:
        return f"shops:{shop}"
    return None
