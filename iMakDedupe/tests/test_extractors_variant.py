"""variant extractor unit tests (offline)."""

import pytest

from dedupe.extractors.variant import VARIANT_PRIORITY, extract_variant

pytestmark = pytest.mark.offline


class TestExtractVariant:
    @pytest.mark.parametrize(
        "text,expected",
        [
            # secret 系
            ("One Piece Card Uta OP02-120 Secret Alternate Art PSA 10", "sec"),
            ("Secret Rare card", "sec"),
            ("XYZ Secret", "sec"),
            # alt 系
            ("OP08-106 Alt Art Nami", "alt"),
            ("Alternate Art Luffy", "alt"),
            ("Alternative Art (aspect 表記)", "alt"),
            # parallel
            ("Pokemon Parallel Pikachu", "par"),
            # promo
            ("P-115 Promo card", "pro"),
            ("Promotional release", "pro"),
            # special
            ("Special edition card", "spc"),
            # full art
            ("Full Art Charizard", "fa"),
        ],
    )
    def test_single_hit(self, text, expected):
        assert extract_variant(text) == expected

    def test_priority_secret_over_alt(self):
        """sec > alt: Secret Alternate Art は sec を返す."""
        assert extract_variant("Secret Alternate Art") == "sec"

    def test_priority_alt_over_promo(self):
        """alt > pro: Alt Art Promo は alt."""
        assert extract_variant("Alt Art Promo card") == "alt"

    def test_priority_par_over_fa(self):
        assert extract_variant("Parallel Full Art") == "par"

    def test_priority_order_complete(self):
        """6 種 全混在 → sec を返す (= priority 最高)."""
        text = "Secret Alternate Art Parallel Promo Special Full Art"
        assert extract_variant(text) == "sec"

    @pytest.mark.parametrize(
        "text",
        [
            "",
            None,
            "Normal card no variant keywords",
            "PSA10 DON!! CARD 1周年イベント0792",
            "OP01-016 シャンクス SR",  # SR は variant code じゃない
        ],
    )
    def test_no_hit_returns_empty(self, text):
        assert extract_variant(text) == ""

    def test_case_insensitive(self):
        assert extract_variant("SECRET RARE") == "sec"
        assert extract_variant("alt art") == "alt"
        assert extract_variant("FULL ART") == "fa"

    def test_priority_constant_order(self):
        """VARIANT_PRIORITY が rarity 順であることを文書化."""
        assert VARIANT_PRIORITY == ("sec", "alt", "par", "pro", "spc", "fa")
