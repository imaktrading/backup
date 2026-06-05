# -*- coding: utf-8 -*-
"""取下再出品② — gshock_to_csv --relist モードの targets/価格据置ロジック。

2026-06-06: B空欄キュー(61件)を無視し保留リストの指定URLだけ即live再出品する
--relist モードを gshock_to_csv に追加。本テストはそのコア (load_relist_targets +
元価格維持 _RELIST_FORCE_PRICE) を検証。
"""
import csv
import importlib.util
import os

import pytest

_GSHOCK = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakG-shock", "gshock_to_csv.py"))


@pytest.fixture(scope="module")
def g():
    spec = importlib.util.spec_from_file_location("gshock_to_csv_relist", _GSHOCK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_pending(tmp_path, rows):
    p = tmp_path / "pending.csv"
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["sku", "old_item_id", "category", "supply_url", "price", "title"])
        w.writeheader()
        w.writerows(rows)
    return str(p)


def test_relist_targets_gshock_only_and_force_price(g, tmp_path):
    g._RELIST_FORCE_PRICE.clear()
    pending = _write_pending(tmp_path, [
        {"sku": "B0DDS4Z29W", "old_item_id": "357370826397", "category": "Wristwatches",
         "supply_url": "https://www.amazon.co.jp/dp/B0DDS4Z29W/?coliid=I29", "price": "525.98",
         "title": "CASIO G-SHOCK GM-2110D-2AJF Metal Bezel Band Silver Watch"},
        {"sku": "ZP37Dt8Zoaof", "old_item_id": "358545495042", "category": "Reels",  # reel → 除外
         "supply_url": "https://jp.mercari.com/shops/product/2JNysv3RcsZP37Dt8Zoaof", "price": "410.98",
         "title": "Shimano 17 Calcutta Conquest BFS HG Reel"},
    ])
    targets = g.load_relist_targets(pending)
    # G-shock(Wristwatches) 1件のみ、reel は除外
    assert len(targets) == 1
    url, model, price_jpy = targets[0]
    assert model == "GM-2110D-2AJF"          # URLでなく title から型番抽出
    assert price_jpy == ""                    # JPYコストは空(USD価格は別途強制)
    # 元の出品価格が強制維持dictに載る (¥5000 fallback の $90.98 誤価格を防ぐ)
    assert g._RELIST_FORCE_PRICE[url] == 525.98


def test_relist_targets_skips_partial_model(g, tmp_path):
    g._RELIST_FORCE_PRICE.clear()
    pending = _write_pending(tmp_path, [
        {"sku": "X", "old_item_id": "1", "category": "Wristwatches",
         "supply_url": "https://www.amazon.co.jp/dp/B0XXXXXXXX", "price": "200",
         "title": "CASIO G-Shock with no parseable model here"},
    ])
    targets = g.load_relist_targets(pending)
    assert targets == []                       # 型番抽出不可 → 除外 (Precision 100%)


def test_immediate_schedule_flag(g):
    # _IMMEDIATE_SCHEDULE True で get_schedule_time が即時(現在以前)を返す
    g._IMMEDIATE_SCHEDULE = True
    try:
        imm = g.get_schedule_time()
        g._IMMEDIATE_SCHEDULE = False
        future = g.get_schedule_time()
    finally:
        g._IMMEDIATE_SCHEDULE = False
    # 即時 < 通常(2週間後)
    assert imm < future
