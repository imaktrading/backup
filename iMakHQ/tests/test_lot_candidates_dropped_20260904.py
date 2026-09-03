# -*- coding: utf-8 -*-
"""まとめ売り/連番は 仕入候補にしない (2026-09-04)。

## なぜ
まとめ売り・連番スラブは **1枚だけ買えない**。買うと全部付いてくるので仕入値が
想定と違い、出品は1つしか作れないのに現物は複数枚になる。

**出品する対象**側では 2026-08-23 から弾いていたが、**仕入候補**側には当てていなかった。
実測 (2026-09-04): 人が『違う』と外した候補249件のうち **34件がこれ**。
機械で判るものを毎回 人に見せて、1クリックずつ捨てさせていた。

## 直し方
判定は listing_common.supply_lot_hint の1か所。psa_to_csv (重い) にあったのを
共通モジュールへ移し、候補側からも同じものを呼ぶ。二重実装しない。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (os.path.join(_ROOT, "iMakHQ", "tools"), os.path.join(_ROOT, "iMakeBayAPI")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mercari_psa_resource as mp                              # noqa: E402
from listing_common import supply_lot_hint                     # noqa: E402

HINT = ["ナイトワンダラー【SV6a】", "", "Night Wanderer", "", "AR", "タッツー"]
LOT = {"price": 16666, "href": "https://jp.mercari.com/item/m1",
       "name": "PSA10 2枚 タッツー AR SV6a ナイトワンダラー 067/064"}
ONE = {"price": 17000, "href": "https://jp.mercari.com/item/m2",
       "name": "PSA10 タッツー AR SV6a ナイトワンダラー 067/064"}


def test_the_rule_lives_in_one_place():
    """psa_to_csv からも同じものが引ける (名前を保ったまま移設した)。"""
    assert supply_lot_hint("PSA10 2枚 タッツー") == "2枚"
    assert supply_lot_hint("PSA10 ルフィ P-106 連番③") == "連番"
    assert supply_lot_hint("PSA10 エース OP03-001") is None


def test_brag_about_rarity_is_not_a_lot():
    """「世界に4枚」は希少さの自慢であって出品枚数ではない (既存の除外)。"""
    assert supply_lot_hint("【8/8時点世界に4枚！】【PSA10】ロロノア・ゾロ") is None


def test_strict_candidates_drop_lots():
    got = [i["name"] for i in mp._variant_matches([LOT, ONE], "SV6A-067", HINT, "067/064")]
    assert got == [ONE["name"]]


def test_loose_candidates_drop_lots():
    """番号で引けなかった枠 (名前一致だけ) でも同じく落とす。"""
    got = [c[2] for c in mp.pick_psa10_loose_candidates([LOT, ONE], "タッツー")]
    assert got == [ONE["name"]]


def test_a_lot_only_result_yields_nothing():
    """まとめ売りしか無いなら候補ゼロ = 買えないので正しい。"""
    assert mp._variant_matches([LOT], "SV6A-067", HINT, "067/064") == []
