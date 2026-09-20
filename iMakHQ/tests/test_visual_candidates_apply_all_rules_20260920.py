# -*- coding: utf-8 -*-
"""目視に出す一覧は、**見せる時にも** 全部の門を通す (2026-09-20)。

ユーザー「同じようなこと二度とするなよ。他のボタンも同じやぞ」。
探す時だけ門を置くと、**既に貯まった cache から出続ける**。見せる時にも同じ門を通せば、
cache が古くても画面には出ない。この4つが1つでも外れたら、ここが赤になる。

  1. 買えないと判明済の URL      (not_buyable)
  2. 仕入上限を超える値段        (cost_sanity)
  3. まとめ売り/連番             (_is_lot)
  4. 絵柄が複数あるカードの番号未確認枠 (2026-09-20 追加)

実測 2026-09-20 の cache 2,137本: 1が337本・2が63本・3が5本 残っていたが、
1〜3 は見せる時に落ちていたので画面には出ていなかった。4 だけ門が無く、
83出品/392本 が毎日出ていた。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(r"C:\dev\iMak\iMakHQ", "tools"))

import psa_resource_gate as G  # noqa: E402

SRC = open(os.path.join(r"C:\dev\iMak\iMakHQ", "tools", "psa_resource_gate.py"),
           encoding="utf-8").read()
BODY = SRC.split("def _build_visual_candidates(")[1].split("\ndef ", 1)[0]


def test_買えないURLの門がある():
    assert "load_not_buyable" in BODY and "_ng_urls" in BODY


def test_仕入上限の門がある():
    assert "cost_sanity" in BODY


def test_まとめ売りの門がある():
    assert "_is_lot" in BODY


def test_多変種の番号未確認枠の門がある():
    assert "_is_multi_variant" in BODY


def test_どのカードかを受け取れる():
    """呼ぶ側が どのカードか を渡せないと 4 の門は効かない。"""
    import inspect
    p = inspect.signature(G._build_visual_candidates).parameters
    assert "card_no" in p and "category" in p


def test_補URLの目視がカードを渡している():
    hoju = open(os.path.join(r"C:\dev\iMak\iMakHQ", "tools", "psa_hoju_fill.py"),
                encoding="utf-8").read()
    assert "_build_visual_candidates(mr, c, card_no=" in hoju
