# -*- coding: utf-8 -*-
"""補URL・再仕入れを **特定した商品** で探す (2026-09-12).

ユーザー「補の概念とか重複出品とか PSA と同じ運用にするんだよ」(設計 iMakHQ/UT_FLOW.md)。
出品者が書いたタイトルは店ごとに語がばらつくので、目視で商品が決まった行は
カタログの作品名で探す。
"""
from __future__ import annotations

import os
import sys

import pytest

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_HQ, "tools"))
import ut_hoju_fill as U  # noqa: E402


class TestCatalogKeyword:
    @pytest.mark.parametrize("name,collab,kw", [
        ("ポケモン UT", "ポケモン", "ポケモン UT Tシャツ"),
        # コラボ名が併記の時は先頭を採る
        ("ドラゴンボール UT", "ドラゴンボール / ドラゴンボールDAIMA", "ドラゴンボール UT Tシャツ"),
        # コラボ名が無い時は商品名の末尾 (マンガUT 集英社創業100周年 /呪術廻戦)
        ("マンガUT 集英社創業100周年 /呪術廻戦", "", "呪術廻戦 UT Tシャツ"),
        ("鬼滅の刃 UT", "鬼滅の刃（UT）", "鬼滅の刃 UT Tシャツ"),
    ])
    def test_keyword(self, name, collab, kw):
        assert U.catalog_keyword(name, collab) == kw

    def test_sonota_is_not_a_work_name(self):
        """★「その他」を検索語にすると全く別の商品が並ぶ."""
        assert U.catalog_keyword("ポケモン ミーツ UT", "その他") == "ポケモン ミーツ UT Tシャツ"

    def test_no_name(self):
        assert U.catalog_keyword("", "") == ""


class TestHints:
    LED = {"https://a": {"decision": "go", "product_id": "E1", "color": "WHITE", "size": "XL(LL)",
                         "title": "UNIQLO UT ポケモン Tシャツ XL"},
           "https://b": {"decision": "go", "product_id": "E1", "color": "WHITE", "size": "",
                         "title": "UNIQLO UT ポケモン Tシャツ Mサイズ"},
           "https://c": {"decision": "skip", "product_id": "E1", "color": "WHITE", "size": "M"},
           "https://d": {"decision": "go", "product_id": "NOPE", "color": "W", "size": "M"}}

    def _load(self, pid, db=None):
        return {"product_id": pid, "name": "ポケモン UT", "category": "uniqlo_ut",
                "specs": {"collab": "ポケモン"}} if pid == "E1" else None

    def test_hints(self):
        got = U.identity_hints(self.LED, load_product=self._load)
        assert got["https://a"] == {"kw": "ポケモン UT Tシャツ", "size": "XL"}   # XL(LL) = XL
        # サイズ欄が空なら出品タイトルから読む
        assert got["https://b"]["size"] == "M"
        # 見送り / カタログに無い商品は対象外
        assert "https://c" not in got and "https://d" not in got


class TestJapaneseSizeNames:
    """★2026-09-12: 日本の表記は LL = XL。「LL → XXL」と読んでいたので
    「XL(LL)」の出品に 1サイズ大きい候補を並べていた (メルカリの UT はこの書き方)。"""

    @pytest.mark.parametrize("txt,jp", [("XL(LL)", "XL"), ("LL", "XL"), ("2L", "XL"),
                                        ("2XL(3L)", "XXL"), ("3L", "XXL"),
                                        ("3XL(4L)", "3XL"), ("4L", "3XL"), ("5L", "4XL"),
                                        ("M", "M"), ("120cm", "KIDS")])
    def test_size(self, txt, jp):
        assert U.jp_size_of(txt) == jp


class TestSelectTargets:
    def _rows(self):
        hdr = [""] * 33
        r = [""] * 33
        r[0], r[1], r[2], r[17] = "https://a", "358900000001", "⭐️ユニクロ 何かのTシャツ XL⭐️", "Tシャツ"
        return [hdr, r]

    def test_hint_wins_over_the_seller_title(self):
        got = U.select_targets(self._rows(), hints={"https://a": {"kw": "ポケモン UT Tシャツ",
                                                                 "size": "XL"}})
        assert got[0]["keyword"] == "ポケモン UT Tシャツ" and got[0]["from_catalog"] is True

    def test_falls_back_to_the_title(self):
        got = U.select_targets(self._rows())
        assert got[0]["from_catalog"] is False and got[0]["keyword"].endswith("UT Tシャツ")

    def test_search_uses_hints(self):
        import io
        src = io.open(os.path.join(_HQ, "tools", "ut_hoju_fill.py"), encoding="utf-8").read()
        i = src.index("def search(")
        body = src[i:i + 1200]
        assert "identity_hints(" in body and "hints=hints" in body
