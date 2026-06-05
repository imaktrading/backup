# -*- coding: utf-8 -*-
"""取下再出品② — mercari_to_ebay_csv --relist の skumap/即liveヘルパ。

2026-06-06: リール等 mercari カテゴリにも --relist 追加(指定URLのみ即live再出品)。
無在庫方針で価格ALERTのHOLDを relist時 bypass。SKU規約がカテゴリ別(reel=末尾12)で
pending sku と食い違うため、出品くんが付けた実 sku を skumap に記録 → ③書戻しの権威。
本テストは skumap 追記と即liveスケジュール(network無し)を検証。
"""
import csv
import importlib.util
import os

import pytest

_MERCARI = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakMercari", "mercari_to_ebay_csv.py"))


@pytest.fixture(scope="module")
def m():
    # mercari_to_ebay_csv は import 時に相対パス "API key.txt" を開くため、当該 dir で import
    prev = os.getcwd()
    os.chdir(os.path.dirname(_MERCARI))
    try:
        spec = importlib.util.spec_from_file_location("mercari_to_ebay_csv_relist", _MERCARI)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        os.chdir(prev)
    return mod


def test_append_skumap_creates_header_and_rows(m, tmp_path):
    pending = str(tmp_path / "relist_pending_20260606.csv")
    # append_skumap は pending パスの "relist_pending_" を "relist_skumap_" に置換した先へ追記
    m.append_skumap(pending, "p/B08NP6PKZM", "https://www.amazon.co.jp/dp/B08NP6PKZM", "reel")
    m.append_skumap(pending, "ZP37Dt8Zoaof", "https://jp.mercari.com/shops/product/2JNysv3RcsZP37Dt8Zoaof", "reel")
    skumap = str(tmp_path / "relist_skumap_20260606.csv")
    assert os.path.exists(skumap)
    rows = list(csv.DictReader(open(skumap, encoding="utf-8-sig")))
    assert [r["sku"] for r in rows] == ["p/B08NP6PKZM", "ZP37Dt8Zoaof"]
    assert rows[0]["supply_url"].endswith("B08NP6PKZM")
    assert rows[0]["category"] == "reel"
    # 末尾12規約(p/B08NP6PKZM) は pending の ASIN と食い違う = skumap が ③の橋渡しに必須


def test_append_skumap_noop_without_pending(m, tmp_path):
    # pending パス空なら何もしない (通常出品時に skumap を作らない)
    m.append_skumap("", "x", "y", "reel")  # 例外を出さず no-op
    assert not list(tmp_path.glob("relist_skumap_*.csv"))


def test_immediate_schedule_blank(m):
    # 即live = ScheduleTime 空欄 (過去時刻は eBay が reject=2026-06-06 実機判明)
    m._IMMEDIATE_SCHEDULE = True
    try:
        imm = m.get_schedule_time()
        m._IMMEDIATE_SCHEDULE = False
        future = m.get_schedule_time()
    finally:
        m._IMMEDIATE_SCHEDULE = False
    assert imm == ""        # 空欄=即時出品
    assert future != ""
