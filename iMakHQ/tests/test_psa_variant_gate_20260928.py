# -*- coding: utf-8 -*-
"""PSA ラベルの刷りと KEY を突き合わせる (2026-09-28)。

9/27〜28 の自動出品で 8件が別の刷りで出た (全部 手で Revise)。ユーザー
「毎回毎回、修正用CSVの対応になっているけど」「修正しないように作ればいいだけでは？」
"""
import os
import sys

import pytest

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import psa_variant_gate as G  # noqa: E402

OP = "one_piece_tcg"


def row(pid, set_text="", vt=None, fe=None, rarity=""):
    return {"product_id": pid, "set_name": set_text, "set_name_official": "",
            "specs": {"variant_type": vt, "features_ebay": fe, "rarity": rarity}}


def test_set_code_from_brand():
    assert G.op_set_code("ONE PIECE JAPANESE PRB01-PREMIUM BOOSTER -ONE PIECE CARD THE BEST-") == "PRB01"
    assert G.op_set_code("ONE PIECE JAPANESE OP09-EMPERORS IN THE NEW WORLD") == "OP09"
    assert G.op_set_code("ONE PIECE JAPANESE PROMOS") == ""


def test_prb01_slab_rejects_op05_row():
    r = row("OP05-119", "BOOSTER PACK -AWAKENING OF THE NEW ERA- [OP-05]")
    assert G.conflict(OP, "ONE PIECE JAPANESE PRB01-PREMIUM BOOSTER", "MONKEY D. LUFFY", r)


def test_alt_art_slab_rejects_base_row():
    r = row("OP01-070_OP-01", "ROMANCE DAWN【OP-01】", rarity="SR")
    assert G.conflict(OP, "ONE PIECE JAPANESE OP01-ROMANCE DAWN", "DRACULE MIHAWK ALTERNATE ART", r)
    ok = row("OP01-070_p1", "ROMANCE DAWN【OP-01】", vt="alt_art", fe="Alternative Art", rarity="SR")
    assert not G.conflict(OP, "ONE PIECE JAPANESE OP01-ROMANCE DAWN", "DRACULE MIHAWK ALTERNATE ART", ok)


def test_wanted_needs_sp_row():
    b = "ONE PIECE JAPANESE OP09-EMPERORS IN THE NEW WORLD"
    alt = row("OP09-051_p1", "新たなる皇帝【OP-09】", vt="alt_art", fe="Alternative Art", rarity="R")
    sp = row("OP09-051_p3", "新たなる皇帝【OP-09】", vt="alt_art", fe="Alternative Art", rarity="SPカード")
    assert G.conflict(OP, b, "BUGGY WANTED ALTERNATE ART", alt)
    assert not G.conflict(OP, b, "BUGGY WANTED ALTERNATE ART", sp)
    assert G.conflict(OP, b, "BUGGY ALTERNATE ART", sp)


def test_mirror_pokemon_is_not_the_base_row():
    r = row("SV2a-008")
    assert G.conflict("pokemon_tcg", "POKEMON JAPANESE SV2A-POKEMON CARD 151",
                      "WARTORTLE MASTER BALL REVERSE HOLO", r)
    assert not G.conflict("pokemon_tcg", "POKEMON JAPANESE M2A-MEGA DREAM EX",
                          "MEGA FROSLASS EX MEGA ATTACK", row("M2a-224"))


def test_promo_and_anniversary_are_left_alone():
    # 人が選んだ正しい答えを消しかけた (PSA は刷りの印を書かない / Brand は元のセット)
    promo_row = row("ST01-007_P_win", "Promotion Card", vt="promo", fe="Promo")
    assert not G.conflict(OP, "ONE PIECE JAPANESE STARTER DECK ST01-STRAW HAT CREW",
                          "NAMI STANDARD BATTLE WINNER", promo_row)
    assert not G.conflict(OP, "ONE PIECE JAPANESE 3RD ANNIVERSARY SET", "CHARLOTTE KATAKURI",
                          row("OP11-067_p3", "", vt="alt_art", fe="Alternative Art"))
    assert not G.conflict(OP, "ONE PIECE JAPANESE PROMOS", "BUGGY SAIKYO JUMP-MAY SP PACK",
                          row("ST17-003_P", "Promotion Card", vt="promo"))


def test_lowercase_p_is_parallel_uppercase_p_is_promo():
    assert G.row_is_alt(row("OP05-119_PRB01_2_p"))
    assert not G.row_is_alt(row("EB02-010_P"))


@pytest.mark.skipif(not os.path.exists(G.CATALOG_DB), reason="catalog DB が無い環境")
def test_pick_fixes_or_refuses_the_8_cases():
    b01 = "ONE PIECE JAPANESE OP01-ROMANCE DAWN"
    assert G.pick(OP, b01, "DRACULE MIHAWK ALTERNATE ART", "OP01-070_OP-01")[0] == "OP01-070_p1"
    b09 = "ONE PIECE JAPANESE OP09-EMPERORS IN THE NEW WORLD"
    assert G.pick(OP, b09, "BUGGY WANTED ALTERNATE ART", "OP09-051")[0] == "OP09-051_p3"
    assert G.pick(OP, "ONE PIECE JAPANESE EB04-EXTRA BOOSTER EGGHEAD CRISIS",
                  "MONKEY D. LUFFY ALTERNATE ART", "EB04-061_p2")[0] == "EB04-061_p1"
    # PRB01 の通常版は PSA ラベルから決めきれない (公式に2つ) → 出さない
    assert G.pick(OP, "ONE PIECE JAPANESE PRB01-PREMIUM BOOSTER -ONE PIECE CARD THE BEST-",
                  "MONKEY D. LUFFY", "OP05-119")[0] == ""
    assert G.pick("pokemon_tcg", "POKEMON JAPANESE SV2A-POKEMON CARD 151",
                  "WARTORTLE MASTER BALL REVERSE HOLO", "SV2a-008")[0] == ""
    assert G.pick(OP, "ONE PIECE JAPANESE OP06-WINGS OF THE CAPTAIN",
                  "RORONOA ZORO ALTERNATE ART", "OP06-118_p1")[0] == "OP06-118_p1"


def test_gundam_plus_is_parallel():
    # cert 151333415 GD02-094 のラベル3行目は RARE+ (パラレル)。PSA データでは Variety 欄にだけ出る
    base = {"product_id": "GD02-094", "specs": {"rarity": "R"}}
    para = {"product_id": "GD02-094_para", "specs": {"rarity": "R+", "variant_type": "parallel"}}
    b = "GUNDAM JAPANESE DUAL IMPACT"
    assert G.conflict("gundam_tcg", b, "GARROD RAN/TIFFA ADILL RARE+", base)
    assert not G.conflict("gundam_tcg", b, "GARROD RAN/TIFFA ADILL RARE+", para)
    assert G.conflict("gundam_tcg", b, "GARROD RAN/TIFFA ADILL RARE", para)
    # レアリティが読めない (古いキャッシュ) 時は判断しない
    assert not G.conflict("gundam_tcg", b, "GARROD RAN/TIFFA ADILL", base)


def test_label_text_keeps_variety_and_stripped_rarity():
    assert G.label_text({"Subject": "GARROD RAN/TIFFA ADILL", "Variety": None,
                         "LabelRarity": "RARE+"}) == "GARROD RAN/TIFFA ADILL  RARE+"
