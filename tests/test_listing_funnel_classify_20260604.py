"""listing_funnel.classify() の分類ロジック回帰テスト (2026-06-04, Seller Hub レポート版)。

LQR(impressions/CTR) で views=0 を「検索に出ない / クリックされない / 買われない」に分解。
qty==0(在庫切れ)は OUT_OF_STOCK に隔離。改善切り口は在庫あり(qty!=0)限定。
ネットワーク非依存 (classify は純関数)。
"""
import importlib.util
import os

import pytest

_SPEC = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools", "listing_funnel.py"))
_spec = importlib.util.spec_from_file_location("listing_funnel", _SPEC)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)
classify = mod.classify


def _row(item_id, impr=0.0, ctr=0.0, sold=0, sales90=0, watch=0, qty=1,
         price=100.0, trend=0.0, has_lqr=True, age=60, site="US"):
    return {"item_id": item_id, "title": item_id, "site": site, "category": "X",
            "qty": qty, "sold_qty": sold, "sales90": sales90, "watch": watch,
            "price": price, "trend_price": trend, "impr": impr, "ctr": ctr,
            "has_lqr": has_lqr, "age_days": age, "photos": 3, "keywords": 8}


def test_no_search_is_zero_impressions_in_stock():
    """在庫あり & 出品>=21日 & impr/日<=3 → NO_SEARCH(検索に出ていない)。"""
    rows = [
        _row("dark", impr=1, age=60),
        _row("shown", impr=50, ctr=0.05),
    ]
    assert {r["item_id"] for r in classify(rows)["NO_SEARCH"]} == {"dark"}


def test_new_listing_excluded_from_no_search():
    """適正化: 新規出品(<21日)でimpr低は時間不足 → NEW_WAIT に隔離、NO_SEARCH に入れない。"""
    rows = [
        _row("new", impr=1, age=5),    # 新規 → NEW_WAIT
        _row("old", impr=1, age=90),   # 古い → NO_SEARCH
        _row("unknown", impr=1, age=0),  # age不明 → 安全側で NO_SEARCH に残す
    ]
    c = classify(rows)
    assert {r["item_id"] for r in c["NEW_WAIT"]} == {"new"}
    assert {r["item_id"] for r in c["NO_SEARCH"]} == {"old", "unknown"}


def test_buckets_sorted_by_price():
    """適正化: NO_SEARCH は利益額(価格)高い順。"""
    rows = [_row("cheap", impr=1, age=60, price=50), _row("rich", impr=1, age=60, price=500)]
    order = [r["item_id"] for r in classify(rows)["NO_SEARCH"]]
    assert order == ["rich", "cheap"]


def test_out_of_stock_excluded():
    """qty==0 は impr0 でも NO_SEARCH でなく OUT_OF_STOCK。"""
    rows = [_row("oos", impr=0, qty=0), _row("dark", impr=0, qty=1)]
    c = classify(rows)
    assert {r["item_id"] for r in c["NO_SEARCH"]} == {"dark"}
    assert {r["item_id"] for r in c["OUT_OF_STOCK"]} == {"oos"}


def test_no_click_is_shown_but_low_ctr():
    """impr十分だが CTR 下位25% → NO_CLICK。高CTRは除外。"""
    rows = [
        _row("strong", impr=50, ctr=0.05, sold=1),
        _row("ok1", impr=50, ctr=0.04),
        _row("ok2", impr=50, ctr=0.03),
        _row("weak", impr=50, ctr=0.001),   # 下位 → NO_CLICK
    ]
    ids = {r["item_id"] for r in classify(rows)["NO_CLICK"]}
    assert "weak" in ids and "strong" not in ids


def test_no_convert_is_clicked_but_unsold():
    """CTR 良好(上位)だが無販売 → NO_CONVERT。売れていれば除外。"""
    rows = [
        _row("a", impr=50, ctr=0.04),
        _row("b", impr=50, ctr=0.05),
        _row("c", impr=50, ctr=0.06),
        _row("hot_unsold", impr=50, ctr=0.50, sold=0),   # 高CTR・無販売
        _row("hot_sold", impr=50, ctr=0.50, sold=2),     # 売れた → 除外
    ]
    ids = {r["item_id"] for r in classify(rows)["NO_CONVERT"]}
    assert "hot_unsold" in ids
    assert "hot_sold" not in ids


