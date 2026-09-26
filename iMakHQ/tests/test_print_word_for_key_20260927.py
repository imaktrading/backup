"""補URL の検索語に、KEY の版 (パラレル / SP) を足す (2026-09-27)。

EB04-007_p1 (パラレル) を「PSA10 ロロノア・ゾロ EB04-007」で探し、通常版しか候補に出なかった。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from mercari_psa_resource import print_word_for_key  # noqa: E402


def test_one_piece_parallel_and_sp():
    assert print_word_for_key("one_piece_tcg:EB04-007_p1", ["event", "SR"]) == "パラレル"
    assert print_word_for_key("one_piece_tcg:EB04-007_p2", ["", "SPカード"]) == "SP"


def test_normal_dummy_and_other_games_add_nothing():
    assert print_word_for_key("one_piece_tcg:EB04-007", ["SR"]) == ""
    assert print_word_for_key("one_piece_tcg:EB04-007_OP17_SP_Zoro_dummy", []) == ""
    assert print_word_for_key("pokemon_tcg:SV2a-172", ["AR"]) == ""
    assert print_word_for_key("", []) == ""


def test_set_name_starting_with_sp_is_not_rarity():
    assert print_word_for_key("one_piece_tcg:P-001_p1", ["SPECIAL GOODS SET", "P"]) == "パラレル"


def test_snkrdunk_reads_parallel_from_hint():
    import snkrdunk_psa_resource as sp
    assert sp._print_signal(["event", "SR", "パラレル"]) == "P"
    assert sp._print_signal(["event", "SR"]) == ""
