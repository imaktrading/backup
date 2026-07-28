"""PSA ラベル由来 finish の回帰テスト (2026-07-28).

「間違うと事故になるから入れない」方針で C:Finish は空欄運用だった。
ラベル明記(PSA が現物を鑑定して打った一次情報)だけを転記する層のみ解禁する。
守るべき性質:
  1. 明記が無ければ空 (推測しない = 従来の安全側を崩さない)
  2. Holo と Reverse Holo を取り違えない (別物・価格も違う。SNAD 直結)
  3. セット名(SHINY STAR V 等)を finish と誤認しない
"""
import os
import sys

sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "iMakTCG")))

from psa_label_finish import finish_from_psa_label as f  # noqa: E402


def test_holo_forms():
    assert f("SNORLAX-HOLO") == "Holo"
    assert f("NAMI HOLOFOIL") == "Holo"
    assert f("LILLIE-HOLO SKY LEGEND") == "Holo"


def test_reverse_is_not_confused_with_holo_or_foil():
    """'REV.FOIL' を FOIL で拾うと Reverse Holo が Foil になる(実在ラベル)。"""
    assert f("HO-OH-REV.FOIL 25TH ANNIVERSARY COLL.") == "Reverse Holo"
    assert f("CLEFAIRY MASTER BALL REVERSE HOLO") == "Reverse Holo"
    assert f("TEAM ROCKET'S GOLBAT TEAM ROCKET REVERSE HOLO") == "Reverse Holo"
    assert f("PIKACHU REVERSE FOIL") == "Reverse Holo"


def test_foil_forms():
    assert f("MONKEY D. LUFFY SPARKLE FOIL") == "Foil"


def test_no_marking_returns_empty():
    """明記が無ければ空。ここが崩れると推測で埋まり事故になる。"""
    for s in ("PIKACHU VMAX", "CHARIZARD EX", "", None, "   "):
        assert f(s) == ""


def test_set_names_are_not_treated_as_finish():
    """'SHINY STAR V' はセット名。finish ではない。"""
    assert f("PIKACHU SHINY STAR V") == ""
    assert f("GENGAR-HOLO SHINY STAR V") == "Holo"   # こちらは -HOLO が根拠


def test_does_not_match_inside_other_words():
    """HOLOGRAM / FOILED 等の部分一致で誤検出しない。"""
    assert f("SOMETHING HOLOGRAM CARD") == ""
    assert f("FOILED AGAIN") == ""
