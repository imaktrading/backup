# -*- coding: utf-8 -*-
"""出品済みの UT 行に KEY を書く (2026-09-12).

ユーザー「補の概念とか重複出品とか PSA と同じ運用にするんだよ」。
重複くんは KEY で二重出品を止めるので、UT も出品したら KEY を書く。
重複くんの申し送り: 色・サイズが決まってから書く (空 KEY を作らない)。
"""
from __future__ import annotations

import io
import os
import sys

import pytest

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_HQ, "tools"))
sys.path.insert(0, r"C:\dev\iMak\iMakMercari")
import ut_key_backfill as B  # noqa: E402

LED = {"https://a": {"decision": "go", "product_id": "E1", "color": "BLUE", "size": "3XL(4L)"},
       "https://b": {"decision": "go", "product_id": "E2", "color": "WHITE", "size": ""},
       "https://c": {"decision": "skip", "product_id": "E3", "color": "WHITE", "size": "M"}}


def _row(url, itemid="", cat="Tシャツ", size="", key="", title="UNIQLO UT"):
    r = [""] * 36
    r[0], r[1], r[2], r[17], r[19], r[34] = url, itemid, title, cat, size, key
    return r


class TestPlan:
    def test_listed_and_identified_gets_a_key(self):
        got = B.plan([[], _row("https://a", "358900000001", size="3XL(4L)")], LED)
        assert got == [{"row": 2, "item_id": "358900000001",
                        "key": "uniqlo_ut:E1:BLUE:3XL", "title": "UNIQLO UT"}]

    def test_not_listed_yet_is_skipped(self):
        """★出品前の行に KEY を書くと「出品済み」と読まれて二度と出せない (orphan KEY)."""
        assert B.plan([[], _row("https://a", "", size="3XL")], LED) == []

    def test_existing_key_is_not_touched(self):
        rows = [[], _row("https://a", "358900000001", size="3XL", key="uniqlo_ut:手で入れた値")]
        assert B.plan(rows, LED) == []

    def test_size_from_title_when_the_column_is_empty(self):
        got = B.plan([[], _row("https://a", "1", size="", title="UNIQLO UT ONE PIECE Tシャツ Mサイズ")],
                     {"https://a": {"decision": "go", "product_id": "E1", "color": "BLUE", "size": ""}})
        assert got and got[0]["key"] == "uniqlo_ut:E1:BLUE:M"

    def test_undecided_size_writes_nothing(self):
        """色・サイズが決まらない行は書かない (重複くんの申し送り)."""
        assert B.plan([[], _row("https://b", "1", title="UNIQLO UT")], LED) == []

    def test_other_categories_and_decisions(self):
        assert B.plan([[], _row("https://a", "1", cat="PSA TCG", size="M")], LED) == []
        assert B.plan([[], _row("https://c", "1", size="M")], LED) == []      # 見送りは出品していない

    def test_unknown_url(self):
        assert B.plan([[], _row("https://zzz", "1", size="M")], LED) == []


class TestSafety:
    SRC = io.open(os.path.join(_HQ, "tools", "ut_key_backfill.py"), encoding="utf-8").read()

    def test_writes_only_with_flag(self):
        assert 'if not a.write:' in self.SRC and "sheet_io.write_keys(" in self.SRC

    def test_runs_every_night(self):
        bat = io.open(os.path.join(_HQ, "tools", "run_hoju_search.bat"), encoding="ascii").read()
        assert "ut_key_backfill.py --write" in bat

    def test_uses_the_shared_key_writer(self):
        """AI列だけを触る書き手 (sheet_io.write_keys) を使う。自前で書かない."""
        assert "ws.update" not in self.SRC and "batch_update" not in self.SRC
