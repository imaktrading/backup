"""variant メタ adapter — 出品くん / 重複くん 共通利用 (= Catalog SSOT 案).

依頼: 2026-05-27_catalog_variant_meta_phase_a_implementation.md

設計:
  - PSA Subject の表記揺れ吸収 (= 'ALTERNATE ART' / 'ALT ART' → 'AR') を catalog 側で一元化
  - products.variants (JSON) から variant 別メタ (features/finish/rarity_ebay/title_token) 取得
  - 各 worker (= 出品くん psa_to_csv / 重複くん dedup) は本 adapter 経由で SSOT 参照

設計 (= memory `catalog_ssot_principle`):
  - 公式値そのまま返却、 推測拡張なし
  - variant_code 未登録 → None (= fail-closed)
  - variants JSON 構造不正 → graceful None
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

# iMakCatalog/api.py を import
_CATALOG_ROOT = Path(__file__).resolve().parent.parent
if str(_CATALOG_ROOT) not in sys.path:
    sys.path.insert(0, str(_CATALOG_ROOT))
import api  # noqa: E402


# ============================================================================
# 表記揺れ → variant_code (= PSA 略号)
# ============================================================================
# Tier 1: 具体的 alias 文字列 (= subject に明示記載されてる場合)
# 'SAR' は 'AR' を含むので 'SPECIAL ART RARE' を 'ALTERNATE ART' より先に判定
_SPECIFIC_ALIASES: list[tuple[str, str]] = [
    ("SPECIAL ART RARE",      "SAR"),
    ("SPECIAL ART",           "SAR"),
    ("ALTERNATE ART",         "AR"),
    ("ALT ART",               "AR"),
    ("HYPER RARE",            "HR"),
    ("ULTRA RARE",            "UR"),
    ("SECRET RARE",           "SR"),
    ("SUPER RARE",            "SR"),
    ("FULL ART",              "FA"),
    ("MASTER",                "MA"),
]

# Tier 2: 単語境界で直接 略号も拾う (= 'AREA' 等 false match 回避)
_DIRECT_CODES = ["SAR", "AR", "SR", "UR", "HR", "FA", "MA", "RR", "RRR"]

# Tier 3: 一般 distribution marker (= 具体 variant_code 不在時の fallback)
_GENERAL_MARKERS: list[tuple[str, str]] = [
    ("JUMBO", "Jumbo"),
    ("PROMO", "Promo"),
]


def extract_variant_alias(subject: str) -> Optional[str]:
    """PSA Subject から variant_code 抽出 (= 表記揺れ吸収).

    優先順位:
      Tier 1: 具体的 alias (= 'SPECIAL ART RARE' / 'ALTERNATE ART' 等)
      Tier 2: 単語境界で直接 略号 (= 'CHARIZARD UR PROMO' → 'UR' = 具体 code 優先)
      Tier 3: 一般 marker (= 'PROMO' / 'JUMBO'、 具体 variant_code 不在時)

    例:
      'ALTERNATE ART' / 'ALT ART'    → 'AR'
      'SPECIAL ART RARE' / 'SAR'     → 'SAR'
      'SECRET RARE' / 'SR'           → 'SR'
      'HYPER RARE'                   → 'HR'
      'ULTRA RARE'                   → 'UR'
      'CHARIZARD UR PROMO'           → 'UR' (= Tier 2 優先で 'Promo' より先)
      'FULL ART' / 'FA'              → 'FA'
      'PROMO'                        → 'Promo'
      'JUMBO'                        → 'Jumbo'

    Args:
        subject: PSA Subject 文字列 (= 任意 case)

    Returns:
        正規化 variant_code | None (= 該当なし)
    """
    if not subject:
        return None
    upper = subject.upper()

    # Tier 1: 具体的 alias
    for alias, code in _SPECIFIC_ALIASES:
        if alias in upper:
            return code

    # Tier 2: 単語境界で直接 略号
    for code in _DIRECT_CODES:
        if re.search(rf"\b{code}\b", upper):
            return code

    # Tier 3: 一般 marker (= fallback)
    for alias, code in _GENERAL_MARKERS:
        if alias in upper:
            return code

    return None


# ============================================================================
# variants JSON 取得
# ============================================================================
def get_variant_meta(
    product_id: str,
    variant_code: str,
    category: str = "pokemon_tcg",
) -> Optional[dict]:
    """catalog products.variants から該当 variant メタ取得.

    Args:
        product_id: catalog product_id (例 'SV1V-086')
        variant_code: PSA 略号 (例 'AR' / 'SAR' / 'SR')
        category: catalog category (default 'pokemon_tcg')

    Returns:
        {'features': ..., 'finish': ..., 'rarity_ebay': ..., 'title_token': ...} | None
    """
    if not product_id or not variant_code:
        return None

    record = api.lookup(category, product_id)
    if not record:
        return None

    variants_raw = record.get("variants")
    if not variants_raw:
        return None

    try:
        variants = (
            json.loads(variants_raw) if isinstance(variants_raw, str) else variants_raw
        )
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(variants, dict):
        return None

    meta = variants.get(variant_code)
    if not isinstance(meta, dict):
        return None
    return meta
