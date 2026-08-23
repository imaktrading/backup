# -*- coding: utf-8 -*-
"""1文字で終わるタイトルを、名前なのか欠けなのかで分ける (2026-08-23)。

## 何が起きたか
2026-08-23 11:57 の走行で
`PSA 10 Pokemon Japanese 25th Anniversary Collection #023/028 Flying Pikachu V`
が「タイトルが1文字'V'で終わっている (末尾が欠けた疑い)」で **出品除外**された。
V まで含めて **カードの名前** (Pikachu V / Charizard V / Aegislash V) なので、欠けていない。

## 元のルールが正しい場面もある
ドラゴンボール FB01-071 は catalog の生値 `L★` が変換されずに入り、★が落ちて
`... Son Gohan : Childhood L` になっていた。これは本当に壊れている。

## 分け方
カタログの名前 (C:Card Name / C:Character) の末尾がその1文字なら **名前**。
一致しなければ従来どおり欠けを疑う。実測 605タイトル中 8件が1文字終わりで、
内訳は V が4件 (名前・出してよい) / L が4件 (欠け・止めるべき)。
"""
import os
import sys

import pytest

_TCG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakTCG")
if _TCG not in sys.path:
    sys.path.insert(0, _TCG)


@pytest.fixture()
def C():
    import check_csv
    check_csv.HEADER_MAP = {"*Title": 0, "C:Card Name": 1, "C:Character": 2,
                            "C:Rarity": 3, "C:Card Type": 4, "C:Features": 5}
    return check_csv


def _issues(C, title, name, char="", rarity=""):
    row = [title, name, char, rarity, "", ""]
    return [m for _s, m in C.specifics_sanity_issues(row, title) if "タイトルが1文字" in m]


def test_pokemon_v_is_a_name_not_a_truncation(C):
    """★今回の実害。V はカード名の一部。"""
    assert _issues(C, "PSA 10 Pokemon Japanese 25th Anniversary Collection #023/028 Flying Pikachu V",
                   "Flying Pikachu V", "Flying Pikachu V") == []


@pytest.mark.parametrize("name", ["Charizard V", "Aegislash V", "Pikachu V"])
def test_other_v_cards(C, name):
    assert _issues(C, f"PSA 10 Pokemon Japanese Something #001/100 {name}", name) == []


def test_truncated_rarity_is_still_caught(C):
    """`L★` の★が落ちて末尾が L になった本物の欠けは、これまでどおり止める。"""
    got = _issues(C, "PSA 10 Dragon Ball Japanese Awakened Pulse #FB01-071 Son Gohan : Childhood L",
                  "Son Gohan : Childhood", rarity="L")
    assert got and "末尾が欠けた疑い" in got[0]


def test_letter_must_match_the_name_tail(C):
    """名前に1文字の語があっても、末尾の文字が違えば見逃さない。"""
    got = _issues(C, "PSA 10 Pokemon Japanese Something #001/100 Pikachu L", "Pikachu V")
    assert got, "名前は V なのに末尾 L。これは欠けとして止めるべき"


def test_normal_titles_are_silent(C):
    assert _issues(C, "PSA 10 Pokemon Japanese Sv1s: Scarlet Ex #093/078 Great Tusk ex Super Rare",
                   "Great Tusk Ex") == []
