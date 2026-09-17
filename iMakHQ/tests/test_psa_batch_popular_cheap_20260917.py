# -*- coding: utf-8 -*-
"""PSA 新規の並べ順: カード特定済 → 人気キャラ → 仕入値の安い順 (2割ランダム) / 1カード1枠 (2026-09-17 ユーザー承認)。

経緯: セット単位の売れ筋点で並べていたため、19:03 の20枠が S8b だけで11枠 (ゼクロム6) に偏った。
新規出品の目的 = 出していない種類を増やす。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "iMakTCG"))

import tcg_batch_select as T  # noqa: E402

NOSHUFFLE = lambda _l: None  # noqa: E731
EN, JA = {"SNORLAX", "MEW", "LUFFY"}, {"カビゴン", "ミュウ", "ルフィ", "ゾロ"}


def test_popular_name_word_match_not_substring():
    assert T.is_popular_name("Snorlax", "", "", EN, JA)
    assert T.is_popular_name("Mew ex", "", "", EN, JA)
    assert not T.is_popular_name("Mewtwo", "ミュウツー", "", {"MEW"}, set())
    assert T.is_popular_name("Monkey D. Luffy", "", "", EN, JA)


def test_title_fallback_only_when_card_unknown_and_3chars():
    assert T.is_popular_name("", "", "【PSA10】カビゴン 何か", EN, JA)
    assert not T.is_popular_name("", "", "PSA10 ゾロアーク", EN, JA)      # 2文字の「ゾロ」は使わない
    assert not T.is_popular_name("Zekrom", "ゼクロム", "カビゴン と書いてある", EN, JA)


def test_title_card_key_groups_same_card():
    assert T.title_card_key("PSA10 ブラッキーVMAX 101/184 RRR") == T.title_card_key("ブラッキー 101 / 184 PSA10")
    assert T.title_card_key("【PSA10】ウタ P-011 プロモ") == "T:P-011"
    assert T.title_card_key("PSA10 メガディアンシーex ポケモンカード") == T.title_card_key("PSA10　メガディアンシーex　ポケモンカード")


def _pop(pop, known, card):
    f = lambda c: c in pop   # noqa: E731
    f.known = lambda c: c in known
    f.card_of = card.get
    return f


def test_order_known_then_popular_then_cheap_and_one_per_card():
    certs = ["u1", "k_pop_hi", "k_plain_lo", "k_pop_lo", "k_pop_lo_dup"]
    tm = {c: "ポケモン PSA10" for c in certs}
    cost = {"u1": 100, "k_pop_hi": 9000, "k_plain_lo": 500, "k_pop_lo": 3000, "k_pop_lo_dup": 2000}
    card = {"u1": "T:X", "k_pop_hi": "A-001", "k_plain_lo": "B-001", "k_pop_lo": "C-001", "k_pop_lo_dup": "C-001"}
    f = _pop({"u1", "k_pop_hi", "k_pop_lo", "k_pop_lo_dup"}, {"k_pop_hi", "k_plain_lo", "k_pop_lo", "k_pop_lo_dup"}, card)
    got = T.balanced_sample(certs, tm, 4, shuffle=NOSHUFFLE, cost_of=cost.get, popular_of=f, explore=0)
    assert got == ["k_pop_lo_dup", "k_pop_hi", "k_plain_lo", "u1"], got


def test_psa_to_csv_uses_popular_order():
    src = open(os.path.join(_ROOT, "iMakTCG", "psa_to_csv.py"), encoding="utf-8").read()
    assert "popular_of=build_popular_of(cert_numbers, mercari_title_map)" in src
    assert "cost_of=cost_map.get" in src
