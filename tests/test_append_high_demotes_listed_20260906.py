# -*- coding: utf-8 -*-
"""既に出品中のカードは、証明番号を聞く前に 用途=補URL へ落とす (2026-09-06)。

実害 (2026-09-06 の走行): 「用途=出品 で未転記 19件」と出た画面で人が証明番号を
**16件 打ち込んだのに、全部「同じカードが既に出品中」で捨てられ、追加0件**。
しかも印が付かないので次回また同じ16件が出る = 押しても減らないボタン。
用途は台帳に積んだ時点の判定なので、後からそのカードが出品されると古くなる。
2枚目を出さないのは正しいが、**仕入元としては使える**ので補URLに回す (捨てない)。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools")))

import newcand_confirm as nc   # noqa: E402


def _it(i, key):
    return {"i": i, "key": key, "url": f"https://jp.mercari.com/item/m{i}",
            "title": f"PSA10 card {i}", "price": 1000, "pid": key.split(":")[-1]}


def test_listed_cards_are_demoted_not_shown():
    items = [_it(0, "one_piece_tcg:OP01-001"),
             _it(1, "pokemon_tcg:SV8a-220"),
             _it(2, "one_piece_tcg:OP02-004_p2")]
    keep, demoted = nc.demote_listed_to_aux(
        items, {"pokemon_tcg:SV8a-220", "one_piece_tcg:OP02-004_p2"})
    assert [it["i"] for it in keep] == [0]
    assert demoted == {1, 2}


def test_nothing_demoted_when_nothing_listed():
    items = [_it(0, "one_piece_tcg:OP01-001")]
    keep, demoted = nc.demote_listed_to_aux(items, set())
    assert keep == items and demoted == set()


def test_rows_without_key_are_kept():
    """KEY が無い行は判定材料が無い → 落とさない (人に見せる。fail-closed)。"""
    items = [_it(0, "")]
    keep, demoted = nc.demote_listed_to_aux(items, {"one_piece_tcg:OP01-001"})
    assert keep == items and demoted == set()


def test_blank_listed_keys_are_ignored():
    """空文字が listed に混ざっても、KEY 空の行を巻き込まない。"""
    items = [_it(0, "one_piece_tcg:OP01-001")]
    keep, demoted = nc.demote_listed_to_aux(items, {"", "   "})
    assert keep == items and demoted == set()


def test_demoted_value_is_the_aux_use_label():
    """落とし先は 用途=補URL(2枚目以降)。別の文字列にすると夜間が拾わない。"""
    assert nc.USE_AUX and nc.USE_AUX != nc.USE_LIST
