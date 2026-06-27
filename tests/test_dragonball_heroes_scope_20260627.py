# -*- coding: utf-8 -*-
"""Dragon Ball Heroes 誤カテゴリ 回帰テスト (2026-06-27 K4)。

バグ: detect_game_info の "DRAGON BALL" 総称分岐が Super Dragon Ball Heroes(アーケード)も
Dragon Ball Super Card Game(SCG) に誤分類 → catalog(SCG専用)に無く missing_models を汚染
(seen×3 で再発)。Heroes は専用 franchise を返し、build_row で fail-closed skip させる。
(pre-commit が collect する tests/ に配置)
"""
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_ROOT, "iMakTCG"))

import psa_to_csv as pc  # noqa: E402


def test_heroes_is_out_of_scope_franchise():
    """Heroes は SCG でなく専用 franchise 'Dragon Ball Heroes' に分類される。"""
    for brand in [
        "DRAGON BALL HEROES GALAXY MISSION 10",
        "DRAGON BALL HEROES GOD MISSION 1",
        "SUPER DRAGON BALL HEROES BIG BANG MISSION",
    ]:
        game, _set, franchise = pc.detect_game_info(brand)
        assert franchise == "Dragon Ball Heroes", f"{brand} → {franchise}"
        assert game == "Dragon Ball Heroes"   # SCG に倒れない


def test_real_scg_still_classified_as_scg():
    """正規 Dragon Ball Super Card Game は従来通り SCG(回帰なし)。"""
    game, short_set, franchise = pc.detect_game_info(
        "DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE BLAZING AURA")
    assert game == "Dragon Ball Super Card Game"
    assert franchise == "Dragon Ball"
    assert short_set == "Blazing Aura"

    # Divers Advance Pack 40th (今回の本物欠落カード)も SCG 側
    game2, _s2, fr2 = pc.detect_game_info(
        "DRAGON BALL SUPER DIVERS ADVANCE PACK DRAGON BALL 40TH ANNIVERSARY EDITION")
    assert fr2 == "Dragon Ball" and game2 == "Dragon Ball Super Card Game"


def test_pokemon_black_deck_kit_out_of_scope():
    """K2: Black Deck Kit (e-card期・catalog0件) は out-of-scope。XY期は対象外にしない。"""
    assert pc.pokemon_out_of_scope("Pokemon", "POKEMON JAPANESE BLACK DECK KIT") is True
    # XY期は catalog に173件あるので除外しない(K3不採用=出せるカードを殺さない)
    assert pc.pokemon_out_of_scope("Pokemon", "POKEMON JAPANESE XY BLUE SHOCK") is False
    # 他 franchise は無関係
    assert pc.pokemon_out_of_scope("One Piece", "BLACK DECK KIT") is False
