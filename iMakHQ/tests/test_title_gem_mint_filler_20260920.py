# -*- coding: utf-8 -*-
"""レアリティが公式に無い行のタイトルを `Gem Mint` で埋める (2026-09-20)。

ユーザー指示 (2026-09-20)。公式にレアリティ表示が無いカード (pokemon_tcg だけで 9,729行)
はタイトルが 53〜69字になり、監査が毎回「キーワード不足」を出していた。
`Gem Mint` は PSA 10 の正式な呼び名で全 PSA10 行に当てはまる事実 (推測語ではない)。
優先度は最下位 = **余った枠だけ**使うので、レアリティ/年号が入る行は今までと変わらない。
"""
from __future__ import annotations

import sys
from pathlib import Path

_TCG = Path(__file__).resolve().parents[2] / "iMakTCG"
if str(_TCG) not in sys.path:
    sys.path.insert(0, str(_TCG))

import tcg_listing_fields as T  # noqa: E402


def _f(**kw):
    f = {"C:Game": "Pokemon TCG", "C:Language": "Japanese",
         "C:Set": "S4a: Shiny Star V", "C:Card Number": "071", "C:Character": "Gengar"}
    f.update(kw)
    return f


def test_レアリティが無い時は埋まる():
    t = T.build_title_from_fields(_f())
    assert t.endswith("Gem Mint"), t
    assert len(t) <= 80


def test_レアリティがある時は末尾に来る():
    """同定語を押し出さない (足せる時だけ足す)。"""
    t = T.build_title_from_fields(_f(**{"C:Rarity": "Special Art Rare"}))
    assert "Special Art Rare" in t
    assert len(t) <= 80


def test_枠が無ければ足さない():
    long_set = "Sun & Moon Team Up Ultra Shiny Full Art Secret Rare Collection Box"
    t = T.build_title_from_fields(_f(**{"C:Set": long_set}))
    assert len(t) <= 80


def test_PSA10以外には足さない():
    """`Gem Mint` は PSA 10 の呼び名。9 以下に付けたら誤記になる。"""
    t = T.build_title_from_fields(_f(), grade="9")
    assert "Gem Mint" not in t


def test_同じ語が既に在れば足さない():
    t = T.build_title_from_fields(_f(**{"C:Rarity": "Gem Mint"}))
    assert t.lower().count("gem mint") == 1, t
