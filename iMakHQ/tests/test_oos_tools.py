#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在庫切れ対応ツール A(restock_worklist) / B(cull_end) の回帰テスト。

B の安全策 (2026-06-05 ユーザー合意) が崩れないことを固定する:
  - age>=21日 のみ (NEW_WAIT補正)
  - age 不明(0)は fail-closed で対象外
  - CAP 50件/回 (burst禁止)
  - age 降順・同 age は価格昇順
A: G-SHOCK は型番=完全一致キーワード / dedup は title で集約。
"""
import importlib.util
import os

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_TOOLS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cull_end = _load("cull_end")
restock = _load("restock_worklist")


def _row(item_id, flags="CULL", age=100, price=10.0, **kw):
    r = {"item_id": item_id, "flags": flags, "age_days": str(age), "price": str(price),
         "title": kw.get("title", "x"), "site": kw.get("site", "US"),
         "sold_qty": str(kw.get("sold", 0)), "sales90": "0", "watch": str(kw.get("watch", 0))}
    return r


# ---------- B: cull_end.select ----------
def test_cull_excludes_young_and_unknown_age():
    rows = [
        _row("a", age=100),          # OK
        _row("b", age=20),           # age<21 → 除外
        _row("c", age=0),            # age不明 → fail-closed 除外
        _row("d", age=21),           # 境界 OK
        _row("e", flags="RESTOCK", age=100),  # CULL でない → 除外
    ]
    _cull, eligible, picked = cull_end.select(rows)
    ids = {r["item_id"] for r in eligible}
    assert ids == {"a", "d"}
    assert all(cull_end._i(r["age_days"]) >= 21 for r in picked)


def test_cull_cap_limits_50():
    rows = [_row(str(i), age=30 + i) for i in range(120)]
    _cull, eligible, picked = cull_end.select(rows)
    assert len(eligible) == 120
    assert len(picked) == 50


def test_cull_order_oldest_then_cheapest():
    rows = [
        _row("old_cheap", age=300, price=50),
        _row("old_exp", age=300, price=200),
        _row("new", age=30, price=5),
    ]
    _cull, _elig, picked = cull_end.select(rows)
    assert [r["item_id"] for r in picked] == ["old_cheap", "old_exp", "new"]


def test_cull_custom_cap():
    rows = [_row(str(i), age=30 + i) for i in range(10)]
    _cull, _elig, picked = cull_end.select(rows, cap=3)
    assert len(picked) == 3


# ---------- A: restock_worklist ----------
def test_restock_gshock_keyword_is_model():
    kw = restock.mercari_kw("G-SHOCK", "CASIO G-SHOCK GXW-56-1AJF King of G Solar Radio Black")
    assert kw == "GXW-56-1AJF"


def test_restock_jp_vein_uses_facet_seed():
    assert restock.mercari_kw("PORTER", "PORTER Tanker 2Way Shoulder Bag Black Nylon") == "PORTER タンカー 2Way"
    assert restock.mercari_kw("一番くじ", "Ichiban Kuji Jujutsu Kaisen I Prize Figure") == "一番くじ Jujutsu"


def test_restock_keep_us_only():
    rows = [
        _row("1", flags="RESTOCK", title="On US", site="US", watch=2),
        _row("2", flags="RESTOCK", title="On US", site="UK", watch=1),   # 同商品の非US行
        _row("3", flags="RESTOCK", title="NonUS only", site="DE", watch=3),  # US無 → 除外
    ]
    us, dropped = restock.keep_us(rows)
    assert {r["item_id"] for r in us} == {"1"}   # US 行のみ
    assert dropped == 1                          # "NonUS only" 1商品が落ちる


def test_restock_dedup_aggregates_sites_and_demand():
    rows = [
        _row("1", flags="RESTOCK", title="Same Item", site="US", sold=1, watch=2),
        _row("2", flags="RESTOCK", title="Same Item", site="UK", sold=0, watch=3),
        _row("3", flags="RESTOCK", title="Other", site="DE", sold=0, watch=1),
    ]
    items = restock.dedup_by_title(rows)
    same = next(d for d in items if d["title"] == "Same Item")
    assert same["sites"] == {"US", "UK"}
    assert same["sold"] == 1 and same["watch"] == 5
    assert len(items) == 2


if __name__ == "__main__":
    import pytest
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
