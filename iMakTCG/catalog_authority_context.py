"""catalog_authority_context - iMakCatalog hit 時の 3AI 判定 context 生成 (独立モジュール).

設計原則 (修正連鎖を生まないため):
  - 既存モジュール (listing_validator / catalog_psa / iMakCatalog) を一切修正しない
  - psa_to_csv は import + 1関数呼出のみで導入、try/except で完全フォールバック
  - 失敗時は None 返却 (3AI は通常判定継続)

設計思想:
  - iMakCatalog (Bandai 公式 DB) が ID 完全一致で hit した時、
    PSA Brand 文字列との表記揺れを「矛盾」と扱わない context を 3AI に注入
  - 例: iMakCatalog "The Three Captains" vs PSA Brand "AZURE SEA'S SEVEN"
    → 同じ OP-14 のサブテーマ表記、3AI が機械的 BLOCK しないように説明

修正連鎖を生まない仕掛け:
  - context 生成専用、判定ロジックには一切介入しない
  - listing_validator の override_context パイプを再利用 (既存機構)
  - hit/miss 判定もこのモジュール内で完結 (本体に flag 持たせない)

使用例:
    from catalog_authority_context import maybe_build_context
    context = maybe_build_context(brand, card_number, subject, franchise)
    # context が None なら 3AI 通常判定、文字列なら override_context として渡す
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional


# ============================================================================
# iMakCatalog adapter import (失敗してもフォールバック)
# ============================================================================
def _import_catalog():
    """iMakCatalog の adapter (catalog_psa) を遅延 import.
    隣で開発中なので import 失敗しても落ちないようにする."""
    try:
        # psa_to_csv.py と同じ sys.path 設定 (iMakCatalog/integrations を見せる)
        catalog_root = Path(__file__).resolve().parent.parent / "iMakCatalog"
        if str(catalog_root) not in sys.path:
            sys.path.insert(0, str(catalog_root))
        from integrations import psa_to_csv as catalog_psa  # type: ignore
        return catalog_psa
    except Exception:
        return None


# ============================================================================
# 公開 API
# ============================================================================
def maybe_build_context(
    brand: str,
    card_number: str,
    subject: str = "",
    franchise: str = "",
) -> Optional[str]:
    """iMakCatalog ID 一致 hit 時、3AI への context 文字列を返す.

    Args:
        brand:       PSA Brand (例: 'ONE PIECE JAPANESE OP14-AZURE SEA\\'S SEVEN')
        card_number: PSA card number (例: '034')
        subject:     PSA Subject (キャラ名検証用)
        franchise:   "One Piece" / "Pokemon" / その他

    Returns:
        context str (hit 時) | None (miss / 例外 / 対象 franchise 外)
    """
    if not card_number or not brand:
        return None

    catalog = _import_catalog()
    if catalog is None:
        return None

    if franchise == "One Piece":
        return _one_piece_context(catalog, brand, card_number, subject)
    if franchise == "Pokemon":
        return _pokemon_context(catalog, brand, card_number, subject)
    return None


def _one_piece_context(catalog, brand, card_number, subject) -> Optional[str]:
    try:
        record = catalog.lookup_one_piece(brand, card_number, subject, verbose=False)
    except Exception:
        return None
    if not record:
        return None

    catalog_set_name = (
        record.get("set_name_ebay")
        or record.get("set_name_official")
        or ""
    ).strip()
    catalog_card_id = (record.get("card_id") or "").strip()
    catalog_name = (record.get("name_en") or "").strip()
    if not catalog_set_name and not catalog_card_id:
        return None

    return (
        "=== iMakCatalog AUTHORITY (One Piece) ===\n"
        f"iMakCatalog (Bandai 公式DB を集約した内部マスター) が ID 完全一致で hit しました:\n"
        f"  card_id:       {catalog_card_id}\n"
        f"  card_name(EN): {catalog_name}\n"
        f"  set_name(EN):  '{catalog_set_name}'  ← eBay 正規セット名\n\n"
        f"PSA Brand 文字列: '{brand}'\n\n"
        "判定ルール:\n"
        " - card_number が一致 + iMakCatalog ID hit がある場合、catalog set_name を正規とみなす\n"
        " - PSA Brand は同じカードシリーズの「サブテーマ/プロモ別名」(例: 'AZURE SEA\\'S SEVEN' = OP-14 内の七武海テーマ表記) の可能性が高い\n"
        " - set_name の文字列差だけを根拠に矛盾扱いしない (BLOCK しない)\n"
        " - 検証は引き続き Subject/character/image 整合性に集中する\n"
    )


def _pokemon_context(catalog, brand, card_number, subject) -> Optional[str]:
    """Pokemon 用 3AI context. catalog hit 時に Attribute/MTG:Color 列の解釈と
    set_name 表記揺れを 3AI に説明する."""
    try:
        record = catalog.lookup_pokemon(brand, card_number, subject, verbose=False)
    except Exception:
        return None
    if not record:
        return None

    catalog_set_name = (
        record.get("set_name_ebay")
        or record.get("set_name_official")
        or ""
    ).strip()
    catalog_card_id = (record.get("card_id") or "").strip()
    catalog_name = (record.get("name_jp") or record.get("name_en") or "").strip()
    catalog_type = (record.get("type_en") or "").strip()
    catalog_rarity = (record.get("rarity") or record.get("rarity_en") or "").strip()

    if not catalog_set_name and not catalog_card_id:
        return None

    return (
        "=== iMakCatalog AUTHORITY (Pokemon) ===\n"
        f"iMakCatalog (pokemon-card.com 公式DBを集約した内部マスター) が ID 完全一致で hit:\n"
        f"  card_id:       {catalog_card_id}\n"
        f"  card_name(JP): {catalog_name}\n"
        f"  set_name(EN):  '{catalog_set_name}'  ← eBay 正規セット名\n"
        f"  type(EN):      '{catalog_type}'      ← Pokemon タイプ (Psychic/Fire/Grass 等)\n"
        f"  rarity:        '{catalog_rarity}'    ← Pokemon 公式ラリリティ short code\n\n"
        f"PSA Brand 文字列: '{brand}'\n"
        f"PSA Subject:      '{subject}'\n\n"
        "判定ルール (Pokemon TCG eBay 出品の慣習):\n"
        " 1. **C:Attribute/MTG:Color 列**: Pokemon TCG では eBay の慣習として\n"
        "    Pokemon タイプ (Psychic/Fire/Water/Lightning/Grass/Fighting/Darkness/Metal\n"
        "    /Fairy/Dragon/Colorless) を入れる. 'Psychic' 等が入っていても矛盾扱い禁止.\n"
        "    (列名に 'Color' とあっても、TCG/MTG 共通フィールドのため Pokemon タイプ可)\n\n"
        " 2. **rarity short code**: 公式 image filename 由来 (SAR/SR/AR/RR/UR/HR/MA/L 等).\n"
        "    eBay の rarity フィルタ値と一致するので、'SAR' = 'Special Art Rare', 'AR' = 'Art Rare'\n"
        "    等の表記揺れ (省略形 vs 展開形) で BLOCK しない.\n\n"
        " 3. **set_name 表記揺れ**: PSA Brand が省略形で書く場合 (例: 'SV9-BATTLE PARTNERS' →\n"
        "    catalog '拡張パック「バトルパートナーズ」'), iMakCatalog の set_name(EN) を正規とする.\n\n"
        " 4. **card_number 一致 + ID hit がある場合、catalog 値を信頼**.\n"
        "    検証は Subject/character/image 整合性に集中する.\n"
    )


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    samples = [
        ("ONE PIECE JAPANESE OP14-AZURE SEA'S SEVEN", "034", "MONKEY D. LUFFY", "One Piece"),
        ("ONE PIECE JAPANESE OP06-WINGS OF THE CAPTAIN", "022", "MONKEY D. LUFFY", "One Piece"),
        ("Pokemon SV9 #105", "105", "LILLIE'S RIBOMBEE", "Pokemon"),  # 対象外 → None
        ("", "", "", "One Piece"),  # 空入力 → None
    ]
    for brand, num, subj, fr in samples:
        print(f"--- brand={brand!r} card#={num} subject={subj!r} franchise={fr}")
        ctx = maybe_build_context(brand, num, subj, fr)
        if ctx is None:
            print("    → context: None (catalog miss / out-of-scope)")
        else:
            print(f"    → context ({len(ctx)}文字):")
            for line in ctx.splitlines():
                print(f"      | {line}")
        print()
