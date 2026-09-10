# -*- coding: utf-8 -*-
"""捨てた候補→新規出品 の画面で スニダンの画像を出す (2026-09-10 ユーザー指摘).

> スニダンだけ画像が出てこないのはおかしくない?

画面は候補URLをプロキシに渡して画像を作っていた。mercari は CDN の実画像に
解決できるが、**snkrdunk の商品ページの og:image はサイト既定のロゴ**なので
カードの絵が出ない。snkrdunk は cache に {price, url, image} を持っているので
それを使えばよい (補URL側の確証画面は 2026-08 に対応済で、こちらだけ残っていた)。

実測 2026-09-10: cache の snkrdunk 候補 7,387本すべてに image があった。
"""
import os
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

import newcand_confirm as N          # noqa: E402


def _cache():
    return {"111": {"snkrdunk": {"psa10_listings": [
        {"price": 1000, "url": "https://snkrdunk.com/apparels/1/used/2",
         "image": "https://cdn.snkrdunk.com/x.webp"}]},
        "mercari": {"cands": [[500, "https://jp.mercari.com/item/m1", "ルフィ"]]}}}


def test_snkrdunk_image_is_picked_up():
    m = N.url_image_map(_cache())
    assert m == {"https://snkrdunk.com/apparels/1/used/2": "https://cdn.snkrdunk.com/x.webp"}


def test_mercari_is_left_to_the_url(): 
    """mercari は URL から実画像に解決できるので、この表には入れない。"""
    assert "https://jp.mercari.com/item/m1" not in N.url_image_map(_cache())


def test_missing_image_is_skipped():
    c = {"111": {"snkrdunk": {"psa10_listings": [
        {"price": 1, "url": "https://snkrdunk.com/a/1"}]}}}
    assert N.url_image_map(c) == {}


def test_empty_cache():
    assert N.url_image_map({}) == {}
    assert N.url_image_map(None) == {}


def test_viewer_prefers_the_image_over_the_url():
    src = open(os.path.join(TOOLS, "newcand_confirm.py"), encoding="utf-8").read()
    assert 'prc._proxied(it.get("image") or it["url"])' in src
    assert 'prc._proxied(it["url"])' not in src, "URL 直渡しが残っている"
    assert '"image": u2i.get(p["url"], "")' in src, "items に画像を積むこと"
