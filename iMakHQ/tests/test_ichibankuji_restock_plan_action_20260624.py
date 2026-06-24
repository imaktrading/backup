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
