# -*- coding: utf-8 -*-
"""SNKRDUNK Dragon Ball 変種解決の回帰テスト (2026-06-19)。

真因: SB02-033 が SNKRDUNK に JP「L」/JP「L*」/EN「L」/EN「L*」の4変種あり、(1)[EN]を除外
してない (2)Dragon Ball の asterisk(L*=パラレル)を print 判定できてない、で曖昧→
card_not_found→毎回「候補なし」になっていた。EN除外 + asterisk検出で base/parallel を解決。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import snkrdunk_psa_resource as sp


_SB = {"streetwears": [
    {"id": 1, "productNumber": "", "thumbnailUrl": "lstar",
     "name": 'Son Goku L* [SB02-033](FUSION WORLD "MANGA BOOSTER 02")'},
    {"id": 2, "productNumber": "", "thumbnailUrl": "lbase",
     "name": 'Son Goku L [SB02-033](FUSION WORLD "MANGA BOOSTER 02")'},
    {"id": 3, "productNumber": "", "thumbnailUrl": "lstar_en",
     "name": 'Son Goku L* [SB02-033][EN](FUSION WORLD "MANGA BOOSTER 02")'},
    {"id": 4, "productNumber": "", "thumbnailUrl": "lbase_en",
     "name": 'Son Goku L [SB02-033][EN](FUSION WORLD "MANGA BOOSTER 02")'},
]}

_BASE_HINT = ["MANGA BOOSTER 02 [SB02]", "", "", "", "L", "孫悟空"]
_PARA_HINT = ["MANGA BOOSTER 02 [SB02]", "", "", "", "L*", "孫悟空"]


def test_item_print_detects_asterisk_parallel():
    assert sp._item_print("Son Goku L* [SB02-033]") == "P"     # asterisk = パラレル
    assert sp._item_print("Son Goku L [SB02-033]") == ""        # base = 通常


def test_print_signal_from_asterisk_rarity():
    assert sp._print_signal(_PARA_HINT) == "P"                 # rarity 'L*' = パラレル
    assert sp._print_signal(_BASE_HINT) == ""                  # rarity 'L' = 通常


def test_en_excluded_base_resolves_to_jp_base():
    """[EN]除外 + base hint → JP base「L」(id=2)に解決。EN版・L* は外れる。"""
    it = sp._match_item(_SB, "SB02-033", variant_hint=_BASE_HINT)
    assert it is not None and it["id"] == 2
    assert it["thumbnailUrl"] == "lbase"


def test_parallel_hint_resolves_to_jp_parallel():
    """parallel hint(rarity 'L*')→ JP「L*」(id=1)に解決。"""
    it = sp._match_item(_SB, "SB02-033", variant_hint=_PARA_HINT)
    assert it is not None and it["id"] == 1


def test_no_hint_ambiguous_is_failclosed():
    """hint無 → JP L と L* で曖昧 → None(誤variant買わない=fail-closed)。"""
    assert sp._match_item(_SB, "SB02-033") is None


def test_en_only_yields_no_match():
    """EN版しか無ければ JP再仕入れ対象なし → None(EN は別カード)。"""
    en_only = {"streetwears": [_SB["streetwears"][2], _SB["streetwears"][3]]}
    assert sp._match_item(en_only, "SB02-033", variant_hint=_BASE_HINT) is None
