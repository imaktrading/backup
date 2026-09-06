"""SKU シート重複行の掃除ロジック (2026-09-07)。

同じ (listing, size, color) の行が複数ある時、最も上の行だけ残す。
size 空欄の行 (UUID 同期の置き土産) は別問題なので触らない。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.dedupe_sku_rows import plan_deletions  # noqa: E402


def _row(listing, size, color):
    return ["FALSE", "FALSE", "", listing, "t", "sku", size, color, "◎", "1000", "1", ""]


def test_keeps_topmost_row_of_each_duplicate_group():
    rows = [
        _row("111", "XL", "NV"),   # row2 ← 残す
        _row("111", "XL", "NV"),   # row3
        _row("111", "XL", "NV"),   # row4
        _row("111", "M", "NV"),    # row5 (別 size = 重複ではない)
        _row("222", "S", "RD"),    # row6
    ]
    delete, detail = plan_deletions(rows)
    assert delete == [3, 4]
    assert detail == [{"key": ("111", "XL", "NV"), "rows": 3, "keep": 2}]


def test_size_blank_rows_are_never_deleted():
    rows = [
        _row("333", "", "BGN"),
        _row("333", "", "BGN"),
        _row("333", "", "BGN"),
    ]
    delete, detail = plan_deletions(rows)
    assert delete == []
    assert detail == []


def test_no_duplicates_means_nothing_to_delete():
    rows = [_row("444", "S", "BK"), _row("444", "M", "BK"), _row("555", "S", "BK")]
    assert plan_deletions(rows)[0] == []
