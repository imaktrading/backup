# -*- coding: utf-8 -*-
"""早く落とすほど仕入元が痩せる、を防ぐ (2026-08-18).

KEY(AI列) を書く処理は **その日のCSVに載った行** しか見ない。
枠を選ぶ前に重複を落とすと、その行の KEY は永久に空のまま残る。
KEY が空だと補URL追記 (hoju_url_from_dupes) が拾えないので、
**同じカードの生きた仕入元を1本捨てる**ことになる。

実測 2026-08-18 (同じ「重複」なのに扱いが割れていた):
    前段で落ちた cert153574704 → 行 1357 の KEY は空のまま = 補URLに回らない
    後段で落ちた5件           → KEY が入り、補URL候補になっていた

夜間の PSA 先貯めで前段の除外が増えるので、ここを塞がないと **供給を痩せさせる方向**に効く。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from psa_to_csv import _keys_for_dropped_dupes  # noqa: E402

HEADER = ["h"] * 40


def _row(cert="", key=""):
    r = [""] * 40
    r[8], r[34] = cert, key
    return r


CLS = {
    "111": {"category": "one_piece_tcg", "product_id": "ST30-001"},
    "222": {"category": "pokemon_tcg", "product_id": "SV1V-102"},
    "333": {},                                   # product_id を引けない
}


class TestKeyIsWrittenBeforeDropping:
    def test_writes_key_for_dropped_dupe(self):
        vals = [HEADER, _row("111"), _row("999")]
        rows, keys = _keys_for_dropped_dupes(vals, ["111"], CLS)
        assert rows == {"111": 2}
        assert keys == {"111": "one_piece_tcg:ST30-001"}

    def test_does_not_overwrite_an_existing_key(self):
        """人が確定した値を上書きしない."""
        vals = [HEADER, _row("111", "one_piece_tcg:ST30-001_p2")]
        assert _keys_for_dropped_dupes(vals, ["111"], CLS) == ({}, {})

    def test_unresolvable_cert_is_not_guessed(self):
        vals = [HEADER, _row("333")]
        assert _keys_for_dropped_dupes(vals, ["333"], CLS) == ({}, {})

    def test_cert_not_in_sheet_is_skipped(self):
        vals = [HEADER, _row("999")]
        assert _keys_for_dropped_dupes(vals, ["111"], CLS) == ({}, {})

    def test_multiple_certs(self):
        vals = [HEADER, _row("111"), _row("222"), _row("333")]
        rows, keys = _keys_for_dropped_dupes(vals, ["111", "222", "333"], CLS)
        assert set(keys) == {"111", "222"} and rows["222"] == 3

    def test_empty_inputs_are_safe(self):
        assert _keys_for_dropped_dupes([HEADER], [], {}) == ({}, {})
        assert _keys_for_dropped_dupes([HEADER], ["111"], None) == ({}, {})


class TestWiredIntoThePreflight:
    def test_preflight_writes_keys_before_dropping(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "psa_to_csv.py"), encoding="utf-8").read()
        i = src.index('_drop["LIVE-DUP"] = _dup')
        block = src[i:i + 1200]
        assert "_keys_for_dropped_dupes(" in block and "_si.write_keys(" in block, \
            "前段で落とす分の KEY を書かないと、補URL に回らず仕入元を捨てる"
