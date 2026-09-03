# -*- coding: utf-8 -*-
"""同じ番号の別変種を掴まない — print種別は候補が1件でも見る (残務№64)。

## 実害
「補URL 候補26件が絞り込みで全滅。何回目視しても減らない」(2026-09-03)。
候補NG台帳 249件を分類したら **81件が『番号一致・変種違い』** だった
(例: 出品=ポートガス・D・エース(L) 通常 OP03-001 / 候補=リーダーパラレル OP03-001)。
人が外すたび台帳に積まれ、やがて候補が尽きて全滅する。

## 原因 (実測で再現した)
_variant_matches は set 確証のあと、候補が **1件だけなら print種別を見ずに返して**いた
(「set で一意」を理由にした近道)。同じものが2件あると正しく落ちる = **1件の時だけ緩い**
という逆さまの作りだった。

## 直し方
- 候補が print種別を **書いていて** target と違うなら、1件でも落とす
- 書いていない候補は落とさない。メルカリは変種を書かない出品が多く、
  落とすと在庫が実在するのに候補ゼロになる (2026-06-10 からの既存挙動を守る)
- 書いてあって一致する候補が在るなら、そちらを優先する
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOLS = os.path.join(_ROOT, "iMakHQ", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import mercari_psa_resource as mp                              # noqa: E402

HINT_NORMAL = ["謀略の王国【OP-03】", "", "Pillars of Strength", "", "L", "ポートガス・D・エース"]
HINT_PARA = ["謀略の王国【OP-03】", "alt_art", "Pillars of Strength", "", "L", "ポートガス・D・エース"]


def _it(name, price=9000):
    return {"price": price, "name": name, "href": "https://jp.mercari.com/item/m%d" % price}


PARA = _it("PSA10 ポートガス・D・エース リーダーパラレル OP03-001 謀略の王国")
NORM = _it("PSA10 ポートガス・D・エース OP03-001 謀略の王国")


def _names(items, hint):
    return [i["name"] for i in mp._variant_matches(items, "OP03-001", hint)]


def test_single_parallel_is_rejected_for_a_normal_target():
    """★これが直したかった穴。候補1件でも『パラレル』と書いてあれば落とす。"""
    assert _names([PARA], HINT_NORMAL) == []


def test_two_parallels_were_already_rejected():
    """2件ある時は前から落ちていた = 1件の時だけ緩かった、の証拠。"""
    assert _names([PARA, _it("PSA10 エース パラレル OP03-001 謀略の王国", 9500)],
                  HINT_NORMAL) == []


def test_normal_candidate_passes_for_a_normal_target():
    assert _names([NORM], HINT_NORMAL) == [NORM["name"]]


def test_parallel_passes_for_a_parallel_target():
    assert _names([PARA], HINT_PARA) == [PARA["name"]]


def test_silent_candidate_is_kept_for_a_parallel_target():
    """変種を書かない出品は落とさない (落とすと在庫が在るのに候補ゼロになる)。"""
    assert _names([NORM], HINT_PARA) == [NORM["name"]]


def test_explicit_match_wins_over_silent():
    """書いてあって一致する候補が在るなら、黙っている候補より優先する。"""
    got = _names([NORM, PARA], HINT_PARA)
    assert got == [PARA["name"]]
