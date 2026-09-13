# -*- coding: utf-8 -*-
"""セット名の中の Pokémon を消さない (2026-09-13)。

実害: `remove_redundant_pokemon` が前後にスペースのある Pokémon を全部消していたので、
セット名 `S10b: Pokémon GO` が `S10b: GO` になった。live で3件
(820121669220 Radiant Charizard / 820104169624 Snorlax / 820110211694 Eevee)。
消してよいのはカード種別の `Pokémon Card` だけ。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "tools"))

from post_title_fix import remove_redundant_pokemon  # noqa: E402


def test_set_name_pokemon_go_is_kept():
    t = "PSA 10 Pokemon Japanese S10b: Pokémon GO #011/071 Radiant Charizard Card 2022"
    new, changed = remove_redundant_pokemon(t)
    assert new == t and not changed
    assert "S10b: Pokémon GO" in new


def test_set_names_card_151_and_card_game_are_kept():
    for t in ("PSA 10 Pokemon Japanese Sv2a: Pokémon Card 151 #201/165 Mew ex",
              "PSA 10 Pokemon Japanese Pokémon Card Game Classic #007/032 Gyarados"):
        new, changed = remove_redundant_pokemon(t)
        assert new == t and not changed, t


def test_card_type_pokemon_card_is_still_removed():
    t = "PSA 10 Pokemon GO #011 Radiant Charizard Pokémon Card"
    new, changed = remove_redundant_pokemon(t)
    assert changed and new == "PSA 10 Pokemon GO #011 Radiant Charizard Card"
