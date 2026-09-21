# -*- coding: utf-8 -*-
"""タイトルの `Gem Mint` は禁止語にしない (2026-09-21)。

9/20 のユーザー指示で、生成側がタイトルの余った枠を `Gem Mint` で埋める。
監査の禁止語 `mint` を直し忘れていて、9/21 の入稿で3件が除外された。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import check_csv as C  # noqa: E402


def test_GemMintは通す():
    t = "PSA 10 Pokemon Japanese Sm9: Tag Bolt #073/095 Farfetch'd Common 2018 Gem Mint"
    assert C._banned_title_words_in(t, C.BANNED_TITLE_WORDS) == []


def test_NearMintとMint単独は弾く():
    assert "mint" in C._banned_title_words_in("PSA 10 Pikachu Near Mint", C.BANNED_TITLE_WORDS)
    assert "mint" in C._banned_title_words_in("PSA 10 Pikachu Mint Card", C.BANNED_TITLE_WORDS)


def test_GemMTは弾く():
    assert C._banned_title_words_in("PSA 10 Pikachu GEM MT", C.BANNED_TITLE_WORDS) == ["gem mt"]
