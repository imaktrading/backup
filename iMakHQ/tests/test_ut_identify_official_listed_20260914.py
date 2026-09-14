# -*- coding: utf-8 -*-
"""公式仕入で出品中の商品と同じメルカリ出品は、目視に出さない (2026-09-14)。

ユーザー「目視に、現役商品が出てるんだけど」→「そもそも候補に入れないで欲しい」「無駄な作業だから」
→「(公式仕入の出品シートと) 突き合わせしてないの？重複出品にもなるんだけど」→「うん」。
- 1件目 (ONE PIECE マンガUT) は、在庫なしの昔の商品3件と現役 (E487575・公式仕入で出品中) が
  素の点数で同点。売り切れ +2 で昔の商品が上に来て、現役が候補から隠れていた
- 目視待ち 672件中 99件 が「一番の候補に 公式仕入で出品中の商品がある」
"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import ut_identify as U  # noqa: E402


def _p(pid, l1, sold_out=True, tok=("one piece",), desc=""):
    return {"pid": pid, "l1": l1, "name": pid, "sold_out": sold_out, "colors": [],
            "_tok": [U.norm(t) for t in tok], "_desc": desc}


CAT = [_p("E478827-000", "478827"), _p("E480698-000", "480698"),
       _p("E487575-000", "487575", sold_out=False)]


def test_rank_order_is_unchanged_sold_out_first_on_tie():
    got = U.rank_candidates("新品 UNIQLO ONE PIECE Tシャツ XL", "", CAT, limit=0)
    assert [p["pid"] for p in got] == ["E478827-000", "E480698-000", "E487575-000"]
    scored = U.score_candidates("新品 UNIQLO ONE PIECE Tシャツ XL", "", CAT)
    assert len({sc for sc, _p in scored}) == 1                      # 素の点数は同点


def test_tie_with_an_officially_listed_product_is_excluded():
    scored = U.score_candidates("新品 UNIQLO ONE PIECE Tシャツ XL", "", CAT)
    assert U.officially_listed_best(scored, "", {"487575"}) == "E487575-000"
    assert U.officially_listed_best(scored, "", {"999999"}) == ""
    assert U.officially_listed_best(scored, "", None) == ""


def test_lower_score_listed_product_does_not_exclude():
    # E1 は説明にタイトルの語 (ルフィ) があり +5 で勝つ。出品中の E2 は点数が下なので外す理由にならない
    cat = [_p("E1", "111111", desc="ルフィ ギア5"), _p("E2", "222222", sold_out=False)]
    scored = U.score_candidates("ONE PIECE ルフィ Tシャツ", "", cat)
    assert max(scored, key=lambda x: x[0])[1]["pid"] == "E1"
    assert U.officially_listed_best(scored, "", {"222222"}) == ""


def _row(url, title):
    r = [""] * 40
    r[U.C_URL], r[U.C_TITLE] = url, title
    return r


def _patch_rows(monkeypatch, rows, official):
    monkeypatch.setattr(U, "load_ledger", lambda path=None: {})
    monkeypatch.setattr(U, "_product_values", lambda: [])
    monkeypatch.setattr(U, "_read_src", lambda: [])
    monkeypatch.setattr(U, "_high_urls", lambda prod=None: set())
    monkeypatch.setattr(U, "pending_rows", lambda src, led, high: list(enumerate(rows, 2)))
    monkeypatch.setattr(U, "sheet_pending_rows", lambda prod, led: [])
    monkeypatch.setattr(U, "load_demand", lambda *a, **k: {})
    monkeypatch.setattr(U, "load_catalog", lambda db=None: CAT + [_p("E459207-000", "459207", tok=("naruto",))])
    monkeypatch.setattr(U, "load_official_l1", lambda: official)


def test_excluded_rows_do_not_use_up_the_limit(monkeypatch):
    rows = [_row("https://jp.mercari.com/item/m1", "ONE PIECE Tシャツ"),
            _row("https://jp.mercari.com/item/m2", "NARUTO Tシャツ"),
            _row("https://jp.mercari.com/item/m3", "NARUTO Tシャツ L")]
    _patch_rows(monkeypatch, rows, {"487575"})
    stats = {}
    items, n = U.load_items(limit=2, stats=stats)
    assert [it["row"][U.C_URL][-2:] for it in items] == ["m2", "m3"]
    assert stats["official"] == 1 and n == 3


def test_listed_product_is_hidden_from_candidates(monkeypatch):
    rows = [_row("https://jp.mercari.com/item/m9", "ONE PIECE エッグヘッド Tシャツ")]
    cat = [_p("E1", "111111", tok=("one piece", "エッグヘッド")), _p("E487575-000", "487575", sold_out=False)]
    _patch_rows(monkeypatch, rows, {"487575"})
    monkeypatch.setattr(U, "load_catalog", lambda db=None: cat)
    items, _n = U.load_items(limit=5)
    assert all(p["l1"] != "487575" for it in items for p in it["cands"])


def test_unreadable_official_sheet_excludes_nothing(monkeypatch):
    import ut_catalog_values as UCV
    monkeypatch.setattr(UCV, "load_official_identities", lambda *a, **k: {})
    assert U.load_official_l1() is None
