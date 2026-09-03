#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""視覚確証の候補を「同番号の全変種」複数で出す (2026-06-22)。

ユーザー要望: 候補を複数(別変種含む)出せば、同番号別変種の取り違え→「違う」再検索の繰り返しが消える。
mercari を最安1件でなく all_cands(variant_hint無=全変種)で並べる。
"""
import os
import sys
import importlib.util

_P = os.path.join(os.path.dirname(__file__), "..", "tools", "psa_resource_gate.py")
_spec = importlib.util.spec_from_file_location("psa_resource_gate", _P)
import pytest
try:
    g = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(g)
    _LOADED = True
except Exception:
    _LOADED = False
pytestmark = pytest.mark.skipif(not _LOADED, reason="psa_resource_gate import 不可")


def test_uses_all_cands_multiple_variants():
    """all_cands(全変種)を複数候補として出す。"""
    mr = {"best": (39000, "u_prb02", "レベッカ SP OP05-091 PRB-02"),
          "cands": [(39000, "u_prb02", "レベッカ SP OP05-091 PRB-02")],
          "all_cands": [(39000, "u_prb02", "レベッカ SP PRB-02"),
                        (52000, "u_op05", "レベッカ OP05-091 新時代")]}
    c = {"snkrdunk_urls": [], "mercari_url": "u_prb02", "mercari_jpy": 39000}
    out = g._build_visual_candidates(mr, c)
    urls = [x["url"] for x in out]
    assert "u_prb02" in urls and "u_op05" in urls, "別変種(OP-05)も候補に出る"
    assert out[0]["name"] and out[1]["name"], "変種名を保持(判別用)"


def test_fallback_to_cands_then_best():
    """all_cands 無い古cacheは cands、それも無ければ best。"""
    mr = {"best": (100, "b", "x"), "cands": [(100, "b", "x")]}  # all_cands なし
    c = {"snkrdunk_urls": [], "mercari_url": "b", "mercari_jpy": 100}
    out = g._build_visual_candidates(mr, c)
    assert [x["url"] for x in out] == ["b"]

    # ★2026-09-04: 価格の下限 (¥100) を入れたので、フォールバックの検査には
    #   ありえる値を使う (¥5 は「安すぎる」で落ちる = それ自体は正しい動き)。
    out2 = g._build_visual_candidates(
        {}, {"mercari_url": "b2", "mercari_jpy": 5000, "snkrdunk_urls": []})
    assert out2 and out2[0]["url"] == "b2", "mrもcandsも無ければ best フォールバック"


def test_includes_snkrdunk_and_dedups():
    mr = {"all_cands": [(100, "m1", "n1")]}
    c = {"snkrdunk_urls": [{"url": "s1", "price": 200, "image": "img1"},
                           {"url": "m1", "price": 90, "image": "img2"}]}  # m1 重複
    out = g._build_visual_candidates(mr, c)
    urls = [x["url"] for x in out]
    assert urls.count("m1") == 1, "重複URLは1回"
    assert "s1" in urls


def test_empty():
    assert g._build_visual_candidates({}, {}) == []