def test_overpriced_vs_trend():
    """価格 > 適正価格×1.05 → OVERPRICED。差額大きい順。"""
    rows = [
        _row("over", impr=20, ctr=0.03, price=150, trend=100),  # +50%
        _row("fair", impr=20, ctr=0.03, price=102, trend=100),  # +2% → 除外
        _row("notrend", impr=20, ctr=0.03, price=150, trend=0),  # trend無 → 除外
    ]
    assert {r["item_id"] for r in classify(rows)["OVERPRICED"]} == {"over"}


def test_relist_is_all_nosearch_and_noclick():
    """取下げ再出品候補 = NO_SEARCH+NO_CLICK 全件 (watcher有も含む=ブースト+全項目再生成 > watcher保持)。

    2026-06-05: NO_SEARCH のみ → watcher無 NS+NC → 全 NS+NC へ段階拡張 (ユーザー判断)。
    """
    rows = [
        _row("ns_nw", impr=1, age=60, watch=0),               # NO_SEARCH watcher無
        _row("ns_w", impr=1, age=60, watch=4),                # NO_SEARCH watcher有
        _row("nc_nw", impr=50, ctr=0.001, age=60, watch=0),   # NO_CLICK watcher無
        _row("nc_w", impr=50, ctr=0.001, age=60, watch=4),    # NO_CLICK watcher有
        _row("good", impr=50, ctr=0.5, age=60, sold=2),       # 高CTR・販売有 → 問題バケツ外
    ]
    c = classify(rows)
    assert {r["item_id"] for r in c["RELIST"]} == {"ns_nw", "ns_w", "nc_nw", "nc_w"}
    assert {r["item_id"] for r in c["NO_SEARCH"]} == {"ns_nw", "ns_w"}


def test_out_of_stock_split_restock_vs_cull():
    """在庫切れは需要シグナルで分岐: 過去販売/watch/90d販売 有=RESTOCK, 皆無=CULL。需要大きい順。"""
    rows = [
        _row("sold_oos", qty=0, sold=3, watch=0),     # 過去販売 → RESTOCK
        _row("watch_oos", qty=0, sold=0, watch=5),    # watcher → RESTOCK
        _row("s90_oos", qty=0, sold=0, watch=0, sales90=2),  # 90d販売 → RESTOCK
        _row("dead_oos", qty=0, sold=0, watch=0, sales90=0),  # 需要皆無 → CULL
    ]
    c = classify(rows)
    assert {r["item_id"] for r in c["RESTOCK"]} == {"sold_oos", "watch_oos", "s90_oos"}
    assert {r["item_id"] for r in c["CULL"]} == {"dead_oos"}
    # 需要大きい順: sold_oos(3)+? ... watch_oos(5) が先頭
    assert c["RESTOCK"][0]["item_id"] == "watch_oos"


def test_in_stock_not_in_restock_or_cull():
    """在庫あり listing は RESTOCK/CULL に入らない (在庫切れ専用)。"""
    rows = [_row("instock", qty=1, watch=9, sold=0, impr=50, ctr=0.04)]
    c = classify(rows)
    assert c["RESTOCK"] == [] and c["CULL"] == []


def test_non_lqr_falls_back_to_simple():
    """LQR 非対象(非US等)は impr/CTR が無いので watch/sold ベースの DEAD_SIMPLE。"""
    rows = [
        _row("nolqr_dead", has_lqr=False, site="AU", watch=0, sold=0),
        _row("nolqr_watch", has_lqr=False, site="AU", watch=5, sold=0),  # watch有 → 除外
    ]
    c = classify(rows)
    assert {r["item_id"] for r in c["DEAD_SIMPLE"]} == {"nolqr_dead"}
    assert c["NO_SEARCH"] == []  # LQR 無は funnel 段階に入らない


def test_us_ebay_url_prefers_us_listing():
    """eBayリンクは同タイトルの US 出品(USD)に解決。US無ければ自サイト item_id。"""
    active = {
        "111": {"title": "PSA 10 One Piece OP09-061 Luffy", "site": "US"},
        "222": {"title": "PSA 10 One Piece OP09-061 Luffy", "site": "AU"},
        "333": {"title": "G-SHOCK GA-2100 (UK only)", "site": "UK"},
    }
    us_map = mod.build_us_title_map(active)
    # AU 行 → US(111) に解決
    au_row = {"item_id": "222", "title": "PSA 10 One Piece OP09-061 Luffy"}
    assert mod.us_ebay_url(au_row, us_map) == "https://www.ebay.com/itm/111"
    # US 出品が無いカード → 自分の item_id
    uk_row = {"item_id": "333", "title": "G-SHOCK GA-2100 (UK only)"}
    assert mod.us_ebay_url(uk_row, us_map) == "https://www.ebay.com/itm/333"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
