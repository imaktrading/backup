"""復活 二重出品 gate の regression test (2026-08-07 revive_qty1_impl §5).

依頼書 §「仕様」 の⑤: 同 canonical KEY (AI列) の別 itemID が live かつ qty>0 なら
復活しない。 KEY 空欄行は fail-open で通す (元々 1点もの中心 = 復活対象外なので実害小、
ただし件数を decision_log に必ず計上)。

apply_gates() 経由で:
  - 同 KEY 別 iid が qty>0     → 復活しない
  - 同 KEY 別 iid が qty=0     → 復活する
  - KEY 空欄                   → 突合 skip (他 gate に委ねる、 "no_key" 通し)
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ebay_actions.revive_csv_generator import (  # noqa: E402
    apply_gates, check_no_duplicate_live, build_sheet_key_map,
)


def _row(iid, key="", url="https://amazon.co.jp/dp/B00000000X"):
    return {
        "row_index": 100,
        "url": url,
        "item_id": iid,
        "title": iid,
        "current_sold": "",
        "err_flag_prev": "",
        "checked_at": "2026/08/07 12:00:00",
        "sheet_label": "HIGH",
        "key_number": key,
        "category": "G-SHOCK",
        "price": "10000",
        "current_m_jpy_str": "10000",
    }


# ============================================================================
# check_no_duplicate_live 単体
# ============================================================================
def test_no_key_returns_ok_no_key():
    """KEY 空欄 = 突合 skip (fail-open 通し、 decision_log で計上)。"""
    row = _row("IID_A")
    ok, reason = check_no_duplicate_live(row, active_qty_map={},
                                          sheet_key_map={})
    assert ok is True
    assert reason == "no_key"


def test_same_key_no_other_iid_returns_ok():
    """同 KEY 他 iid なし (この行のみ) → ok。"""
    row = _row("IID_A", key="K1")
    ok, _ = check_no_duplicate_live(row, active_qty_map={"IID_A": 0},
                                     sheet_key_map={"K1": ["IID_A"]})
    assert ok is True


def test_same_key_other_iid_qty_zero_returns_ok():
    """同 KEY 別 iid あり + eBay 上 qty=0 → 復活 OK。"""
    row = _row("IID_A", key="K1")
    ok, _ = check_no_duplicate_live(row,
                                     active_qty_map={"IID_A": 0, "IID_B": 0},
                                     sheet_key_map={"K1": ["IID_A", "IID_B"]})
    assert ok is True


def test_same_key_other_iid_qty_positive_returns_false():
    """同 KEY 別 iid が eBay で qty>0 → 復活しない (二重出品防止)。"""
    row = _row("IID_A", key="K1")
    ok, reason = check_no_duplicate_live(
        row, active_qty_map={"IID_A": 0, "IID_B": 1},
        sheet_key_map={"K1": ["IID_A", "IID_B"]})
    assert ok is False
    assert "duplicate_live_key" in reason
    assert "IID_B" in reason


def test_same_key_qty_map_none_is_fail_closed():
    """同 KEY 別 iid あり + qty_map=None (eBay 状態不明) → 温存 (復活しない)。"""
    row = _row("IID_A", key="K1")
    ok, reason = check_no_duplicate_live(
        row, active_qty_map=None,
        sheet_key_map={"K1": ["IID_A", "IID_B"]})
    assert ok is False
    assert "duplicate_key_unknown_qty" in reason


# ============================================================================
# build_sheet_key_map
# ============================================================================
def test_build_sheet_key_map_skips_empty():
    rows = [
        {"row_index": 1, "key_number": "K1", "item_id": "IID_A"},
        {"row_index": 2, "key_number": "K1", "item_id": "IID_B"},
        {"row_index": 3, "key_number": "K2", "item_id": "IID_C"},
        {"row_index": 4, "key_number": "",   "item_id": "IID_D"},   # 空欄 → skip
        {"row_index": 5, "key_number": "K3", "item_id": ""},        # 空欄 → skip
    ]
    m = build_sheet_key_map(rows)
    assert m == {"K1": ["IID_A", "IID_B"], "K2": ["IID_C"]}


# ============================================================================
# apply_gates 経由: duplicate_live gate が働くこと
# ============================================================================
def test_apply_gates_duplicate_live_key_deferred():
    """同 KEY 別 iid が qty>0 のとき、 復活 candidate は deferred へ落ちる。"""
    cycle_start = datetime(2026, 8, 7, 11, 0, 0)
    candidates = [_row("IID_A", key="K1"), _row("IID_C", key="K2")]
    sheet_key_maps = {"HIGH": {
        "K1": ["IID_A", "IID_B"],   # K1 は別 iid IID_B が存在
        "K2": ["IID_C"],             # K2 はこの行のみ
    }}
    active_qty_map = {"IID_A": 0, "IID_B": 1, "IID_C": 0}

    allowed, deferred, price_hold = apply_gates(
        candidates=candidates,
        sheet_key_maps=sheet_key_maps,
        cycle_started_at=cycle_start,
        active_qty_map=active_qty_map,
        fetch_price_fn=lambda iid: (300.0, 0),
        compute_fn=lambda cost, med, cat: {"price": 100.0},
    )
    allowed_iids = {c["item_id"] for c in allowed}
    deferred_iids = {c["item_id"]: c["skip_reason"] for c in deferred}
    assert "IID_C" in allowed_iids
    assert "IID_A" in deferred_iids
    assert "duplicate_live_key" in deferred_iids["IID_A"]


def test_apply_gates_ebay_already_live_deferred():
    """自分自身が eBay で qty>0 (既に何らかの理由で live 復活済) → skip。"""
    cycle_start = datetime(2026, 8, 7, 11, 0, 0)
    candidates = [_row("IID_ALREADY", key="")]
    allowed, deferred, _ = apply_gates(
        candidates=candidates,
        sheet_key_maps={"HIGH": {}},
        cycle_started_at=cycle_start,
        active_qty_map={},
        fetch_price_fn=lambda iid: (300.0, 3),   # ebay_qty=3 > 0
        compute_fn=lambda cost, med, cat: {"price": 100.0},
    )
    assert len(allowed) == 0
    assert deferred[0]["skip_reason"].startswith("ebay_already_qty_")
