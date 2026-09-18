"""pokemon_out_of_scope の対象を固定 (2026-07-26)。

契機: cert 138056958 (Brand='POKEMON JAPANESE BLACK DECK KIT', Subject='DARK HOUNDOOM ...')
が毎回候補にならない。真因: pokemon_out_of_scope が "BLACK DECK KIT" を問答無用 skip していたが、
その後 catalog に BDK-005/006 (わるいマグカルゴ/わるいヘルガー) が収録され、cert 138056958=BDK-006
が catalog hit するのにこの skip で殺されていた (2026-06-27 に 0件だった時のハードコード除外が陳腐化)。
対策: BLACK DECK KIT を除外リストから外し、catalog 有無で判定 (hit→出品 / no-hit→下流 fail-closed)。
★2026-09-14: FAMILY POKEMON CARD GAME も同様に撤廃 (catalog 実測53件で「0件」前提が崩れた)。
純関数のみ。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psa_to_csv import pokemon_out_of_scope


def test_black_deck_kit_no_longer_skipped():
    # catalog に BDK-005/006 収録済 → ハードコード skip しない (catalog 有無で判定させる)
    assert pokemon_out_of_scope("Pokemon", "POKEMON JAPANESE BLACK DECK KIT") is False


def test_family_no_longer_skipped():
    # ★2026-09-14: catalog 実測 53件 (SH-prefix) で「catalog 0件」の前提が崩れたため
    # 除外を撤廃。catalog 有無で下流が fail-closed 判定する (SSOT)。
    assert pokemon_out_of_scope("Pokemon", "FAMILY POKEMON CARD GAME") is False


def test_non_pokemon_never_scoped():
    assert pokemon_out_of_scope("OnePiece", "ANYTHING BLACK DECK KIT") is False


def test_normal_pokemon_not_scoped():
    assert pokemon_out_of_scope("Pokemon", "POKEMON JAPANESE SV5a CRIMSON HAZE") is False


def test_empty_brand():
    assert pokemon_out_of_scope("Pokemon", "") is False
    assert pokemon_out_of_scope("Pokemon", None) is False
