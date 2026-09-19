"""スニダンの個体違いは「新しい供給」ではない (2026-09-19)。

ユーザー報告「820133533434 も何回も目視している」。
スニダンは同じカードに **個体ごとの URL** を付ける
(`/apparels/761394/used/50273173` … `/used/49135740`)。売れて新しい個体が並ぶたびに
URL が変わるので、URL で比べると毎回「新しい供給が出た」ことになり、判定済みの出品が
何度も目視に戻っていた。商品ID (apparels/NNN) まで で1つの供給とみなす。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import psa_hoju_fill as H

SD = "https://snkrdunk.com/apparels/761394/used/"


def test_個体が入れ替わっただけなら新しくない():
    assert H._has_new_supply([SD + "50273173"], [SD + "49135740"]) is False


def test_別の商品が出たら新しい():
    assert H._has_new_supply([SD + "50273173"],
                             [SD + "49135740", "https://snkrdunk.com/apparels/999/used/1"]) is True


def test_メルカリは今までどおり出品ごとに見る():
    m = "https://jp.mercari.com/item/"
    assert H._has_new_supply([m + "m1"], [m + "m1"]) is False
    assert H._has_new_supply([m + "m1"], [m + "m1", m + "m2"]) is True


def test_記録が無ければ出す():
    assert H._has_new_supply([], [SD + "1"]) is True


def test_候補ゼロなら出さない():
    assert H._has_new_supply([SD + "1"], []) is False
