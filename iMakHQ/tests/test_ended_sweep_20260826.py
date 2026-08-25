# -*- coding: utf-8 -*-
"""手で落とした出品の後始末を itemID を控えずに拾う (2026-08-26)。

取下げは Seller Hub で手作業してもよいが、B列を空にする / 済みリストに記録する、の2つが
抜けると「出品済み」のまま残り、仕入元が復活しても二度と出品されない。
落とした itemID を人が控えるのは無理なので、eBay の出品一覧と突き合わせて機械的に拾う。

★初回実装で踏んだ罠: B列は itemID だけの欄ではない。`9999` は「出品しない」確定の
  見送りマーカー (女性物など) で、eBay に居ないのは当然。itemID として扱うと
  **見送り印を50行以上消していた** (dry-run で気づいて未実行)。
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import ended_sweep as ES  # noqa: E402


def _sheet(*b_values):
    head = [""] * 3
    return [head] + [["url", b, "タイトル"] for b in b_values]


def test_miokuri_marker_is_not_an_itemid():
    """★9999 は見送り印。触ってはいけない。"""
    assert not ES.is_real_itemid("9999")
    assert ES.find_ended({"HIGH": _sheet("9999")}, live_ids=set()) == set()


def test_real_itemid_not_live_is_ended():
    assert ES.is_real_itemid("358870181858")
    assert ES.find_ended({"HIGH": _sheet("358870181858")}, live_ids=set()) == {"358870181858"}


def test_live_itemid_is_left_alone():
    assert ES.find_ended({"HIGH": _sheet("358870181858")},
                         live_ids={"358870181858"}) == set()


def test_blank_and_junk_are_ignored():
    for v in ("", "  ", "なし", "TBD", "123"):
        assert not ES.is_real_itemid(v), v
    assert ES.find_ended({"HIGH": _sheet("", "なし", "123")}, live_ids=set()) == set()


def test_both_sheets_are_swept():
    got = ES.find_ended({"HIGH": _sheet("358870181858"), "LOW": _sheet("820045155453")},
                        live_ids=set())
    assert got == {"358870181858", "820045155453"}
