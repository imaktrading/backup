#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""psa_resource_gate.combine の回帰テスト (2026-06-09)。

PSA10 2チャネル(メルカリ＆SNKRDUNK)の再仕入れ可否を束ねる純関数を検証。
どちらか在庫あり→可、両方なし→不能、最安は両者の安い方。
"""
import importlib.util
import os

_MOD = os.path.join(os.path.dirname(__file__), "..", "tools", "psa_resource_gate.py")
_spec = importlib.util.spec_from_file_location("psa_resource_gate", _MOD)
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)


def _snkr(count, *prices):
    return {"psa10_count": count,
            "psa10_details": [{"price": p, "url": f"u{p}"} for p in prices],
            "search_failed": False}


def test_both_channels_cheapest_wins():
    c = g.combine((12000, "murl", "x"), _snkr(2, 9800, 15000))
    assert c["resourceable"] is True
    assert set(c["channels"]) == {"mercari", "snkrdunk"}
    assert c["cheapest_jpy"] == 9800
    assert c["cheapest_channel"] == "snkrdunk"
    assert c["mercari_jpy"] == 12000 and c["snkrdunk_jpy"] == 9800


def test_mercari_cheaper():
    c = g.combine((7000, "murl", "x"), _snkr(1, 9800))
    assert c["cheapest_jpy"] == 7000 and c["cheapest_channel"] == "mercari"


def test_only_mercari():
    c = g.combine((8000, "murl", "x"), None)
    assert c["resourceable"] is True and c["channels"] == ["mercari"]
    assert c["cheapest_jpy"] == 8000 and c["snkrdunk_count"] == 0


def test_only_snkrdunk():
    c = g.combine(None, _snkr(3, 5000, 6000, 7000))
    assert c["resourceable"] is True and c["channels"] == ["snkrdunk"]
    assert c["cheapest_jpy"] == 5000 and c["cheapest_channel"] == "snkrdunk"


def test_neither_is_not_resourceable():
    c = g.combine(None, _snkr(0))
    assert c["resourceable"] is False and c["channels"] == []
    assert c["cheapest_jpy"] is None and c["cheapest_channel"] is None


def test_snkrdunk_search_failed_treated_as_none():
    c = g.combine(None, {"psa10_count": 0, "psa10_details": [], "search_failed": True})
    assert c["resourceable"] is False


def test_snkrdunk_urls_all_returned_sorted():
    """補URL: SNKRDUNK の全PSA10 URLが価格昇順で返る (1つに潰さない)。"""
    c = g.combine((99999, "m", "x"), _snkr(3, 15000, 9800, 12000))
    urls = c["snkrdunk_urls"]
    assert len(urls) == 3
    assert [u["price"] for u in urls] == [9800, 12000, 15000]  # 価格昇順
    assert urls[0]["url"] == "u9800"


def test_http_shape_snkrdunk_available():
    """HTTP shape (check_by_keyword): available=True → snkrdunk channel + 最安 + カードページ補URL。"""
    http = {"available": True, "psa10_price_jpy": 22000,
            "card_url": "https://snkrdunk.com/apparels/129628"}
    c = g.combine(None, http)
    assert c["resourceable"] is True and c["channels"] == ["snkrdunk"]
    assert c["cheapest_jpy"] == 22000
    assert c["snkrdunk_urls"][0]["url"].endswith("/129628")


def test_http_shape_snkrdunk_unavailable():
    http = {"available": False, "psa10_price_jpy": None, "card_url": ""}
    c = g.combine((14500, "m", "x"), http)
    assert c["channels"] == ["mercari"]      # snkrdunk在庫なし→channel外
    assert c["cheapest_jpy"] == 14500


def test_http_shape_both_channels():
    http = {"available": True, "psa10_price_jpy": 63333,
            "card_url": "https://snkrdunk.com/apparels/520553"}
    c = g.combine((158888, "m", "x"), http)
    assert set(c["channels"]) == {"mercari", "snkrdunk"}
    assert c["cheapest_jpy"] == 63333 and c["cheapest_channel"] == "snkrdunk"


def test_mercari_url_present():
    c = g.combine((8000, "https://jp.mercari.com/item/mXYZ", "x"), None)
    assert c["mercari_url"] == "https://jp.mercari.com/item/mXYZ"


def test_snkrdunk_count_but_no_price_still_channel():
    # 在庫はあるが price 取れず → channel には入る、cheapest は mercari 側
    c = g.combine((9000, "m", "x"), _snkr(1))  # _snkr(1) は price無し詳細0件
    # psa10_count=1 だが details空 → snkrdunk channel 入り、cheapest は mercari
    assert "snkrdunk" in c["channels"]
    assert c["cheapest_channel"] == "mercari" and c["cheapest_jpy"] == 9000
