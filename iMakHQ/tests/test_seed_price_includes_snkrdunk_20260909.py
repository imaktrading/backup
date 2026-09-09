# -*- coding: utf-8 -*-
"""種の値段は snkrdunk も引く (2026-09-09 ユーザー指摘「何件か、価格入ってないけど」)。

`url_title_map` が **mercari しか見ていなかった**。実測: 台帳の価格なし47件のうち
**44件が snkrdunk**。値段が無いと:
  - 仕入値の上限で外せない (fail-open で素通りする)
  - 商品管理シートに足した時に M列が空 = 仕入値 N=(M or F)−K が作れない
補URL側 (`hoju_url_from_dupes.price_by_url_from_cache`) は 2026-09-07 に同じ穴を
塞いでいたのに、こちらだけ残っていた。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import newcand_confirm as N     # noqa: E402

_CACHE = {
    "111": {
        "mercari": {"cands": [[5000, "https://jp.mercari.com/item/m1", "PSA10 A"]]},
        "snkrdunk": {"psa10_listings": [
            {"price": 7700, "url": "https://snkrdunk.com/apparels/1/used/2",
             "image": "https://cdn/x.jpg"},
            {"price": 9900, "url": "https://snkrdunk.com/apparels/1/used/3"},
        ]},
    },
}


def test_snkrdunkの値段も引ける():
    got = N.url_title_map(_CACHE)
    assert got["https://snkrdunk.com/apparels/1/used/2"] == (7700, "")
    assert got["https://snkrdunk.com/apparels/1/used/3"] == (9900, "")


def test_mercariは今までどおり():
    got = N.url_title_map(_CACHE)
    assert got["https://jp.mercari.com/item/m1"] == (5000, "PSA10 A")


def test_urlが無い行は捨てる():
    got = N.url_title_map({"1": {"snkrdunk": {"psa10_listings": [{"price": 100}]}}})
    assert got == {}


def test_snkrdunkが無くても壊れない():
    assert N.url_title_map({"1": {"mercari": {}}}) == {}
    assert N.url_title_map({}) == {}


def test_引けた値段が上限判定に効く():
    """値段が入って初めて、上限超を外せる (入っていないと fail-open で素通り)。"""
    got = N.url_title_map({"1": {"snkrdunk": {"psa10_listings": [
        {"price": 199800, "url": "https://snkrdunk.com/apparels/9/used/9"}]}}})
    price = got["https://snkrdunk.com/apparels/9/used/9"][0]
    assert N.over_cost_cap(price) is True
