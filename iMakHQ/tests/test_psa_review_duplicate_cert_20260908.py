# -*- coding: utf-8 -*-
"""PSA目視: 同じ cert を2回出さない (2026-09-08 ユーザー報告).

> 最後の１個が合ってるを押せないんだけど

実測 (port 8765 の実ページ): カード16枚のうち cert 158452544 が2枚あり、
2枚目の id (btns_/target_/cand_) が1枚目と衝突していた。answer() は
getElementById で引くので、クリックは1枚目に効き、2枚目は無反応に見える。
回答数も Object.keys(ANSWERS) で数えるため 15/16 で止まり、
「未回答1件」が永久に消えない状態だった。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import post_psa_review as R          # noqa: E402


def test_duplicate_cert_is_folded():
    assert R.dedupe_certs_keep_order(["a", "b", "a"]) == ["a", "b"]


def test_order_is_kept():
    assert R.dedupe_certs_keep_order(["c", "a", "b"]) == ["c", "a", "b"]


def test_empty_and_none():
    assert R.dedupe_certs_keep_order([]) == []
    assert R.dedupe_certs_keep_order(None) == []


def test_viewer_uses_the_dedupe_before_building_targets():
    """目視リストを組み立てる前に畳んでいること (畳まないと id が衝突する)。"""
    src = open(os.path.join(ROOT, "tools", "post_psa_review.py"), encoding="utf-8").read()
    i = src.index("_uniq_c = dedupe_certs_keep_order(_viewer_certs)")
    j = src.index("for cert in _viewer_certs:", i)
    assert i < j, "畳む処理は targets 組み立てより前"
    assert "_viewer_certs = _uniq_c" in src[i:j]
