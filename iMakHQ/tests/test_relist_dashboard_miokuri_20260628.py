# -*- coding: utf-8 -*-
"""取下再出品ダッシュ: 見送り(B=9999)カテゴリ 回帰テスト (2026-06-28)。"""
import os, sys
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import relist_dashboard as rd  # noqa: E402
import relist_from_funnel as rf  # noqa: E402


def _frow(item_id, supply_url, price=100):
    return {"item_id": item_id, "price": str(price), "flags": "RELIST",
            "supply_url": supply_url, "category": "G-shock", "title": "T"}


def test_miokuri_9999_counted_separately():
    rows = [
        _frow("ok", "https://www.amazon.co.jp/dp/B000000001"),   # 未(B==fid)
        _frow("mi", "https://www.amazon.co.jp/dp/B000000009"),   # 見送り(B=9999)
        _frow("dn", "https://www.amazon.co.jp/dp/B000000002"),   # 済(B!=fid)
    ]
    b_map = {"B000000001": "ok", "B000000009": rf.MIOKURI_B, "B000000002": "newid123"}
    _out, s = rd.build_rows(rows, b_map, stock_index={}, times_map={})
    assert s["miokuri"] == 1     # 9999 は見送り
    assert s["done"] == 1        # B!=fid の通常分のみ(9999は済に数えない)
    assert s["todo"] == 1
