"""tests/test_sheet_writer_amazon_dedupe - sheet_writer_amazon の ASIN dedupe / 列レイアウト検証.

Mercari 用 sheet_writer.py の Amazon 版コピー (sheet_writer_amazon.py) のテスト。
Mercari 用テスト (test_sheet_writer_dedupe.py) とは独立。
"""
from __future__ import annotations

import pytest

from sheet_writer_amazon import (
    append_new_urls,
    dedupe_key,
    read_existing_dedupe_keys,
)


pytestmark = pytest.mark.offline


class _MockWorksheet:
    """get_all_values / append_rows のみ実装した最小モック."""

    def __init__(self, existing_rows: list[list[str]]):
        self._values = existing_rows
        self.append_calls: list[list[list[str]]] = []
        self.update_calls: list[tuple] = []
        self.batch_update_calls: list[list] = []

    def get_all_values(self):
        return self._values

    def append_rows(self, rows, value_input_option=None):  # noqa: ARG002
        self.append_calls.append(rows)

    def update(self, *args, **kwargs):  # noqa: ARG002
        self.update_calls.append((args, kwargs))

    def batch_update(self, *args, **kwargs):  # noqa: ARG002
        self.batch_update_calls.append((args, kwargs))


def _empty_row(url: str = "", ebay_id: str = "") -> list[str]:
    row = [""] * 8
    row[0] = url
    row[1] = ebay_id
    return row


def _ws_with_existing_amazon_urls(asins: list[str]) -> _MockWorksheet:
    """A 列に Amazon /dp/ASIN URL のみ、他は空欄で 8 列モックを構築."""
    rows = [["URL"] + [""] * 7]
    for asin in asins:
        rows.append(_empty_row(url=f"https://www.amazon.co.jp/dp/{asin}"))
    return _MockWorksheet(rows)


def _ws_with_mixed_urls(rows_data: list[tuple[str, str]]) -> _MockWorksheet:
    """A 列に Mercari/Amazon 混在 URL + B 列 eBay item ID の既存スプシ."""
    rows = [["URL", "eBay itemID"] + [""] * 6]
    for url, ebay_id in rows_data:
        rows.append(_empty_row(url=url, ebay_id=ebay_id))
    return _MockWorksheet(rows)


# --------------------------------------------------------------------------
# dedupe_key
# --------------------------------------------------------------------------
class TestDedupeKey:
    def test_amazon_dp_url(self):
        assert dedupe_key("https://www.amazon.co.jp/dp/B08N5WRWNW") == "amzn:B08N5WRWNW"

    def test_amazon_gp_product_url(self):
        # /dp/ と /gp/product/ は同一 ASIN → 同じ key
        k1 = dedupe_key("https://www.amazon.co.jp/dp/B08N5WRWNW")
        k2 = dedupe_key("https://www.amazon.co.jp/gp/product/B08N5WRWNW")
        assert k1 == k2 == "amzn:B08N5WRWNW"

    def test_amazon_with_ref_suffix(self):
        # /dp/<ASIN>/ref=foo の suffix を吸収
        assert dedupe_key(
            "https://www.amazon.co.jp/dp/B08N5WRWNW/ref=cm_sw_r_other"
        ) == "amzn:B08N5WRWNW"

    def test_amazon_with_query(self):
        assert dedupe_key(
            "https://www.amazon.co.jp/dp/B08N5WRWNW?th=1"
        ) == "amzn:B08N5WRWNW"

    def test_lowercase_asin_normalized_uppercase(self):
        assert dedupe_key("https://www.amazon.co.jp/dp/b08n5wrwnw") == "amzn:B08N5WRWNW"

    def test_empty(self):
        assert dedupe_key("") == ""
        assert dedupe_key("   ") == ""

    def test_mercari_url_falls_back_to_normalized(self):
        # Mercari URL は ASIN regex にマッチしない → URL 正規化フォールバック
        # (Mercari 行は Amazon writer から見ると単なる文字列、ぶつからない)
        k = dedupe_key("https://jp.mercari.com/item/m12345678901")
        assert not k.startswith("amzn:")
        assert "mercari" in k

    def test_mercari_and_amazon_keys_never_collide(self):
        # Mercari と Amazon の key は prefix が異なるので絶対衝突しない
        amzn_key = dedupe_key("https://www.amazon.co.jp/dp/B08N5WRWNW")
        merc_key = dedupe_key("https://jp.mercari.com/item/m12345678901")
        assert amzn_key != merc_key
        assert not amzn_key.startswith(merc_key)
        assert not merc_key.startswith(amzn_key)


