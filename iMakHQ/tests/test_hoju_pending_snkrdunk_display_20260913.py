# -*- coding: utf-8 -*-
"""補URL③ に混ぜる「目視待ち」のスニダン候補に、画像と値段が出ること (2026-09-13 ユーザー報告)。

    「PSA補URL③のHTMLだけど、スニダンの分が画像が出なかったり、価格が出なかったり」

実測で分かった原因は3つ:
  1. 目視待ちの候補は url/site/price/note だけで画面に混ぜていた。通常の候補が持つ
     **channel / image / 整数の price** が無い
  2. image が空だと画面は出品ページの og:image を取りに行くが、スニダンの og:image は
     **全ページ共通のサイトロゴ** (`cdn.snkrdunk.com/images/ogp/og-image.png`・実測6本とも同じ)
  3. 値段は float (7700.0) で、画面は int しか `¥7,700` にしない

キャッシュに無いスニダン URL は最新の検索に居ない = 大半が売り切れ
(実測: 値段が引けない21本のうち先頭8本中7本が売り切れ)。黙って消さず、その旨を出す。
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import psa_resource_confirm as prc     # noqa: E402

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")


class _Resp:
    def __init__(self, html):
        self._b = html.encode("utf-8")

    def read(self):
        return self._b


def _og(monkeypatch, content):
    html = f'<html><head><meta property="og:image" content="{content}"></head></html>'
    monkeypatch.setattr(prc.urllib.request, "urlopen", lambda *a, **k: _Resp(html))
    prc._OG_CACHE.clear()


def test_スニダンのサイトロゴは画像として返さない(monkeypatch):
    _og(monkeypatch, "https://cdn.snkrdunk.com/images/ogp/og-image.png")
    assert prc._fetch_og_image("https://snkrdunk.com/apparels/562155/used/48710099") == ""


def test_本物の画像は今までどおり返す(monkeypatch):
    real = "https://static.mercdn.net/item/detail/orig/photos/m123_1.jpg"
    _og(monkeypatch, real)
    assert prc._fetch_og_image("https://jp.mercari.com/shops/product/abc") == real


def _src():
    return io.open(os.path.join(_TOOLS, "psa_hoju_fill.py"), encoding="utf-8").read()


def test_目視待ちの候補は通常の候補と同じ項目を持つ():
    """画面は channel (ラベル) / image (写真) / int の price (¥表記) / name (補足) を読む。"""
    src = _src()
    load = src[src.index("_sd_info = {}"):src.index("if _pending_by_iid:")]
    for key in ('"channel":', '"image":', '"name":', '"price": _pp'):
        assert key in load, f"目視待ちの候補に {key} が無い"
    assert "int(round(float(_pp)))" in load, "値段を整数にしていない (画面は int しか ¥ 表記しない)"
    assert "psa10_listings" in load, "スニダンの値段・画像を通常の候補と同じ出どころから取っていない"
    merge = src[src.index('"note": f"目視待ち ('):]
    merge = src[src.rindex("cands = list(cands) + [{", 0, src.index('"note": f"目視待ち (')):
                src.index('"note": f"目視待ち (')]
    for key in ('"channel":', '"image":', '"name":'):
        assert key in merge, f"画面に混ぜる時に {key} を渡していない"


def test_最新の検索に無いスニダンは黙って消さずに補足を出す():
    src = _src()
    assert "最新の検索に無い (売り切れの可能性)" in src
