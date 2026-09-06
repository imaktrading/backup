"""eBay に枠が無い行の K 列を 0 に戻す (2026-09-07)。

K 列 (eBay 現Qty) はシート自身の値を書き戻すだけだったので、出品や variation が
終了しても 1 のまま残り、その行は「仕入元✕ × eBay在庫あり」= 永久に対処要として
数えられていた (実測 218 行)。要対処の件数が実態と合わず、増減アラートが機能しない。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ebay_qty_sync as q  # noqa: E402

UUID_A = "11111111-1111-1111-1111-111111111111"
UUID_B = "22222222-2222-2222-2222-222222222222"


def _row(listing, sku, stock, k, done="FALSE"):
    return ["FALSE", done, "", listing, "t", sku, "M", "BK", stock, "1000", str(k), ""]


def test_rows_of_ended_listing_are_zeroed():
    """出品自体が eBay に無い行 (仕入元✕) は K=0 に戻す."""
    ebay = {"111": [{"sku": UUID_A, "qty": "1"}]}
    uuid_qty = q.build_uuid_to_qty(ebay)
    rows = [_row("111", UUID_A, "✕", 1), _row("999", UUID_B, "✕", 1)]   # 999 は終了済
    out = q.find_vanished_rows(ebay, uuid_qty, rows)
    assert [(o["listing_id"], o["new_qty"], o["reason"]) for o in out] == [
        ("999", 0, "listing_not_active")]


def test_vanished_variation_of_live_listing_is_zeroed():
    """出品は生きているが その variation が無い行は K=0 に戻す."""
    ebay = {"111": [{"sku": UUID_A, "qty": "1"}]}
    uuid_qty = q.build_uuid_to_qty(ebay)
    rows = [_row("111", UUID_B, "✕", 1)]        # 同じ出品だが UUID が無い
    out = q.find_vanished_rows(ebay, uuid_qty, rows)
    assert out and out[0]["reason"] == "variation_not_in_listing"


def test_in_stock_rows_are_never_zeroed():
    """仕入元◎ の行は触らない (0 にすると復活対象と誤解され、無い枠に qty=1 を送る)."""
    ebay = {"111": [{"sku": UUID_A, "qty": "1"}]}
    uuid_qty = q.build_uuid_to_qty(ebay)
    rows = [_row("999", UUID_B, "◎", 1)]
    assert q.find_vanished_rows(ebay, uuid_qty, rows) == []


def test_handled_rows_sync_down_but_not_up():
    """対処済 (B=TRUE) 行は 下げる方向だけ反映する (取下げ結果を巻き戻さない)."""
    ebay = {"111": [{"sku": UUID_A, "qty": "0"}, {"sku": UUID_B, "qty": "5"}]}
    uuid_qty = q.build_uuid_to_qty(ebay)
    down = q.match_qty_updates(uuid_qty, [_row("111", UUID_A, "✕", 1, done="TRUE")])
    up   = q.match_qty_updates(uuid_qty, [_row("111", UUID_B, "◎", 1, done="TRUE")])
    assert [u["new_qty"] for u in down] == [0]     # 1 → 0 は反映
    assert up == []                                # 1 → 5 は反映しない
