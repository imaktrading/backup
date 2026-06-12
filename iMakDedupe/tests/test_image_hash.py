"""image_hash unit tests — mock 経由 (network 不要)."""

from unittest.mock import patch

import pytest

from dedupe import image_hash

pytestmark = pytest.mark.offline


# === fixture hashes (= 16 桁 hex) ===
# imagehash.hex_to_hash で復元、 hamming distance を計算
# - HASH_A: 全 0 (= base)
# - HASH_A_6BIT: HASH_A から 6 bit 差 (= 同 variant 別画像 想定)
# - HASH_B_24BIT: HASH_A から 24 bit 差 (= 異 variant 想定)
HASH_A = "0000000000000000"  # 全 0
HASH_A_6BIT = "000000000000003f"  # 下位 6 bit が 1 (= 6 hamming)
HASH_A_24BIT = "0000000000ffffff"  # 下位 24 bit が 1 (= 24 hamming)


def _stub_phash_returning(value):
    """compute_phash の挙動を mock するヘルパ."""

    def _fn(url):
        return value

    return _fn


class TestComputePhash:
    def test_returns_none_on_empty_url(self):
        assert image_hash.compute_phash("") is None

    def test_returns_none_on_http_error(self):
        with patch("dedupe.image_hash.requests.get") as m:
            m.return_value.status_code = 404
            assert image_hash.compute_phash("http://x") is None

    def test_returns_none_on_exception(self):
        with patch("dedupe.image_hash.requests.get", side_effect=Exception("timeout")):
            assert image_hash.compute_phash("http://x") is None


class TestIdentifyVariantByImage:
    @pytest.fixture
    def catalog_variants(self):
        return {
            "AR": {"image_phash": HASH_A},                # base
            "SAR": {"image_phash": HASH_A_24BIT},          # 24 bit diff from AR
            "Promo": {"image_phash": HASH_A_6BIT},         # 6 bit diff from AR (= 近接)
        }

    def test_identifies_exact_match(self, catalog_variants):
        """新規 hash = AR と完全一致 (0 bit) → AR 返却."""
        result = image_hash.identify_variant_by_image(
            "http://x",
            {"AR": {"image_phash": HASH_A_24BIT}, "SAR": {"image_phash": HASH_A}},
            threshold=10,
            _phash_fn=_stub_phash_returning(HASH_A),
        )
        # 新規 = HASH_A、 SAR が HASH_A と一致 (distance 0)
        assert result == "SAR"

    def test_identifies_within_threshold(self, catalog_variants):
        """新規 hash と AR が 6 bit 差 → threshold=10 内で AR 採用."""
        # NOTE: Promo が HASH_A_6BIT で AR (= HASH_A) と 6 bit 差、
        # 新規 hash = HASH_A → AR vs Promo の distance: AR=0, Promo=6
        # 最小 distance = AR (0) なので AR 返却
        result = image_hash.identify_variant_by_image(
            "http://x",
            catalog_variants,
            threshold=10,
            _phash_fn=_stub_phash_returning(HASH_A),
        )
        assert result == "AR"

    def test_threshold_boundary_exact(self, catalog_variants):
        """threshold=6 で 6 bit 差まで採用、 7 bit 以上は fail-closed."""
        # 新規 hash = HASH_A_6BIT。 AR (HASH_A) と 6 bit 差、 Promo (HASH_A_6BIT) と 0 bit 差
        # 最小 = Promo
        result = image_hash.identify_variant_by_image(
            "http://x",
            catalog_variants,
            threshold=6,
            _phash_fn=_stub_phash_returning(HASH_A_6BIT),
        )
        assert result == "Promo"

    def test_returns_none_when_above_threshold(self, catalog_variants):
        """全 catalog hash から閾値超え → None (= fail-closed)."""
        # 新規 = 全 1 hash → 全 variant と 大 distance
        result = image_hash.identify_variant_by_image(
            "http://x",
            catalog_variants,
            threshold=5,
            _phash_fn=_stub_phash_returning("ffffffffffffffff"),
        )
        assert result is None

    def test_returns_none_on_tie(self):
        """2 variant が同 distance → tie で None (= 推測しない)."""
        variants = {
            "V1": {"image_phash": HASH_A_6BIT},      # 6 bit 差 from HASH_A
            "V2": {"image_phash": "00000000000003f0"},  # 6 bit 差 from HASH_A (= 別 bits)
        }
        result = image_hash.identify_variant_by_image(
            "http://x",
            variants,
            threshold=10,
            _phash_fn=_stub_phash_returning(HASH_A),
        )
        assert result is None  # 同 distance 6 で tie

    def test_returns_none_on_phash_failure(self, catalog_variants):
        """compute_phash が None 返却 (= fetch failed) → None."""
        result = image_hash.identify_variant_by_image(
            "http://x",
            catalog_variants,
            _phash_fn=_stub_phash_returning(None),
        )
        assert result is None

    def test_returns_none_on_empty_variants(self):
        result = image_hash.identify_variant_by_image(
            "http://x", {},
            _phash_fn=_stub_phash_returning(HASH_A),
        )
        assert result is None

    def test_skips_variants_without_image_phash(self):
        """image_phash 列無 variant は skip、 残 variant のみで判定."""
        variants = {
            "V1": {"image_phash": HASH_A},
            "V2": {"features": "no hash here"},  # image_phash 欠
        }
        result = image_hash.identify_variant_by_image(
            "http://x", variants, threshold=10,
            _phash_fn=_stub_phash_returning(HASH_A),
        )
        assert result == "V1"

    def test_skips_variants_with_invalid_hash(self):
        """hex_to_hash で parse 失敗する hash は skip."""
        variants = {
            "V1": {"image_phash": HASH_A},
            "V2": {"image_phash": "not_hex_garbage_zzz"},
        }
        result = image_hash.identify_variant_by_image(
            "http://x", variants, threshold=10,
            _phash_fn=_stub_phash_returning(HASH_A),
        )
        assert result == "V1"

    def test_distance_just_above_threshold(self):
        """closest hash が threshold+1 bit 差 → None (= 境界外)."""
        variants = {"V1": {"image_phash": HASH_A_6BIT}}  # 6 bit 差
        result = image_hash.identify_variant_by_image(
            "http://x", variants,
            threshold=5,  # 5 < 6
            _phash_fn=_stub_phash_returning(HASH_A),
        )
        assert result is None

    def test_distance_equals_threshold(self):
        """closest hash が ちょうど threshold bit 差 → 採用 (= <=)."""
        variants = {"V1": {"image_phash": HASH_A_6BIT}}
        result = image_hash.identify_variant_by_image(
            "http://x", variants,
            threshold=6,
            _phash_fn=_stub_phash_returning(HASH_A),
        )
        assert result == "V1"


class TestDefaultThreshold:
    def test_default_threshold_is_10(self):
        """5/27 POC 確定値が定数として保持."""
        assert image_hash._DEFAULT_THRESHOLD == 10
