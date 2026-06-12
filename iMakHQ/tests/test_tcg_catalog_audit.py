"""tcg_catalog_audit の回帰テスト (2026-06-13 新設・並行ビルド第一歩)。

catalog照合チェックが、既存チェックの素通りさせた誤りを捕まえることを固定する:
  - C:Card Name / C:Character へのセット名混入 (#4 Zamazenta 'Vmax Climax')
  - catalog に rarity 無いのに C:Rarity を推測で埋めた (#1 Marnie 'Common')
  - 正常行は誤検出しない
比較は純関数 compare_to_catalog で DB/網羅に依存せずテストする。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from tcg_catalog_audit import compare_to_catalog, _norm_tokens, _detect_franchise, RARITY_MAP


def _tags(findings):
    return [t for t, _ in findings]


# --- セット名混入の検出 (#4 Zamazenta) ---
def test_setname_pollution_in_cardname_and_character():
    rec = {"name_en": "Zamazenta V", "rarity_code": "RR"}
    f = compare_to_catalog("Zamazenta V Vmax Climax", "Zamazenta V Vmax Climax", "Double Rare", rec)
    tags = _tags(f)
    assert "MISMATCH" in tags      # Card Name ≠ name_en
    assert "POLLUTION" in tags     # Character に vmax/climax 混入


# --- rarity 推測の検出 (#1 Marnie: catalog に rarity 無) ---
def test_rarity_guessed_when_catalog_has_none():
    rec = {"name_en": "Marnie's Morpeko", "rarity_code": ""}
    f = compare_to_catalog("Marnie's Morpeko", "Marnie", "Common", rec)
    assert "GUESSED" in _tags(f)


def test_rarity_mismatch():
    rec = {"name_en": "Altaria", "rarity_code": "CHR"}
    f = compare_to_catalog("Altaria", "Altaria", "Common", rec)
    assert "MISMATCH" in _tags(f)   # Common ≠ CHR→Character Rare


# --- 正常行は誤検出しない ---
def test_clean_row_no_findings():
    rec = {"name_en": "Altaria", "rarity_code": "CHR"}
    f = compare_to_catalog("Altaria", "Altaria", "Character Rare", rec)
    assert f == []


def test_trainer_character_subset_ok():
    """C:Character がキャラ(トレーナー)名で name_en の部分集合なら汚染でない。"""
    rec = {"name_en": "Marnie's Morpeko", "rarity_code": ""}
    f = compare_to_catalog("Marnie's Morpeko", "Marnie", "", rec)
    assert "POLLUTION" not in _tags(f)   # Marnie ⊂ Marnie's Morpeko


# --- helper ---
def test_norm_tokens_strips_possessive():
    assert _norm_tokens("Marnie's Morpeko") == ["marnie", "morpeko"]


def test_detect_franchise_handles_accent():
    assert _detect_franchise("Pokémon TCG", "") == "pokemon_tcg"
    assert _detect_franchise("One Piece Card Game", "") == "one_piece_tcg"


def test_rarity_map_covers_common_codes():
    for code in ("AR", "SAR", "RR", "SR", "CHR", "UR", "C"):
        assert code in RARITY_MAP
