# -*- coding: utf-8 -*-
"""PSA再仕入れ 目視ゲートの虫眼鏡 (2026-09-01)。

ユーザー「虫眼鏡つけて」。この画面だけ 🔍 が無く、絵柄を見比べられなかった
(CSS(.zm/#zov)は入っていたのに、ボタンと JS が一度も配線されていなかった)。

虫眼鏡は **①現物と候補を並べて**出す (viewer_zoom)。片方だけ全画面にすると
見比べられない = 目視の目的を果たさない。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import psa_resource_confirm as prc  # noqa: E402


def _page(cands, psa_image="https://example/psa.jpg", card_no="053/050"):
    return prc.build_confirm_html([{
        "idx": 0, "title": "PSA 10 Pokemon #053/050 Alolan Ninetales", "card_no": card_no,
        "psa_image": psa_image, "candidates": cands, "resolved_key": None,
        "ebay_url": "https://example/item", "no_image": not psa_image}])


CANDS = [{"key": "SM7b-053", "image": "https://example/c1.jpg", "label": "[SM7b-053]"},
         {"key": "SM2K-053", "image": "https://example/c2.jpg", "label": "[SM2K-053]"}]


def test_every_candidate_has_a_magnifier():
    h = _page(CANDS)
    assert h.count("class='zm'") == 3, "候補2件 + 現物1件 に 🔍 が要る"


def test_magnifier_opens_side_by_side_with_the_real_item():
    """候補の 🔍 は **現物も一緒に**開く (data-ref)。片方だけでは見比べにならない。"""
    h = _page(CANDS)
    assert "id='zov'" in h and "id='zref'" in h and "id='zcand'" in h
    assert h.count("data-ref=") == 3
    assert "psa.jpg" in h.split("data-ref=")[1][:120], "候補の 🔍 に現物画像が渡っていない"


def test_magnifier_js_is_shipped():
    """CSS だけ在って JS が無い状態を二度と作らない (今回それだった)。"""
    h = _page(CANDS)
    assert "function zoom(" in h and "function zclose(" in h
    assert ".zm{" in h, "拡大ボタンの CSS が無い"


def test_no_magnifier_when_no_image():
    """画像が無い候補にボタンだけ出さない (押しても何も出ない = 迷わせる)。"""
    h = _page([{"key": "X-1", "image": "", "label": "[X-1]"}], psa_image="")
    assert "class='zm'" not in h


def test_zoom_button_does_not_toggle_the_radio():
    """🔍 は <label> の中に在る。preventDefault/stopPropagation が無いと押しただけで選択が動く。"""
    h = _page(CANDS)
    assert "preventDefault" in h and "stopPropagation" in h
