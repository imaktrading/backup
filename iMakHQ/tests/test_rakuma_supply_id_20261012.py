# -*- coding: utf-8 -*-
"""ラクマ仕入の出品を itemID 書戻し・広告8%・入稿直前の在庫確認で引けるように (2026-10-12)。

Tシャツのラクマ仕入は SKU = 出品番号の末尾8桁 (tshirt_listing.py)。どちらの道具もこの形を知らず、
10/12 の🤖自動で出した11件のうち8件の itemID が書き戻されず「書き戻し漏れ 0件」と出ていた。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import itemid_writeback_audit as W  # noqa: E402
import sheet_io  # noqa: E402

URL = "https://item.fril.jp/38bc3c4cc0dd72bc625a871c"
URL_GL = "https://item.fril.jp/4b8aaddcbec7356be33697fc337e8ac5?_gl=1*19ew1vg*Rakuma"


def test_shared_helper_gives_last_8():
    assert sheet_io.supply_id_from_url(URL) == "625a871c"
    assert sheet_io.supply_id_from_url(URL_GL) == "337e8ac5"
    assert sheet_io.supply_id_from_url("https://jp.mercari.com/item/m123456789") == "m123456789"


def test_writeback_finds_rakuma_row():
    live = {"820230301227": {"sku": "625a871c", "cur": "USD", "avail": 1}}
    by_cert, by_supply = W.build_live_index(live)
    row = [""] * (W.COL_CAT + 1)
    row[W.COL_A] = URL
    miss = W.find_missing([["h"] * (W.COL_CAT + 1), row], by_cert, by_supply, "HIGH")
    assert [m["item_id"] for m in miss] == ["820230301227"]


def test_writeback_url_key_matches_listing_sku():
    m = W._RE_SUPPLY_URL.search(URL_GL)
    assert next(g for g in m.groups() if g) == "337e8ac5"
