# -*- coding: utf-8 -*-
"""需要表をカード単位で作る (2026-09-21)。

`demand_market.csv` は 2枚以上売れた83枚しか持っておらず、**市場の1割**しか見ずに
門を判定していた。台帳には676種類入っている。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(r"C:\dev\iMak\iMakHQ", "tools"))

import demand_table_build as D  # noqa: E402


def _row(t, qty, price, iid, day=""):
    return {"タイトル": t, "売れた数": qty, "平均落札": price, "itemId": iid,
            "最終落札日": day}


def test_番号を拾う():
    assert D.card_numbers("PSA10 Magikarp 080/073 AR sv1a") == ["080/073"]
    assert D.card_numbers("PSA 10 One Piece OP06-106 Hiyori") == ["OP06-106"]
    assert D.card_numbers("PSA10 Pikachu 126/S-P Promo") == ["126/S-P"]
    assert D.card_numbers("番号なし") == []


def test_同じカードを出品者ごとに畳む():
    out = D.build([_row("A 080/073 x", 3, "$100", "1"),
                   _row("B 080/073 y", 2, "$200", "2")])
    assert len(out) == 1
    r = out[0]
    assert r["売れた枚数"] == 5 and r["出品者数"] == 2
    assert r["実売最安"] == 100 and r["実売最高"] == 200
    assert r["価格分散"] == 2.0          # 門3: 最安でなくても買われる市場か


def test_最高値は門0の材料なので必ず出す():
    """自社価格がこれを超えていたら出さない、という判定に使う。"""
    out = D.build([_row("A OP06-106", 1, "$48", "1")])
    assert out[0]["実売最高"] == 48


def test_値段が読めない行でも枚数は数える():
    out = D.build([_row("A OP06-106", 2, "", "1")])
    assert out[0]["売れた枚数"] == 2 and out[0]["実売最高"] == ""


def test_ゲームを分ける():
    out = D.build([_row("PSA10 One Piece OP06-106", 1, "$10", "1")])
    assert out[0]["ゲーム"] == "one_piece_tcg"
