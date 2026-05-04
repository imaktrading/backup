"""tests/test_mercari_size_extract - Mercari サイズ抽出 + S/T 列書込テスト.

Phase 1d (size 構造化抽出 + color Vision AI 判定) の検証:
  - mercari_item_detail._extract_size の selector 戦略 (mock driver)
  - sheet_writer._build_row が S 列 (色) / T 列 (サイズ) を正しく書込
  - sheet_writer_amazon._build_row も同様 (Amazon は通常空欄)
"""
from __future__ import annotations

import pytest

from scrapers.mercari_item_detail import SIZE_TESTID, _extract_size
import sheet_writer
import sheet_writer_amazon


pytestmark = pytest.mark.offline


# --------------------------------------------------------------------------
# _extract_size: mock driver で selector 戦略を検証
# --------------------------------------------------------------------------
class _MockSpan:
    def __init__(self, testid: str | None, text: str):
        self._testid = testid
        self._text = text

    @property
    def text(self) -> str:
        return self._text

    def get_attribute(self, name: str):
        if name == "data-testid":
            return self._testid
        return None


class _MockDriver:
    """find_element / find_elements を最小モック.

    css_map: {"span[data-testid='商品のサイズ']": <span>} 等の CSS selector → 要素
    spans:   全 span のリスト (フォールバックのため)
    """
    def __init__(self, css_map: dict, spans: list):
        self._css_map = css_map
        self._spans = spans

    def find_element(self, by, value):
        from selenium.common.exceptions import NoSuchElementException  # noqa: PLC0415
        if value in self._css_map:
            return self._css_map[value]
        raise NoSuchElementException(f"not found: {value}")

    def find_elements(self, by, value):
        # tag_name='span' のみサポート
        if value == "span":
            return self._spans
        return []


class TestExtractSizeSelectorPrimary:
    def test_returns_size_via_testid_css(self):
        # 第 1 候補: span[data-testid="商品のサイズ"] でヒット
        target = _MockSpan(testid=SIZE_TESTID, text="L")
        driver = _MockDriver(
            css_map={f'span[data-testid="{SIZE_TESTID}"]': target},
            spans=[target],
        )
        assert _extract_size(driver) == "L"

    def test_strips_whitespace(self):
        target = _MockSpan(testid=SIZE_TESTID, text="  XL\n")
        driver = _MockDriver(
            css_map={f'span[data-testid="{SIZE_TESTID}"]': target},
            spans=[target],
        )
        assert _extract_size(driver) == "XL"


class TestExtractSizeFallbackTagScan:
    def test_falls_back_to_span_scan(self):
        # CSS selector が NoSuchElement を投げるが、tag scan で見つかる
        target = _MockSpan(testid=SIZE_TESTID, text="M")
        noise = _MockSpan(testid="other", text="ignored")
        driver = _MockDriver(
            css_map={},  # primary selector 失敗
            spans=[noise, target, noise],
        )
        assert _extract_size(driver) == "M"

    def test_returns_empty_when_not_found_in_either_path(self):
        # primary も fallback も失敗 → 空文字 (fail-closed)
        noise = _MockSpan(testid="other", text="x")
        driver = _MockDriver(css_map={}, spans=[noise])
        assert _extract_size(driver) == ""

    def test_returns_empty_on_no_spans_at_all(self):
        driver = _MockDriver(css_map={}, spans=[])
        assert _extract_size(driver) == ""


class TestExtractSizeJapaneseSizeValues:
    """Mercari でよく出るサイズ表記がそのまま透過されるか."""

    @pytest.mark.parametrize("size_text", [
        "S",
        "M",
        "L",
        "XL",
        "XXL",
        "FREE",
        "フリーサイズ",
        "150cm",
        "Mサイズ",
        "23cm",
        "27.5cm",
        "ワンサイズ",
        "サイズ表記なし",
    ])
    def test_passes_through_without_modification(self, size_text):
        target = _MockSpan(testid=SIZE_TESTID, text=size_text)
        driver = _MockDriver(
            css_map={f'span[data-testid="{SIZE_TESTID}"]': target},
            spans=[target],
        )
        assert _extract_size(driver) == size_text


