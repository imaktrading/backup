# -*- coding: utf-8 -*-
"""一番くじ refresh の状態分岐 plan_action 回帰テスト (2026-06-24)。

itemID を変えずに済むかは「今 eBay でどうなってるか」だけで決まる(監視くん無関係):
  Active → revise(同ID=view/watcher温存) / Completed → add(新ID=出し直し) / 不明 → skip(fail-closed)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "iMakeBayAPI")))

import ichibankuji_restock as r  # noqa: E402


def test_active_is_revise_same_id(monkeypatch):
    monkeypatch.setattr(r, "_ebay_status", lambda i: ("Active", 0))
    act, st, q = r.plan_action("358284395775")
    assert act == "revise" and st == "Active"


def test_completed_is_add_new_id(monkeypatch):
    monkeypatch.setattr(r, "_ebay_status", lambda i: ("Completed", 0))
    assert r.plan_action("358290872987")[0] == "add"


def test_unknown_status_is_skip_failclosed(monkeypatch):
    monkeypatch.setattr(r, "_ebay_status", lambda i: ("?", -1))
    assert r.plan_action("123")[0] == "skip"


def test_empty_itemid_is_skip(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(r, "_ebay_status", lambda i: called.__setitem__("n", called["n"] + 1) or ("Active", 0))
    assert r.plan_action("")[0] == "skip"
    assert called["n"] == 0   # 空itemIDは GetItem 呼ばない


def test_restock_reqs_write_cost_to_M():
    """★2026-08-02: cost 書込先を N列→M列に切替 (BRAVO 依頼書 D 項)。
    N列は ARRAYFORMULA (M or F)−K の spill 列で、1セル書込むと N1=#REF! で全空に
    なる同型事故 (ichibankuji_restock 実害 2026-07-27〜08-02) の再発防止。M seed に
    して監視くんの次巡回が上書きする一時 seed 運用に変更。"""
    reqs = r.build_restock_reqs({105: {"a": "https://x/mA", "b": "358111", "aux": [], "cost": 4500}})
    ranges = {q["range"]: q["values"][0][0] for q in reqs}
    assert ranges["A105"].endswith("mA")
    assert ranges["B105"] == "358111"
    assert ranges["D105"] == ""          # 売切解除
    assert ranges["M105"] == 4500        # 仕入価格 → M列(seed。N は ARRAYFORMULA が拾う)
    assert "N105" not in ranges          # ★N には二度と書かない (spill 破壊防止)


def test_restock_reqs_no_cost_skips_M():
    """cost 無/0 の行は M列を書かない(既存cost を誤って消さない)。"""
    reqs = r.build_restock_reqs({106: {"a": "u", "b": "x", "aux": [], "cost": 0}})
    assert not any(q["range"].startswith("M") for q in reqs)
    assert not any(q["range"].startswith("N") for q in reqs)


def test_restock_reqs_write_kuji_to_I():
    """公式くじURL(kuji)が I列(=col8)に入る(refresh用)。無い行は I列を書かない。"""
    reqs = r.build_restock_reqs({110: {"a": "u", "b": "x", "aux": [], "cost": 17000,
                                       "kuji": "https://1kuji.com/products/jojo"}})
    ranges = {q["range"]: q["values"][0][0] for q in reqs}
    assert ranges["I110"] == "https://1kuji.com/products/jojo"
    reqs2 = r.build_restock_reqs({111: {"a": "u", "b": "x", "aux": [], "cost": 8000}})
    assert not any(q["range"].startswith("I") for q in reqs2)


def test_write_supplies_records_original_itemid_no_ebay(monkeypatch):
    """Option B: expand/write は スプシ記録のみ。B列=既存itemID(relistしない)・eBay触らない。"""
    captured = {}
    monkeypatch.setattr(r, "write_restock", lambda sr: captured.update(rows=sr) or len(sr))
    monkeypatch.setattr(r, "_retry", lambda fn, **k: fn())   # リトライをインライン実行
    called = {"ebay": 0}
    monkeypatch.setattr(r, "ebay_restock", lambda *a, **k: called.__setitem__("ebay", called["ebay"] + 1) or ("x", "y"))
    n = r._write_supplies({105: {"item_id": "358", "a": "u", "aux": ["x", "y"], "cost": 4500,
                                 "kuji": "https://1kuji.com/j"}})
    sr = captured["rows"][105]
    assert sr["b"] == "358"            # 既存itemID(relist しない=stale無し)
    assert sr["cost"] == 4500 and sr["kuji"] == "https://1kuji.com/j" and sr["aux"] == ["x", "y"]
    assert called["ebay"] == 0         # eBay 在庫補充は呼ばない(refresh CSV入稿に一本化)


def test_confirmed_roundtrip_preserves_cost(tmp_path, monkeypatch):
    """expand で選んだ主supply価格(cost)が confirmed の save/load を生き残る
    (= refresh が壊れた fetch_mercari_price に頼らず実価格を使える)。"""
    monkeypatch.setattr(r, "CONFIRMED_FILE", str(tmp_path / "confirmed.json"))
    r._save_confirmed({105: {"item_id": "358284395775", "a": "https://jp.mercari.com/item/mX",
                             "aux": [], "cost": 4500}})
    got = r._load_confirmed()
    assert got[105]["cost"] == 4500
    assert got[105]["a"].endswith("mX")
