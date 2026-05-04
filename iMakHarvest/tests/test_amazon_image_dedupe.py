"""tests/test_amazon_image_dedupe - Amazon 画像 URL の base ID 抽出 / dedupe / 高解像度正規化.

Amazon は同一商品画像をサイズ違い (._AC_SY355_, ._AC_UL348_ 等) で大量に返してくる。
これを base ID で dedupe + size modifier を剥がした高解像度 URL に正規化する処理を検証。
"""
from __future__ import annotations

import pytest

from scrapers.amazon_item_detail import (
    amazon_image_base_id,
    clean_amazon_image_url,
    dedupe_amazon_images,
)


pytestmark = pytest.mark.offline


# --------------------------------------------------------------------------
# amazon_image_base_id
# --------------------------------------------------------------------------
class TestAmazonImageBaseId:
    def test_with_ac_sy_modifier(self):
        assert amazon_image_base_id(
            "https://m.media-amazon.com/images/I/616VOLLq2bL._AC_SY355_.jpg"
        ) == "616VOLLq2bL"

    def test_with_ac_ul_thumbnail_modifier(self):
        assert amazon_image_base_id(
            "https://images-fe.ssl-images-amazon.com/images/I/616VOLLq2bL._AC_UL348_SR348,348_.jpg"
        ) == "616VOLLq2bL"

    def test_with_ac_sx_modifier(self):
        assert amazon_image_base_id(
            "https://m.media-amazon.com/images/I/616VOLLq2bL._AC_SX679_.jpg"
        ) == "616VOLLq2bL"

    def test_no_modifier(self):
        # 元 URL (size modifier 無し) の場合
        assert amazon_image_base_id(
            "https://m.media-amazon.com/images/I/616VOLLq2bL.jpg"
        ) == "616VOLLq2bL"

    def test_plus_in_base_id(self):
        # 一部の base ID には + が含まれる
        assert amazon_image_base_id(
            "https://images-fe.ssl-images-amazon.com/images/I/61E2+kyPEKL._AC_UL232_SR232,232_.jpg"
        ) == "61E2+kyPEKL"

    def test_png_extension(self):
        assert amazon_image_base_id(
            "https://m.media-amazon.com/images/I/616VOLLq2bL._AC_SY355_.png"
        ) == "616VOLLq2bL"

    def test_non_amazon_url_returns_empty(self):
        assert amazon_image_base_id("https://example.com/foo/bar.jpg") == ""

    def test_empty(self):
        assert amazon_image_base_id("") == ""


# --------------------------------------------------------------------------
# clean_amazon_image_url
# --------------------------------------------------------------------------
class TestCleanAmazonImageUrl:
    def test_strips_size_modifier(self):
        assert clean_amazon_image_url(
            "https://m.media-amazon.com/images/I/616VOLLq2bL._AC_SY355_.jpg"
        ) == "https://m.media-amazon.com/images/I/616VOLLq2bL.jpg"

    def test_thumbnail_to_full(self):
        assert clean_amazon_image_url(
            "https://images-fe.ssl-images-amazon.com/images/I/616VOLLq2bL._AC_UL348_SR348,348_.jpg"
        ) == "https://m.media-amazon.com/images/I/616VOLLq2bL.jpg"

    def test_already_clean(self):
        # 元から size modifier 無し → そのまま
        url = "https://m.media-amazon.com/images/I/616VOLLq2bL.jpg"
        assert clean_amazon_image_url(url) == url

    def test_non_amazon_url_passes_through(self):
        # Amazon CDN 外の URL はそのまま返す (不明な形式を壊さない)
        url = "https://example.com/foo/bar.jpg"
        assert clean_amazon_image_url(url) == url


