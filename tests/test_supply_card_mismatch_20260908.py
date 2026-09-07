# -*- coding: utf-8 -*-
"""仕入元が別カードになっている出品の検査 (2026-09-08)。

きっかけ: バイヤーの問い合わせで発覚。補URL に別カードの安い出品が入り、その値段が
「今の最安 ¥10,900」としてシートに載って $155.98 で出ていた (正しくは $405.98)。
**見た目では分からない**ので、値段の形で絞ってから商品名で確かめる。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools")))

import psa_hoju_fill as hf              # noqa: E402
import supply_card_mismatch as S        # noqa: E402

N = 40


def _row(iid="", cert="", cost="", key="", title="", sold="", url="", aux=(), cat="TCG"):
    r = [""] * N
    r[hf.B], r[hf.CERT], r[hf.KEY] = iid, cert, key
    r[0], r[2], r[3], r[13] = url, title, sold, cost
    r[S.CAT_COL] = cat
    for i, u in enumerate(aux):
        r[hf.AUX0 + i] = u
    return r


def _cache(iid, prices):
    return {iid: {"mercari": {"cands": [[p, f"https://x/{p}", "t"] for p in prices]}}}


def test_cheap_outlier_is_flagged():
    vals = [["h"] * N, _row("111", "c1", "10900", "pokemon_tcg:SV8a-092", "ブラッキー")]
    sus, st = S.find_suspects(vals, _cache("111", [33566, 48780]))
    assert st["compared"] == 1 and len(sus) == 1
    assert sus[0]["cost"] == 10900 and sus[0]["cheapest"] == 33566


def test_normal_price_is_not_flagged():
    vals = [["h"] * N, _row("111", "c1", "33566", "pokemon_tcg:SV8a-092", "ブラッキー")]
    sus, _ = S.find_suspects(vals, _cache("111", [33566, 48780]))
    assert sus == []


def test_sold_rows_are_skipped():
    """売り切れた行は出品されていない = 直す対象ではない。"""
    vals = [["h"] * N, _row("111", "c1", "1000", "k", "t", sold="○")]
    sus, st = S.find_suspects(vals, _cache("111", [50000]))
    assert sus == [] and st["compared"] == 0


def test_rows_without_known_prices_are_skipped():
    """番号一致の供給が1本も無い行は比べる相手が無い (推測で騒がない)。"""
    vals = [["h"] * N, _row("111", "c1", "1000", "k", "t")]
    sus, st = S.find_suspects(vals, {})
    assert sus == [] and st["compared"] == 0 and st["no_market"] == 1


def test_pokemon_collector_number_counts_as_match():
    """`090/071` と `SV2P-090` は同じカード。ここを見ないと一致を不一致と読む
    (2026-09-08 に実際4件 誤判定した)。"""
    assert S.number_matches("pokemon_tcg:SV2P-090", "090/071") is True


def test_plain_number_match_and_mismatch():
    assert S.number_matches("one_piece_tcg:OP03-122", "OP03-122") is True
    assert S.number_matches("one_piece_tcg:P-033", "OP07-033") is False


def test_variant_suffix_is_ignored_in_comparison():
    """KEY の `_p2` 等は版の違いで、番号としては同じ。"""
    assert S.number_matches("one_piece_tcg:OP03-001_p2", "OP03-001") is True


def test_unreadable_number_is_not_a_mismatch():
    """番号が読めない商品名は「不一致」と言わない (fail-closed)。"""
    assert S.number_matches("one_piece_tcg:ST22-001", "") is None


def test_only_psa_rows_are_checked():
    """PSA (R列='TCG') 以外は見ない (2026-09-08 ユーザー指示)。

    バッグの行が cert 欄に商品名を持っていて「cert 有り」を満たし、3件 紛れていた。
    """
    vals = [["h"] * N,
            _row("111", "c1", "1000", "k", "カード", cat="TCG"),
            _row("222", "商品名がcertに入っている", "1000", "k", "バッグ", cat="バッグ")]
    cache = {**_cache("111", [50000]), **_cache("222", [50000])}
    sus, st = S.find_suspects(vals, cache)
    assert st["listed"] == 1
    assert [x["itemID"] for x in sus] == ["111"]


def test_unchecked_rows_are_counted_not_hidden():
    """比べられなかった分を数える。隠すと『全部見た』と誤解される。"""
    vals = [["h"] * N,
            _row("111", "c1", "1000", "k", "a"),
            _row("222", "c2", "1000", "k", "b")]
    sus, st = S.find_suspects(vals, _cache("111", [50000]))
    assert st["listed"] == 2 and st["compared"] == 1 and st["no_market"] == 1