# --------------------------------------------------------------------------
# sheet_writer._build_row: S/T 列に color/size が書き込まれるか
# --------------------------------------------------------------------------
class TestSheetWriterBuildRowColorSize:
    def test_color_and_size_populate_s_and_t_columns(self):
        item = {
            "url": "https://jp.mercari.com/item/m11111111111",
            "title": "テスト",
            "color": "ネイビー",
            "size": "L",
        }
        row = sheet_writer._build_row(item)
        assert len(row) == 20
        assert row[18] == "ネイビー"  # S 列 (1-based 19, 0-based 18)
        assert row[19] == "L"          # T 列 (1-based 20, 0-based 19)

    def test_color_empty_when_missing(self):
        item = {"url": "https://jp.mercari.com/item/m11111111111"}
        row = sheet_writer._build_row(item)
        assert row[18] == ""
        assert row[19] == ""

    def test_color_only(self):
        # color だけあって size 未取得のケース (画像はあるが Mercari size field 未入力)
        item = {
            "url": "https://jp.mercari.com/item/m11111111111",
            "color": "黒",
        }
        row = sheet_writer._build_row(item)
        assert row[18] == "黒"
        assert row[19] == ""

    def test_size_only(self):
        # size だけあって color 判別不能のケース
        item = {
            "url": "https://jp.mercari.com/item/m11111111111",
            "size": "M",
        }
        row = sheet_writer._build_row(item)
        assert row[18] == ""
        assert row[19] == "M"

    def test_other_columns_unchanged_when_color_size_added(self):
        # 既存の C/E/F/G/H 列の挙動が color/size 追加で変わらないこと
        item = {
            "url": "https://jp.mercari.com/item/m11111111111",
            "title": "テスト商品",
            "condition": "目立った傷や汚れなし",
            "price_jpy": 1500,
            "image_urls": ["https://img1.example.com/a.jpg"],
            "description": "説明文",
            "color": "ベージュ",
            "size": "Free",
        }
        row = sheet_writer._build_row(item)
        assert row[0] == "https://jp.mercari.com/item/m11111111111"  # A
        assert row[1] == ""                                            # B
        assert row[2] == "テスト商品"                                  # C
        assert row[3] == ""                                            # D
        assert row[4] == "目立った傷や汚れなし"                         # E
        assert row[5] == "1500"                                        # F
        assert row[6] == "https://img1.example.com/a.jpg"              # G
        assert row[7] == "説明文"                                      # H
        # I-R (8-17) すべて空欄
        for i in range(8, 18):
            assert row[i] == ""
        assert row[18] == "ベージュ"                                   # S
        assert row[19] == "Free"                                       # T


# --------------------------------------------------------------------------
# sheet_writer_amazon._build_row: Amazon の S/T 通常空欄
# --------------------------------------------------------------------------
class TestSheetWriterAmazonBuildRowColorSize:
    def test_amazon_default_empty_color_size(self):
        # Amazon items は通常 color/size key を持たない → S/T 空欄
        item = {
            "url": "https://www.amazon.co.jp/dp/B08N5WRWNW",
            "title": "Amazon 商品",
            "condition": "New",
        }
        row = sheet_writer_amazon._build_row(item)
        assert len(row) == 20
        assert row[18] == ""  # S
        assert row[19] == ""  # T

    def test_amazon_writes_color_size_if_provided(self):
        # 将来 Amazon variant 抽出を実装した時の互換性確保
        item = {
            "url": "https://www.amazon.co.jp/dp/B08N5WRWNW",
            "color": "Black",
            "size": "L",
        }
        row = sheet_writer_amazon._build_row(item)
        assert row[18] == "Black"
        assert row[19] == "L"
