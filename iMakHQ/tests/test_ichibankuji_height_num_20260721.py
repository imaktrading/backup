# -*- coding: utf-8 -*-
"""ichibankuji C:Item Height 二重化バグの回帰テスト (2026-07-21)。

バグ: Claude が item_height_in に整形済み文字列 'X in (Y cm)' を返すと、生成側が
それをさらに ` in ({cm} cm)` で包み 'X in (Y cm) in (Y cm)' と二重化して出力していた
(rarara 検出。onep102 B賞 ベン・ベックマンで '8.5 in (21.5 cm) in (21.5 cm)')。
対策: _height_num で先頭の数値だけ抽出してから組む。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "iMak_ichibankuji")))
from ichibankuji_to_csv import _height_num  # noqa: E402


def _item_height(height_in, height_cm):
    """生成側と同じ組み立て(数値抽出後)を再現。"""
    hi, hc = _height_num(height_in), _height_num(height_cm)
    if hi and hc:
        return f"{hi} in ({hc} cm)"
    if hi:
        return f"{hi} in"
    if hc:
        return f"{hc} cm"
    return ""


def test_dual_string_in_inch_field_not_doubled():
    """★本命: Claude が inch 欄に整形済み文字列を返しても二重化しない。"""
    assert _height_num("8.5 in (21.5 cm)") == "8.5"
    assert _item_height("8.5 in (21.5 cm)", "21.5") == "8.5 in (21.5 cm)"
    assert " in (21.5 cm) in " not in _item_height("8.5 in (21.5 cm)", "21.5")


def test_clean_numeric_passthrough():
    assert _height_num("8.5") == "8.5"
    assert _item_height("8.5", "21.5") == "8.5 in (21.5 cm)"


def test_empty_and_noise():
    assert _height_num("") == ""
    assert _height_num(None) == ""
    assert _height_num("approx 8.5 in") == "8.5"
    assert _item_height("", "") == ""


def test_cm_only_when_inch_missing():
    assert _item_height("", "21.5") == "21.5 cm"
