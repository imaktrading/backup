# -*- coding: utf-8 -*-
"""cache に焼かれた「番号未確認」候補も落とす (2026-09-20)。

ユーザー「何十回も出てくるでって、指摘して直したんちゃうの？何で直ってないの？」。
生成側 (`should_offer_loose`) は直したが、**既に cache に在る分**を洗っていなかったため、
目視画面には出続けていた。実測: 83出品 / 392本。
例: 820041238874 (EB02-003 = 多変種) の m58955733903。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(r"C:\dev\iMak\iMakHQ", "tools"))

import purge_loose_on_multivariant as P  # noqa: E402


class _MP:
    @staticmethod
    def split_key(key):
        return key.split(":", 1) if ":" in key else ("", key)

    @staticmethod
    def _is_multi_variant(cno, cat):
        return cno == "EB02-003"


class _Hoju:
    @staticmethod
    def _card_no_from_key(key):
        return key.split(":")[-1]


def _cache(loose):
    return {"820041238874": {"mercari": {"loose_cands": loose}},
            "999": {"mercari": {"loose_cands": [("x",)]}}}


def test_多変種の出品だけを落とす():
    keymap = {"820041238874": "one_piece_tcg:EB02-003", "999": "one_piece_tcg:OP01-001"}
    tg = P.targets(_cache([("a",), ("b",)]), keymap, _MP, _Hoju())
    assert tg == [("820041238874", 2)], tg


def test_候補が無ければ対象にしない():
    keymap = {"820041238874": "one_piece_tcg:EB02-003"}
    assert P.targets(_cache([]), keymap, _MP, _Hoju()) == []


def test_KEYが無い出品は触らない():
    """どのカードか分からない物を勝手に消さない (fail-closed)。"""
    assert P.targets(_cache([("a",)]), {}, _MP, _Hoju()) == []
