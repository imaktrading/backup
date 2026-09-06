# -*- coding: utf-8 -*-
"""証明番号を打つ画面に拡大を出す (2026-09-06 ユーザー要望)。

証明番号は PSA ラベルの右上に印字されている。180x240 に縮めた写真では読めず、
毎回 仕入元ページを開き直していた。同じ画像を使い回すので通信は増えない。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools")))

import newcand_confirm as nc   # noqa: E402

ITEM = {"i": 0, "url": "https://jp.mercari.com/item/m1", "title": "PSA10 ルフィ",
        "key": "one_piece_tcg:OP01-001", "pid": "OP01-001", "price": 12000}


def _html():
    return nc.build_cert_html([ITEM]).decode("utf-8")


def test_zoom_pane_is_rendered():
    h = _html()
    assert "class='zoomtr'" in h
    assert h.count("<img") == 2          # 元写真 + 拡大


def test_zoom_reuses_the_same_image():
    """同じ URL を使う = 追加の通信もスクレイプも発生しない。"""
    h = _html()
    src = "/img?u=https%3A%2F%2Fjp.mercari.com%2Fitem%2Fm1"
    assert h.count(src) >= 2


def test_zoom_shows_the_top_strip_full_width():
    """幅いっぱいのまま上半分を2倍。角だけ切り出すと構図次第で別の場所が写る
    (2026-09-06: 最初その作りにして「見切れて全然わからない」となった)。"""
    h = _html()
    assert ".zoomtr{" in h and "overflow:hidden" in h
    assert "top:0;left:0" in h            # 左上に寄せる = 上部の帯が全部入る
    assert "width:360px" in h             # 元表示 180px の2倍


def test_cert_input_still_there():
    """拡大を足しても、打ち込み欄と売り切れ印は残っている。"""
    h = _html()
    assert "input class='cert'" in h and "class='sold'" in h
