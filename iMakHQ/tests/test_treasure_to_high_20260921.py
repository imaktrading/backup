# -*- coding: utf-8 -*-
"""トレジャーの候補を HIGH に足す判定 (2026-09-21)。7万円以下・重複は足さない・KEY は書かない。"""
import os
import sys

sys.path.insert(0, os.path.join(r"C:\dev\iMak\iMakHQ", "tools"))

import treasure_to_high as TH  # noqa: E402


def _r(url, cert, price, key=""):
    r = [""] * 38
    r[0], r[8], r[5], r[34] = url, cert, price, key
    return r


def test_7万円以下だけ足す():
    add, _, n = TH.plan([_r("u1", "1", "70000"), _r("u2", "2", "70001")], [])
    assert [a[1][0] for a in add] == ["u1"] and n["over"] == 1


def test_HIGHに在る行は足さないが塗る():
    add, paint, n = TH.plan([_r("u1", "1", "5000"), _r("u2", "9", "5000")], [_r("u1", "", ""), _r("x", "9", "")])
    assert add == [] and paint == [2, 3] and n["in_high"] == 2


def test_タブ内の重複は1行だけ足す():
    add, paint, n = TH.plan([_r("u1", "1", "5000"), _r("u1", "1", "5000")], [])
    assert len(add) == 1 and paint == [2, 3] and n["dup_tab"] == 1


def test_KEYとitemIDは書かずカテゴリはTCG():
    add, _, _ = TH.plan([_r("u1", "1", "5000", key="pokemon_tcg:SV2a-173")], [])
    row = add[0][1]
    assert row[34] == "" and row[1] == "" and row[17] == "TCG"
    assert row[8] == "1" and row[5] == "5000"          # 鑑定番号と仕入値は入れる
    assert row[12] == "" and row[13] == "" and row[15] == ""   # M / N / P は書かない
