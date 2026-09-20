# -*- coding: utf-8 -*-
"""多変種で候補を出さないと決めた時は、救済枠も出さない (2026-09-20)。

2026-09-20 の走行ログ「🚨 違う即対応 4件 — 番号で引けなかった枠が別カードを拾った」。
中身は P-041 と OP06-106 (どちらも多変種) で、画像検索の fail-closed が `all_cands` を
空にした直後に、救済枠が「空だから」と名前一致だけの候補を拾い直していた。
人が「違う」を4回押しており、押すたびに同じ形で再発していた。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(r"C:\dev\iMak\iMakHQ", "tools"))

import mercari_psa_resource as mp  # noqa: E402


def test_fail_closedなら救済枠を出さない():
    assert mp.should_offer_loose([], failclosed=True) is False


def test_番号で引けなかっただけなら救済枠を出す():
    assert mp.should_offer_loose([], failclosed=False) is True


def test_厳密一致が在る時は救済枠を出さない():
    assert mp.should_offer_loose([("x",)], failclosed=False) is False


def test_今回鳴った2枚は多変種():
    """この2枚が多変種でなければ、直す場所が違う。"""
    assert mp._is_multi_variant("P-041", "one_piece_tcg")
    assert mp._is_multi_variant("OP06-106", "one_piece_tcg")
