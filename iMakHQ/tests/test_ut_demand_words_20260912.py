# -*- coding: utf-8 -*-
"""UT: 売れている作品を 次に集める順番に返す (2026-09-12).

設計 iMakHQ/UT_FLOW.md の ⑫。抽出くんは今 カタログの件数順で探しているので、
eBay で動いた順を渡す。
"""
from __future__ import annotations

import io
import os
import sys

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_HQ, "tools"))
sys.path.insert(0, r"C:\dev\iMak\iMakMercari")
import ut_demand_words as D  # noqa: E402
import ut_catalog_values as V  # noqa: E402

WORKS = {"ワンピース": "One Piece", "ONE PIECE": "One Piece", "呪術廻戦": "Jujutsu Kaisen",
         "ポケモン": "Pokémon", "Pokemon": "Pokémon"}


def _row(title, sold=0, s90=0, watch=0, impr=0, qty=1):
    return {"title": title, "sold_qty": sold, "sales90": s90, "watch": watch,
            "impr": impr, "impr_total": 0, "qty": qty}


class TestScore:
    def test_counts_sales_watch_and_exposure(self):
        rows = [_row("UNIQLO UT One Piece Luffy Tee", sold=1, watch=2, impr=3),
                _row("Uniqlo UT One Piece Sabo Tee", s90=1, qty=0),
                _row("UNIQLO UT Jujutsu Kaisen Gojo Tee", watch=1)]
        got = D.score_rows(rows, WORKS, V.title_has)
        assert got["One Piece"]["score"] == (1 * 3 + 2 + 1) + (1 * 3 + 0 + 0)
        assert got["One Piece"]["listings"] == 2 and got["One Piece"]["oos"] == 1
        assert got["Jujutsu Kaisen"]["score"] == 1

    def test_non_ut_listings_are_ignored(self):
        """PSA や他の商材の出品を混ぜない."""
        rows = [_row("PSA 10 One Piece Luffy OP01-001", sold=5)]
        assert D.score_rows(rows, WORKS, V.title_has) == {}

    def test_unknown_work_is_ignored(self):
        assert D.score_rows([_row("UNIQLO UT 何かのTシャツ", sold=1)], WORKS, V.title_has) == {}

    def test_is_ut(self):
        assert D.is_ut("Uniqlo Blue Lock UT Graphic T-Shirt")
        assert D.is_ut("UT Graphic Tee") and not D.is_ut("PSA 10 Pokemon Pikachu")


class TestCollabJp:
    def test_prefers_the_spelling_the_catalog_uses(self):
        """抽出くんはこの語でメルカリを探す = カタログに無い書き方を渡さない."""
        assert D.collab_jp_for("One Piece", WORKS, {"ワンピース"}) == "ワンピース"
        assert D.collab_jp_for("Pokémon", WORKS, {"ポケモン"}) == "ポケモン"

    def test_english_keys_are_not_handed_over(self):
        got = D.collab_jp_for("One Piece", WORKS, set())
        assert got and not got.isascii()

    def test_unknown(self):
        assert D.collab_jp_for("Nothing", WORKS, set()) == ""


class TestHandover:
    SRC = io.open(os.path.join(_HQ, "tools", "ut_demand_words.py"), encoding="utf-8").read()

    def test_writes_to_the_shared_area_only_with_the_flag(self):
        assert "C:/dev/iMak_data/harvest/ut_demand_words.json" in self.SRC
        assert "if not a.write:" in self.SRC

    def test_runs_every_night_after_the_funnel(self):
        bat = io.open(os.path.join(_HQ, "tools", "run_hoju_search.bat"), encoding="ascii").read()
        assert "ut_demand_words.py --write" in bat
        assert bat.index("listing_funnel.py") < bat.index("ut_demand_words.py")
