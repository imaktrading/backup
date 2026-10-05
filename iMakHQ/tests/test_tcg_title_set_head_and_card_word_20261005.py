"""TCG タイトル (2026-10-05 ADV 依頼・ユーザー承認)。

① セット名を前から短くした候補が '&' 等のつなぎ語で始まらない
② 余った枠だけ `Card` をゲーム名の直後に入れる (ギリギリの行は変わらない・既に Card があれば足さない)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "iMakTCG"))
import tcg_listing_fields as T  # noqa: E402


def _f(**kw):
    base = {"C:Game": "Pokémon TCG", "C:Language": "Japanese"}
    base.update(kw)
    return base


def test_set_shorten_never_starts_with_ampersand():
    t = T.build_title_from_fields(_f(**{"C:Set": "Cp5: Mythical & Legendary Dream Shine Collection",
                                        "C:Card Number": "013/036", "C:Character": "Keldeo",
                                        "C:Year Manufactured": "2016"}))
    assert "Japanese & " not in t and "Legendary Dream Shine Collection" in t
    assert len(t) <= 80


def test_card_added_when_room():
    t = T.build_title_from_fields(_f(**{"C:Set": "The Best of XY", "C:Card Number": "044/171",
                                        "C:Character": "Mew", "C:Year Manufactured": "2017"}))
    assert t == "PSA 10 Pokemon Card Japanese The Best of XY #044/171 Mew 2017 Gem Mint"


def test_card_not_doubled_when_set_has_card():
    t = T.build_title_from_fields(_f(**{"C:Set": "Pokemon Card Game Classic", "C:Card Number": "001/032",
                                        "C:Character": "Pikachu"}))
    assert t.lower().split().count("card") == 1


def test_full_title_unchanged_no_room_for_card():
    f = _f(**{"C:Set": "Sv1s: Scarlet Ex", "C:Card Number": "099/078",
              "C:Character": "Professor's Research Extra Long Name Here", "C:Year Manufactured": "2023"})
    t = T.build_title_from_fields(f)
    assert len(t) <= 80
    if "Card" not in t.split():
        assert len(t) + len(" Card") > 80
