# -*- coding: utf-8 -*-
"""tcg_intra_csv_dedup: CSV内同design重複の間引き (2026-07-01)。

2026-07-01 事故: C:Set 空(catalog gap)の identical カード2枚が、design key
(Game,Set,CardNumber)に空要素があるため同定放棄され両方出品CSVに残った。
→ 空要素があれば完全一致タイトルにフォールバックして間引くよう修正。その回帰固定。"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import tcg_intra_csv_dedup as m

HEADER = ["*Title", "C:Game", "C:Set", "C:Card Number"]


def _row(title, game, cset, num):
    return [title, game, cset, num]


def test_complete_design_key_dupe_dropped():
    # 従来挙動: design key 完全 → 2枚目除外
    body = [
        _row("A", "One Piece", "OP12", "OP12-031"),
        _row("A", "One Piece", "OP12", "OP12-031"),
    ]
    assert m.dup_row_indices(body, HEADER) == {1}


def test_set_empty_identical_title_dropped():
    # ★事故の再現→修正: C:Set 空でも identical title で間引く
    t = "PSA 10 One Piece Japanese #OP12-031 Tashigi Rare Alternative Art 2025"
    body = [
        _row(t, "One Piece", "", "OP12-031"),
        _row(t, "One Piece", "", "OP12-031"),
    ]
    assert m.dup_row_indices(body, HEADER) == {1}


def test_set_empty_different_title_kept():
    # Set 空でも title が違えば別カード → 誤除外しない
    body = [
        _row("PSA 10 One Piece #OP12-031 Tashigi", "One Piece", "", "OP12-031"),
        _row("PSA 10 One Piece #OP12-037 Lim", "One Piece", "", "OP12-037"),
    ]
    assert m.dup_row_indices(body, HEADER) == set()


def test_all_identity_empty_kept():
    # design key も title も空 → 同定不能、残す(fail-closed)
    body = [
        _row("", "", "", ""),
        _row("", "", "", ""),
    ]
    assert m.dup_row_indices(body, HEADER) == set()


def test_mixed_only_second_pair_dropped():
    t = "PSA 10 One Piece #OP12-031 Tashigi 2025"
    body = [
        _row(t, "One Piece", "", "OP12-031"),        # 0 keep (title fallback)
        _row("Tyrunt", "Pokemon", "Nihil Zero", "089"),  # 1 keep (design key)
        _row(t, "One Piece", "", "OP12-031"),        # 2 drop (title dupe of 0)
        _row("Tyrunt", "Pokemon", "Nihil Zero", "089"),  # 3 drop (design dupe of 1)
    ]
    assert m.dup_row_indices(body, HEADER) == {2, 3}
