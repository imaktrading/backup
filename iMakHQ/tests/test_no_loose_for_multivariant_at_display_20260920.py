# -*- coding: utf-8 -*-
"""見せる側でも「番号未確認」枠を落とす (2026-09-20)。

ユーザー「同じようなこと二度とするなよ」。探す側 (`should_offer_loose`) だけ直して
cache を洗わなかったため、同じ候補が何十回も目視に出ていた。
**探す側と見せる側の両方に同じ判定を置く** ので、片方だけ直しても漏れない。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(r"C:\dev\iMak\iMakHQ", "tools"))

import psa_resource_gate as G  # noqa: E402

_MR = {"all_cands": [], "cands": [],
       "loose_cands": [(6700, "https://jp.mercari.com/item/m58955733903",
                        # ★2026-09-24: 見せる側で「分かっているレアリティ (SV8a-093=RR) が書かれていない」
                        #   候補は落とすようにしたので、材料の出品名に RR を足した (この試験の目的は多変種の扱い)
                        "ゾロ77 【PSA10】トニートニー・チョッパー EB02-003 RR")]}
_C = {"snkrdunk_urls": [], "mercari_url": "", "mercari_jpy": None}


def _urls(**kw):
    return [x["url"] for x in G._build_visual_candidates(dict(_MR), dict(_C), **kw)]


def test_多変種なら番号未確認の候補を出さない():
    assert _urls(card_no="EB02-003", category="one_piece_tcg") == []


def test_単一変種でも同じ名前が他の番号にあれば出さない():
    """★2026-09-24 ユーザー「候補が1件もなかった。目視に出すべきじゃない」。
    SV8A-093 は1変種だが、同じ名前が別の番号にもある。
    番号の無い出品名ではどの版か決められないので出さない。"""
    assert _urls(card_no="SV8A-093", category="pokemon_tcg") == []


def test_単一変種で名前も1種類なら出す(monkeypatch):
    import mercari_psa_resource as mp
    monkeypatch.setattr(mp, "catalog_name_kinds", lambda *a, **k: 1)
    assert len(_urls(card_no="SV8A-093", category="pokemon_tcg")) == 1


def test_card_noが無ければ今までどおり():
    """どのカードか判らない時に勝手に落とさない (fail-closed)。"""
    assert len(_urls()) == 1
