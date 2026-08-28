# -*- coding: utf-8 -*-
"""検索語の番号は「市場が使う表記」を使う (2026-08-02)。

実測: 補0本のうち候補ゼロ 33件中 **26件がポケカ**。canonical `XY11-034` で検索していたが、
市場は `034/054` と書くため検索が **0件**。しかも名前だけ拾う救済枠(loose_cands)は
**同じ検索結果から**拾う作りなので道連れで空になっていた(all_cands も loose_cands も0)。
catalog は `specs.card_number_text` に市場表記を既に持っている。
= ①catalog は正 / ②引き方が誤り → ②を修正 (1丁目1番地)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import mercari_psa_resource as mp


def test_matcher_accepts_both_notations():
    # 市場表記(034/054)でも canonical(XY11-034)でも同一カードとして通す
    assert mp._name_matches_card("PSA10 イベルタルBREAK 034/054 RR 1ED", "XY11-034", "034/054")
    assert mp._name_matches_card("PSA10 イベルタル XY11-034", "XY11-034", "034/054")


def test_matcher_still_rejects_other_cards():
    # 番号が違えば弾く (fail-closed は緩めない)
    assert not mp._name_matches_card("PSA10 別カード 035/054", "XY11-034", "034/054")
    assert not mp._name_matches_card("PSA10 名前だけ", "XY11-034", "034/054")
    # market_no 無しでも従来どおり動く
    assert mp._name_matches_card("PSA10 x OP06-080", "OP06-080")
    assert not mp._name_matches_card("PSA10 x OP06-081", "OP06-080")


def test_market_notation_is_read_from_catalog():
    """catalog specs.card_number_text を市場表記として拾う (実DB)。"""
    m = mp.card_meta_for_key("pokemon_tcg:XY11-034")
    if not m:                      # catalog 未収録環境ではスキップ
        return
    assert m.get("market_no") == "034/054"


def test_query_uses_market_notation():
    q = mp.build_card_query("PSA10 イベルタルBREAK XY11-034", "XY11-034", "pokemon_tcg:XY11-034")
    if not q.get("market_no"):     # catalog 未収録環境ではスキップ
        return
    assert "034/054" in q["kw"], f"検索語が canonical のまま: {q['kw']}"
    assert q["card_no"] == "XY11-034", "照合用の canonical 番号は保持する"


def test_one_piece_notation_is_unchanged():
    """ワンピースは canonical = 市場表記。挙動を変えない (回帰)。"""
    q = mp.build_card_query("PSA10 x OP06-080", "OP06-080", "one_piece_tcg:OP06-080")
    assert "OP06-080" in q["kw"]


# catalog 実測 (2026-08-28): XY11-034 = 拡張パック「冷酷の反逆者」/ XY - Steam Siege
_HINT_XY11 = ["拡張パック「冷酷の反逆者」", "", "XY - Steam Siege", "", "RR", "イベルタルBREAK"]


def test_candidates_pick_up_market_notation_titles():
    """★2026-08-28: 市場表記で番号が当たっても、採用には set 確証が要る。

    「拡張パック」「ポケモンカード」はどのセットにも出るので確証にならない。
    依頼書: hq/requests/2026-08-28_restock_search_returned_wrong_cards.md
    """
    items = [{"price": 12000, "href": "https://jp.mercari.com/item/m1",
              "name": "PSA10 イベルタルBREAK 034/054 RR 1ED 冷酷の反逆者 ポケモンカード"},
             {"price": 9000, "href": "https://jp.mercari.com/item/m2",
              "name": "PSA10 別のカード 035/054"}]
    got = mp.pick_psa10_candidates(items, "XY11-034", _HINT_XY11, 5, "034/054")
    assert [g[1] for g in got] == ["https://jp.mercari.com/item/m1"]


def test_market_notation_alone_is_not_enough():
    """番号(市場表記)は当たるが set 名が無い出品は候補にしない (別セットの同番号よけ)。"""
    items = [{"price": 12000, "href": "https://jp.mercari.com/item/m1",
              "name": "PSA10 イベルタルBREAK 034/054 RR 1ED ポケモンカード"}]
    assert mp.pick_psa10_candidates(items, "XY11-034", _HINT_XY11, 5, "034/054") == []
