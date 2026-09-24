# -*- coding: utf-8 -*-
"""補URL・再仕入れの画面に A (このカードとして探しているカタログのカード) を出す (2026-09-24)。

ユーザー「A の特定は合っているの？ それが分からない。A を表示したら？ A が間違っているのも分かるし」。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import psa_resource_confirm as prc  # noqa: E402


def _item(**kw):
    it = {"idx": 0, "title": "【PSA10】ジンベエ OP11-021", "card_no": "OP11-021", "ebay_url": "https://www.ebay.com/itm/1",
          "ref_image": "", "candidates": []}
    it.update(kw)
    return it


def test_card_a_is_shown_when_catalog_given():
    cat = {"key": "one_piece_tcg:OP11-021_p", "name": "ジンベエ", "card_no": "OP11-021",
           "set": "BOOSTER -A FIST OF DIVINE SPEED- [OP-11]", "image": "https://example.com/a.png"}
    html = prc.build_restock_html([_item(catalog=cat)])
    assert "このカードとして探しています" in html
    assert "OP11-021_p" in html and "FIST OF DIVINE SPEED" in html


def test_no_catalog_no_block():
    assert "このカードとして探しています" not in prc.build_restock_html([_item()])


def test_catalog_view_empty_key():
    assert prc.catalog_view("") == {}
