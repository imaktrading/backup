# -*- coding: utf-8 -*-
"""タイトルの任意要素は「入る物だけ拾う」(2026-09-16)。

実害 (2026-09-16 の走行): 16件中 **7件が70字未満**、平均 74字 → 70.9字に落ち、
監査が「キーワード不足」を9件指摘した。原因は 任意要素 (Rarity / Features / Year) を
**末尾からまとめて捨てる** 作りで、1つ長い要素があると その後ろの短い要素まで道連れになっていた:

  本体 64字 + Rarity 'Special Art Rare' (17) = 81字 → 1字超過
  → Rarity も Year も捨てて **64字** で確定 (Year '2024' だけなら 69字で入る)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "iMakTCG"))

import tcg_listing_fields as T  # noqa: E402

SV8A = {"C:Game": "Pokémon TCG", "C:Language": "Japanese", "C:Set": "Sv8a: Terastal Fest Ex",
        "C:Card Number": "223/187", "C:Character": "Eevee ex", "C:Rarity": "Special Art Rare",
        "C:Features": "Special Art", "C:Year Manufactured": "2024"}


def test_short_optional_is_kept_when_a_long_one_does_not_fit():
    t = T.build_title_from_fields(SV8A)
    assert t.endswith("2024"), t              # 長い Rarity は入らないが Year は入る
    assert 65 <= len(t) <= T._TITLE_MAX, len(t)


def test_everything_fits_is_unchanged():
    """全部収まる普通のケースは今までどおり (Rarity も Year も入る)。"""
    f = dict(SV8A, **{"C:Set": "Sv5k: Wild Force", "C:Card Number": "074/071",
                      "C:Character": "Bronzor", "C:Rarity": "Art Rare", "C:Features": ""})
    t = T.build_title_from_fields(f)
    assert "Art Rare" in t and t.endswith("2024") and len(t) <= T._TITLE_MAX


def test_core_is_never_cut_for_an_optional():
    """同定に要る語 (Set/番号/キャラ/Japanese/PSA10) は落とさない。"""
    t = T.build_title_from_fields(SV8A)
    for must in ("PSA 10", "Japanese", "#223/187", "Eevee ex"):
        assert must in t, must
