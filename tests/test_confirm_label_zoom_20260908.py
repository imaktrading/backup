# -*- coding: utf-8 -*-
"""目視画面に「ラベル拡大」を出す (2026-09-08 ユーザー指示)。

ユーザー「目視の際は、ラベルを見比べるよ。それが一番確実かなと」。
拡大は元々あったが **全体表示**で、ラベルの文字が小さいままだった。

実害 (2026-09-08・バイヤーの問い合わせで2件発覚):
  ST10-006 はカタログに版が8つあり、**全部 SR**。商品名では見分けが付かない。
  通常版の安い供給を掴み、$202.98 で出ていた (正しくは $814.98)。
  一方 **ラベルには `ONE PIECE DAY` と印字**されていた = ラベルを見れば分かった。
"""
import os
import re
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools")))

import psa_resource_confirm as prc   # noqa: E402

ITEM = {"idx": 0, "itemID": "820049712142", "title": "PSA 10 One Piece ST10-006",
        "ref": "https://i.ebayimg.com/x.jpg",
        "candidates": [{"url": "https://jp.mercari.com/item/m1", "site": "mercari",
                        "price": 57747}]}


def _html():
    h = prc.build_restock_html([dict(ITEM)])
    return h.decode("utf-8") if isinstance(h, bytes) else h


def test_label_zoom_button_exists():
    h = _html()
    assert "ラベルを拡大" in h and "zlbtn" in h


def test_both_images_are_wrapped_so_they_can_be_cropped():
    """現物と候補の **両方** を切り出せないと見比べにならない。"""
    h = _html()
    assert re.search(r"id='zref'.{0,120}?zwrap.{0,40}?<img", h, re.S)
    assert re.search(r"id='zcand'.{0,300}?zwrap.{0,40}?<img", h, re.S)


def test_label_mode_crops_the_top_at_2x():
    """ラベルは上端にある。上半分を2倍 (46vw → 92vw) で出す。"""
    h = _html()
    assert "#zov.label .zwrap{height:44vh;overflow:hidden" in h
    assert "width:92vw" in h


def test_keyboard_shortcut_is_wired():
    """毎回ボタンを探すと目視が遅くなる。L キーで切り替えられること。"""
    h = _html()
    assert "function zlabel" in h
    assert "'l'" in h and "'L'" in h


def test_whole_image_view_is_still_the_default():
    """既定は今までどおり全体表示 (絵柄も見るので、勝手に切り取らない)。"""
    h = _html()
    assert "id='zov' onclick='zclose(event)'" in h
    assert "#zov.label" in h          # label は追加クラス = 既定では付かない
