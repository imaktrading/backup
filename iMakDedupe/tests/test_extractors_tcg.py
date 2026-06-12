"""TCG extractor unit tests (offline, no network)."""

import pytest

from dedupe.extractors.tcg import (
    extract_one_piece_id,
    extract_pokemon_id,
    extract_tcg_id,
    extract_yugioh_id,
)

pytestmark = pytest.mark.offline


class TestOnePiece:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("ワンピース #OP01-016 シャンクス SR", "OP01-016"),
            ("OP09-001 シャンクス リーダー", "OP09-001"),
            ("ST01-001 モンキー・D・ルフィ", "ST01-001"),
            ("EB01-006 SR ロー", "EB01-006"),
            ("PRB01-001 プロモ", "PRB01-001"),
            ("P-115 イベントプロモ", "P-115"),
            ("# P-001 プロモ", "P-001"),
            ("op01-001 小文字", "OP01-001"),
        ],
    )
    def test_hit(self, title, expected):
        assert extract_one_piece_id(title) == expected

    @pytest.mark.parametrize(
        "title",
        [
            "",
            "ワンピース ノーマルカード",
            "OPナンバーなしカード",
            "AB01-001 (= 取扱外 prefix)",
        ],
    )
    def test_miss_returns_none(self, title):
        assert extract_one_piece_id(title) is None

    @pytest.mark.parametrize(
        "title,expected",
        [
            # Phase 1d-TCG: 分離形 (= eBay snapshot 形式)
            ("One Piece Card OP13 #119 Portgas D. Ace PSA 10 GEM MT", "OP13-119"),
            ("One Piece Card OP11 #010 Hibari Alternate Art PSA 10", "OP11-010"),
            ("One Piece Card OP13 #113 Lilith Alternate Art PSA 10", "OP13-113"),
            ("One Piece Card OP13 #004 Sabo Alternate Art PSA 10", "OP13-004"),
            ("One Piece EB03 Heroines Edition #003 Uta Alternate Art", "EB03-003"),
            ("ST29 JP Stussy Promo #042 Card", "ST29-042"),
        ],
    )
    def test_split_set_and_card_number(self, title, expected):
        """set 番号 + space + # 番号 分離形を結合した card_id で hit."""
        assert extract_one_piece_id(title) == expected

    @pytest.mark.parametrize(
        "title",
        [
            # set 番号 (OP/ST/EB/PRB) なし → fail-closed
            "One Piece Card Game Nami #017 3rd Anniversary Promo PSA 10",
            "One Piece Card 2nd Anniversary #081 Marshall D. Teach PSA 10",
            "One Piece Heroines Special Set Don!! Card PSA 10 GEM MT",
        ],
    )
    def test_split_fail_closed_when_no_set_prefix(self, title):
        """set prefix (OP/ST/EB/PRB) なしの # 番号のみ title は推測しない."""
        assert extract_one_piece_id(title) is None

    def test_existing_form_still_wins(self):
        """結合形 `OP13-100` が title にあれば、 後続の分離形より優先 (= 確度高)."""
        title = "PSA10 OP13-100 Ace Card + OP14 #200 Other card"
        assert extract_one_piece_id(title) == "OP13-100"


class TestPokemon:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("ポケモン SV1a-001 SAR", "SV1A-001"),
            ("#SM12-100 リザードン", "SM12-100"),
        ],
    )
    def test_hit(self, title, expected):
        assert extract_pokemon_id(title) == expected

    def test_miss(self):
        assert extract_pokemon_id("ポケカ 普通のカード") is None


class TestYugioh:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("LB-JP001 レアコレ", "LB-JP001"),
            ("LIOV-EN042 Blue-Eyes", "LIOV-EN042"),
        ],
    )
    def test_hit(self, title, expected):
        assert extract_yugioh_id(title) == expected

    def test_miss(self):
        assert extract_yugioh_id("遊戯王 ノーマルカード") is None


class TestUnified:
    def test_falls_through_categories(self):
        assert extract_tcg_id("#OP01-016 シャンクス") == "OP01-016"
        assert extract_tcg_id("SV1a-001 ピカチュウ") == "SV1A-001"
        assert extract_tcg_id("LIOV-EN042 ブルーアイズ") == "LIOV-EN042"

    def test_empty_returns_none(self):
        assert extract_tcg_id("") is None
        assert extract_tcg_id(None) is None

    def test_fail_closed_on_ambiguous(self):
        """regex hit せず無関係 string → None (= fail-closed)."""
        assert extract_tcg_id("ポケモン センター限定 メタルキーホルダー") is None
