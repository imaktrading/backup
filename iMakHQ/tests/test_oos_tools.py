#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在庫切れ対応ツール A(restock_worklist) / B(cull_end) の回帰テスト。

B の安全策 (2026-06-05 ユーザー合意) が崩れないことを固定する:
  - age>=21日 のみ (NEW_WAIT補正)
  - age 不明(0)は fail-closed で対象外
  - CAP 200件/回 (burst禁止。2026-08-23 に 50→200)
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
noclick = _load("noclick_targets")
price_res = _load("price_resistance")
relist_tool = _load("relist_from_funnel")


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
    """1回あたりの件数に上限があること (burst 禁止)。

    ★2026-08-23 ユーザー指示で 50 → 200。理由: eBay 公式のとおり **月末時点で
      生きている出品は翌月の枠にも計上される** ので、月末までに落とせるかで
      翌月の出発点が変わる。残り約1,800件を 50/回 では間に合わない。
      上限そのものは残す (一括 End はしない)。
    """
    import cull_end
    assert cull_end.CAP == 200

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


# ---------- ④: noclick_targets ----------
def test_noclick_returns_all_noclick():
    rows = [
        {"flags": "NO_CLICK", "watch": "3", "price": "50", "title": "a"},   # watcher有
        {"flags": "NO_CLICK", "watch": "0", "price": "99", "title": "b"},   # watcher無 も対象
        {"flags": "NO_SEARCH", "watch": "5", "price": "10", "title": "c"},  # NO_CLICKでない → 除外
    ]
    assert {r["title"] for r in noclick.select(rows)} == {"a", "b"}


def test_noclick_order_by_price():
    rows = [
        {"flags": "NO_CLICK", "watch": "1", "price": "10", "title": "lo"},
        {"flags": "NO_CLICK", "watch": "3", "price": "300", "title": "hi"},
    ]
    assert [r["title"] for r in noclick.select(rows)] == ["hi", "lo"]   # 価格降順


def test_noclick_fix_method_by_watcher():
    assert "in-place" in noclick.fix_method(3)     # watcher有 → in-place推奨
    assert "relist" in noclick.fix_method(0)       # watcher無 → relist可


def test_noclick_fix_hint():
    assert "語数" in noclick.fix_hint(5, 10)        # 語数不足
    assert "写真" in noclick.fix_hint(15, 3)        # 写真不足
    assert "見直し" in noclick.fix_hint(15, 10)     # 両方足りてる → 一般ヒント


# ---------- 価格抵抗: price_resistance ----------
def test_clicks_reconstructed_from_ctr_times_impr():
    # clicks = ctr_total × impr_total
    assert round(price_res.clicks_of({"ctr_total": "0.02", "impr_total": "500"})) == 10


def test_proven_ref_prefers_gshock_series():
    vein_sold = {"G-SHOCK": [100, 200, 300]}
    series_sold = {"DW-5600": [150, 165]}
    # G-SHOCK DW-5600 → 系統基準(中央157.5/最高165) を vein より優先
    kind, med, mx = price_res.proven_ref("G-SHOCK", "Casio G-Shock DW-5600MNC-8A2JF", vein_sold, series_sold)
    assert kind == "系統" and mx == 165


def test_proven_ref_falls_back_to_vein_then_none():
    vein_sold = {"Montbell": [100, 139]}
    k1, _, mx1 = price_res.proven_ref("Montbell", "Montbell Plasma 1000", vein_sold, {})
    assert k1 == "vein" and mx1 == 139
    # 実績 vein が無い/1件のみ → なし
    k2, m2, mx2 = price_res.proven_ref("PORTER", "PORTER Tanker", {"PORTER": [200]}, {})
    assert k2 == "なし" and m2 is None


# ---------- 取下再出品: relist_from_funnel ----------
def test_relist_cap10_price_order_supply_required():
    # 2026-06-06: 半自動化で CAP=10 復活 + supply_url(行固定キー)必須に変更
    rows = [{"flags": "RELIST", "item_id": str(i), "price": str(i),
             "supply_url": f"https://jp.mercari.com/item/m{i:011d}"} for i in range(70)]
    rows.append({"flags": "NO_CLICK", "item_id": "x", "price": "999",
                 "supply_url": "https://jp.mercari.com/item/m99999999999"})  # RELIST 無 → 除外
    rows.append({"flags": "RELIST", "item_id": "nosup", "price": "999",
                 "supply_url": ""})  # supply_url 欠落 → 除外
    picked, total, skipped, already, oos, unsup = relist_tool.select(rows)
    assert total == 71                               # RELIST フラグ総数 (70 + nosup)
    assert skipped == 1                              # supply_url 欠落 1 件
    assert already == 0                              # sheet_b_map 未指定 → 除外なし
    assert len(picked) == 10                         # CAP=10
    assert picked[0]["item_id"] == "69"              # 価格(利益)降順
    assert all(r["item_id"] not in ("x", "nosup") for r in picked)


if __name__ == "__main__":
    import pytest
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
