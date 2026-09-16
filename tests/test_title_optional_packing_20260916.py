# -*- coding: utf-8 -*-
"""タイトルの任意要素は「入る物だけ拾う」(2026-09-16)。

実害 (2026-09-16 の走行): 16件中 **7件が70字未満**、平均 74字 → 70.9字に落ち、
監査が「キーワード不足」を9件指摘した。原因は 任意要素 (Rarity / Features / Year) を
**末尾からまとめて捨てる** 作りで、1つ長い要素があると その後ろの短い要素まで道連れになっていた:

  本体 64字 + Rarity 'Special Art Rare' (17) = 81字 → 1字超過
  → Rarity も Year も捨てて **64字** で確定 (Year '2024' だけなら 69字で入る)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "iMakTCG"))

import tcg_listing_fields as T  # noqa: E402

SV8A = {"C:Game": "Pokémon TCG", "C:Language": "Japanese", "C:Set": "Sv8a: Terastal Fest Ex",
        "C:Card Number": "223/187", "C:Character": "Eevee ex", "C:Rarity": "Special Art Rare",
        "C:Features": "Special Art", "C:Year Manufactured": "2024"}


def test_short_optional_is_kept_when_a_long_one_does_not_fit():
    t = T.build_title_from_fields(SV8A)
    assert t.endswith("2024"), t              # 長い Rarity は入らないが Year は入る
    assert 65 <= len(t) <= T._TITLE_MAX, len(t)


def test_everything_fits_is_unchanged():
    """全部収まる普通のケースは今までどおり (Rarity も Year も入る)。"""
    f = dict(SV8A, **{"C:Set": "Sv5k: Wild Force", "C:Card Number": "074/071",
                      "C:Character": "Bronzor", "C:Rarity": "Art Rare", "C:Features": ""})
    t = T.build_title_from_fields(f)
    assert "Art Rare" in t and t.endswith("2024") and len(t) <= T._TITLE_MAX


def test_core_is_never_cut_for_an_optional():
    """同定に要る語 (Set/番号/キャラ/Japanese/PSA10) は落とさない。"""
    t = T.build_title_from_fields(SV8A)
    for must in ("PSA 10", "Japanese", "#223/187", "Eevee ex"):
        assert must in t, must


def test_a_word_that_is_already_there_is_not_added_again():
    """3文字以下でも「全部すでに出ている」語は足さない (2026-09-16 ユーザー指摘)。

    実例: Rarity 'Art Rare' を足した後に Features 'Art' が通り、
    「… Bronzor Art Rare Art 2024」になっていた (重複チェックが4文字以上しか見ていなかった)。
    """
    f = {"C:Game": "Pokémon TCG", "C:Language": "Japanese", "C:Set": "Sv5k: Wild Force",
         "C:Card Number": "074/071", "C:Character": "Bronzor", "C:Rarity": "Art Rare",
         "C:Features": "Art", "C:Year Manufactured": "2024"}
    t = T.build_title_from_fields(f)
    assert t.lower().split().count("art") == 1, t                       # Art は1回だけ
    assert "Art Rare" in t and t.endswith("2024")


def test_a_new_word_is_still_added_even_if_part_overlaps():
    """一部だけ被る物 (Art Rare) は今までどおり足す — 'rare' は新しい語。"""
    f = {"C:Game": "Pokémon TCG", "C:Language": "Japanese", "C:Set": "Sv5k: Art Collection",
         "C:Card Number": "074/071", "C:Character": "Bronzor", "C:Rarity": "Art Rare",
         "C:Features": "", "C:Year Manufactured": "2024"}
    assert "Rare" in T.build_title_from_fields(f)


def test_character_inside_the_set_name_is_not_repeated():
    """キャラ名がセット名に丸ごと入っている時は出さない (2026-09-16 ユーザー「１。再発もしないように」)。

    実害: 「Starter Deck Frieza #FS04-01 **Frieza** Leader 2025」
          「Wish for Shenron #FB07-097 **Shenron** Leader」
    と同じ語が2回出て、監査が「タイトル内で重複」と指摘していた。
    名前はセット名の中に残るので同定は落ちない。空いた分はレアリティ/年号が埋める。
    """
    f = {"C:Game": "Dragon Ball Super CCG", "C:Language": "Japanese",
         "C:Set": "Starter Deck Frieza", "C:Card Number": "FS04-01", "C:Character": "Frieza",
         "C:Rarity": "Leader", "C:Year Manufactured": "2025"}
    t = T.build_title_from_fields(f)
    assert t.lower().split().count("frieza") == 1, t
    assert "Starter Deck Frieza" in t and "#FS04-01" in t          # 同定語は残る
    assert "Leader" in t and t.endswith("2025")                    # 空いた分に入る

    g = dict(f, **{"C:Set": "Wish for Shenron", "C:Card Number": "FB07-097", "C:Character": "Shenron"})
    assert T.build_title_from_fields(g).lower().split().count("shenron") == 1


def test_partly_overlapping_character_is_kept():
    """一部だけ被る物は今までどおり出す (Set 'Mega Brave' + Chara 'Mega Venusaur')。"""
    f = {"C:Game": "Pokémon TCG", "C:Language": "Japanese", "C:Set": "Mega Brave",
         "C:Card Number": "001/100", "C:Character": "Mega Venusaur",
         "C:Rarity": "Double Rare", "C:Year Manufactured": "2025"}
    t = T.build_title_from_fields(f)
    assert "Mega Brave" in t and "Mega Venusaur" in t


def test_character_is_kept_when_there_is_no_set():
    f = {"C:Game": "Pokémon TCG", "C:Language": "Japanese", "C:Set": "",
         "C:Card Number": "001/100", "C:Character": "Pikachu"}
    assert "Pikachu" in T.build_title_from_fields(f)


def test_game_word_inside_the_set_name_is_not_repeated():
    """ゲーム名がセット名に入っているなら2回出さない (2026-09-16)。

    実害: 「Pokemon Japanese **Pokemon** Card Game Classic」「Sv2a: **Pokemon** Card 151」。
    直近12本のCSV 119タイトル中 7件が語の重複で、うち3件がこの形だった。
    """
    f = {"C:Game": "Pokémon TCG", "C:Language": "Japanese", "C:Set": "Pokemon Card Game Classic",
         "C:Card Number": "007/032", "C:Character": "Gyarados", "C:Year Manufactured": "2023"}
    t = T.build_title_from_fields(f)
    assert t.lower().split().count("pokemon") == 1, t
    assert "Pokemon Card Game Classic" in t and "Gyarados" in t


def test_punctuation_does_not_hide_a_duplicate():
    """記号違いでも同じ語とみなす (Set 'Monkey D Luffy' と Chara 'Monkey D. Luffy')。"""
    f = {"C:Game": "One Piece TCG", "C:Language": "Japanese", "C:Set": "Monkey D Luffy",
         "C:Card Number": "P-110", "C:Character": "Monkey D. Luffy", "C:Features": "Promo",
         "C:Year Manufactured": "2022"}
    t = T.build_title_from_fields(f)
    assert t.lower().split().count("luffy") == 1, t


def test_a_meaningful_difference_is_kept():
    """'Gengar V' と 'Gengar VMAX' は別物なので両方残す (消すと同定が壊れる)。"""
    f = {"C:Game": "Pokémon TCG", "C:Language": "Japanese", "C:Set": "Gengar VMAX High Class Deck",
         "C:Card Number": "001/019", "C:Character": "Gengar V", "C:Year Manufactured": "2020"}
    t = T.build_title_from_fields(f)
    assert "Gengar VMAX High Class Deck" in t and t.rstrip().endswith("2020")
    assert "Gengar V " in t or t.count("Gengar V") >= 1
