# -*- coding: utf-8 -*-
"""新規に出せる PSA は「新しく出せるカードの種類」で数える (2026-10-15 ユーザー「意味不明な数字を出すな」)。

194枚 = 行 (現物) の数で、同じカードの2枚目や、別の鑑定番号で出品中のカードまで数えていた。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import psa_new_count as P  # noqa: E402

C = {"1": {"Brand": "POKEMON", "CardNumber": "083", "Subject": "RALTS", "Variety": "AR"},
     "2": {"Brand": "POKEMON", "CardNumber": "083", "Subject": "RALTS", "Variety": "AR"},
     "3": {"Brand": "POKEMON", "CardNumber": "089", "Subject": "MANECTRIC EX", "Variety": ""},
     "9": {"Brand": "POKEMON", "CardNumber": "089", "Subject": "MANECTRIC EX", "Variety": ""}}


def test_same_card_counts_once_and_listed_card_is_excluded():
    got = P.count_cards(["1", "2", "3", "7"], {"9"}, C)
    assert got == {"cards": 1, "dup_listed": 1, "unknown": 1}


def test_screen_shows_kinds_not_rows():
    js = open(os.path.join(os.path.dirname(__file__), "..", "console", "static", "app.js"), encoding="utf-8").read()
    assert "種類</b>" in js and "pn.cards" in js
