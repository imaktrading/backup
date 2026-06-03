"""listing_funnel.classify() の分類ロジック回帰テスト (2026-06-04, snapshot ベース)。

データ源 = Seller Hub snapshot (views/watchers/qty)。
qty==0(在庫切れ)は OUT_OF_STOCK に隔離し改善対象から外す。
改善切り口 (DEAD=views0 / STALE=多view無販売 / WATCHED=watch無販売) は在庫ありに限定。
ネットワークには触れない (classify は純関数)。
"""
import importlib.util
import os

import pytest

_SPEC_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools", "listing_funnel.py")
)
_spec = importlib.util.spec_from_file_location("listing_funnel", _SPEC_PATH)
listing_funnel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(listing_funnel)
classify = listing_funnel.classify


def _row(item_id, views=0, watch=0, sold=0, qty=1, age=10, site="US"):
    return {"item_id": item_id, "title": item_id, "price": 100.0, "site": site,
            "views": views, "watch": watch, "qty": qty, "listed": "",
            "age_days": age, "sold_qty": sold, "revenue": 0.0}


def test_dead_is_zero_views_in_stock():
    """在庫あり & views==0 → DEAD。views が付けば DEAD でない。"""
    rows = [
        _row("dead", views=0),
        _row("seen", views=5),     # 見られている → DEAD でない
    ]
    assert {r["item_id"] for r in classify(rows)["DEAD"]} == {"dead"}


def test_out_of_stock_excluded_from_dead():
    """qty==0(在庫切れ)は views==0 でも DEAD でなく OUT_OF_STOCK に隔離。"""
    rows = [
        _row("oos", views=0, qty=0),
        _row("dead", views=0, qty=1),
    ]
    c = classify(rows)
    assert {r["item_id"] for r in c["DEAD"]} == {"dead"}
    assert {r["item_id"] for r in c["OUT_OF_STOCK"]} == {"oos"}


def test_unknown_qty_treated_as_in_stock():
    """qty==-1(不明)は在庫あり扱い → DEAD 判定に乗る。"""
    c = classify([_row("u", views=0, qty=-1)])
    assert {r["item_id"] for r in c["DEAD"]} == {"u"}
    assert c["OUT_OF_STOCK"] == []


def test_dead_sorted_oldest_first():
    rows = [_row("new", views=0, age=10), _row("old", views=0, age=300), _row("mid", views=0, age=100)]
    assert [r["item_id"] for r in classify(rows)["DEAD"]] == ["old", "mid", "new"]


def test_stale_is_high_view_no_sale():
    """在庫あり & 累計views>=50 & 無販売 → STALE。売れていれば除外。"""
    rows = [
        _row("stale", views=200, sold=0),
        _row("sold", views=200, sold=2),     # 売れた → 除外
        _row("lowview", views=10, sold=0),   # view 不足 → 除外
    ]
    assert {r["item_id"] for r in classify(rows)["STALE"]} == {"stale"}


def test_watched_is_watch_no_sale():
    """在庫あり & watchers>=3 & 無販売 → WATCHED (watch 多い順)。"""
    rows = [
        _row("hot", views=100, watch=12, sold=0),
        _row("warm", views=100, watch=4, sold=0),
        _row("sold", views=100, watch=9, sold=2),    # 売れた → 除外
        _row("nowatch", views=100, watch=1, sold=0),  # watch 不足 → 除外
    ]
    assert [r["item_id"] for r in classify(rows)["WATCHED"]] == ["hot", "warm"]


def test_buy_intent_ratio_order_and_oos_excluded():
    """在庫あり & views>=10 & watch>0 を watch/view 比率順。在庫切れは除外。"""
    rows = [
        _row("hi", views=20, watch=10),      # 0.50
        _row("lo", views=100, watch=10),     # 0.10
        _row("oos", views=20, watch=20, qty=0),  # 在庫切れ → 除外
        _row("noview", views=5, watch=5),    # views<10 → 除外
    ]
    intent = classify(rows)["BUY_INTENT"]
    assert [r["item_id"] for r in intent] == ["hi", "lo"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