# --------------------------------------------------------------------------
# dedupe_amazon_images
# --------------------------------------------------------------------------
class TestDedupeAmazonImages:
    def test_dedupes_same_base_id_across_sizes(self):
        # 同一 BASE_ID のサイズ違い → 1 URL に集約
        raws = [
            "https://m.media-amazon.com/images/I/616VOLLq2bL._AC_SY355_.jpg",
            "https://m.media-amazon.com/images/I/616VOLLq2bL._AC_SY450_.jpg",
            "https://m.media-amazon.com/images/I/616VOLLq2bL._AC_SX679_.jpg",
            "https://images-fe.ssl-images-amazon.com/images/I/616VOLLq2bL._AC_UL348_SR348,348_.jpg",
        ]
        result = dedupe_amazon_images(raws)
        assert result == ["https://m.media-amazon.com/images/I/616VOLLq2bL.jpg"]

    def test_keeps_different_base_ids(self):
        raws = [
            "https://m.media-amazon.com/images/I/616VOLLq2bL._AC_SY355_.jpg",
            "https://m.media-amazon.com/images/I/51haKXy4gfL._AC_SY355_.jpg",
            "https://m.media-amazon.com/images/I/61E2+kyPEKL._AC_SY355_.jpg",
        ]
        result = dedupe_amazon_images(raws)
        assert result == [
            "https://m.media-amazon.com/images/I/616VOLLq2bL.jpg",
            "https://m.media-amazon.com/images/I/51haKXy4gfL.jpg",
            "https://m.media-amazon.com/images/I/61E2+kyPEKL.jpg",
        ]

    def test_real_world_amazon_response(self):
        # 実 dry-run で観測された冗長な image_urls を圧縮できるか
        raws = [
            "https://m.media-amazon.com/images/I/616VOLLq2bL._AC_SY355_.jpg",
            "https://m.media-amazon.com/images/I/616VOLLq2bL._AC_SY450_.jpg",
            "https://m.media-amazon.com/images/I/616VOLLq2bL._AC_SX425_.jpg",
            "https://m.media-amazon.com/images/I/616VOLLq2bL._AC_SX466_.jpg",
            "https://m.media-amazon.com/images/I/616VOLLq2bL._AC_SX522_.jpg",
            "https://m.media-amazon.com/images/I/616VOLLq2bL._AC_SX569_.jpg",
            "https://m.media-amazon.com/images/I/616VOLLq2bL._AC_SX679_.jpg",
            "https://images-fe.ssl-images-amazon.com/images/I/616VOLLq2bL._AC_UL116_SR116,116_.jpg",
            "https://images-fe.ssl-images-amazon.com/images/I/616VOLLq2bL._AC_UL232_SR232,232_.jpg",
            "https://images-fe.ssl-images-amazon.com/images/I/616VOLLq2bL._AC_UL348_SR348,348_.jpg",
            "https://images-fe.ssl-images-amazon.com/images/I/51haKXy4gfL._AC_UL116_SR116,116_.jpg",
            "https://images-fe.ssl-images-amazon.com/images/I/51haKXy4gfL._AC_UL232_SR232,232_.jpg",
            "https://images-fe.ssl-images-amazon.com/images/I/51haKXy4gfL._AC_UL348_SR348,348_.jpg",
            "https://images-fe.ssl-images-amazon.com/images/I/61E2+kyPEKL._AC_UL116_SR116,116_.jpg",
            "https://images-fe.ssl-images-amazon.com/images/I/61E2+kyPEKL._AC_UL232_SR232,232_.jpg",
            "https://images-fe.ssl-images-amazon.com/images/I/61E2+kyPEKL._AC_UL348_SR348,348_.jpg",
        ]
        result = dedupe_amazon_images(raws)
        # 16 URL → 3 URL (商品画像 3 種類分) に圧縮される
        assert len(result) == 3
        assert result == [
            "https://m.media-amazon.com/images/I/616VOLLq2bL.jpg",
            "https://m.media-amazon.com/images/I/51haKXy4gfL.jpg",
            "https://m.media-amazon.com/images/I/61E2+kyPEKL.jpg",
        ]

    def test_preserves_order_of_first_occurrence(self):
        raws = [
            "https://m.media-amazon.com/images/I/AAAAA1.jpg",
            "https://m.media-amazon.com/images/I/BBBBB2._AC_SY355_.jpg",
            "https://m.media-amazon.com/images/I/AAAAA1._AC_SY450_.jpg",  # 既出
            "https://m.media-amazon.com/images/I/CCCCC3.jpg",
        ]
        result = dedupe_amazon_images(raws)
        assert result == [
            "https://m.media-amazon.com/images/I/AAAAA1.jpg",
            "https://m.media-amazon.com/images/I/BBBBB2.jpg",
            "https://m.media-amazon.com/images/I/CCCCC3.jpg",
        ]

    def test_non_amazon_urls_dedupe_by_full_url(self):
        # Amazon CDN 外の URL は base ID 抽出できないので URL 完全一致で dedupe
        raws = [
            "https://example.com/foo.jpg",
            "https://example.com/bar.jpg",
            "https://example.com/foo.jpg",  # 重複
        ]
        result = dedupe_amazon_images(raws)
        assert result == [
            "https://example.com/foo.jpg",
            "https://example.com/bar.jpg",
        ]

    def test_empty_input(self):
        assert dedupe_amazon_images([]) == []

    def test_skips_empty_strings(self):
        raws = ["", "https://m.media-amazon.com/images/I/AAAAA1.jpg", ""]
        result = dedupe_amazon_images(raws)
        assert result == ["https://m.media-amazon.com/images/I/AAAAA1.jpg"]
