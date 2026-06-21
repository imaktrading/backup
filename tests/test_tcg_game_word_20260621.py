"""Regression: 2026-06-21 — タイトルからゲーム名が落ちる bug の是正。

catalog の C:Game が 'One Piece CCG' なのに _GAME_TITLE_WORD のキーは 'One Piece Card Game'
のみで照合空振り → タイトルに 'One Piece' が入らず 'PSA 10 Japanese ...' になっていた。
_game_word を完全一致→部分一致に頑健化。Pokemon 等の既存挙動は不変。
"""
import importlib.util
from pathlib import Path
import sys

_P = Path(__file__).resolve().parent.parent / "iMakTCG" / "tcg_listing_fields.py"
sys.path.insert(0, str(_P.parent))
_spec = importlib.util.spec_from_file_location("tcg_listing_fields_t", _P)
lf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lf)


def test_game_word_one_piece_variants():
    # bug 本体: 'One Piece CCG'(catalog実値)が落ちていた
    assert lf._game_word("One Piece CCG") == "One Piece"
    assert lf._game_word("One Piece Card Game") == "One Piece"


def test_game_word_existing_unchanged():
    # 既存マッピングは不変(回帰なし)
    assert lf._game_word("Pokémon TCG") == "Pokemon"
    assert lf._game_word("Pokemon TCG") == "Pokemon"
    assert lf._game_word("Gundam Card Game") == "Gundam"
    assert lf._game_word("Dragon Ball Super Card Game") == "Dragon Ball"


def test_game_word_unknown_empty():
    assert lf._game_word("") == ""
    assert lf._game_word("Weiss Schwarz") == ""   # 未対応ゲーム → 空(誤挿入しない)


def test_one_piece_title_includes_game():
    f = {"C:Game": "One Piece CCG", "C:Language": "Japanese",
         "C:Set": "Legacy of the Master", "C:Card Number": "OP09-037",
         "C:Character": "Lim", "C:Rarity": "Super Rare", "C:Year Manufactured": "2025"}
    title = lf.build_title_from_fields(f)
    assert "One Piece" in title          # ゲーム名が入る(bug 是正)
    assert "Lim" in title and "Legacy of the Master" in title
