# -*- coding: utf-8 -*-
"""棚割りの金額は eBay の US 出品価格 (ファネル) から取る (2026-09-16)。

2026-09-05 に金額を足した時、統合シートの M列を「今の出品価格 (US$)」と思って合計していたが、
実際の見出しは **「現在価格(円)」= 仕入元の値**。円を $ として足していたため
棚 $16.84M / TCG +$7.82M と桁が狂い、予算 ($229,661) との比較が意味を成していなかった。
"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HQ)

import control_panel as cp  # noqa: E402

SRC = open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()


def test_price_map_takes_us_rows_only():
    rows = [
        {"item_id": "111", "site": "US", "price": "159.00"},
        {"item_id": "222", "site": "UK", "price": "180.00"},      # ミラーは数えない
        {"item_id": "333", "site": "US", "price": "$1,200.50"},
        {"item_id": "444", "site": "US", "price": ""},            # 価格なしは入れない
        {"item_id": "", "site": "US", "price": "10"},             # itemID なしは入れない
    ]
    m = cp.price_map_from_funnel_rows(rows)
    assert m == {"111": 159.0, "333": 1200.5}


def test_shelf_does_not_use_the_yen_column():
    """M列 (現在価格(円)) を金額として足さない。"""
    body = SRC.split("def _fetch_consolidated_counts")[1].split("def _fetch_seller_stats")[0]
    assert "_funnel_prices.get(item_id" in body
    assert "usd = _to_usd(price)" not in body          # 円の列を $ として足していた行


def test_price_source_is_visible():
    """どのファネルから取ったかを画面に出せるようにしておく (出所不明の数字にしない)。"""
    assert "PRICE_SOURCE" in SRC
    server = open(os.path.join(HQ, "console", "server.py"), encoding="utf-8").read()
    assert 'home["price_source"]' in server
    assert 'home["price_missing"]' in server           # ファネルが無い時は「金額を出せません」
