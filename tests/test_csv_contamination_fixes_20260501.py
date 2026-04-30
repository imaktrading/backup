"""Regression: 2026-05-01 CSV 汚染事故対応 (3件 list 拡張).

事故 (csv_output/tcg_upload_20260501_053854.csv):
  - 行 6 (cert 141820414) Bonney Mini-Tin Vol.2: catalog ヒットせず Card Name 汚染
    "Jewelry Bonney Mini-Tin Ps VOL.2-Rokushiro" / Card # "113" (P- 欠落)
  - 行 7 (cert 141820371) Robin Mini-Tin Vol.2: 同型
  - 行 1 (cert 120628342) Pokemon Elesa Sparkle: title に "Fa/" 残存
  - 行 5 (cert 88756207) Nami OP01-016: title 末尾 "Promotion Card Set 1"

修正方針 (本体 logic 不変、既存 list への entry 追加のみ):
  Fix 1: iMakCatalog/integrations/psa_to_csv.py promo_keywords に "MINI-TIN" 追加
  Fix 2: iMakTCG/title_generation_agent.py EBAY_FORBIDDEN_TERMS に Pokemon prefix
  Fix 3: iMakTCG/psa_to_csv.py extract_character_name suffix_patterns に
         "PROMOTION CARD SET N"

本テストは 3 修正を物理ギブス化、退化を pre-commit で拒否する.
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TCG = _REPO_ROOT / "iMakTCG"
_CATALOG = _REPO_ROOT / "iMakCatalog"
for p in (_TCG, _CATALOG):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _load_module_by_path(path: Path, name: str):
    """sys.path 経由でなく絶対パスから module を load.

    test_gshock_lookup.py が iMakCatalog/integrations を sys.path に挿入するため、
    `from psa_to_csv import` が iMakCatalog 側 psa_to_csv に解決される競合を回避.
    """
    spec = importlib.util.spec_from_file_location(name, str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# iMakTCG/psa_to_csv.py を一意な module 名で load (sys.path 競合を回避)
_psa_tcg = _load_module_by_path(_TCG / "psa_to_csv.py", "_test_psa_to_csv_tcg")


# ============================================================================
# Fix 1: extract_set_code_from_brand に MINI-TIN を P 扱い化
# ============================================================================
def test_extract_set_code_mini_tin_vol2():
    """Mini-Tin Vol.2 系 PSA brand → set_code='P' (catalog promo lookup 経由)."""
    from integrations.psa_to_csv import extract_set_code_from_brand
    # 実際の PSA brand 例 (Bonney/Robin Mini-Tin Vol.2)
    assert extract_set_code_from_brand("MINI-TIN VOL.2 ROKUSHIRO") == "P"
    assert extract_set_code_from_brand("ONE PIECE MINI TIN VOL.2") == "P"
    assert extract_set_code_from_brand("Mini-Tin Pack Set Vol.2") == "P"


def test_extract_set_code_specific_set_still_wins():
    """Set-specific code (OP07 等) が brand に含まれる場合は MINI-TIN より優先."""
    from integrations.psa_to_csv import extract_set_code_from_brand
    # OP07 等の set code が混在する brand では、specific code が勝つ
    assert extract_set_code_from_brand("ONE PIECE OP07-WINGS OF THE CAPTAIN") == "OP07"
    assert extract_set_code_from_brand("OP14 MINI-TIN") == "OP14"


def test_extract_set_code_unrelated_brand_unchanged():
    """既存挙動: 認識できない brand は None."""
    from integrations.psa_to_csv import extract_set_code_from_brand
    assert extract_set_code_from_brand("RANDOM SET") is None
    assert extract_set_code_from_brand("") is None
    assert extract_set_code_from_brand(None) is None


# ============================================================================
# Fix 2: EBAY_FORBIDDEN_TERMS で Pokemon rarity prefix を strip
# ============================================================================
def test_title_strips_pokemon_fa_prefix():
    """Title 中の 'Fa/' (= FA/Full Art) を除去 (Elesa Sparkle 事故)."""
    from title_generation_agent import _apply_ng_filter
    result = _apply_ng_filter("PSA 10 Pokemon VSTAR Universe #246 Fa/Elesa's Sparkle Card")
    assert "Fa/" not in result
    assert "FA/" not in result
    assert "Elesa's Sparkle" in result


def test_title_strips_pokemon_other_rarity_prefixes():
    """AR/SAR/SR/UR/HR/MR/PR/ も同様に除去 (Pokemon prefix 全種)."""
    from title_generation_agent import _apply_ng_filter
    for prefix in ["AR", "SAR", "SR", "UR", "HR", "MR", "PR"]:
        # 大小文字混在で check (smart_titlecase 後の形式)
        title = f"PSA 10 Pokemon #100 {prefix.title()}/Pikachu Card"
        result = _apply_ng_filter(title)
        assert f"{prefix.title()}/" not in result, f"{prefix} prefix が残存"
        assert "Pikachu" in result


def test_title_does_not_strip_unrelated_slashes():
    """関係ない文字列 (URL 等) は影響を受けない (副作用ゼロ確認)."""
    from title_generation_agent import _apply_ng_filter
    # 'OPS/' 等の架空 prefix は対象外 → そのまま残る
    assert "OPS/" in _apply_ng_filter("X OPS/Y")
    # eBay 内部の "Mini-Tin Pk Set" 既存ルールも生きていること
    result = _apply_ng_filter("Test Mini-Tin Pk Set X")
    assert "Pk Set" not in result


# ============================================================================
# Fix 3: extract_character_name に "PROMOTION CARD SET N" suffix 追加
# ============================================================================
def test_extract_character_strips_promotion_card_set():
    """末尾 'PROMOTION CARD SET N' を剥がす (OP01-016 Nami 事故)."""
    extract_character_name = _psa_tcg.extract_character_name
    assert extract_character_name("NAMI PROMOTION CARD SET 1") == "NAMI"
    assert extract_character_name("MONKEY D LUFFY PROMOTION CARD SET 2") == "MONKEY D LUFFY"


def test_extract_character_does_not_overstrip():
    """'PROMOTION' 単独 / 番号無し は剥がさない (副作用回避)."""
    extract_character_name = _psa_tcg.extract_character_name
    # 既知の 'PROMO' 単独 suffix 規則は維持される
    assert extract_character_name("NAMI PROMO") == "NAMI"
    # 番号無し 'PROMOTION CARD SET' は新規パターン非マッチ
    # PROMO 規則が末尾の 'OTION CARD SET' を剥がさないことを確認
    result = extract_character_name("NAMI PROMOTION CARD SET")
    assert "NAMI" in result
