# -*- coding: utf-8 -*-
"""セット名/レアリティの言い換え表は1本だけ (2026-08-21).

★2026-08-21 ユーザー指摘で棚卸しした結果、この6表が
  `psa_to_csv.py` と `psa_restock_csv.py` に **同じ内容で2本ずつ**あった。
  片方だけ直せば即ズレる = 直し依頼が繰り返される発生源のひとつ
  (set/rarity 絡みの依頼は3ヶ月で65本)。

  この test は「また2本に戻る」のを防ぐためのもの。
"""
from __future__ import annotations

import ast
import io
import os

TCG = r"C:\dev\iMak\iMakTCG"
NAMES = ["_DRAGONBALL_SET_NAME_MAP", "_RARITY_FULL_FOR_TITLE", "_RARITY_TO_FEATURES",
         "DRAGONBALL_SET_PREFIX", "GUNDAM_SET_PREFIX", "POKEMON_SET_NAME_MAP"]


def _top_level_assigns(path):
    src = io.open(path, encoding="utf-8").read()
    return {n.targets[0].id for n in ast.parse(src).body
            if isinstance(n, ast.Assign) and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)}


def test_共有モジュールが表を持っている():
    got = _top_level_assigns(os.path.join(TCG, "tcg_set_rarity_maps.py"))
    assert set(NAMES) <= got


def test_生成器の中で再定義していない():
    """★ここに定義を書き戻したら、また2本になる."""
    for f in ("psa_to_csv.py", "psa_restock_csv.py"):
        got = _top_level_assigns(os.path.join(TCG, f))
        again = sorted(set(NAMES) & got)
        assert not again, "%s が表を再定義している: %s" % (f, again)


def test_両方が同じ物を見ている():
    import sys
    sys.path.insert(0, TCG)
    import psa_restock_csv as B                                  # noqa: E402
    import psa_to_csv as A                                       # noqa: E402
    for n in NAMES:
        assert getattr(A, n) is getattr(B, n), n
