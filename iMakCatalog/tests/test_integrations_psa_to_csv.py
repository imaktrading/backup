"""iMakCatalog/integrations/psa_to_csv.py の動作確認テスト.

主に「PRB02-005 と ST16-005 が決して混同されない」「未登録 → None」を保証.
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
# extract_set_code_from_brand
# ============================================================================
class TestExtractSetCode:
    def test_op_set(self):
        assert catalog_psa.extract_set_code_from_brand(
            "ONE PIECE JAPANESE OP06-WINGS OF THE CAPTAIN"
        ) == "OP06"

    def test_st_set(self):
        assert catalog_psa.extract_set_code_from_brand(
            "ONE PIECE JAPANESE ST16 UTA"
        ) == "ST16"

    def test_prb_set(self):
        assert catalog_psa.extract_set_code_from_brand(
            "ONE PIECE JAPANESE PRB02 PROMOS"
        ) == "PRB02"

    def test_eb_set(self):
        assert catalog_psa.extract_set_code_from_brand(
            "ONE PIECE JAPANESE EB02 25TH ANNIVERSARY"
        ) == "EB02"

    def test_promo_keyword_yields_p(self):
        assert catalog_psa.extract_set_code_from_brand(
            "ONE PIECE DAY 23 PROMOS"
        ) == "P"

    def test_no_match_returns_none(self):
        assert catalog_psa.extract_set_code_from_brand("RANDOM TEXT") is None
        assert catalog_psa.extract_set_code_from_brand("") is None
        assert catalog_psa.extract_set_code_from_brand(None) is None


# ============================================================================
# _variant_candidates
# ============================================================================
class TestVariantCandidates:
    def test_alt_art(self):
        out = catalog_psa._variant_candidates("MONKEY D LUFFY ALTERNATE ART")
        assert "p" in out and "p1" in out

    def test_parallel(self):
        out = catalog_psa._variant_candidates("ZORO PARALLEL FOIL")
        assert "p" in out

    def test_no_hint_empty(self):
        assert catalog_psa._variant_candidates("PLAIN SUBJECT") == []
        assert catalog_psa._variant_candidates("") == []
        assert catalog_psa._variant_candidates(None) == []

    def test_special_resolves(self):
        out = catalog_psa._variant_candidates("LUFFY SPECIAL CARD")
        assert "p" in out


# ============================================================================
# lookup_one_piece (DB roundtrip — 前提: PRB02-005 / ST16-005 / OP06-022 in DB)
# ============================================================================
def _trigger_cards_in_db() -> bool:
    return all(
        api.lookup("one_piece_tcg", pid) is not None
        for pid in ("PRB02-005", "ST16-005", "OP06-022")
    )


REQUIRES_DB = pytest.mark.skipif(
    not _trigger_cards_in_db(),
    reason="Trigger cards not in DB",
)


@REQUIRES_DB
class TestLookupOnePiece:
    def test_prb02_005_via_psa_brand(self):
        """PSA Brand 'ONE PIECE JAPANESE PRB02 PROMOS' + card_number '005' → PRB02-005."""
        result = catalog_psa.lookup_one_piece(
            brand="ONE PIECE JAPANESE PRB02 PROMOS",
            card_number="005",
            subject="MONKEY D LUFFY",
            verbose=False,
        )
        assert result is not None
        assert result["card_id"] == "PRB02-005"
        assert result["name_en"] == "Monkey.D.Luffy"
        assert result["rarity_en"] == "SR"
        assert result["power"] == "5000"
        # 旧形式互換フィールド
        assert "PRB-02" in result["get_info_jp"]
        # 新規拡張フィールド
        assert result["set_name_ebay"] == "Premium Booster Vol.2"
        assert result["card_text"]
        assert result["card_text_jp"]
        assert result["language"] == "both"

    def test_st16_005_distinct_from_prb02_005_via_brand(self):
        """事故再発防止: 同じ subject ('MONKEY D LUFFY') でも brand が違えば別レコード."""
        prb = catalog_psa.lookup_one_piece(
            "ONE PIECE JAPANESE PRB02", "005", "MONKEY D LUFFY", verbose=False
        )
        st = catalog_psa.lookup_one_piece(
            "ONE PIECE JAPANESE ST16 UTA", "005", "MONKEY D LUFFY", verbose=False
        )
        assert prb is not None and st is not None
        assert prb["card_id"] != st["card_id"]
        assert prb["rarity_en"] == "SR"
        assert st["rarity_en"] == "C"
        assert prb["power"] == "5000"
        assert st["power"] == "3000"

    def test_unregistered_brand_returns_none(self):
        """未登録 ID → None (フォールバック禁止の保証)."""
        result = catalog_psa.lookup_one_piece(
            "ONE PIECE JAPANESE OP01-ROMANCE DAWN", "999",
            subject="TEST", verbose=False,
        )
        assert result is None

    def test_unparseable_brand_returns_none(self):
        result = catalog_psa.lookup_one_piece(
            brand="UNRELATED CARD GAME", card_number="123",
            subject="X", verbose=False,
        )
        assert result is None

    def test_op06_022_base(self):
        """Brand 'OP06' + card_number '022' → OP06-022 (Yamato Leader)."""
        result = catalog_psa.lookup_one_piece(
            "ONE PIECE JAPANESE OP06-WINGS OF THE CAPTAIN", "022",
            subject="YAMATO", verbose=False,
        )
        assert result is not None
        assert result["card_id"] == "OP06-022"
        assert result["type_en"] == "Leader"
        assert result["rarity_en"] == "L"
        # set_name_ebay は yaml ロード後 "Wings of the Captain"
        assert result["set_name_ebay"] == "Wings of the Captain"

    def test_alt_art_variant_resolution(self):
        """PSA Subject に 'ALTERNATE ART' 含まれる + base が見つかる場合、base を返す
        (variant 候補は base が None の時のみ試行)."""
        # OP06-022 base はあるので variant は試さず base を返す
        result = catalog_psa.lookup_one_piece(
            "ONE PIECE JAPANESE OP06", "022",
            subject="YAMATO ALTERNATE ART", verbose=False,
        )
        assert result is not None
        assert result["card_id"] == "OP06-022"  # base、_p ではない


@REQUIRES_DB
class TestNameVerification:
    """ID hit 後の名前検証 (Bonney→Bepo 事件防止)."""

    def test_subject_tokens_strips_stopwords(self):
        # PSA-specific ノイズ語は除外、キャラ名だけ残る
        toks = catalog_psa._subject_tokens("MONKEY D LUFFY ALTERNATE ART")
        assert "MONKEY" in toks
        assert "LUFFY" in toks
        assert "ALTERNATE" not in toks
        assert "ART" not in toks

    def test_subject_tokens_handles_short_words(self):
        # 'D.' や 1-2 字は除外
        toks = catalog_psa._subject_tokens("MONKEY D. LUFFY")
        assert toks == {"MONKEY", "LUFFY"}

    def test_subject_tokens_promo_phrases(self):
        toks = catalog_psa._subject_tokens(
            "JEWELRY BONNEY WEEKLY SHONEN JUMP '24-#35"
        )
        assert "JEWELRY" in toks
        assert "BONNEY" in toks
        assert "WEEKLY" not in toks
        assert "SHONEN" not in toks
        assert "JUMP" not in toks

    def test_record_name_matches(self):
        rec = {"name": "Monkey.D.Luffy", "name_jp": "モンキー・D・ルフィ"}
        assert catalog_psa._record_name_matches_subject(rec, "MONKEY D LUFFY")
        assert catalog_psa._record_name_matches_subject(rec, "MONKEY")

    def test_record_name_mismatches_reject(self):
        # 事件再現: PSA 'BONNEY' / DB record 'Bepo' → 不一致
        rec = {"name": "Bepo", "name_jp": "ベポ"}
        assert not catalog_psa._record_name_matches_subject(
            rec, "JEWELRY BONNEY WEEKLY SHONEN JUMP"
        )

    def test_record_name_empty_subject_skips_check(self):
        rec = {"name": "Bepo", "name_jp": "ベポ"}
        # PSA Subject 空 or stopwords のみ → 検証スキップで True (旧挙動踏襲)
        assert catalog_psa._record_name_matches_subject(rec, "")
        assert catalog_psa._record_name_matches_subject(rec, "ALTERNATE ART RARE")

    def test_lookup_does_not_return_wrong_card_on_promo_collision(self):
        """事件再現: PSA Brand 'PROMO' + card_number '019' で P-019 (Bepo) base hit.
        → 名前検証で reject、その後 promo fallback で正しい OP07-019_P (Bonney) を救済.
           最終結果は None でなく Bonney record (Bepo は絶対返さない)."""
        result = catalog_psa.lookup_one_piece(
            brand="ONE PIECE JAPANESE PROMOS",
            card_number="019",
            subject="JEWELRY BONNEY WEEKLY SHONEN JUMP",
            verbose=False,
        )
        # 結果は Bonney 関連 record (None でも OK だが、Bepo は NG)
        if result is not None:
            name_combined = (
                (result.get("name_en") or "") + " " +
                (result.get("name_jp") or "")
            ).upper()
            assert "BEPO" not in name_combined and "ベポ" not in (result.get("name_jp") or "")
            assert "BONNEY" in name_combined or "ボニー" in (result.get("name_jp") or "")

    def test_lookup_passes_when_subject_matches(self):
        """通常ケース: PSA 'LUFFY' + base lookup OP14-034 = Luffy → 名前一致 → hit."""
        result = catalog_psa.lookup_one_piece(
            brand="ONE PIECE JAPANESE OP14",
            card_number="034",
            subject="MONKEY D LUFFY",
            verbose=False,
        )
        assert result is not None
        assert "Luffy" in result["name_en"]
        assert result["card_id"] == "OP14-034"

    def test_record_name_matches_via_ja_en_dict(self):
        """JA-only record (name='モンキー・D・ルフィ') でも PSA 'LUFFY' で一致する."""
        rec = {"name": "モンキー・D・ルフィ", "name_jp": "モンキー・D・ルフィ"}
        assert catalog_psa._record_name_matches_subject(rec, "MONKEY D LUFFY")
        assert catalog_psa._record_name_matches_subject(rec, "LUFFY ALTERNATE ART")

    def test_record_name_ja_only_bepo_rejects_bonney(self):
        """事件再現: JA-only ベポ record に PSA Bonney トークン → reject."""
        rec = {"name": "ベポ", "name_jp": "ベポ"}
        assert not catalog_psa._record_name_matches_subject(
            rec, "JEWELRY BONNEY WEEKLY SHONEN JUMP"
        )

    def test_lookup_ja_only_promo_passes_when_character_matches(self):
        """JA-only Luffy P-001 + PSA 'MONKEY D LUFFY' → JA→EN dict 経由で通る."""
        result = catalog_psa.lookup_one_piece(
            brand="ONE PIECE JAPANESE PROMOS ICHIBAN KUJI",
            card_number="001",
            subject="MONKEY D LUFFY ICHIBAN KUJI PURCHASE BONUS",
            verbose=False,
        )
        # P-001 は JA-only Luffy promo. Ja→En dict で 'LUFFY' に一致して通る.
        assert result is not None
        assert result["card_id"] == "P-001"

    def test_promo_fallback_resolves_bonney_wsj(self):
        """事件再現+救済: PSA brand=PROMOS / number=019 / subject=JEWELRY BONNEY
        → P-019 (Bepo) reject 後、OP07-019_P (Bonney WSJ 付録版) を救済."""
        result = catalog_psa.lookup_one_piece(
            brand="ONE PIECE JAPANESE PROMOS",
            card_number="019",
            subject="JEWELRY BONNEY WEEKLY SHONEN JUMP '24-#35",
            verbose=False,
        )
        # 名前検証 + 番号一致 で OP07-019_P (Bonney) を見つける
        assert result is not None
        assert result["card_id"] == "OP07-019_P"
        # 名前は JA だが name_jp に "ボニー" 含む
        assert "ボニー" in (result.get("name_jp") or "")

    def test_promo_fallback_skips_when_subject_empty(self):
        """安全装置: PSA Subject から有意トークンが取れない → 救済しない (誤マッチ防止)."""
        result = catalog_psa.lookup_one_piece(
            brand="ONE PIECE JAPANESE PROMOS",
            card_number="019",
            subject="",  # 空 subject
            verbose=False,
        )
        assert result is None

    def test_promo_fallback_skips_when_name_not_match(self):
        """安全装置: 名前が一致しない subject なら全 set_code 候補で reject される."""
        result = catalog_psa.lookup_one_piece(
            brand="ONE PIECE JAPANESE PROMOS",
            card_number="019",
            subject="UNKNOWN CHARACTER XYZ",  # どの 019 にも一致しない
            verbose=False,
        )
        assert result is None

    def test_reprint_fallback_resolves_shirahoshi_sp_alt(self):
        """SP Alt fallback: PSA brand=OP11, num=057, subject=SHIRAHOSHI SP ALT
        → OP11-057 base (Pedro) reject 後、EB01-057_OP11_dummy (Shirahoshi SP) を救済."""
        result = catalog_psa.lookup_one_piece(
            brand="ONE PIECE JAPANESE OP11-A FIST OF DIVINE SPEED",
            card_number="057",
            subject="SHIRAHOSHI SPECIAL ALTERNATE ART",
            verbose=False,
        )
        assert result is not None
        assert result["card_id"].startswith("EB01-057_OP11")
        # 名前が Shirahoshi
        name_combined = (result.get("name_en") or "") + (result.get("name_jp") or "")
        assert "Shirahoshi" in name_combined or "しらほし" in name_combined

    def test_reprint_fallback_resolves_rebecca_sp_alt(self):
        result = catalog_psa.lookup_one_piece(
            brand="ONE PIECE JAPANESE OP06-WINGS OF THE CAPTAIN",
            card_number="091",
            subject="REBECCA SPECIAL ALTERNATE ART",
            verbose=False,
        )
        assert result is not None
        assert "Rebecca" in (result.get("name_en") or "") or "レベッカ" in (result.get("name_jp") or "")

    def test_reprint_fallback_skips_when_subject_no_tokens(self):
        """安全装置: subject が空 → reprint fallback 動かない."""
        result = catalog_psa.lookup_one_piece(
            brand="ONE PIECE JAPANESE OP11",
            card_number="057",
            subject="",
            verbose=False,
        )
        # OP11-057 base (Pedro) は subject 空なら名前検証スキップで accept される
        # → Pedro が返る (Shirahoshi にはならない).
        assert result is not None
        assert result["card_id"] == "OP11-057"


# ============================================================================
# set_code_to_ebay_name (旧 _onepiece_set_code_to_name 置換)
# ============================================================================
@REQUIRES_DB
class TestSetCodeToEbayName:
    def test_known_op_set(self):
        assert catalog_psa.set_code_to_ebay_name("OP-06") == "Wings of the Captain"

    def test_known_st_set(self):
        assert catalog_psa.set_code_to_ebay_name("ST-16") == "Uta"

    def test_known_prb_set(self):
        assert catalog_psa.set_code_to_ebay_name("PRB-02") == "Premium Booster Vol.2"

    def test_unknown_passes_through(self):
        # 旧 _onepiece_set_code_to_name 挙動: 未登録は set_code をそのまま返す
        assert catalog_psa.set_code_to_ebay_name("OP-99") == "OP-99"

    def test_empty_returns_empty(self):
        assert catalog_psa.set_code_to_ebay_name("") == ""
        assert catalog_psa.set_code_to_ebay_name(None) is None

    def test_compound_set(self):
        assert catalog_psa.set_code_to_ebay_name("OP15-EB04") == "Adventure on Kami's Island"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
