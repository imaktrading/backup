"""tests/test_uniqlo_tee - メルカリのユニクロT判定 (2026-08-22 user 確定)."""
from __future__ import annotations

import pytest

from uniqlo_tee import is_collab, is_new_condition, is_target, is_uniqlo_tee

pytestmark = pytest.mark.offline


@pytest.mark.parametrize("title", [
    "ユニクロ UT ワンピース Tシャツ L 新品",
    "UNIQLO UT ポケモン グラフィックTシャツ M",
    "GU ジーユー コラボ Tシャツ 呪術廻戦 L",
])
def test_target_titles(title):
    assert is_target(title)


@pytest.mark.parametrize("title,why", [
    ("ユニクロ 無地 Tシャツ 白 M", "コラボでない"),
    ("ナイキ アニメ Tシャツ L", "ユニクロでない"),
    ("ユニクロ UT ワンピース Tシャツ 3枚セット", "まとめ売り"),
    ("ユニクロ UT ポケモン Tシャツ キッズ 120cm", "子供用"),
    ("ユニクロ UT アニメ Tシャツ 汚れあり", "難あり"),
])
def test_rejected_titles(title, why):
    assert not is_target(title), why


def test_dress_is_not_a_one_piece_collab():
    """★実害 (2026-08-22): 服の「ワンピース」をアニメ ONE PIECE として拾っていた."""
    from uniqlo_tee import is_dress
    dress = "UNIQLO クルーネックTワンピース 半袖 ダークグレー L 新品ユニクロ"
    assert is_dress(dress)
    assert not is_target(dress)
    # アニメの方は通す
    anime = "ユニクロ UT ワンピース ONE PIECE Tシャツ Mサイズ 新品未使用"
    assert not is_dress(anime)
    assert is_target(anime)
    assert is_target("⭐️ONE PIECE UNIQLO ユニクロTシャツ　XL⭐️")


def test_uniqlo_tee_needs_both_brand_and_tee():
    assert not is_uniqlo_tee("ユニクロ パーカー ワンピース")     # T でない
    assert not is_uniqlo_tee("アニメ Tシャツ")                   # ブランド不明


def test_collab_alone_is_not_enough():
    """コラボ語があっても ユニクロの T でなければ採らない."""
    assert is_collab("ポケモン Tシャツ")
    assert not is_target("ポケモン Tシャツ")


@pytest.mark.parametrize("cond,ok", [
    ("新品、未使用", True),
    ("新品, 未使用", True),
    ("未使用に近い", False),
    ("目立った傷や汚れなし", False),
    ("", False),
])
def test_is_new_condition(cond, ok):
    assert is_new_condition(cond) is ok


def test_price_range_default_is_500_to_12000():
    """★UT の価格帯は 500〜12,000円 (2026-09-13 user 確定)。付け忘れても効くよう既定で持つ."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]
           / "run_harvest_mercari_uniqlo.py").read_text(encoding="utf-8")
    assert '"--price-min", type=int, default=500' in src
    assert '"--price-max", type=int, default=12000' in src
