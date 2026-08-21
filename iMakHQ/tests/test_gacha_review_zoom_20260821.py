# -*- coding: utf-8 -*-
"""ガチャの目視画面: 写真が小さすぎて対象年齢が読めなかった (2026-08-21).

回答書 `2026-08-20_gacha_images_correction_response.md`:
  **写真は足りているのに人が読めない**、が真因だった。楽天の元画像は 500x500 で
  対象年齢は台紙に印字されているのに、画面が 140px 角で出していたので読めず、
  「画像を増やす」に倒しかけた。

  ①②とも誤り → ①=アミュームの画像が商品トリミングで台紙が写らない (Harvest 側)
                ②=目視画面が読めないサイズで出していた (ここで直す)

直したこと: サムネイルを元画像に近い大きさで出す + 🔍原寸 で別タブに元の大きさ。
"""
from __future__ import annotations

import os
import re
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import gacha_review as R                                         # noqa: E402

ITEMS = [
    {"url": "https://item.rakuten.co.jp/auc-yuyou/g1/", "title_jp": "A 全5種セット",
     "pieces": 5, "cost_jpy": 2820, "maker_jp": "エール", "series_jp": "A",
     "pics": ["https://shop.r10s.jp/auc-yuyou/cabinet/2206/g220649s01.jpg",
              "https://shop.r10s.jp/auc-yuyou/parts/bn_math.jpg"]},
]


def _thumb_px(html: str) -> int:
    """`.p img` の表示サイズ (px)。"""
    m = re.search(r"\.p img\{width:(\d+)px;height:(\d+)px", html)
    assert m, ".p img の大きさが読めません"
    assert m.group(1) == m.group(2), "正方形のままにする"
    return int(m.group(1))


class Test台紙の対象年齢が読める大きさで出す:
    def test_140pxではない(self):
        """★これが本体。140px では台紙の印字が読めなかった."""
        assert _thumb_px(R.build_html(ITEMS)) > 140

    def test_元画像に近い大きさ(self):
        """楽天の元画像は 500x500。縮めすぎると印字が潰れる."""
        assert _thumb_px(R.build_html(ITEMS)) >= 400

    def test_狭い画面でも縮むだけで消えない(self):
        assert "@media (max-width:1040px)" in R.build_html(ITEMS)


class Test原寸を開ける:
    def test_写真ごとに原寸リンクがある(self):
        h = R.build_html(ITEMS)
        assert h.count('class="zoom"') == 2

    def test_別タブで開く(self):
        assert 'target="_blank" rel="noopener"' in R.build_html(ITEMS)

    def test_原寸リンクは同じ写真を指す(self):
        h = R.build_html(ITEMS)
        for u in ITEMS[0]["pics"]:
            import urllib.parse
            assert 'href="/img/%s"' % urllib.parse.quote(u, safe="") in h

    def test_原寸リンクはチェックの外にある(self):
        """★label の中に入れると、原寸を開くたびに選択が切り替わってしまう."""
        h = R.build_html(ITEMS)
        for block in re.findall(r"<label>.*?</label>", h, re.S):
            assert "zoom" not in block


class Test今までの選び方は壊さない:
    def test_写真は1枚も間引かない(self):
        h = R.build_html(ITEMS)
        assert h.count('type="checkbox"') == 2
        assert "bn_math.jpg" in h                # 店のバナーも隠さず出す

    def test_チェックで選ぶのは今まで通り(self):
        h = R.build_html(ITEMS)
        assert '.p input:checked+img' in h       # 選んだ物に緑枠

    def test_写真が無い行は今まで通り(self):
        assert "G列に写真がありません" in R.build_html([dict(ITEMS[0], pics=[])])

    def test_選んだ物だけが出品に回る(self):
        led = {ITEMS[0]["url"]: {"decision": "list",
                                 "pics": [ITEMS[0]["pics"][0]]}}
        assert R.confirmed(ITEMS, led)[0]["pics"] == [ITEMS[0]["pics"][0]]

    def test_タイトルは今まで通りエスケープされる(self):
        h = R.build_html([dict(ITEMS[0], title_jp="<script>x</script>")])
        assert "<script>x</script>" not in h
