# -*- coding: utf-8 -*-
"""RESTOCK 視覚確証 — 「違う」と「見送り」の意味が画面上で区別されていること.

背景 (2026-07-30 ユーザー報告):
    CGC (別鑑定会社) の候補が出ていたのに、毎日「見送り」が選ばれ続けていた。
    原因は viewer 側の2点:
      (a) 「見送り」が既定選択だった → 惰性で埋まる
      (b) 説明文が「買わない候補(**違うカード** / 高い / …)は仕入見送り」と書いており、
          別に「違う」ボタンがあるのと矛盾していた
    「違う」は go() で『検索の精度事故=即対応対象』として扱う **defect 指標**なので、
    惰性で見送りに流れると候補生成のバグが見えなくなる (実際に CGC 混入を見逃していた)。

守りたい性質:
  1. ラベルが意味を明示している (違う=別商品 / 見送り=商品は合っている)
  2. 理由の既定選択が無い (`sel` クラスが初期状態で付かない)
  3. 説明文が「違うカード → 見送り」と誘導しない
  4. 理由未選択のまま確定したら件数を見せる (黙って見送りにしない)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import psa_resource_confirm as prc  # noqa: E402

ITEM = {
    "idx": 0, "card_no": "OP13-118", "title": "PSA 10 One Piece Luffy",
    "ebay_url": "https://ebay/x", "ref_image": "https://img/ref.jpg",
    "candidates": [{"channel": "mercari", "price": 12345, "name": "CGC10 PSA10 ルフィ",
                    "url": "https://jp.mercari.com/item/m1", "image": "https://img/1.jpg"}],
}


def _html():
    return prc.build_restock_html([ITEM])


def test_labels_state_the_meaning():
    h = _html()
    assert "違う(別商品)" in h, "「違う」の意味 (別商品) がラベルに出ていない"
    assert "見送り(商品は合っている)" in h, "「見送り」の意味がラベルに出ていない"


def test_no_default_selected_reason():
    """既定選択 (`rb sel`) が無い = 惰性で見送りが入らない."""
    h = _html()
    assert "class='rb sel'" not in h, "理由ボタンが既定選択されている"
    assert "data-rsn=''" in h, "チェックボックスの理由が空 (未選択) で始まっていない"


def test_help_text_does_not_route_wrong_item_to_skip():
    """説明文が「違うカードは見送り」と誘導しないこと (誤用の原因だった)."""
    h = _html()
    assert "違うカード" not in h, "説明文が『違うカード → 見送り』に誘導している"
    assert "鑑定会社違い" in h, "別商品の具体例 (鑑定会社違い) が示されていない"


def test_unset_reason_is_surfaced_not_silent():
    """理由未選択を黙って見送りにしない (件数を confirm で見せる)."""
    h = _html()
    assert "理由未選択が" in h, "未選択件数の告知が無い = 黙って見送りにしている"
    assert "unset" in h, "未選択のカウントが JS に無い"


def test_diff_is_treated_as_defect_signal():
    """「違う」は精度事故として即対応扱いであることが画面に出ている."""
    h = _html()
    assert "精度事故" in h
