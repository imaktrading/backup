"""捨てた候補 → 新規出品の種: 目視の前に売り切れを外す (2026-09-15 ユーザー判断).

「売り切れていない方がいいよね。無駄な作業だし」。在庫が判らない物は従来どおり見せる。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import newcand_confirm as N  # noqa: E402


def _it(url, dups=(), **kw):
    d = {"url": url, "title": url, "variants": [], "card_no": "", "dups": [{"url": u, "title": u} for u in dups]}
    d.update(kw)
    return d


def test_sold_candidate_is_not_shown():
    keep, sold = N.split_by_stock([_it("a"), _it("b")], {"a": "sold", "b": "in_stock"})
    assert [k["url"] for k in keep] == ["b"]
    assert [s["url"] for s in sold] == ["a"]


def test_unknown_is_still_shown():
    """判らない物を消さない (候補を減らす側に倒さない)。"""
    keep, sold = N.split_by_stock([_it("a"), _it("b")], {"a": "unknown"})
    assert [k["url"] for k in keep] == ["a", "b"] and sold == []


def test_sold_dups_are_removed():
    keep, sold = N.split_by_stock([_it("a", dups=["a2", "a3"])], {"a2": "sold"})
    assert [d["url"] for d in keep[0]["dups"]] == ["a3"]
    assert [s["url"] for s in sold] == ["a2"]


def test_live_dup_takes_over_when_head_is_sold():
    """代表が売り切れでも、同じカードの生きている仕入元があれば そちらを見せる。"""
    keep, sold = N.split_by_stock([_it("a", dups=["a2", "a3"], card_no="OP01-001")],
                                  {"a": "sold", "a2": "in_stock"})
    assert [k["url"] for k in keep] == ["a2"]
    assert keep[0]["card_no"] == "OP01-001"
    assert [d["url"] for d in keep[0]["dups"]] == ["a3"]
    assert [s["url"] for s in sold] == ["a"]


def test_index_is_renumbered():
    keep, _ = N.split_by_stock([_it("a"), _it("b"), _it("c")], {"b": "sold"})
    assert [k["idx"] for k in keep] == [0, 1]
