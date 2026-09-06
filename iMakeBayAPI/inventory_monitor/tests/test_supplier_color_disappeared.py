"""仕入元から色が消えた時に売切扱いにする regression (2026-09-07).

★1丁目1番地 判定:
  ② 引き方 (監視の読み方) が「該当色 0 枠 = 何もしない」だった = ②が誤り
  → コード側で修正 (カタログには依頼を出さない)。

実害: 357100729078 (montbell サンダーパス Men's Orange) は 9/02 に Orange (HN/MA) が
公式ページから消えたが、監視は「在庫 0/0 あり、要対処 0」と読んで素通りし、
出品が 5 日間 生きたまま残ってオファーが来た (= fail-OPEN)。

切り分け:
  - ページは読めていて他の色が並んでいる (total_skus > 0) → この色は買えない = 売切扱い
  - ページから 1 枠も取れない (total_skus 0/無し)        → 判定不能なので触らない
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402


SHEET_ROWS = [
    # A     B      C   D(listing)      E      F(sku)   G(size) H(color) I  J(price) K(qty) L
    ["FALSE", "FALSE", "", "357100729078", "t", "Montbell", "XL", "HN/MA", "◎", "10850", "1", ""],
]


def _row():
    return {"listing_id": "357100729078", "title": "サンダーパス Men's Orange",
            "url": "https://webshop.montbell.jp/goods/disp_fo.php?product_id=1128635",
            "supplier": "montbell"}


def test_color_gone_from_supplier_is_treated_as_sold_out(monkeypatch):
    """他の色は取れているのに該当色が 0 枠 → 売切 (✕) + 要対処 (= qty=0 化に乗る)."""
    monkeypatch.setattr(main, "fetch_supplier_inventory", lambda *a, **k: {
        "name": "サンダーパス ジャケット Men's", "color": "HN/MA", "skus": [],
        "total_skus": 14, "available_color_codes": ["GP/OC", "NV/PB", "RDBR"],
    })
    res = main.process_listing(None, _row(), all_sku_rows=SHEET_ROWS)

    assert len(res["updates"]) == 1
    u = res["updates"][0]
    assert u["supplier_stock_mark"] == "✕"
    assert u["needs_action"] is True          # 仕入元 ✕ × eBay qty 1 → 対処要
    assert u["supplier_price"] == 10850        # 最後の価格は消さない
    assert res["needs_action_count"] == 1


def test_page_with_no_skus_at_all_is_left_untouched(monkeypatch):
    """ページから 1 枠も取れない = 判定不能 → シートも eBay も触らない (fail-closed)."""
    monkeypatch.setattr(main, "fetch_supplier_inventory", lambda *a, **k: {
        "name": "サンダーパス ジャケット Men's", "color": "HN/MA", "skus": [],
        "total_skus": 0, "available_color_codes": [],
    })
    res = main.process_listing(None, _row(), all_sku_rows=SHEET_ROWS)

    assert res["updates"] == []
    assert res["needs_action_count"] == 0
    assert res["error"] == "supplier_page_returned_no_skus"


def test_total_skus_missing_is_also_left_untouched(monkeypatch):
    """total_skus を持たない supplier (= 色フィルタ無し) の 0 枠も判定不能扱い."""
    monkeypatch.setattr(main, "fetch_supplier_inventory", lambda *a, **k: {
        "name": "x", "color": "", "skus": []})
    res = main.process_listing(None, _row(), all_sku_rows=SHEET_ROWS)
    assert res["updates"] == []
    assert res["error"] == "supplier_page_returned_no_skus"


# ============================================================================
# 単独 listing の行増殖 (2026-09-07)
# ============================================================================
SINGLE_SHEET_ROWS = [
    ["FALSE", "TRUE", "", "357100744887", "t", "Montbell", "XL", "NV/PB", "◎", "10850", "1", ""],
]


def test_single_listing_binds_to_existing_row_not_append(monkeypatch):
    """仕入元 size(S) と eBay size(XL) が違っても既存行に紐づく (毎 cycle append しない).

    実害: 357100744887 が 1 cycle 1 行ずつ増え 91 行になった (3 行/日)。
    """
    monkeypatch.setattr(main, "fetch_supplier_inventory", lambda *a, **k: {
        "name": "サンダーパス ジャケット Men's", "color": "NV/PB", "total_skus": 14,
        "skus": [{"size": "S", "color_code": "NV/PB", "in_stock": True,
                  "quantity": 2, "price_jpy": 10850, "promo_price_jpy": 10850}],
    })
    monkeypatch.setitem(main.__dict__, "_EBAY_VALID_VARIATIONS", {
        "listings_with_var": set(),
        "single_listings": {"357100744887": {"size": "XL", "sku": "Montbell"}},
        "set": set(),
    })
    row = {"listing_id": "357100744887", "title": "サンダーパス Men's BLUE",
           "url": "https://webshop.montbell.jp/goods/disp_fo.php?product_id=1128635",
           "supplier": "montbell"}
    res = main.process_listing(None, row, all_sku_rows=SINGLE_SHEET_ROWS)

    assert len(res["updates"]) == 1
    u = res["updates"][0]
    assert u["row_index"] == 2          # 既存行に紐づく (None なら append される)
    assert u["size"] == "XL"            # eBay 由来 size は従来どおり採用
    # eBay の XL は仕入元 (S のみ) に無いので売切扱い (下の size 不在テストと同じ判定)
    assert u["supplier_stock_mark"] == "✕"


def test_single_listing_size_absent_at_supplier_is_sold_out(monkeypatch):
    """eBay が売る size が仕入元に無い → 別 size の在庫で「在庫あり」にしない.

    実害: 357100744887 は eBay が JP XL、仕入元 NV/PB は S しか無いのに
    「在庫 1/1 あり」と出て 出品が生きていた (色消滅と同じ damage class)。
    """
    monkeypatch.setattr(main, "fetch_supplier_inventory", lambda *a, **k: {
        "name": "サンダーパス ジャケット Men's", "color": "NV/PB", "total_skus": 14,
        "skus": [{"size": "S", "color_code": "NV/PB", "in_stock": True,
                  "quantity": 2, "price_jpy": 10850, "promo_price_jpy": 10850}],
    })
    monkeypatch.setitem(main.__dict__, "_EBAY_VALID_VARIATIONS", {
        "listings_with_var": set(),
        "single_listings": {"357100744887": {"size": "XL", "sku": "Montbell"}},
        "set": set(),
    })
    row = {"listing_id": "357100744887", "title": "サンダーパス Men's BLUE",
           "url": "https://webshop.montbell.jp/goods/disp_fo.php?product_id=1128635",
           "supplier": "montbell"}
    res = main.process_listing(None, row, all_sku_rows=SINGLE_SHEET_ROWS)

    u = res["updates"][0]
    assert u["supplier_stock_mark"] == "✕"
    assert u["needs_action"] is True
    assert res["needs_action_count"] == 1


def test_single_listing_size_present_stays_in_stock(monkeypatch):
    """eBay の size が仕入元にあれば従来どおり在庫あり (締めすぎない)."""
    monkeypatch.setattr(main, "fetch_supplier_inventory", lambda *a, **k: {
        "name": "サンダーパス ジャケット Men's", "color": "NV/PB", "total_skus": 14,
        "skus": [{"size": "XL", "color_code": "NV/PB", "in_stock": True,
                  "quantity": 5, "price_jpy": 10850, "promo_price_jpy": 10850}],
    })
    monkeypatch.setitem(main.__dict__, "_EBAY_VALID_VARIATIONS", {
        "listings_with_var": set(),
        "single_listings": {"357100744887": {"size": "XL", "sku": "Montbell"}},
        "set": set(),
    })
    row = {"listing_id": "357100744887", "title": "t",
           "url": "https://webshop.montbell.jp/goods/disp_fo.php?product_id=1128635",
           "supplier": "montbell"}
    res = main.process_listing(None, row, all_sku_rows=SINGLE_SHEET_ROWS)
    assert res["updates"][0]["supplier_stock_mark"] == "◎"
    assert res["needs_action_count"] == 0


# ============================================================================
# 枠消滅 (multi-color ページで色/サイズが丸ごと落ちた) — 2026-09-07
# ============================================================================
VAR_SHEET_ROWS = [
    ["FALSE", "FALSE", "", "358278977272", "t", "uuid-1", "M", "PRBL", "◎", "50000", "1", ""],
    ["FALSE", "FALSE", "", "358278977272", "t", "uuid-2", "M", "BK",   "◎", "50000", "1", ""],
]
VAR_EBAY = {
    "listings_with_var": {"358278977272"},
    "single_listings": {},
    "set": {("358278977272", "M", "PRBL"), ("358278977272", "M", "BK")},
}


def _var_row():
    return {"listing_id": "358278977272", "title": "プラズマ1000 Men's",
            "url": "https://webshop.montbell.jp/goods/disp.php?product_id=1101493",
            "supplier": "montbell"}


def test_vanished_color_on_multicolor_page_is_marked_sold_out(monkeypatch):
    """色一覧から消えた色の行は ◎ のまま凍らせず売切にする.

    実害: 358278977272 の PRBL は montbell から消えたのにシートは 7/24 から ◎ のまま、
    eBay に 3 枠 (JP S/M/XL) が 45 日間 生き残っていた。
    """
    monkeypatch.setattr(main, "fetch_supplier_inventory", lambda *a, **k: {
        "name": "プラズマ1000", "color": "ALL", "total_skus": 28,
        "available_color_codes": ["BK", "LTSV"],          # PRBL は消えた
        "skus": [{"size": "M", "color_code": "BK", "in_stock": True,
                  "quantity": 3, "price_jpy": 50000, "promo_price_jpy": 50000}],
    })
    monkeypatch.setitem(main.__dict__, "_EBAY_VALID_VARIATIONS", VAR_EBAY)
    res = main.process_listing(None, _var_row(), all_sku_rows=VAR_SHEET_ROWS)

    marks = {(u["size"], u["color"]): u["supplier_stock_mark"] for u in res["updates"]}
    assert marks[("M", "PRBL")] == "✕"     # 消えた色 → 売切
    assert marks[("M", "BK")] == "◎"       # 生きている色はそのまま


def test_other_color_from_a_different_url_is_not_marked_sold_out(monkeypatch):
    """色一覧を返さない supplier で、今引いた色と違う行は触らない (誤検知の防止).

    実害: 同じ itemID に 2 つの商品 URL が紐づいた出品 (358359585353 / 358711287999) が
    互いを「消えた」と判定し合い、買える出品まで売切にしていた。
    """
    monkeypatch.setattr(main, "fetch_supplier_inventory", lambda *a, **k: {
        "name": "UT", "color": "GRAY", "total_skus": 8,   # 色一覧は返さない supplier
        "skus": [{"size": "M", "color_code": "", "in_stock": True,
                  "quantity": 1, "price_jpy": 1500, "promo_price_jpy": 1500}],
    })
    rows = [
        ["FALSE", "FALSE", "", "358359585353", "t", "u1", "M", "GRAY",  "◎", "1500", "1", ""],
        ["FALSE", "FALSE", "", "358359585353", "t", "u2", "M", "WHITE", "◎", "1500", "1", ""],
    ]
    monkeypatch.setitem(main.__dict__, "_EBAY_VALID_VARIATIONS", {
        "listings_with_var": {"358359585353"}, "single_listings": {},
        "set": {("358359585353", "M", "GRAY"), ("358359585353", "M", "WHITE")},
    })
    row = {"listing_id": "358359585353", "title": "UT", "supplier": "uniqlo",
           "url": "https://www.uniqlo.com/jp/ja/products/E487563-000/00?colorDisplayCode=03"}
    res = main.process_listing(None, row, all_sku_rows=rows)
    marks = {(u["size"], u["color"]): u["supplier_stock_mark"] for u in res["updates"]}
    assert marks.get(("M", "WHITE"), "◎") != "✕"
