# -*- coding: utf-8 -*-
"""pdca_store: emit_consolidated_request の category ルーティング (2026-07-02)。

事故: emit が category を無関係に全pendingをダンプし、gshock発行時に TCG項目が gshockラベルの
catalog依頼に混入(Catalog 指摘 = 誤ルーティング)。project→category族で振り分けるよう修正。
TCG は fine-grained(pokemon_tcg 等)と粗い 'tcg' 混在なので '*_tcg'/'*_scg' 包含。その回帰固定。"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import pdca_store as m


def test_tcg_project_includes_card_families():
    for cat in ("tcg", "pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg", "yugioh_tcg"):
        assert m.category_in_project(cat, "tcg"), cat


def test_tcg_project_excludes_others():
    assert not m.category_in_project("gshock", "tcg")
    assert not m.category_in_project("mercari", "tcg")
    assert not m.category_in_project("generic", "tcg")


def test_gshock_project_strict():
    assert m.category_in_project("gshock", "gshock")
    for cat in ("tcg", "pokemon_tcg", "mercari", "one_piece_tcg"):
        assert not m.category_in_project(cat, "gshock"), cat


def test_mercari_project_strict():
    assert m.category_in_project("mercari", "mercari")
    assert not m.category_in_project("tcg", "mercari")
    assert not m.category_in_project("pokemon_tcg", "mercari")


def test_case_and_none_safe():
    assert m.category_in_project("POKEMON_TCG", "tcg")
    assert not m.category_in_project(None, "tcg")
    assert not m.category_in_project("tcg", None)