# --------------------------------------------------------------------------
# read_existing_dedupe_keys
# --------------------------------------------------------------------------
class TestReadExistingDedupeKeys:
    def test_extracts_amazon_keys(self):
        ws = _ws_with_existing_amazon_urls(["B08N5WRWNW", "B0ABCDEFGH"])
        keys = read_existing_dedupe_keys(ws)
        assert keys == {"amzn:B08N5WRWNW", "amzn:B0ABCDEFGH"}

    def test_empty_sheet(self):
        ws = _MockWorksheet([])
        assert read_existing_dedupe_keys(ws) == set()

    def test_header_only(self):
        ws = _MockWorksheet([["URL", "", ""]])
        assert read_existing_dedupe_keys(ws) == set()

    def test_mercari_rows_dont_match_amazon_keys(self):
        # 既存 Mercari 行があっても amzn: prefix の key は混ざらない
        ws = _ws_with_mixed_urls([
            ("https://jp.mercari.com/item/m11111111111", "357401200653"),
            ("https://www.amazon.co.jp/dp/B08N5WRWNW", "357401200999"),
        ])
        keys = read_existing_dedupe_keys(ws)
        assert "amzn:B08N5WRWNW" in keys
        # Mercari URL は URL 正規化形式で set に入る (prefix 違うので衝突しない)
        amzn_keys = {k for k in keys if k.startswith("amzn:")}
        assert amzn_keys == {"amzn:B08N5WRWNW"}

    def test_b_column_ebay_ids_are_ignored(self):
        ws = _ws_with_mixed_urls([
            ("https://www.amazon.co.jp/dp/B08N5WRWNW", "357401200653"),
            ("https://www.amazon.co.jp/dp/B0ABCDEFGH", "357401200999"),
        ])
        keys = read_existing_dedupe_keys(ws)
        # B 列の eBay item ID は混ざらない
        assert "357401200653" not in keys
        assert "357401200999" not in keys
        assert "amzn:B08N5WRWNW" in keys
        assert "amzn:B0ABCDEFGH" in keys


