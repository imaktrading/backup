"""item_id 空欄 (未出品) 行の扱い regression.

方針推移:
- 2026-06-10: item_id 空欄 = 未出品 → scrape skip (取下げ対象が無いので scrape 実益ゼロ)。
- 2026-06-21 (user 指示で反転): 未出品も scrape する。 出品くんが CSV 作成→出品 した後に
  「実は仕入元売切」 が発覚するのを防ぐため、 出品前に源在庫を D 列へ反映する。
  ただし取下げ対象 (eBay listing) は無いので revise/pending/要対応 には入れない (検知のみ)。

本 test は新挙動を担保:
- 空欄行も scrape される (= 源在庫が D 列に乗る)
- 空欄行 scrape は error 計上しない
- 空欄行が newly_sold でも pending / action_required に積まれない (検知のみ)
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


def _patch_common(monkeypatch, rows, fake_check):
    monkeypatch.setattr(ML, "open_sheet_by_id", lambda sid: _FakeSheet())
    monkeypatch.setattr(ML, "get_listings_worksheet", lambda sh, gid=0: _FakeWS())
    monkeypatch.setattr(ML, "read_listings_rows",
                        lambda ws, start_row=None, end_row=None, only_with_url=True: rows)
    monkeypatch.setattr(ML, "check_one_row_with_fallback", fake_check)


def test_blank_item_id_row_is_now_scraped(monkeypatch):
    """2026-06-21 反転: 空欄行も scrape される (出品前の源在庫検知)。"""
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

    _patch_common(monkeypatch, rows, _fake_check)
    summary = ML.process_sheet(sheet_id="dummy", sheet_label="TEST", dry_run=True)

    assert scraped_item_ids == ["", "999"], f"空欄行も scrape されるべき: {scraped_item_ids}"
    assert summary["errors"] == 0, f"空欄行 scrape が error 計上された: {summary}"


def test_blank_item_id_newly_sold_is_detection_only(monkeypatch):
    """空欄行が newly_sold でも pending/action_required に積まれない (検知のみ=D列更新のみ)。"""
    rows = [
        {"row_index": 10, "url": "https://item.fril.jp/abc", "item_id": "",
         "title": "未出品で売切", "current_sold": "", "current_n_jpy_str": ""},
    ]

    def _fake_check(row, **kwargs):
        return {
            "row_index": row["row_index"], "url": row["url"],
            "item_id": "", "supplier": "fril",
            "is_sold": True, "raw_status": "out_of_stock", "current_sold": "",
            "delta": "newly_sold", "error": None, "price_jpy": None,
            "candidates_checked": 1, "current_n_jpy_str": "", "sub_results": [],
        }

    pending_calls, action_calls = [], []
    monkeypatch.setattr(ML, "append_pending_revise",
                        lambda *a, **k: pending_calls.append(a))
    monkeypatch.setattr(ML, "append_action_required",
                        lambda *a, **k: action_calls.append(a))
    _patch_common(monkeypatch, rows, _fake_check)

    summary = ML.process_sheet(sheet_id="dummy", sheet_label="TEST", dry_run=True)

    assert pending_calls == [], "空欄行 newly_sold は pending に積まない (取下げ対象なし)"
    assert action_calls == [], "空欄行 newly_sold は action_required にしない (未出品=正常)"
    assert summary["newly_sold"] == 1, "売切自体は検知される (D列更新用)"
