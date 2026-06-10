"""Req1 regression (2026-06-10): eBay item_id 空欄行 = 未出品 → scrape/error 対象外.

eBay listing ID (B列) が空欄 = まだ出品されていない (= 監視予定行)。
取下げ対象が存在しないため scrape せず、 scraper error/None でも 「要対応」 にしない。
旧挙動: 空欄行も scrape され、 None/error が errors 件数 (= メール「通信エラー」) に計上され誤検知。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor_listings as ML  # noqa: E402


class _FakeWS:
    title = "fake"
    id = 0
    row_count = 10


class _FakeSheet:
    title = "fake-sheet"


def test_blank_item_id_row_is_skipped_not_scraped(monkeypatch):
    # 仕入元 URL は fril (= mercari/amazon driver 生成を回避)
    rows = [
        {"row_index": 10, "url": "https://item.fril.jp/abc", "item_id": "",
         "title": "未出品行", "current_sold": "", "current_n_jpy_str": ""},
        {"row_index": 11, "url": "https://item.fril.jp/def", "item_id": "999",
         "title": "出品済行", "current_sold": "", "current_n_jpy_str": ""},
    ]

    scraped_item_ids = []

    def _fake_check(row, **kwargs):
        scraped_item_ids.append(row.get("item_id"))
        return {
            "row_index": row["row_index"], "url": row["url"],
            "item_id": row.get("item_id", ""), "supplier": "fril",
            "is_sold": False, "raw_status": "in_stock", "current_sold": "",
            "delta": "unchanged", "error": None, "price_jpy": 1000,
            "candidates_checked": 1, "current_n_jpy_str": "", "sub_results": [],
        }

    monkeypatch.setattr(ML, "open_sheet_by_id", lambda sid: _FakeSheet())
    monkeypatch.setattr(ML, "get_listings_worksheet", lambda sh, gid=0: _FakeWS())
    monkeypatch.setattr(ML, "read_listings_rows",
                        lambda ws, start_row=None, end_row=None, only_with_url=True: rows)
    monkeypatch.setattr(ML, "check_one_row_with_fallback", _fake_check)

    summary = ML.process_sheet(sheet_id="dummy_sheet_id", sheet_label="TEST", dry_run=True)

    # 空欄行 (999 のみ scrape され、 "" は scrape されない)
    assert scraped_item_ids == ["999"], f"空欄行が scrape された: {scraped_item_ids}"
    # 空欄行は error 計上されない (= 「要対応」 誤検知の撲滅)
    assert summary["errors"] == 0, f"空欄行が error 計上された: {summary}"
