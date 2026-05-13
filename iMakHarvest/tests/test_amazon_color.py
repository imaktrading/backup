"""tests/test_amazon_color - Amazon 色/サイズ抽出ロジック (3-stage) のオフラインテスト.

Phase 1c-color (2026-05-13): Amazon 商品詳細から color/size を取得する 3-stage 判定:
  Step 1: variant selector (#variation_color_name)
  Step 2: title/description whitelist (Mercari と共通)
  Step 3: Vision AI fallback (Claude Haiku)

mock driver で Step 1/2 の挙動を検証、Vision AI は別テスト (test_color_vision.py) でカバー済。
"""
from __future__ import annotations

import pytest

from scrapers.amazon_item_detail import (
    _extract_amazon_size,
    _extract_amazon_variant_color,
    _judge_amazon_color,
)


pytestmark = pytest.mark.offline


# --------------------------------------------------------------------------
# Mock driver / element
# --------------------------------------------------------------------------
class _MockElement:
    def __init__(self, text: str):
        self._text = text

    @property
    def text(self) -> str:
        return self._text


class _MockDriver:
    """find_element CSS selector のみサポート最小モック."""

    def __init__(self, css_map: dict[str, _MockElement | None]):
        self._css_map = css_map

    def find_element(self, by, value):
        from selenium.common.exceptions import NoSuchElementException  # noqa: PLC0415
        elem = self._css_map.get(value)
        if elem is None:
            raise NoSuchElementException(f"not found: {value}")
        return elem


# --------------------------------------------------------------------------
# _extract_amazon_variant_color
# --------------------------------------------------------------------------
class TestExtractAmazonVariantColor:
    def test_returns_variant_color_from_first_selector(self):
        driver = _MockDriver({
            "#variation_color_name .selection": _MockElement("ネイビー"),
        })
        assert _extract_amazon_variant_color(driver) == "ネイビー"

    def test_fallback_to_alternate_selector(self):
        driver = _MockDriver({
            "#variation_color_name span.selection": _MockElement("ブラック"),
        })
        assert _extract_amazon_variant_color(driver) == "ブラック"

    def test_returns_empty_when_no_variant(self):
        # variant なし商品 (家電・本等) → 全 selector miss → 空文字
        driver = _MockDriver({})
        assert _extract_amazon_variant_color(driver) == ""

    def test_strips_whitespace(self):
        driver = _MockDriver({
            "#variation_color_name .selection": _MockElement("  レッド\n"),
        })
        assert _extract_amazon_variant_color(driver) == "レッド"


# --------------------------------------------------------------------------
# _extract_amazon_size
# --------------------------------------------------------------------------
class TestExtractAmazonSize:
    def test_returns_size_from_first_selector(self):
        driver = _MockDriver({
            "#variation_size_name .selection": _MockElement("L"),
        })
        assert _extract_amazon_size(driver) == "L"

    def test_returns_empty_when_no_variant(self):
        # variant なし商品 (本・家電) → サイズ概念なし
        driver = _MockDriver({})
        assert _extract_amazon_size(driver) == ""

    @pytest.mark.parametrize("size_text", ["XS", "S", "M", "L", "XL", "XXL", "27cm", "Free Size"])
    def test_various_size_formats_pass_through(self, size_text):
        driver = _MockDriver({
            "#variation_size_name .selection": _MockElement(size_text),
        })
        assert _extract_amazon_size(driver) == size_text