# --------------------------------------------------------------------------
# append_new_urls
# --------------------------------------------------------------------------
class TestAppendNewUrls:
    def test_appends_only_new_amazon_items(self):
        ws = _ws_with_existing_amazon_urls(["B08N5WRWNW"])
        items = [
            {"url": "https://www.amazon.co.jp/dp/B08N5WRWNW"},      # 既出
            {"url": "https://www.amazon.co.jp/dp/B098765432"},       # 新規
            {"url": "https://www.amazon.co.jp/dp/B0ABCDEFGH"},       # 新規
        ]
        result = append_new_urls(ws, items)
        assert result == {"appended": 2, "skipped_existing": 1, "input": 3}
        appended = ws.append_calls[0]
        assert [r[0] for r in appended] == [
            "https://www.amazon.co.jp/dp/B098765432",
            "https://www.amazon.co.jp/dp/B0ABCDEFGH",
        ]
        # 全行 8 列、B/D 列は空欄
        for r in appended:
            assert len(r) == 8
            assert r[1] == ""  # B: eBay item ID
            assert r[3] == ""  # D: 売切フラグ

    def test_dp_and_gp_product_collide_correctly(self):
        # /dp/ASIN と /gp/product/ASIN は同じ商品 → 後者は skip される
        ws = _ws_with_existing_amazon_urls(["B08N5WRWNW"])
        items = [
            {"url": "https://www.amazon.co.jp/gp/product/B08N5WRWNW"},  # 既出と同じ ASIN
        ]
        result = append_new_urls(ws, items)
        assert result["appended"] == 0
        assert result["skipped_existing"] == 1

    def test_writes_full_columns_with_detail(self):
        ws = _ws_with_existing_amazon_urls([])
        items = [{
            "url": "https://www.amazon.co.jp/dp/B08N5WRWNW",
            "title": "テスト商品",
            "condition": "New",
            "price_jpy": 1980,
            "image_urls": ["https://m.media-amazon.com/a.jpg",
                           "https://m.media-amazon.com/b.jpg"],
            "description": "Amazon 商品説明文\n複数行",
        }]
        append_new_urls(ws, items)
        r = ws.append_calls[0][0]
        assert r[0] == "https://www.amazon.co.jp/dp/B08N5WRWNW"  # A: URL
        assert r[1] == ""                                          # B: eBay (空)
        assert r[2] == "テスト商品"                                # C: タイトル
        assert r[3] == ""                                          # D: 売切フラグ (空)
        assert r[4] == "New"                                       # E: 状態
        assert r[5] == "1980"                                      # F: 価格
        assert r[6] == "https://m.media-amazon.com/a.jpg|https://m.media-amazon.com/b.jpg"
        assert r[7] == "Amazon 商品説明文\n複数行"                  # H: 説明

    def test_price_none_writes_empty(self):
        ws = _ws_with_existing_amazon_urls([])
        items = [{"url": "https://www.amazon.co.jp/dp/B08N5WRWNW",
                  "price_jpy": None}]
        append_new_urls(ws, items)
        r = ws.append_calls[0][0]
        assert r[5] == ""

    def test_skips_in_batch_duplicates(self):
        # 同一 ASIN でも URL 形式が違う 2 行は 1 件のみ appended
        ws = _ws_with_existing_amazon_urls([])
        items = [
            {"url": "https://www.amazon.co.jp/dp/B08N5WRWNW"},
            {"url": "https://www.amazon.co.jp/gp/product/B08N5WRWNW"},
            {"url": "https://www.amazon.co.jp/dp/B08N5WRWNW/ref=foo"},
        ]
        result = append_new_urls(ws, items)
        assert result["appended"] == 1
        assert result["skipped_existing"] == 2

    def test_mercari_existing_does_not_block_amazon_new(self):
        # 既存 Mercari 行と新規 Amazon ASIN は衝突しないこと
        ws = _ws_with_mixed_urls([
            ("https://jp.mercari.com/item/m11111111111", "357401200653"),
        ])
        items = [
            {"url": "https://www.amazon.co.jp/dp/B08N5WRWNW"},
        ]
        result = append_new_urls(ws, items)
        assert result["appended"] == 1
        assert result["skipped_existing"] == 0

    def test_does_not_call_update_or_batch_update(self):
        # 既存行を一切上書きしない (CLAUDE.md: 既存スプシ行を上書きしない)
        ws = _ws_with_existing_amazon_urls(["B08N5WRWNW"])
        items = [{"url": "https://www.amazon.co.jp/dp/B0ABCDEFGH"}]
        append_new_urls(ws, items)
        assert ws.update_calls == []
        assert ws.batch_update_calls == []

    def test_empty_input(self):
        ws = _ws_with_existing_amazon_urls([])
        result = append_new_urls(ws, [])
        assert result == {"appended": 0, "skipped_existing": 0, "input": 0}
        assert ws.append_calls == []

    def test_skips_invalid_items(self):
        ws = _ws_with_existing_amazon_urls([])
        items = [
            {"url": ""},                                                # url 空
            {"url": "https://www.amazon.co.jp/dp/B08N5WRWNW"},          # OK
        ]
        result = append_new_urls(ws, items)
        assert result["appended"] == 1
        assert result["skipped_existing"] == 1
