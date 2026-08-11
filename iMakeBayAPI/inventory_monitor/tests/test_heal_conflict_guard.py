"""重複行による zero↔restore 往復の停止 (2026-08-11 実測).

SKU詳細シートに同じ eBay variation を指す行が 2 つあり (montbell の size "L" と "L-R" が
同一 SKU UUID を共有、実測 56 組 136 行)、仕入元判定が ✕ と ◎ で食い違うと、
audit_and_heal が **サイクルを跨いで往復**する:
  cycle1: ✕ の行を見て qty=0 → cycle2: ◎ の行が「復活未反映」になり qty=1 →
  cycle3: ✕ の行が「取下げ未反映」になり qty=0 → …

実害: eBay API を毎 cycle 無駄打ち / audit が永久に「不整合あり」を出し続け、
本物の取下げ漏れが埋もれる (アラート疲労)。
方針: 相反する情報には **どちらも自動実行しない** (fail-closed) + 件数を非-silent に報告。
ただし `pending` (未対処の取下げ) は止めない = 危険側を殺さない。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audit_and_heal import find_conflicting_sku_rows, filter_conflicting_targets  # noqa: E402

SKU_A = "e343024f-2485-483b-80e2-b90260c91999"
SKU_B = "3ccad815-0a86-4d99-ae6e-3ed701150f59"
HDR = ["対処要", "対処済", "対処日", "listing", "title", "SKU", "size", "color",
       "仕入元在庫", "仕入元価格", "eBay現Qty", "自動CHK日"]


def _row(listing, sku, size, mark):
    return ["TRUE", "TRUE", "", listing, "t", sku, size, "YL", mark, "1000", "1", ""]


def _rec(row, sku, iid="358275199203"):
    return {"row": row, "item_id": iid, "sku": sku, "var": "Sizes=L|Color=YL"}


# ---------------------------------------------------------------- 検知
def test_detects_real_case_L_and_LR():
    """★実測ケース: row244(L,✕) と row587(L-R,◎) が同一 SKU UUID"""
    rows = [HDR,
            _row("358275199203", SKU_A, "L", "✕"),      # row2
            _row("358275199203", SKU_A, "L-R", "◎")]    # row3
    got = find_conflicting_sku_rows(rows)
    assert len(got) == 1
    assert got[0]["sku"] == SKU_A and got[0]["rows"] == [(2, "✕"), (3, "◎")]


def test_duplicate_but_consistent_is_not_conflict():
    """重複していても 仕入元判定が一致していれば矛盾ではない (止めない)"""
    rows = [HDR,
            _row("358275199203", SKU_A, "L", "✕"),
            _row("358275199203", SKU_A, "L-R", "✕")]
    assert find_conflicting_sku_rows(rows) == []


def test_same_sku_different_listing_is_not_conflict():
    """UUID は listing 跨ぎで共有される。listing が違えば別 variation"""
    rows = [HDR, _row("111", SKU_A, "L", "✕"), _row("222", SKU_A, "L", "◎")]
    assert find_conflicting_sku_rows(rows) == []


def test_non_uuid_and_blank_marks_ignored():
    rows = [HDR,
            _row("358275199203", "not-a-uuid", "L", "✕"),
            _row("358275199203", SKU_B, "L", ""),
            _row("358275199203", SKU_B, "L-R", "◎")]
    assert find_conflicting_sku_rows(rows) == []      # 空 mark は判定材料にしない


# ---------------------------------------------------------------- 除去
def test_conflicting_keys_removed_from_zero_and_restore():
    inc = {"zero": [_rec(244, SKU_A)], "restore": [_rec(587, SKU_A)], "pending": []}
    conflicts = [{"item_id": "358275199203", "sku": SKU_A, "rows": [(244, "✕"), (587, "◎")]}]
    removed = filter_conflicting_targets(inc, conflicts)
    assert removed == 2
    assert inc["zero"] == [] and inc["restore"] == []


def test_clean_rows_survive():
    inc = {"zero": [_rec(244, SKU_A), _rec(915, SKU_B)], "restore": [], "pending": []}
    conflicts = [{"item_id": "358275199203", "sku": SKU_A, "rows": [(244, "✕"), (587, "◎")]}]
    filter_conflicting_targets(inc, conflicts)
    assert [r["row"] for r in inc["zero"]] == [915]     # 衝突していない取下げは残す


def test_pending_is_never_filtered():
    """未対処の取下げ (危険側) は矛盾していても止めない"""
    inc = {"zero": [], "restore": [], "pending": [_rec(300, SKU_A)]}
    conflicts = [{"item_id": "358275199203", "sku": SKU_A, "rows": [(300, "✕"), (587, "◎")]}]
    filter_conflicting_targets(inc, conflicts)
    assert [r["row"] for r in inc["pending"]] == [300]


def test_no_conflicts_is_noop():
    inc = {"zero": [_rec(1, SKU_A)], "restore": [_rec(2, SKU_B)], "pending": []}
    assert filter_conflicting_targets(inc, []) == 0
    assert len(inc["zero"]) == 1 and len(inc["restore"]) == 1
