#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""① 効果測定ループ funnel_diff の回帰テスト。

固定したい挙動 (2026-06-05 設計):
  - 突合: item_id一致=in_place / item_id消滅&同(title,site)再出現=relisted / どちらも無=gone
  - 判定: 売れた(sold増)=SOLD最優先 / 基準差ありなら バケツ移動を効果と見なさない(基準差判定不能) /
          同基準ならバケツ脱出=改善 / 同バケツ残=停滞
  - pl_based: impr_total に非ゼロがあれば PL累計世代 (organic-only 旧世代と区別)
"""
import importlib.util
import os

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_TOOLS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fd = _load("funnel_diff")


def _row(item_id, flags="NO_CLICK", title="g-shock dw-5600", site="US",
         sold=0, sales90=0, price=50.0, impr=5.0, impr_total=0.0, ctr=0.01, supply_url=""):
    return {"item_id": item_id, "flags": flags, "title": title, "site": site,
            "sold_qty": str(sold), "sales90": str(sales90), "price": str(price),
            "impr": str(impr), "impr_total": str(impr_total), "ctr": str(ctr),
            "ctr_total": "", "ebay_url": "", "supply_url": supply_url}


# ---------- pl_based ----------
def test_pl_based_detects_promo_aware_generation():
    assert fd.pl_based([_row("a", impr_total=120.0)]) is True
    assert fd.pl_based([_row("a", impr_total=0.0)]) is False   # organic-only 旧世代


# ---------- match_new ----------
def test_match_in_place_by_item_id():
    new = _row("a", title="x")
    nr, state = fd.match_new(_row("a", title="x"), {"a": new}, {})
    assert state == "in_place" and nr is new


def test_match_relisted_by_supply_url_when_id_and_title_change():
    # old "a" が消え、title も変わったが 同じ仕入元URL が新 id "b" で再出現 = 取下再出品された個体。
    # (relist は出品くんが title 再生成 → title 突合では追えない。仕入元URL=不変キーで追う)
    new = _row("b", title="completely different title", site="US", supply_url="https://m.jp/item/m111")
    by_supply = {"https://m.jp/item/m111": new}
    old = _row("a", title="g-shock dw-5600", site="US", supply_url="https://m.jp/item/m111")
    nr, state = fd.match_new(old, {"b": new}, by_supply)
    assert state == "relisted" and nr is new


def test_match_gone_when_no_id_and_no_supply_url():
    # supply_url 無し(旧世代CSV) で item_id も消滅 → relist 追跡不可 = gone
    nr, state = fd.match_new(_row("a", title="x", supply_url=""), {}, {})
    assert state == "gone" and nr is None


def test_match_no_false_relist_across_different_supply_urls():
    # 別商品(別仕入元URL)には絶対に誤マッチしない (title 偶然一致の偽陽性を防ぐ)
    new = _row("b", title="g-shock dw-5600", site="US", supply_url="https://m.jp/item/m999")
    by_supply = {"https://m.jp/item/m999": new}
    old = _row("a", title="g-shock dw-5600", site="US", supply_url="https://m.jp/item/m111")
    nr, state = fd.match_new(old, {"b": new}, by_supply)
    assert state == "gone" and nr is None


# ---------- verdict ----------
def test_verdict_sold_takes_priority_even_if_stuck():
    old = _row("a", flags="NO_CLICK", sold=0)
    new = _row("a", flags="NO_CLICK", sold=1)   # 同バケツでも売れたら SOLD
    vd, gain = fd.verdict(old, new, "in_place", comparable=True)
    assert vd == "SOLD" and gain == 1


def test_verdict_basis_diff_blocks_bucket_interpretation():
    # 基準差あり = バケツ移動を効果と見なさない (0604→0605 のロジック変更ケース)
    old = _row("a", flags="NO_SEARCH", sold=0)
    new = _row("a", flags="", sold=0)           # バケツを抜けてるが…
    vd, _ = fd.verdict(old, new, "in_place", comparable=False)
    assert vd == "基準差(判定不能)"


def test_verdict_improved_when_left_bucket_same_basis():
    old = _row("a", flags="NO_SEARCH", sold=0)
    new = _row("a", flags="", sold=0)
    vd, _ = fd.verdict(old, new, "in_place", comparable=True)
    assert vd == "改善(バケツ脱出)"


def test_verdict_stalled_when_stays_in_bucket():
    old = _row("a", flags="NO_CLICK", sold=0)
    new = _row("a", flags="NO_CLICK", sold=0)
    vd, _ = fd.verdict(old, new, "in_place", comparable=True)
    assert vd == "停滞(同バケツ残)"
