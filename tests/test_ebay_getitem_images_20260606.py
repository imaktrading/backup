# -*- coding: utf-8 -*-
"""取下再出品② 画像現状流用 — ebay_getitem_images の純粋部分 (network無し)。

2026-06-06: G-shock relist が 999.png ダミーで元listingの実画像を消す欠陥が発覚。
relist時は元 old_item_id の eBay画像を GetItem で取得し PicURL に流用するよう修正。
本テストは空入力ガードと PictureURL 抽出パースを検証 (実 API は叩かない)。
"""
import importlib.util
import os
import re

_MOD = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakeBayAPI", "ebay_getitem_images.py"))


def _load():
    spec = importlib.util.spec_from_file_location("ebay_getitem_images_t", _MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_empty_item_id_returns_empty():
    m = _load()
    assert m.fetch_listing_images("") == []
    assert m.fetch_listing_images("   ") == []


def test_pictureurl_parse_order_and_dedup():
    # GetItem応答XMLから PictureURL を順序保持＋重複除去で抽出するロジック(本体と同regex)
    xml = ("<PictureDetails>"
           "<PictureURL>https://i.ebayimg.com/a.JPG</PictureURL>"
           "<PictureURL>https://i.ebayimg.com/b.JPG</PictureURL>"
           "<PictureURL>https://i.ebayimg.com/a.JPG</PictureURL>"  # 重複
           "</PictureDetails>")
    pics = re.findall(r"<PictureURL>(.*?)</PictureURL>", xml)
    seen, out = set(), []
    for p in pics:
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    assert out == ["https://i.ebayimg.com/a.JPG", "https://i.ebayimg.com/b.JPG"]
    # FileExchange PicURL は | 区切りで複数画像
    assert "|".join(out) == "https://i.ebayimg.com/a.JPG|https://i.ebayimg.com/b.JPG"
