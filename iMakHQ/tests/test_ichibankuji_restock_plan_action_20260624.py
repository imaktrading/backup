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


def test_restock_reqs_write_cost_to_N():
    """cost(新supply実価格)が N列(=col13)に入る。A/B/D も。"""
    reqs = r.build_restock_reqs({105: {"a": "https://x/mA", "b": "358111", "aux": [], "cost": 4500}})
    ranges = {q["range"]: q["values"][0][0] for q in reqs}
    assert ranges["A105"].endswith("mA")
    assert ranges["B105"] == "358111"
    assert ranges["D105"] == ""          # 売切解除
    assert ranges["N105"] == 4500        # 仕入価格 → N列(V8 SSOT)


def test_restock_reqs_no_cost_skips_N():
    """cost 無/0 の行は N列を書かない(既存cost を誤って消さない)。"""
    reqs = r.build_restock_reqs({106: {"a": "u", "b": "x", "aux": [], "cost": 0}})
    assert not any(q["range"].startswith("N") for q in reqs)


def test_restock_reqs_write_kuji_to_I():
    """公式くじURL(kuji)が I列(=col8)に入る(refresh用)。無い行は I列を書かない。"""
    reqs = r.build_restock_reqs({110: {"a": "u", "b": "x", "aux": [], "cost": 17000,
                                       "kuji": "https://1kuji.com/products/jojo"}})
    ranges = {q["range"]: q["values"][0][0] for q in reqs}
    assert ranges["I110"] == "https://1kuji.com/products/jojo"
    reqs2 = r.build_restock_reqs({111: {"a": "u", "b": "x", "aux": [], "cost": 8000}})
    assert not any(q["range"].startswith("I") for q in reqs2)


def test_confirmed_roundtrip_preserves_cost(tmp_path, monkeypatch):
    """expand で選んだ主supply価格(cost)が confirmed の save/load を生き残る
    (= refresh が壊れた fetch_mercari_price に頼らず実価格を使える)。"""
    monkeypatch.setattr(r, "CONFIRMED_FILE", str(tmp_path / "confirmed.json"))
    r._save_confirmed({105: {"item_id": "358284395775", "a": "https://jp.mercari.com/item/mX",
                             "aux": [], "cost": 4500}})
    got = r._load_confirmed()
    assert got[105]["cost"] == 4500
    assert got[105]["a"].endswith("mX")
