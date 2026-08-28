#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""補URL = メルカリ＆SNKRDUNK 混合の最安5件を高い順 の回帰テスト (2026-06-10)。

「補」= 最安が売切/状態相違時の代替候補。両ch横断で安い順に拾い、補URL列には高い順
([0]=高 … [-1]=最安)で並べる(ユーザー指示)。最安1件のみだと最安値列と重複し補の意味が無い。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import psa_resource_gate as gate   # noqa: E402
import mercari_psa_resource as mp  # noqa: E402


def _snk_http(*prices):
    """HTTP shape: psa10_listings を価格付きで。"""
    listings = [{"price": p, "url": f"https://snkrdunk.com/used/{p}"} for p in prices]
    return {"available": bool(prices), "psa10_price_jpy": (prices[0] if prices else None),
            "psa10_listings": listings, "card_id": 1, "card_url": "https://snkrdunk.com/c/1"}


def test_aux_mixes_both_channels_cheapest5_high_to_low():
    """メルカリ3 + SNKRDUNK3 = 6候補 → 最安5件を高い順。"""
    merc_cands = [(14000, "m14", "x"), (16000, "m16", "x"), (20000, "m20", "x")]
    snk = _snk_http(15000, 18000, 22000)
    c = gate.combine((14000, "m14", "x"), snk, mercari_cands=merc_cands, max_aux=5)
    prices = [u["price"] for u in c["aux_urls"]]
    # 6候補(14,15,16,18,20,22k)の最安5 = 14,15,16,18,20k を 高い順
    assert prices == [20000, 18000, 16000, 15000, 14000]
    # 最安(14000)が末尾、最高(20000)が先頭
    assert c["aux_urls"][0]["url"] == "m20"
    assert c["aux_urls"][-1]["url"] == "m14"
    # 22000 は最安5から漏れる
    assert 22000 not in prices


def test_aux_channel_tagged():
    """混合候補は channel タグを持つ(メルカリ/SNKRDUNK 由来が分かる)。"""
    c = gate.combine((10000, "m10", "x"), _snk_http(12000),
                     mercari_cands=[(10000, "m10", "x")], max_aux=5)
    chans = {u["channel"] for u in c["aux_urls"]}
    assert chans == {"mercari", "snkrdunk"}


def test_aux_caps_at_max_aux():
    snk = _snk_http(1000, 2000, 3000, 4000, 5000, 6000, 7000)
    c = gate.combine(None, snk, mercari_cands=None, max_aux=5)
    assert len(c["aux_urls"]) == 5
    # 最安5(1000-5000)を高い順
    assert [u["price"] for u in c["aux_urls"]] == [5000, 4000, 3000, 2000, 1000]


def test_aux_snkrdunk_only_when_no_mercari():
    c = gate.combine(None, _snk_http(8000, 9000), mercari_cands=[], max_aux=5)
    assert [u["price"] for u in c["aux_urls"]] == [9000, 8000]
    assert all(u["channel"] == "snkrdunk" for u in c["aux_urls"])


def test_aux_mercari_only_when_no_snkrdunk():
    c = gate.combine((5000, "m5", "x"), None,
                     mercari_cands=[(5000, "m5", "x"), (6000, "m6", "x")], max_aux=5)
    assert [u["price"] for u in c["aux_urls"]] == [6000, 5000]
    assert all(u["channel"] == "mercari" for u in c["aux_urls"])


def test_aux_empty_when_no_candidates():
    c = gate.combine(None, None, mercari_cands=None, max_aux=5)
    assert c["aux_urls"] == []


# ---- pick_psa10_candidates (メルカリ複数候補) ----
def _items(*pairs):
    return [{"price": p, "href": h, "name": n} for p, h, n in pairs]


# ★2026-08-28: 候補採用は「番号一致 かつ set 確証」。出品名に set 名 (神速の拳) を入れ、
#   hint を渡して呼ぶ。番号だけの出品は候補にならない
#   (依頼書 hq/requests/2026-08-28_restock_search_returned_wrong_cards.md)。
_HINT_OP11 = ["ブースターパック 神速の拳【OP-11】", "", "A Fist of Divine Speed", "", "R", "ゼウス"]


def test_pick_candidates_returns_multiple_price_asc():
    items = _items((14000, "h1", "Luffy PSA10 [OP11-106] 神速の拳"),
                   (16000, "h2", "Luffy PSA10 [OP11-106] 神速の拳"),
                   (2000, "h3", "raw card OP11-106 神速の拳"))  # PSA10でない→除外
    got = mp.pick_psa10_candidates(items, "OP11-106", _HINT_OP11, limit=5)
    assert [g[0] for g in got] == [14000, 16000]
    assert got[0][1] == "h1"


def test_pick_candidates_respects_limit():
    items = _items(*[(1000 * k, f"h{k}", f"PSA10 [OP11-106] 神速の拳 #{k}") for k in range(1, 9)])
    got = mp.pick_psa10_candidates(items, "OP11-106", _HINT_OP11, limit=3)
    assert len(got) == 3
    assert [g[0] for g in got] == [1000, 2000, 3000]


def test_pick_candidates_number_only_is_failclosed():
    """set 名の無い出品 = 番号一致だけ → 候補に出さない。"""
    items = _items((14000, "h1", "Luffy PSA10 [OP11-106]"))
    assert mp.pick_psa10_candidates(items, "OP11-106", _HINT_OP11, limit=5) == []


def test_pick_candidates_failclosed_empty():
    """変種曖昧(hint無+複数set)時は [] (誤variant候補を出さない)。pick_cheapest と整合。"""
    items = _items((100, "a", "Zeus PSA10 [OP11-106] Booster"),
                   (200, "b", "Zeus PSA10 [OP11-106] Egghead"))
    # hint で一意化できない複数 → pick_cheapest も None、candidates も []
    got = mp.pick_psa10_candidates(items, "OP11-106", variant_hint=["全然違うXYZ"], limit=5)
    assert got == []
    assert mp.pick_cheapest_psa10(items, "OP11-106", variant_hint=["全然違うXYZ"]) is None
