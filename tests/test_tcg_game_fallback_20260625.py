# -*- coding: utf-8 -*-
"""TCG タイトルのゲーム語落ち 回帰テスト (2026-06-25)。

XY-140 Hex Maniac: catalog game_ebay=None → C:Game 空 → タイトルに 'Pokemon' が入らない
(最終C:Gameは別経路で埋まるので不整合)。catalog 空の時のみ game_hint(row/PSAのC:Game)を
C:Game に補完し、タイトルにゲーム語を残す。(pre-commit が collect する tests/ に配置)
"""
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_ROOT, "iMakTCG"))
sys.path.insert(0, os.path.join(_ROOT, "iMakeBayAPI"))

import tcg_listing_fields as lf  # noqa: E402


def test_fill_game_fallback_only_when_empty():
    assert lf._fill_game_fallback({"C:Game": ""}, "Pokémon TCG")["C:Game"] == "Pokémon TCG"
    assert lf._fill_game_fallback({"C:Game": ""}, "")["C:Game"] == ""       # hint も空 → 空のまま
    # 既に catalog 値がある時は上書きしない
    assert lf._fill_game_fallback({"C:Game": "One Piece Card Game"}, "Pokémon TCG")["C:Game"] == "One Piece Card Game"


def test_title_keeps_game_word_after_fallback():
    """C:Game が(fallbackで)埋まればタイトルに Pokemon が入る。空だと落ちる(=fixの必要性)。"""
    base = {"C:Game": "Pokémon TCG", "C:Language": "Japanese", "C:Set": "The Best of XY",
            "C:Card Number": "140/171", "C:Character": "Hex Maniac"}
    t = lf.build_title_from_fields(base, grade="10")
    assert "Pokemon" in t

    empty = dict(base); empty["C:Game"] = ""
    assert "Pokemon" not in lf.build_title_from_fields(empty, grade="10")   # 空だと落ちる(fixが防ぐ)
