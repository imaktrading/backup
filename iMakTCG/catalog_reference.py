"""catalog_reference - iMakCatalog 参照サブルーチン (補助情報源として).

設計原則 (修正連鎖を生まないため):
  - 既存モジュール (psa_to_csv / catalog_psa / iMakCatalog) を一切修正しない
  - psa_to_csv の build_row 末尾で 1 関数呼出のみ (try/except で完全フォールバック)
  - 失敗時は元 specs 返却 + 警告 0 件 (既存挙動維持)

設計思想:
  iMakCatalog は隣セッションで開発中で、正式運用合意は未済 (2026-04-27 確認).
  → メインパイプラインは従来通り動く. catalog は **補助情報源** として参照のみ.

  動作モード:
    1. 既存 specs に空欄 (未確定値) → catalog 値で **補完** (副次情報、低リスク)
    2. 既存 specs に値あり × catalog と一致 → 何もしない (validation 通過)
    3. 既存 specs に値あり × catalog と相違 → console 警告 (上書きしない、人間判断)
    4. catalog miss → 何もしない (catalog 不完備なケース、メインパイプライン優先)

  補完対象フィールド (One Piece TCG の数値系):
    - cost (life_or_cost)
    - power
    - color (color_en)
    - card_type (type_en)

  カバー範囲:
    - One Piece TCG のみ (Phase 1 範囲)
    - Pokemon / Dragon Ball / Gundam は隣セッションが正式運用宣言するまで対象外

使用例:
    from catalog_reference import reference_catalog_for_specs
    specs_improved, warnings = reference_catalog_for_specs(
        franchise="One Piece",
        card_number="OP07-019",
        current_specs={"cost": "", "power": "5000", "color": "Green"},
    )
    # specs_improved["cost"] が catalog 由来で補完される
    # warnings: 矛盾あれば文字列リスト
"""
from __future__ import annotations

import os
import sys
from typing import Optional

# iMakCatalog adapter 遅延 import (隣で開発中、import 失敗してもフォールバック)
def _import_catalog():
    try:
        catalog_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "iMakCatalog"
        )
        if catalog_root not in sys.path:
            sys.path.insert(0, catalog_root)
        from integrations import psa_to_csv as catalog_psa  # type: ignore
        return catalog_psa
    except Exception:
        return None


# specs キー → catalog dict キー の対応 (補完候補)
# 原則: 数値系 + 安定 textual のみ. card_type は catalog 側で
# Leader/Character 表記揺れあり (rarity との混同) で警告ノイズ多いため除外.
_FILL_FIELD_MAP = {
    "cost":  "life_or_cost",
    "power": "power",
    "color": "color_en",
    # "card_type": "type_en",  # 警告ノイズが多いため対象外 (Leader vs Character 表記揺れ)
}


# ============================================================================
# 公開 API
# ============================================================================
def reference_catalog_for_specs(
    franchise: str,
    card_number: str,
    current_specs: dict,
    psa_brand: str = "",
    psa_subject: str = "",
) -> tuple:
    """既存 specs を catalog で照合して、空欄補完 + 矛盾警告を返す.

    Args:
        franchise:      "One Piece" / 他 (現状 One Piece のみ対応)
        card_number:    最終確定 card# (例: "OP07-019" / "PRB02-005")
        current_specs:  {"cost": "5", "power": "5000", "color": "Green", "card_type": "Character"}
        psa_brand:      catalog adapter の lookup ヒント (One Piece adapter で必須)
        psa_subject:    同上 (Bonney/ベポ name 検証で必要)

    Returns:
        (improved_specs, warnings_list)
            improved_specs: 空欄補完済 dict
            warnings_list:  矛盾発見時の警告文字列 list (空 if no issue)
    """
    # 範囲外 franchise は何もしない
    if franchise != "One Piece":
        return dict(current_specs), []
    if not card_number:
        return dict(current_specs), []

    catalog = _import_catalog()
    if catalog is None:
        return dict(current_specs), []

    # adapter は card_number を「数字部分のみ」期待 (例: '019', '005')
    # Vision/build_row の最終形 'OP07-019' / 'PRB02-005' / 'P-001' から数字部分抽出
    import re as _re
    num_only_match = _re.search(r"(\d+)\s*$", str(card_number))
    num_only = num_only_match.group(1) if num_only_match else str(card_number)

    try:
        record = catalog.lookup_one_piece(
            psa_brand or "", num_only, psa_subject or "", verbose=False
        )
    except Exception:
        return dict(current_specs), []

    if not record:
        return dict(current_specs), []

    out = dict(current_specs)
    warnings = []

    for spec_key, catalog_key in _FILL_FIELD_MAP.items():
        catalog_val = (record.get(catalog_key) or "").strip() if isinstance(
            record.get(catalog_key), str
        ) else str(record.get(catalog_key) or "").strip()
        if not catalog_val:
            continue
        current_val = str(out.get(spec_key, "") or "").strip()
        if not current_val:
            # case 1: 空欄補完
            out[spec_key] = catalog_val
            print(
                f"    🔍 catalog_reference: '{spec_key}' 空欄 → catalog 値 "
                f"'{catalog_val}' で補完 (card={card_number})"
            )
        elif current_val == catalog_val:
            # case 2: 一致、何もしない
            pass
        else:
            # case 3: 相違、警告のみ
            msg = (
                f"⚠️ catalog_reference: '{spec_key}' 不一致 "
                f"pipeline='{current_val}' vs catalog='{catalog_val}' "
                f"(card={card_number}) — 上書きせず人間判断"
            )
            warnings.append(msg)
            print(f"    {msg}")

    return out, warnings


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    samples = [
        # ケース 1: 空欄補完 (cost が空)
        {
            "franchise": "One Piece",
            "card_number": "OP07-019",
            "current_specs": {"cost": "", "power": "5000", "color": "Green", "card_type": "Character"},
            "psa_brand": "ONE PIECE OP07",
            "psa_subject": "JEWELRY BONNEY",
        },
        # ケース 2: 矛盾警告 (cost=4 vs catalog=5)
        {
            "franchise": "One Piece",
            "card_number": "OP07-019",
            "current_specs": {"cost": "4", "power": "5000", "color": "Green", "card_type": "Character"},
            "psa_brand": "ONE PIECE OP07",
            "psa_subject": "JEWELRY BONNEY",
        },
        # ケース 3: 一致、無音
        {
            "franchise": "One Piece",
            "card_number": "OP14-034",
            "current_specs": {"cost": "3", "power": "3000", "color": "Green", "card_type": "Character"},
            "psa_brand": "ONE PIECE OP14",
            "psa_subject": "MONKEY D. LUFFY",
        },
        # ケース 4: 範囲外 (Pokemon)
        {
            "franchise": "Pokemon",
            "card_number": "001",
            "current_specs": {"cost": "", "power": "60"},
            "psa_brand": "Pokemon",
            "psa_subject": "PIKACHU",
        },
    ]
    for i, s in enumerate(samples, 1):
        print(f"--- Sample {i} ({s['franchise']} #{s['card_number']}) ---")
        print(f"  IN : {s['current_specs']}")
        out, warns = reference_catalog_for_specs(**s)
        print(f"  OUT: {out}")
        print(f"  warnings: {warns}")
        print()
