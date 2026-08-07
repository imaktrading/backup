# -*- coding: utf-8 -*-
"""Step6 P1: 商品管理シート itemID→canonical KEY map (build_key_map 純関数) の test."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from sheet_io import build_key_map, PRODUCT_COL_ITEMID, PRODUCT_COL_KEY


def _row(itemid, key, ncols=36):
    r = [""] * ncols
    r[PRODUCT_COL_ITEMID] = itemid
    r[PRODUCT_COL_KEY] = key
    return r


def test_build_key_map_basic():
    rows = [["URL", "itemID", "..."], _row("358353408395", "OP10-049_p1"),
            _row("358369069659", "ST01-006_p1")]
    m = build_key_map(rows)
    assert m == {"358353408395": "OP10-049_p1", "358369069659": "ST01-006_p1"}


def test_build_key_map_skips_url_key_and_empty():
    rows = [
        ["URL", "itemID"],
        _row("111", "item:m12345"),     # url-key → 除外 (catalog-backed のみ)
        _row("222", "shops:abc"),        # shops url-key → 除外
        _row("333", ""),                 # KEY空 → 除外
        _row("", "OP01-001_p1"),         # itemID空 → 除外
        _row("444", "OP04-112_P"),       # 正常
    ]
    m = build_key_map(rows)
    assert m == {"444": "OP04-112_P"}


def test_build_key_map_handles_short_rows():
    rows = [["URL", "itemID"], ["only", "two"], _row("555", "EB02-015_p")]
    m = build_key_map(rows)
    assert m == {"555": "EB02-015_p"}


def test_build_key_map_last_write_wins_on_dup_itemid():
    rows = [["h"], _row("999", "OP01-001"), _row("999", "OP01-001_p1")]
    m = build_key_map(rows)
    assert m["999"] == "OP01-001_p1"
