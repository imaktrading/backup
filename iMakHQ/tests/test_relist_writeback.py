# -*- coding: utf-8 -*-
"""取下再出品③書戻し (relist_writeback) の純粋ロジック検証。"""
import csv
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import relist_writeback as rw  # noqa: E402


def test_plan_overwrite_old_with_new():
    add_pairs = [("B0DDS4Z29W", "999000111222")]
    skumap = {"B0DDS4Z29W": "https://www.amazon.co.jp/dp/B0DDS4Z29W"}
    supply_to_row = {
        "https://www.amazon.co.jp/dp/B0DDS4Z29W": {"sheet": "スプシ2", "row": 279, "current_b": "357370826397"},
    }
    plan = rw.plan_writeback(add_pairs, skumap, supply_to_row)
    assert len(plan) == 1
    e = plan[0]
    assert e["status"] == "WRITE"           # 旧itemID残り → 上書き
    assert e["row"] == 279
    assert e["current_b"] == "357370826397"
    assert e["new_item_id"] == "999000111222"


def test_plan_skip_when_already_new():
    add_pairs = [("X", "555")]
    skumap = {"X": "u1"}
    supply_to_row = {"u1": {"sheet": "s", "row": 5, "current_b": "555"}}
    assert rw.plan_writeback(add_pairs, skumap, supply_to_row)[0]["status"] == "SKIP_SAME"


def test_plan_no_skumap_and_no_row():
    skumap = {"known": "u1"}
    supply_to_row = {}   # u1 が sheet に無い
    plan = rw.plan_writeback([("unknown", "1"), ("known", "2")], skumap, supply_to_row)
    by_sku = {e["sku"]: e["status"] for e in plan}
    assert by_sku["unknown"] == "NO_SKUMAP"   # skumap に無い sku
    assert by_sku["known"] == "NO_ROW"        # supply_url が sheet に無い


def test_plan_reel_sku_regime_mismatch_resolved_by_skumap():
    # Daiwa: Add結果の CustomLabel は mercari実値 'p/B08NP6PKZM' (pendingの 'B08NP6PKZM' でない)
    add_pairs = [("p/B08NP6PKZM", "777")]
    skumap = {"p/B08NP6PKZM": "https://www.amazon.co.jp/dp/B08NP6PKZM"}
    supply_to_row = {"https://www.amazon.co.jp/dp/B08NP6PKZM":
                     {"sheet": "スプシ2", "row": 645, "current_b": "358477829629"}}
    e = rw.plan_writeback(add_pairs, skumap, supply_to_row)[0]
    assert e["status"] == "WRITE" and e["row"] == 645   # skumapが橋渡し→正しい行に着地


def test_parse_add_report_and_skumap(tmp_path):
    # FileExchange Add結果レポート風 (ItemID/CustomLabel/Status 列)
    rep = tmp_path / "add_result.csv"
    with open(rep, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Line Number", "Action", "Status", "ItemID", "CustomLabel"])
        w.writerow(["2", "Add", "Success", "111222333444", "B0DDS4Z29W"])
        w.writerow(["3", "Add", "Failure", "", "B0F9JP4JX5"])   # 失敗行 → 除外
    pairs = rw.parse_add_report(str(rep))
    assert pairs == [("B0DDS4Z29W", "111222333444")]

    sk = tmp_path / "relist_skumap_x.csv"
    with open(sk, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["sku", "supply_url", "category"])
        w.writerow(["B0DDS4Z29W", "https://www.amazon.co.jp/dp/B0DDS4Z29W", "Wristwatches"])
    assert rw.load_skumap(str(sk)) == {"B0DDS4Z29W": "https://www.amazon.co.jp/dp/B0DDS4Z29W"}
