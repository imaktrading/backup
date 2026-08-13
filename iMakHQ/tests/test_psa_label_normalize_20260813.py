# -*- coding: utf-8 -*-
"""PSA ラベルの書式差を畳んで比較する (2026-08-13)。

★ユーザー指摘「このてのラベル違いがちょいちょいある」。
  PSA は同じカードを複数の書式で印字する。今日 実物で確認した2枚 (どちらも同じカード):
    A: 1行目 "2023 ONE PIECE OP05 JP"  / 3行目 "ALTERNATE ART"      (cert 147704361)
    B: 1行目 "2023 ONE PIECE JPN."      / 3行目 "OP05-ALTERNATE ART" (cert 83561618)
  書式が違うだけで中身 (OP05 / ALTERNATE ART / #002) は同一。人はこれを見て「違う」を
  押し、使える仕入元を捨てていた。→ **畳んでから比べる**。

固定する挙動:
  1. セット記号は brand 側にも variety 側にも入りうるので、両方から拾う
  2. 変種名から先頭のセット記号を落とす ("OP05-ALTERNATE ART" → "ALTERNATE ART")
  3. 3点 (セット/変種/番号) が揃って一致した時だけ「同じ」。欠けたら False (推測しない)
  4. セットが違えば別カード (再録版。絵柄が同じでも別物)
"""
from __future__ import annotations

import os
import sys

_TOOLS = r"C:\dev\iMak\iMakHQ\tools"
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import psa_resource_confirm as P  # noqa: E402


def test_same_card_across_label_formats():
    a = P.normalize_label("ONE PIECE JAPANESE OP05-AWAKENING OF THE NEW ERA",
                          "ALTERNATE ART", "002")
    b = P.normalize_label("2023 ONE PIECE JPN.", "OP05-ALTERNATE ART", "#002")
    c = P.normalize_label("2023 ONE PIECE OP05 JP", "ALTERNATE ART", "002")
    assert a["set"] == b["set"] == c["set"] == "OP05"
    assert a["variety"] == b["variety"] == c["variety"] == "ALTERNATE ART"
    assert P.same_card_by_label(a, b) and P.same_card_by_label(a, c)


def test_different_set_is_a_different_card():
    """再録版は絵柄が同じでも別物 (OP02-013 は OP08 / PRB01 にも再録がある)。"""
    op02 = P.normalize_label("2022 ONE PIECE JPN.", "OP02-ALTERNATE ART", "013")
    op08 = P.normalize_label("2024 ONE PIECE JPN.", "OP08-ALTERNATE ART", "013")
    assert not P.same_card_by_label(op02, op08)


def test_missing_field_is_not_a_match():
    """欠けている時は「同じ」と言わない (推測しない)。"""
    a = P.normalize_label("2023 ONE PIECE OP05 JP", "ALTERNATE ART", "002")
    assert not P.same_card_by_label(a, P.normalize_label("2023 ONE PIECE JPN.", "", "002"))
    assert not P.same_card_by_label(a, P.normalize_label("", "ALTERNATE ART", "002"))
    assert not P.same_card_by_label(a, {})


def test_viewer_shows_the_three_matching_points():
    src = open(os.path.join(_TOOLS, "psa_resource_confirm.py"), encoding="utf-8").read()
    assert "セット記号" in src
    assert "の3点だけ見る" in src
