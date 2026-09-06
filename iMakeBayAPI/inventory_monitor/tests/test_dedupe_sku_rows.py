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


def test_blank_size_rows_are_deleted_only_when_a_sized_row_exists():
    """サイズ空欄行は、同じ listing にサイズ入り行がある時だけ消す (唯一の記録は残す)."""
    from tools.dedupe_sku_rows import plan_blank_size_deletions
    rows = [
        _row("111", "M", "BK"),    # row2 サイズ入り
        _row("111", "", "BK"),     # row3 空欄 → 消す
        _row("222", "", "BK"),     # row4 空欄だが 222 にサイズ入り行が無い → 残す
    ]
    assert plan_blank_size_deletions(rows) == [3]
