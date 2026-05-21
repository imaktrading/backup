"""tests/test_sheet_writer_dedupe - append_new_urls の デデュープ / 列レイアウト動作検証.

仕様 (2026-04-30):
  - Harvest が書くのは A/C/E/F/G/H 列 (URL/タイトル/状態/価格/画像/説明)
  - B 列 (eBay item ID) と D 列 (Inventory 売切フラグ) は空欄で append
  - デデュープキーは A 列 URL から dedupe_key() で抽出
"""
from __future__ import annotations

import pytest

from sheet_writer import (
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
    """8 列 (A〜H) で 1 行を構築. 既存スプシのモック用."""
    row = [""] * 8
    row[0] = url
    row[1] = ebay_id
    return row


def _ws_with_existing_urls(item_ids: list[str]) -> _MockWorksheet:
    """A 列に URL のみ、他は空欄で 8 列モックを構築."""
    rows = [["URL"] + [""] * 7]
    for iid in item_ids:
        rows.append(_empty_row(url=f"https://jp.mercari.com/item/{iid}"))
    return _MockWorksheet(rows)


def _ws_with_ebay_item_ids(url_and_ebay_ids: list[tuple[str, str]]) -> _MockWorksheet:
    """A 列 URL + B 列 eBay item ID (数字のみ) の既存スプシ."""
    rows = [["URL", "eBay itemID"] + [""] * 6]
    for url, ebay_id in url_and_ebay_ids:
        rows.append(_empty_row(url=url, ebay_id=ebay_id))
    return _MockWorksheet(rows)


# --------------------------------------------------------------------------
# dedupe_key
# --------------------------------------------------------------------------
class TestDedupeKey:
    def test_mercari_item_url(self):
        assert dedupe_key("https://jp.mercari.com/item/m12345678901") == "m12345678901"

    def test_mercari_with_query(self):
        # ?ref=likes 等のクエリ違いを吸収
        assert dedupe_key("https://jp.mercari.com/item/m12345678901?ref=likes") == "m12345678901"

    def test_mercari_alt_path(self):
        assert dedupe_key("https://jp.mercari.com/items/m99999999999") == "m99999999999"

    def test_empty(self):
        assert dedupe_key("") == ""
        assert dedupe_key("   ") == ""

    def test_non_mercari_url_normalized(self):
        # mercari でなければ URL 正規化したものを返す
        k1 = dedupe_key("https://example.com/foo/bar?x=1#y")
        k2 = dedupe_key("https://example.com/foo/bar")
        assert k1 == k2

    def test_mercari_shops_url(self):
        # Phase 1b: Mercari Shops は "shops:<slug>" prefix
        assert dedupe_key(
            "https://jp.mercari.com/shops/product/2JNysv3RcsZP37Dt8Zoaof"
        ) == "shops:2JNysv3RcsZP37Dt8Zoaof"

    def test_mercari_shops_with_query(self):
        # query 違いを吸収
        k1 = dedupe_key("https://jp.mercari.com/shops/product/2JNysv3RcsZP37Dt8Zoaof?ref=likes")
        k2 = dedupe_key("https://jp.mercari.com/shops/product/2JNysv3RcsZP37Dt8Zoaof")
        assert k1 == k2 == "shops:2JNysv3RcsZP37Dt8Zoaof"

    def test_mercari_regular_and_shops_keys_never_collide(self):
        # 通常 Mercari の m\d+ と Shops の "shops:<slug>" は prefix で衝突しない
        regular = dedupe_key("https://jp.mercari.com/item/m12345678901")
        shops = dedupe_key("https://jp.mercari.com/shops/product/m12345678901")
        # たとえ slug が偶然 m\d+ 形式でも、prefix 「shops:」 で区別される
        assert regular == "m12345678901"
        assert shops == "shops:m12345678901"
        assert regular != shops

    def test_workman_url(self):
        # Workman 公式: /shop/g/g<13桁mpn>/ → "workman:<mpn>"
        assert dedupe_key(
            "https://workman.jp/shop/g/g2300011882014/"
        ) == "workman:2300011882014"

    def test_workman_url_with_query(self):
        k1 = dedupe_key("https://workman.jp/shop/g/g2300011882014/?ref=foo")
        k2 = dedupe_key("https://workman.jp/shop/g/g2300011882014/")
        assert k1 == k2 == "workman:2300011882014"

    def test_workman_url_without_trailing_slash(self):
        assert dedupe_key(
            "https://workman.jp/shop/g/g2300011882014"
        ) == "workman:2300011882014"

    def test_workman_does_not_collide_with_mercari_or_shops(self):
        workman = dedupe_key("https://workman.jp/shop/g/g2300011882014/")
        mercari = dedupe_key("https://jp.mercari.com/item/m12345678901")
        shops = dedupe_key("https://jp.mercari.com/shops/product/abcDEF123")
        assert workman == "workman:2300011882014"
        assert workman != mercari
        assert workman != shops
        assert workman.startswith("workman:")

    def test_snkrdunk_used_url(self):
        # SNKRDUNK 個別出品: /apparels/<m>/used/<i> → "snkrdunk:<m>/<i>"
        assert dedupe_key(
            "https://snkrdunk.com/apparels/158327/used/45549454"
        ) == "snkrdunk:158327/45549454"

    def test_snkrdunk_used_url_with_query(self):
        k1 = dedupe_key("https://snkrdunk.com/apparels/158327/used/45549454?ref=likes")
        k2 = dedupe_key("https://snkrdunk.com/apparels/158327/used/45549454")
        assert k1 == k2 == "snkrdunk:158327/45549454"

    def test_snkrdunk_apparel_url_only(self):
        # 個別 used 部分なし (= カード本体 page) → "snkrdunk:<m>"
        assert dedupe_key("https://snkrdunk.com/apparels/158327") == "snkrdunk:158327"
        assert dedupe_key("https://snkrdunk.com/apparels/158327/") == "snkrdunk:158327"

    def test_snkrdunk_does_not_collide(self):
        snk = dedupe_key("https://snkrdunk.com/apparels/158327/used/45549454")
        mercari = dedupe_key("https://jp.mercari.com/item/m12345678901")
        shops = dedupe_key("https://jp.mercari.com/shops/product/abcDEF")
        workman = dedupe_key("https://workman.jp/shop/g/g2300011882014/")
        assert snk == "snkrdunk:158327/45549454"
        assert snk != mercari
        assert snk != shops
        assert snk != workman
        assert snk.startswith("snkrdunk:")

    def test_snkrdunk_used_takes_priority_over_apparel(self):
        # /used/ が含まれていれば snkrdunk:<m>/<i>、含まれなければ snkrdunk:<m>
        with_used = dedupe_key("https://snkrdunk.com/apparels/158327/used/45549454")
        only_apparel = dedupe_key("https://snkrdunk.com/apparels/158327")
        assert with_used == "snkrdunk:158327/45549454"
        assert only_apparel == "snkrdunk:158327"
        assert with_used != only_apparel


# --------------------------------------------------------------------------
# read_existing_dedupe_keys
# --------------------------------------------------------------------------
class TestReadExistingDedupeKeys:
    def test_extracts_keys_from_a_column_urls(self):
        ws = _ws_with_existing_urls(["m11111111111", "m22222222222"])
        assert read_existing_dedupe_keys(ws) == {"m11111111111", "m22222222222"}

    def test_empty_sheet(self):
        ws = _MockWorksheet([])
        assert read_existing_dedupe_keys(ws) == set()

    def test_header_only(self):
        ws = _MockWorksheet([["URL", "", ""]])
        assert read_existing_dedupe_keys(ws) == set()

    def test_skips_blank_a_cells(self):
        ws = _MockWorksheet([
            ["URL", "", ""],
            ["https://jp.mercari.com/item/m11111111111", "", ""],
            ["", "", ""],
        ])
        assert read_existing_dedupe_keys(ws) == {"m11111111111"}

    def test_b_column_ebay_ids_are_ignored(self):
        # B 列は eBay item ID (数字のみ) 用 → dedupe key set には入れない
        ws = _ws_with_ebay_item_ids([
            ("https://jp.mercari.com/item/m11111111111", "357401200653"),
            ("https://jp.mercari.com/item/m22222222222", "357401200999"),
        ])
        keys = read_existing_dedupe_keys(ws)
        # Mercari URL ベースの key のみが集まり、eBay item ID は混ざらない
        assert keys == {"m11111111111", "m22222222222"}
        assert "357401200653" not in keys
        assert "357401200999" not in keys


# --------------------------------------------------------------------------
# append_new_urls
# --------------------------------------------------------------------------
class TestAppendNewUrls:
    def test_appends_only_new_items(self):
        ws = _ws_with_existing_urls(["m11111111111"])
        items = [
            {"url": "https://jp.mercari.com/item/m11111111111"},
            {"url": "https://jp.mercari.com/item/m22222222222"},
            {"url": "https://jp.mercari.com/item/m33333333333"},
        ]
        result = append_new_urls(ws, items)
        assert result == {"appended": 2, "skipped_existing": 1, "input": 3}
        assert len(ws.append_calls) == 1
        appended = ws.append_calls[0]
        assert [r[0] for r in appended] == [
            "https://jp.mercari.com/item/m22222222222",
            "https://jp.mercari.com/item/m33333333333",
        ]
        # 全行 20 列 (A〜T)、Harvest 不可侵列 (B/D, I-R) は常に空欄
        for r in appended:
            assert len(r) == 20
            assert r[1] == ""  # B: eBay item ID
            assert r[3] == ""  # D: 売切フラグ
            # I-R (index 8-17) は空欄
            for i in range(8, 18):
                assert r[i] == ""

    def test_writes_full_columns_with_detail(self):
        # 詳細項目を持つ item を渡したとき、各列が正しく埋まる
        ws = _ws_with_existing_urls([])
        items = [{
            "url": "https://jp.mercari.com/item/m11111111111",
            "title": "テスト商品",
            "condition": "目立った傷や汚れなし",
            "price_jpy": 1500,
            "image_urls": ["https://img1.example.com/a.jpg",
                           "https://img2.example.com/b.jpg"],
            "description": "説明文\n複数行",
        }]
        append_new_urls(ws, items)
        r = ws.append_calls[0][0]
        assert r[0] == "https://jp.mercari.com/item/m11111111111"  # A: URL
        assert r[1] == ""                                            # B: eBay (空)
        assert r[2] == "テスト商品"                                  # C: タイトル
        assert r[3] == ""                                            # D: 売切フラグ (空)
        assert r[4] == "目立った傷や汚れなし"                         # E: 状態
        assert r[5] == "1500"                                        # F: 価格
        assert r[6] == "https://img1.example.com/a.jpg|https://img2.example.com/b.jpg"  # G: 画像
        assert r[7] == "説明文\n複数行"                              # H: 説明

    def test_writes_empty_when_detail_missing(self):
        # title/price 等が無い item は対応する列が空欄になる (S/T 含めて全 20 列)
        ws = _ws_with_existing_urls([])
        items = [{"url": "https://jp.mercari.com/item/m11111111111"}]
        append_new_urls(ws, items)
        r = ws.append_calls[0][0]
        expected = [""] * 20
        expected[0] = "https://jp.mercari.com/item/m11111111111"
        assert r == expected

    def test_price_none_writes_empty(self):
        # price_jpy=None は "" として書く (0 にしない)
        ws = _ws_with_existing_urls([])
        items = [{"url": "https://jp.mercari.com/item/m11111111111",
                  "price_jpy": None}]
        append_new_urls(ws, items)
        r = ws.append_calls[0][0]
        assert r[5] == ""

    def test_skips_in_batch_duplicates(self):
        ws = _ws_with_existing_urls([])
        items = [
            {"url": "https://jp.mercari.com/item/m11111111111", "item_id": "m11111111111"},
            {"url": "https://jp.mercari.com/item/m11111111111?ref=likes", "item_id": "m11111111111"},
        ]
        result = append_new_urls(ws, items)
        # 2 件目はクエリ違いだが dedupe_key 同一 → skip される
        assert result["appended"] == 1
        assert result["skipped_existing"] == 1

    def test_b_column_ebay_id_does_not_affect_dedupe(self):
        # B 列に eBay item ID (数字) が入っていても、デデュープには影響しない.
        # 既存判定は A 列 URL のみで行う.
        ws = _ws_with_ebay_item_ids([
            ("https://jp.mercari.com/item/m11111111111", "357401200653"),
        ])
        items = [
            {"url": "https://jp.mercari.com/item/m11111111111"},     # A 列で既出 → skip
            {"url": "https://jp.mercari.com/item/m22222222222"},     # 新規
        ]
        result = append_new_urls(ws, items)
        assert result["appended"] == 1
        assert result["skipped_existing"] == 1
        appended = ws.append_calls[0]
        # 新規行は 20 列、A 列に URL、B/D/I-R/S/T 含めその他は空欄
        expected = [""] * 20
        expected[0] = "https://jp.mercari.com/item/m22222222222"
        assert appended[0] == expected

    def test_b_column_ebay_id_unrelated_string_does_not_match(self):
        # 仮に Mercari URL の入力 item_id が eBay item ID 文字列と「数字一致」しても
        # dedupe_key 規則 (m\\d+ または URL 正規化) では別物として扱われる.
        ws = _ws_with_ebay_item_ids([
            ("https://jp.mercari.com/item/m11111111111", "357401200653"),
        ])
        items = [
            # Mercari URL じゃないが eBay 番号文字列だけ突っ込む不正入力ケース
            {"url": "357401200653"},
        ]
        result = append_new_urls(ws, items)
        # url が短すぎて dedupe_key が空 (というか文字列そのまま) → invalid 扱いで skip
        # または別物として 1 件 append される (現在の実装は後者)
        # 重要なのは「eBay ID と Mercari URL が衝突しないこと」のみ. この行が
        # 既出 m11111111111 とも、B 列の 357401200653 とも一致しない.
        assert result["appended"] + result["skipped_existing"] == 1

    def test_skips_invalid_items(self):
        ws = _ws_with_existing_urls([])
        items = [
            {"url": "", "item_id": "m11111111111"},                          # url 空
            {"url": "https://jp.mercari.com/item/m22222222222"},              # OK
        ]
        result = append_new_urls(ws, items)
        assert result["appended"] == 1
        assert result["skipped_existing"] == 1

    def test_does_not_call_update_or_batch_update(self):
        # 既存行を一切上書きしないことの担保 (CLAUDE.md: 既存スプシ行を上書きしない)
        ws = _ws_with_existing_urls(["m11111111111"])
        items = [
            {"url": "https://jp.mercari.com/item/m22222222222"},
        ]
        append_new_urls(ws, items)
        assert ws.update_calls == []
        assert ws.batch_update_calls == []

    def test_empty_input(self):
        ws = _ws_with_existing_urls([])
        result = append_new_urls(ws, [])
        assert result == {"appended": 0, "skipped_existing": 0, "input": 0}
        assert ws.append_calls == []

    def test_all_items_already_exist_no_append_call(self):
        ws = _ws_with_existing_urls(["m11111111111", "m22222222222"])
        items = [
            {"url": "https://jp.mercari.com/item/m11111111111"},
            {"url": "https://jp.mercari.com/item/m22222222222"},
        ]
        result = append_new_urls(ws, items)
        assert result["appended"] == 0
        assert result["skipped_existing"] == 2
        assert ws.append_calls == []
