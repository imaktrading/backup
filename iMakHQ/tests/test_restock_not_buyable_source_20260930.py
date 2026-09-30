# -*- coding: utf-8 -*-
"""「買えない」と登録済みの仕入元で 再仕入れ可 と判定しない / 件数と画面をそろえる (2026-09-30)。

実例 820153270215 ジンベエ ST01-005: 唯一の候補 (m82100837736) が 9/28 の目視で「まとめ売り」と
判定済みなのに最安として採られ「再仕入れ可◎」。照合の画面では外れて候補0本 → 黙って飛ばされ、
コンソールの「再仕入れ① 目視 1件」が押しても数え直しても消えなかった。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import psa_resource_gate as G  # noqa: E402

BAD = "https://jp.mercari.com/item/m82100837736"
GOOD = "https://jp.mercari.com/item/m1"


def test_not_buyable_best_is_not_restockable():
    c = G.combine((16000, BAD, "PSA10 ジンベエ"), None, mercari_cands=[(16000, BAD, "x")],
                  not_buyable=[BAD])
    assert c["resourceable"] is False
    assert c["mercari_url"] == "" and c["aux_urls"] == []


def test_falls_back_to_next_buyable_candidate():
    c = G.combine((16000, BAD, "x"), None, mercari_cands=[(16000, BAD, "x"), (18000, GOOD, "y")],
                  not_buyable=[BAD + "?utm=1"])
    assert c["mercari_url"] == GOOD and c["mercari_jpy"] == 18000
    assert [u["url"] for u in c["aux_urls"]] == [GOOD]


def test_snkrdunk_not_buyable_dropped():
    s = {"available": True, "psa10_price_jpy": 9000,
         "psa10_listings": [{"price": 9000, "url": "https://snkrdunk.com/apparels/1/used/2"}]}
    c = G.combine(None, s, not_buyable=["https://snkrdunk.com/apparels/1/used/2"])
    assert c["resourceable"] is False and c["snkrdunk_count"] == 0


def test_count_blocks_card_whose_candidates_all_filtered():
    cache = {"820153270215": {"mercari": {"best": [16000, BAD, "x"], "cands": [[16000, BAD, "x"]]}}}
    blocked = G.count_ng_blocked(["820153270215"], cache, {},
                                 lambda *a, **k: {}, lambda mr, c: [])
    assert blocked == {"820153270215"}


def test_count_keeps_unknown_cache():
    assert G.count_ng_blocked(["1"], {}, {}, lambda *a, **k: {}, lambda mr, c: []) == set()


def test_gate_reports_zero_candidate_skips():
    src = open(G.__file__, encoding="utf-8").read()
    assert "候補0本" in src and "_nocand.append" in src
