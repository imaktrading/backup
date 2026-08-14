# -*- coding: utf-8 -*-
"""「DONQUIXOTE」を DON!!カードと誤判定して候補ゼロになっていた (2026-08-14)。

★実害: cert 165788214 'DONQUIXOTE DOFLAMINGO WANTED ALTERNATE ART' (OP03) が、
  Subject に "DON" を含むだけで **DON!!カード専用検索**に入り、そこで外れて
  `return None` → 目視画面の候補ゼロ。生成器は ST03-009_OP03 と解決できているのに、
  目視だけ確定できず **2走行連続で同じカードを聞いていた**。

固定する挙動:
  1. DON!!カード判定は "DON!!" (`!!` まで) で行う。DONQUIXOTE を巻き込まない
  2. DON 検索が外れても打ち切らず、通常の One Piece 検索に落とす
"""
from __future__ import annotations

import os
import sys

_TOOLS = r"C:\dev\iMak\iMakHQ\tools"
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import post_psa_review as R  # noqa: E402


def test_donquixote_is_not_treated_as_don_card():
    got = R._catalog_lookup_expected(
        "ONE PIECE JAPANESE OP03-PILLARS OF STRENGTH",
        "DONQUIXOTE DOFLAMINGO WANTED ALTERNATE ART", "009", "one_piece_tcg")
    assert got == "ST03-009_OP03", f"ドフラミンゴを解決できていない: {got}"


def test_don_branch_matches_the_real_don_card_only():
    src = open(os.path.join(_TOOLS, "post_psa_review.py"), encoding="utf-8").read()
    assert '"DON!!" in subj_up' in src, "DON 判定が部分一致のまま"
    assert '"DON" in subj_up' not in src


def test_don_lookup_failure_falls_through():
    """DON 検索が外れたら通常検索に落とす (return None で打ち切らない)。"""
    src = open(os.path.join(_TOOLS, "post_psa_review.py"), encoding="utf-8").read()
    i = src.index('if "DON!!" in subj_up:')
    block = src[i:i + 400]
    assert "lookup_one_piece" in block, "DON 失敗時に通常検索へ落ちていない"
