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
