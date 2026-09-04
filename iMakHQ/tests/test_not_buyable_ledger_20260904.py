# -*- coding: utf-8 -*-
"""買えないと分かった URL は、どの出品でも二度と出さない (2026-09-04)。

ユーザー報告「PSA補URL③で m30195199994 AUC まだ出てるけど」。

## なぜ残っていたか (2つ)
1. オークションかどうかは **詳細ページを開かないと判らない**。全候補を毎回開くのは
   遅すぎるので、詳細を開くのは価格判定に使う `cands` だけだった。
   目視画面が並べるのは `all_cands` / `loose_cands` で、そちらは素通りしていた。
2. さらに **最後の逃げ道**があった:
     if not out and c.get("mercari_url"): out.append(...)
   上の枠で全部落として out が空になると、ここが同じ URL を入れ直していた。
   門を1つ足しても、抜け道が残っていれば意味がない。

## 直し方
一度 開いて「買えない」と分かった URL を台帳に覚え、以後どの出品でも出さない。
台帳は URL 単位 (候補NG台帳は 出品×URL 単位で別物)。
"""
import io as _io
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOLS = os.path.join(_ROOT, "iMakHQ", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import mercari_psa_resource as M                               # noqa: E402
import psa_resource_gate as G                                  # noqa: E402

AUC = "https://jp.mercari.com/item/m30195199994"
OK = "https://jp.mercari.com/item/m11111111111"


def test_ledger_round_trip(tmp_path):
    p = str(tmp_path / "nb.json")
    assert M.load_not_buyable(p) == {}          # 無い時は空 (候補を消す方に倒さない)
    M.remember_not_buyable(AUC, "オークション", p)
    d = M.load_not_buyable(p)
    assert list(d) == [AUC] and d[AUC]["why"] == "オークション"


def test_ledger_is_written_when_a_detail_says_not_buyable():
    s = _io.open(os.path.join(_TOOLS, "mercari_psa_resource.py"), encoding="utf-8").read()
    i = s.index("def _detail_supply_check")
    j = s.index(chr(10) + "def ", i + 10)
    assert "remember_not_buyable" in s[i:j], "詳細で分かったのに覚えていない"


def _cands(mr, c):
    return [x["url"] for x in G._build_visual_candidates(mr, c)]


def test_a_known_auction_is_not_shown(monkeypatch):
    monkeypatch.setattr(M, "load_not_buyable", lambda *a, **k: {AUC: {"why": "auction"}})
    mr = {"best": (19999, AUC, "n"), "cands": [(19999, AUC, "n")],
          "all_cands": [(19999, AUC, "n")]}
    c = G.combine(mr["best"], None, mercari_cands=mr["cands"])
    assert _cands(mr, c) == []


def test_the_last_resort_fallback_is_gated_too(monkeypatch):
    """★これが実体。上で全部落として空になった時の逃げ道も同じ門を通す。"""
    monkeypatch.setattr(M, "load_not_buyable", lambda *a, **k: {AUC: {"why": "auction"}})
    c = {"mercari_url": AUC, "mercari_jpy": 19999, "snkrdunk_urls": []}
    assert G._build_visual_candidates({}, c) == []
    # 買える URL なら従来どおり出る (落としすぎない)
    c2 = {"mercari_url": OK, "mercari_jpy": 9999, "snkrdunk_urls": []}
    assert [x["url"] for x in G._build_visual_candidates({}, c2)] == [OK]


def test_a_normal_candidate_still_shows(monkeypatch):
    monkeypatch.setattr(M, "load_not_buyable", lambda *a, **k: {AUC: {"why": "auction"}})
    mr = {"best": (9999, OK, "n"), "cands": [(9999, OK, "n")],
          "all_cands": [(19999, AUC, "n"), (9999, OK, "n")]}
    c = G.combine(mr["best"], None, mercari_cands=mr["cands"])
    assert _cands(mr, c) == [OK]
