"""tests/test_montbell_jacket - モンベル ジャケット系の判定 (2026-09-05 user 確定)."""
from __future__ import annotations

import pytest

from montbell_jacket import condition_label, is_montbell_jacket

pytestmark = pytest.mark.offline


@pytest.mark.parametrize("title", [
    "モンベル ストームクルーザー ジャケット メンズ M",
    "mont-bell ウインドブラスト パーカ L 美品",
    "モンベル ライトシェル アウター ネイビー M",
    "montbell インナーダウン ジャケット S",
])
def test_target(title):
    assert is_montbell_jacket(title)


@pytest.mark.parametrize("title,why", [
    ("モンベル 寝袋 ダウンハガー800 #3", "寝袋はジャケットでない"),
    ("モンベル トレッキングパンツ M", "ボトムス"),
    ("ノースフェイス ジャケット M", "別ブランド"),
    ("モンベル ジャケット キッズ 130cm", "子供用"),
    ("モンベル ジャケット まとめ売り 3点セット", "まとめ売り"),
    ("モンベル ジャケット 破れあり ジャンク", "難あり"),
])
def test_rejected(title, why):
    assert not is_montbell_jacket(title), why


def test_sleeping_bag_with_down_word_is_not_a_jacket():
    """「ダウン」はジャケット語だが、寝袋は落とす (NG が優先)."""
    assert not is_montbell_jacket("モンベル ダウンハガー 寝袋 800")


@pytest.mark.parametrize("cond,label", [
    ("新品、未使用", "新品"),
    ("未使用に近い", "中古"),
    ("目立った傷や汚れなし", "中古"),
    ("", ""),
])
def test_condition_label(cond, label):
    """中古と新品を **列で見分けられる** ようにする (user 確定)."""
    assert condition_label(cond) == label
