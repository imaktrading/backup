"""Phase 2 (Gundam + Dragon Ball) adapter functions のテスト.

Phase 1 と同じ構造を踏襲:
  - extract_set_code_from_brand_*  : PSA Brand → set_code
  - lookup_*                       : ID 完全一致 lookup + 名前検証
  - set_code_to_ebay_name_*        : set_code → eBay 公式名

DB roundtrip は --full 完走後に有効になる (それまで pending skip).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import api  # noqa: E402
from integrations import psa_to_csv as catalog_psa  # noqa: E402


# ============================================================================
# Gundam: extract_set_code_from_brand_gundam
# ============================================================================
class TestGundamExtractSetCode:
    def test_gd_set(self):
        assert catalog_psa.extract_set_code_from_brand_gundam(
            "GUNDAM JAPANESE GD01-NEWTYPE RISING"
        ) == "GD01"

    def test_gd_compact(self):
        assert catalog_psa.extract_set_code_from_brand_gundam(
            "GUNDAM CARD GAME GD04 PHANTOM ARIA"
        ) == "GD04"

    def test_st_set(self):
        assert catalog_psa.extract_set_code_from_brand_gundam(
            "GUNDAM CARD ST01"
        ) == "ST01"

    def test_promo_keyword(self):
        assert catalog_psa.extract_set_code_from_brand_gundam(
            "GUNDAM PROMOS"
        ) == "P"

    def test_no_match(self):
        assert catalog_psa.extract_set_code_from_brand_gundam("RANDOM") is None
        assert catalog_psa.extract_set_code_from_brand_gundam("") is None
        assert catalog_psa.extract_set_code_from_brand_gundam(None) is None


# ============================================================================
# DBSCG: extract_set_code_from_brand_dragonball
# ============================================================================
class TestDragonballExtractSetCode:
    def test_fb_set(self):
        assert catalog_psa.extract_set_code_from_brand_dragonball(
            "DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE FB02 BLAZING AURA"
        ) == "FB02"

    def test_fs_starter(self):
        assert catalog_psa.extract_set_code_from_brand_dragonball(
            "DRAGON BALL FUSION WORLD JAPANESE FS04 STARTER FRIEZA"
        ) == "FS04"

    def test_sb_manga(self):
        assert catalog_psa.extract_set_code_from_brand_dragonball(
            "DRAGON BALL SCG MANGA BOOSTER SB02"
        ) == "SB02"

    def test_promo_keyword(self):
        assert catalog_psa.extract_set_code_from_brand_dragonball(
            "DRAGON BALL TOURNAMENT PROMO"
        ) == "FP"

    def test_no_match(self):
        assert catalog_psa.extract_set_code_from_brand_dragonball("RANDOM") is None


# ============================================================================
# Variant candidates
# ============================================================================
class TestGundamVariantCandidates:
    def test_alt_art(self):
        out = catalog_psa._variant_candidates_gundam("UNICORN GUNDAM ALTERNATE ART")
        assert "para" in out or "SP" in out

    def test_special(self):
        out = catalog_psa._variant_candidates_gundam("STRIKE FREEDOM SPECIAL")
        assert "SP" in out

    def test_no_hint(self):
        assert catalog_psa._variant_candidates_gundam("PLAIN") == []


class TestDragonballVariantCandidates:
    def test_parallel(self):
        out = catalog_psa._variant_candidates_dragonball("GOGETA PARALLEL FOIL")
        assert "PARA" in out

    def test_super_parallel(self):
        out = catalog_psa._variant_candidates_dragonball("VEGETA SUPER PARALLEL")
        assert "SUPERPARA" in out

    def test_alt_art(self):
        out = catalog_psa._variant_candidates_dragonball("FRIEZA ALTERNATE ART")
        assert any(s in out for s in ("Leader_F_PARA", "PARA"))


# ============================================================================
# JA→EN dict 拡張確認 (Phase 2 で DBSCG / Gundam キャラを追加した)
# ============================================================================
class TestJaCharDictExpansion:
    def test_dbscg_chars(self):
        for jp, expected in [
            ("孫悟空",   "GOKU"),
            ("ベジータ", "VEGETA"),
            ("フリーザ", "FRIEZA"),
            ("ゴジータ", "GOGETA"),
        ]:
            tokens = catalog_psa._JA_CHAR_TO_EN_TOKENS.get(jp, set())
            assert expected in tokens, f"{jp} → {tokens}, expected {expected}"

    def test_gundam_chars(self):
        for jp, expected in [
            ("アムロ・レイ",     "AMURO"),
            ("シャア・アズナブル", "CHAR"),
            ("バナージ・リンクス", "BANAGHER"),
            ("キラ・ヤマト",      "KIRA"),
        ]:
            tokens = catalog_psa._JA_CHAR_TO_EN_TOKENS.get(jp, set())
            assert expected in tokens, f"{jp} → {tokens}, expected {expected}"

    def test_one_piece_chars_still_present(self):
        # regression: 既存 One Piece キャラが生きているか
        assert "LUFFY" in catalog_psa._JA_CHAR_TO_EN_TOKENS.get("モンキー・D・ルフィ", set())
        assert "ZORO" in catalog_psa._JA_CHAR_TO_EN_TOKENS.get("ロロノア・ゾロ", set())


# ============================================================================
# DB roundtrip (前提: gundam_tcg / dragonball_scg --full 完走済み)
# ============================================================================
def _gundam_data_loaded() -> bool:
    """Gundam に最低限の base record (GD04-001 等) があるか."""
    return api.lookup("gundam_tcg", "GD04-001") is not None


def _dragonball_data_loaded() -> bool:
    return api.lookup("dragonball_scg", "FB09-001") is not None


REQUIRES_GUNDAM_DB = pytest.mark.skipif(
    not _gundam_data_loaded(),
    reason="Gundam --full not yet completed",
)

REQUIRES_DBSCG_DB = pytest.mark.skipif(
    not _dragonball_data_loaded(),
    reason="Dragon Ball --full not yet completed",
)


@REQUIRES_GUNDAM_DB
class TestGundamDbLookup:
    def test_lookup_gd04_001(self):
        result = catalog_psa.lookup_gundam(
            "GUNDAM JAPANESE GD04 PHANTOM ARIA",
            "001",
            subject="GUNDAM",
            verbose=False,
        )
        assert result is not None
        assert result["card_id"] == "GD04-001"
        assert result["card_number"] == "GD04-001"

    def test_unregistered_returns_none(self):
        result = catalog_psa.lookup_gundam(
            "GUNDAM JAPANESE GD99",
            "999",
            subject="X",
            verbose=False,
        )
        assert result is None


@REQUIRES_DBSCG_DB
class TestDragonballDbLookup:
    def test_lookup_fb09_001(self):
        result = catalog_psa.lookup_dragonball(
            "DRAGON BALL FUSION WORLD JAPANESE FB09 DUAL EVOLUTION",
            "001",
            subject="GOGETA",
            verbose=False,
        )
        assert result is not None
        assert result["card_id"] == "FB09-001"
        assert result["card_type"] == "Leader"
        assert result["rarity"] == "L"
        assert result["color"] == "Red"
        assert result["power"] == "15000"

    def test_lookup_parallel_variant(self):
        # PSA Subject に PARALLEL 含まれて base が存在する場合 → base 優先
        result = catalog_psa.lookup_dragonball(
            "DRAGON BALL FUSION WORLD JAPANESE FB09",
            "001",
            subject="GOGETA PARALLEL",
            verbose=False,
        )
        # FB09-001 base が存在するので base 返す (variant 試行はベース miss 時のみ)
        assert result is not None
        assert result["card_id"] == "FB09-001"

    def test_unregistered_returns_none(self):
        result = catalog_psa.lookup_dragonball(
            "DRAGON BALL FUSION WORLD JAPANESE FB99",
            "999",
            subject="X",
            verbose=False,
        )
        assert result is None

    def test_set_code_to_ebay_name(self):
        # FB02 → "Blazing Aura" (yaml で定義済み)
        assert catalog_psa.set_code_to_ebay_name_dragonball("FB02") == "Blazing Aura"


# ============================================================================
# Pokemon: extract_set_code_from_brand_pokemon
# ============================================================================
class TestPokemonExtractSetCode:
    def test_m_set_lowercase_suffix(self):
        # PSA brand は大文字、image_url は混在 → 末尾 1 文字を小文字化
        assert catalog_psa.extract_set_code_from_brand_pokemon(
            "POKEMON JAPANESE M2A-MEGA DREAM EX"
        ) == "M2a"

    def test_s8a_25th(self):
        assert catalog_psa.extract_set_code_from_brand_pokemon(
            "POKEMON JAPANESE S8A 25TH ANNIVERSARY"
        ) == "S8a"

    def test_sv_no_suffix(self):
        # 末尾英字無し → そのまま大文字
        assert catalog_psa.extract_set_code_from_brand_pokemon(
            "POKEMON JAPANESE SV4 RULER OF THE BLACK FLAME"
        ) == "SV4"

    def test_sv5_with_letter(self):
        assert catalog_psa.extract_set_code_from_brand_pokemon(
            "POKEMON JAPANESE SV5K WILD FORCE"
        ) == "SV5k"

    def test_promo(self):
        assert catalog_psa.extract_set_code_from_brand_pokemon(
            "POKEMON JAPANESE PROMOS"
        ) == "P"

    def test_no_match(self):
        assert catalog_psa.extract_set_code_from_brand_pokemon("RANDOM TEXT") is None


class TestPokemonSetCodeToEbay:
    def test_m2a(self):
        # yaml で定義済み
        assert catalog_psa.set_code_to_ebay_name_pokemon("M2a") == "Mega Dream ex"

    def test_s8a_25th(self):
        assert catalog_psa.set_code_to_ebay_name_pokemon("S8a") == "25th Anniversary Collection"

    def test_case_insensitive(self):
        # PSA brand は大文字 → 末尾小文字版を試行する
        assert catalog_psa.set_code_to_ebay_name_pokemon("M2A") == "Mega Dream ex"

    def test_unmapped_passthrough(self):
        # 未収録 → そのまま返す
        assert catalog_psa.set_code_to_ebay_name_pokemon("XX99") == "XX99"


# Pokemon DB roundtrip — --full 完走後に有効化
def _pokemon_data_loaded() -> bool:
    """Pokemon DB に最低限 base record があるか."""
    return api.lookup("pokemon_tcg", "M2a-240") is not None


REQUIRES_POKEMON_DB = pytest.mark.skipif(
    not _pokemon_data_loaded(),
    reason="Pokemon --full not yet completed",
)


@REQUIRES_POKEMON_DB
class TestPokemonDbLookup:
    def test_lookup_m2a_240(self):
        # メガゲンガーex (M2a-240) — 既知の SAR card
        result = catalog_psa.lookup_pokemon(
            "POKEMON JAPANESE M2A-MEGA DREAM EX",
            "240",
            subject="MEGA GENGAR EX",
            verbose=False,
        )
        assert result is not None
        assert result["card_id"] == "M2a-240"
        assert result["rarity"] == "SAR"
        assert result["card_type"] == "Pokémon"
        assert result["hp"] == "350"

    def test_unregistered_returns_none(self):
        result = catalog_psa.lookup_pokemon(
            "POKEMON JAPANESE M2A",
            "999",
            subject="X",
            verbose=False,
        )
        assert result is None


class TestPokemonPromoHint:
    """FA/Promo subject ヒントの誤検出防止."""

    def test_fa_prefix_detected(self):
        assert catalog_psa._is_pokemon_promo_hint("FA/PIKACHU 25TH ANNIVERSARY")

    def test_full_art_detected(self):
        assert catalog_psa._is_pokemon_promo_hint("PIKACHU FULL ART")

    def test_promo_detected(self):
        assert catalog_psa._is_pokemon_promo_hint("PIKACHU PROMO")

    def test_special_art_detected(self):
        assert catalog_psa._is_pokemon_promo_hint("EEVEE EX SPECIAL ART")

    def test_sar_word_boundary(self):
        # 'ANNIVERSARY' の 'SAR' 部分一致を誤検出しない
        assert not catalog_psa._is_pokemon_promo_hint(
            "FLYING PIKACHU V 25TH ANNIVERSARY COLL."
        )
        # 単独 SAR は検出
        assert catalog_psa._is_pokemon_promo_hint("PIKACHU EX SAR")

    def test_ar_word_boundary(self):
        # 'ART' の 'AR' 部分一致を誤検出しない
        assert not catalog_psa._is_pokemon_promo_hint("LILLIE'S RIBOMBEE ART")
        # 単独 AR は検出 (Art Rare 短縮)
        assert catalog_psa._is_pokemon_promo_hint("PIKACHU AR")

    def test_no_hint(self):
        assert not catalog_psa._is_pokemon_promo_hint("MEGA GENGAR EX")
        assert not catalog_psa._is_pokemon_promo_hint("")


@REQUIRES_POKEMON_DB
class TestPokemonFaUpgrade:
    """FA hint で base → promo set への自動切替 (同名キャラのみ)."""

    def test_fa_pikachu_25th_upgrades_to_promo(self):
        # FA/PIKACHU 25TH → S8a-001 base (Common Pikachu) → S-P-001 (Promo Pikachu) に upgrade
        result = catalog_psa.lookup_pokemon(
            "POKEMON JAPANESE 25TH ANNIVERSARY COLLECTION",
            "001",
            subject="FA/PIKACHU 25TH ANNIVERSARY COLL.",
            verbose=False,
        )
        assert result is not None
        # Promo upgrade で S-P-001 になる (S8a-001 では NG)
        assert result["card_id"] == "S-P-001"
        assert "ピカチュウ" in (result["name_jp"] or "")

    def test_fa_elesa_keeps_base_when_promo_diff_character(self):
        # FA/ELESA #246 → S12a-246 (Elesa SR) base. S-P-246 は別キャラ (基本エネ) なので
        # upgrade しない. base のまま返る.
        result = catalog_psa.lookup_pokemon(
            "POKEMON JAPANESE SWORD & SHIELD VSTAR UNIVERSE",
            "246",
            subject="FA/ELESA'S SPARKLE VSTAR UNIVERSE",
            verbose=False,
        )
        assert result is not None
        assert result["card_id"] == "S12a-246"
        assert "カミツレ" in (result["name_jp"] or "")

    def test_no_fa_hint_keeps_base(self):
        # subject に FA/Promo ヒント無し → base のまま
        result = catalog_psa.lookup_pokemon(
            "POKEMON JAPANESE 25TH ANNIVERSARY COLLECTION",
            "023",
            subject="FLYING PIKACHU V 25TH ANNIVERSARY COLL.",
            verbose=False,
        )
        assert result is not None
        assert result["card_id"] == "S8a-023"
        assert "そらをとぶ" in (result["name_jp"] or "") or "ピカチュウ" in (result["name_jp"] or "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