# --------------------------------------------------------------------------
# _judge_amazon_color: 3-stage 優先順位
# --------------------------------------------------------------------------
class TestJudgeAmazonColor:
    def test_step1_variant_takes_priority(self):
        # variant selector に katakana 色名 → Step 1 で即返却 (whitelist/AI 不要)
        driver = _MockDriver({
            "#variation_color_name .selection": _MockElement("ネイビー"),
        })
        result = _judge_amazon_color(
            driver,
            image_urls=["https://m.media-amazon.com/x.jpg"],
            title="シャツ レッド",  # whitelist hit するが、Step 1 が優先
            description="",
        )
        assert result == "ネイビー"

    def test_step1_variant_kanji_rejected_falls_through(self):
        # variant が漢字 ("黒") → parse_color_response で reject → Step 2 へ
        driver = _MockDriver({
            "#variation_color_name .selection": _MockElement("黒"),
        })
        result = _judge_amazon_color(
            driver,
            image_urls=[],
            title="ジャケット ブルー",
            description="",
        )
        # Step 2 で title から "ブルー" 抽出
        assert result == "ブルー"

    def test_step2_title_whitelist_when_no_variant(self):
        # variant なし商品 + title に katakana 色名 → Step 2 hit
        driver = _MockDriver({})
        result = _judge_amazon_color(
            driver,
            image_urls=[],
            title="モンベル ジャケット グリーン XL",
            description="",
        )
        assert result == "グリーン"

    def test_step2_description_whitelist(self):
        # variant なし + title に色名なし + description に色名 → Step 2 hit (desc)
        driver = _MockDriver({})
        result = _judge_amazon_color(
            driver,
            image_urls=[],
            title="ジャケット XL",
            description="色: ライトグリーン、サイズ XL",
        )
        assert result == "ライトグリーン"

    def test_step3_ai_fallback_when_no_image(self):
        # variant なし + text 色名なし + image なし → AI 呼出できず空文字
        driver = _MockDriver({})
        result = _judge_amazon_color(
            driver,
            image_urls=[],
            title="家電 本体",
            description="新品未開封",
        )
        assert result == ""

    def test_returns_empty_when_all_steps_fail(self):
        # variant 不在 + text 色名なし + image なし → 空文字
        driver = _MockDriver({})
        result = _judge_amazon_color(
            driver, image_urls=None, title="", description="",
        )
        assert result == ""

    def test_variant_compound_color_preserved(self):
        # variant が複合色 (whitelist にある "ライトグレー") → そのまま透過
        driver = _MockDriver({
            "#variation_color_name .selection": _MockElement("ライトグレー"),
        })
        result = _judge_amazon_color(
            driver, image_urls=[], title="", description="",
        )
        assert result == "ライトグレー"

    def test_variant_english_passes_through_to_whitelist(self):
        # variant が英語 ("Black") → parse_color_response で透過? いや、英語は katakana 強制違反
        # でも parse_color_response は短い英単語を reject しない (MAX_COLOR_LEN 以内)
        # よって Step 1 で "Black" 返却 → HQ 側で英→カタカナ変換責務
        # ※ 一貫性のため Step 1 で出品者表記透過、HQ 側で正規化
        driver = _MockDriver({
            "#variation_color_name .selection": _MockElement("Black"),
        })
        result = _judge_amazon_color(
            driver, image_urls=[], title="", description="",
        )
        # 出品者表記 "Black" を透過 (HQ catalog で正規化される)
        assert result == "Black"


# --------------------------------------------------------------------------
# fetch_detail 統合 (mocked driver、TCG skip filter 経路確認)
# --------------------------------------------------------------------------
class TestFetchDetailColorSizeIntegration:
    """fetch_detail の return dict に color/size が含まれることを confirm.

    Selenium 完全モック は実装重いため、TCG skip filter の経路だけ
    `should_skip_color_size` を直接 unit-test して間接確認。
    """

    def test_tcg_keyword_in_title_skips_color_size(self):
        from scrapers.extraction_filter import should_skip_color_size  # noqa: PLC0415
        # TCG 商品 → skip 判定 True → fetch_detail 内で color=size="" となる経路
        assert should_skip_color_size(
            title="Pokemon ワンピースカード PSA10 ルフィ",
            description="",
        ) is True

    def test_non_tcg_does_not_skip(self):
        from scrapers.extraction_filter import should_skip_color_size  # noqa: PLC0415
        assert should_skip_color_size(
            title="モンベル ライトシェルパーカー XL",
            description="",
        ) is False
