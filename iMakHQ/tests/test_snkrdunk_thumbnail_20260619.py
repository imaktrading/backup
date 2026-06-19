# -*- coding: utf-8 -*-
"""SNKRDUNK 実カード画像(thumbnailUrl)を RESTOCK確証へ流す配線の回帰テスト (2026-06-19)。

真因: RESTOCK確証の SNKRDUNK 候補が listing ページの og:image を拾い、全候補が同じ
サイト既定ロゴになっていた。search API の thumbnailUrl(実カード画像)を resolve_card_id→
check_by_keyword→combine→候補 と流して直す。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import snkrdunk_psa_resource as sp
import psa_resource_gate as gate


_SEARCH = {
    "tradingCards": [
        {"id": 520553, "productNumber": "OP11-106", "name": "[OP11-106] ゾロ",
         "thumbnailUrl": "https://cdn.snkrdunk.com/upload_bg_removed/zoro.webp?size=m"},
    ]
}


def test_match_item_returns_item_with_thumbnail():
    it = sp._match_item(_SEARCH, "OP11-106")
    assert it["id"] == 520553
    assert it["thumbnailUrl"].endswith("zoro.webp?size=m")


def test_parse_search_for_card_still_returns_id():
    """後方互換: parse_search_for_card は従来どおり id (int) を返す。"""
    assert sp.parse_search_for_card(_SEARCH, "OP11-106") == 520553


def test_resolve_card_id_fills_meta_thumbnail(monkeypatch):
    class _R:
        status_code = 200
        def json(self):
            return _SEARCH
    monkeypatch.setattr(sp.requests, "get", lambda *a, **k: _R())
    meta = {}
    cid = sp.resolve_card_id("OP11-106", _meta=meta)
    assert cid == 520553
    assert meta["thumbnail"].endswith("zoro.webp?size=m")


def test_combine_attaches_image_to_snkrdunk_urls():
    """check_by_keyword 形(card_image付き)→ combine の snkrdunk_urls 各entryに image が乗る。"""
    snkr = {
        "available": True, "psa10_price_jpy": 30000, "card_image": "https://cdn.snkrdunk.com/x.webp",
        "psa10_listings": [
            {"price": 30000, "url": "https://snkrdunk.com/trading-cards/1/listings/11"},
            {"price": 35000, "url": "https://snkrdunk.com/trading-cards/1/listings/22"},
        ],
    }
    c = gate.combine(None, snkr)
    assert len(c["snkrdunk_urls"]) == 2
    assert all(u["image"] == "https://cdn.snkrdunk.com/x.webp" for u in c["snkrdunk_urls"])
