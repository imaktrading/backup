"""補URL 売切消込 + 売切日時 stamp + positional 5枠read の regression test.

★ 2026-07-25 実装 (HQ 2026-07-25_hoju_url_sold_cleanup_poc_and_impl_go)。
仕様:
- 懸念1: read は AC-AG を固定 5 枠 positional (空=None)。消込/stamp/色塗りは列番号ベース
  (空詰め index で列を推定しない = 穴で誤セルを消す事故を構造的に防ぐ)。
- 懸念2: clear_sold_backup_cells は書込直前に re-read し、監視が is_sold=True と見た URL と
  セル現在値が一致する時だけ消す (compare-and-clear)。不一致=HQ差替 → 消さず要対応。
- fail-closed: is_sold=True 確定のみ消込 (caller が候補を絞る)。主URL は対象外。
- 消込急増ガード: 候補 > CLEAR_SURGE_THRESHOLD → 一括消込を HOLD。
- 売切日時: newly_sold 遷移時に AO=41 へ 1 回記録 (別ラベル在なら header 触らない)。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================================
# positional 5枠 read
# ============================================================================
def test_read_backup_url_slots_positional_with_gap():
    """AC空・AD有 のとき slots=[None, url, ...] で位置を保つ (backup_urls は詰める)."""
    from sheet_updater import read_listings_rows
    ws = MagicMock()
    # row2: A=url, AC(29)空, AD(30)=b2, AE(31)=b3, AF/AG 空
    row = [""] * 33
    row[0] = "https://main"          # A
    row[29] = "https://b2"           # AD (index 29 = col30)
    row[30] = "https://b3"           # AE (index 30 = col31)
    ws.get_all_values = MagicMock(return_value=[["header"], row])
    rows = read_listings_rows(ws, start_row=2, end_row=2)
    assert len(rows) == 1
    slots = rows[0]["backup_url_slots"]
    assert slots == [None, "https://b2", "https://b3", None, None]  # AC-AG positional
    assert rows[0]["backup_urls"] == ["https://b2", "https://b3"]    # 後方互換 (詰め)


def test_sold_at_col_constant():
    from sheet_updater import LISTINGS_COL_SOLD_AT, LISTINGS_SOLD_AT_HEADER
    assert LISTINGS_COL_SOLD_AT == 41       # AO (実機ヘッダ確認: AL=38 は使用中、AO=41 が未使用)
    assert LISTINGS_SOLD_AT_HEADER == "売切日時"


# ============================================================================
# check_one_row_with_fallback: backup_slot_results が列に positional マップ
# ============================================================================
def test_fallback_backup_slot_results_positional_with_gap(monkeypatch):
    """空枠を挟んでも backup_slot_results の slot が AC-AG 列番号に一致する (懸念1)."""
    import monitor_listings as ml

    def fake_check(url, *a, **k):
        # main=在庫あり, b2=売切, b3=在庫あり
        table = {"https://main": False, "https://b2": True, "https://b3": False}
        return {"url": url, "supplier": "amazon", "is_sold": table.get(url),
                "raw_status": "", "error": None, "price_jpy": None, "points_jpy": None}
    monkeypatch.setattr(ml, "_check_single_url", fake_check)

    row = {"row_index": 5, "url": "https://main",
           "backup_url_slots": [None, "https://b2", "https://b3", None, None],
           "current_sold": ""}
    res = ml.check_one_row_with_fallback(row)
    slots = res["backup_slot_results"]
    assert slots[0] is None                    # AC 空
    assert slots[1]["slot"] == 1 and slots[1]["is_sold"] is True   # AD 売切
    assert slots[2]["slot"] == 2 and slots[2]["is_sold"] is False  # AE 在庫
    assert slots[3] is None and slots[4] is None
    # 主 or 補に在庫あり → row は取下げない
    assert res["is_sold"] is False


# ============================================================================
# clear_sold_backup_cells: compare-and-clear
# ============================================================================
def _ws_with_backup(cells_by_row):
    """batch_get が row→[AC..AG] を返す MagicMock ws."""
    ws = MagicMock()
    ws.batch_update = MagicMock()

    def fake_batch_get(ranges):
        out = []
        for rg in ranges:
            # "AC{r}:AG{r}"
            r = int("".join(ch for ch in rg.split(":")[0] if ch.isdigit()))
            out.append([cells_by_row.get(r, [])])
        return out
    ws.batch_get = MagicMock(side_effect=fake_batch_get)
    return ws


def test_clear_matches_only_when_cell_equals_expected():
    """セル現在値 == 確認URL の時だけ消す (compare-and-clear 一致)."""
    from sheet_updater import clear_sold_backup_cells
    ws = _ws_with_backup({5: ["", "https://b2", "https://b3", "", ""]})
    cands = [{"row_index": 5, "slot": 1, "expected_url": "https://b2"}]
    res = clear_sold_backup_cells(ws, cands)
    assert res["cleared"] == 1
    assert res["skipped_mismatch"] == []
    # AD5 を "" でクリア
    ranges = [c["range"] for c in ws.batch_update.call_args[0][0]]
    assert "AD5" in ranges
    # ★ 復元用: 消したものが cleared_entries に (row/slot/col/url) で残る
    assert res["cleared_entries"] == [
        {"row_index": 5, "slot": 1, "col": "AD", "url": "https://b2"}]


def test_clear_skips_on_mismatch_hq_replaced():
    """HQ が別 URL に差替済 (セル値≠確認URL) → 消さず skipped_mismatch (silent drop 禁止)."""
    from sheet_updater import clear_sold_backup_cells
    ws = _ws_with_backup({5: ["", "https://NEW_by_hq", "", "", ""]})
    cands = [{"row_index": 5, "slot": 1, "expected_url": "https://b2_old"}]
    res = clear_sold_backup_cells(ws, cands)
    assert res["cleared"] == 0
    assert len(res["skipped_mismatch"]) == 1
    assert res["skipped_mismatch"][0]["actual"] == "https://NEW_by_hq"
    ws.batch_update.assert_not_called()


def test_clear_surge_guard_holds_all():
    """候補が閾値超 → 一括消込を HOLD (誤一括消去防止)、実書込ゼロ."""
    from sheet_updater import clear_sold_backup_cells, CLEAR_SURGE_THRESHOLD
    ws = _ws_with_backup({})
    cands = [{"row_index": i, "slot": 0, "expected_url": f"u{i}"}
             for i in range(CLEAR_SURGE_THRESHOLD + 1)]
    res = clear_sold_backup_cells(ws, cands)
    assert res["held"] is True and res["surge"] is True
    assert res["cleared"] == 0
    ws.batch_get.assert_not_called()   # HOLD 時は re-read すらしない
    ws.batch_update.assert_not_called()


def test_clear_surge_guard_override():
    """enable_surge_guard=False なら閾値超でも消込実行 (緊急 override)."""
    from sheet_updater import clear_sold_backup_cells, CLEAR_SURGE_THRESHOLD
    rows = {i: ["u%d" % i, "", "", "", ""] for i in range(CLEAR_SURGE_THRESHOLD + 1)}
    ws = _ws_with_backup(rows)
    cands = [{"row_index": i, "slot": 0, "expected_url": f"u{i}"}
             for i in range(CLEAR_SURGE_THRESHOLD + 1)]
    res = clear_sold_backup_cells(ws, cands, enable_surge_guard=False)
    assert res["held"] is False
    assert res["cleared"] == CLEAR_SURGE_THRESHOLD + 1


def test_clear_empty_candidates_noop():
    from sheet_updater import clear_sold_backup_cells
    ws = MagicMock()
    res = clear_sold_backup_cells(ws, [])
    assert res == {"cleared": 0, "skipped_mismatch": [], "held": False,
                   "candidate_count": 0, "surge": False, "cleared_entries": [],
                   "deferred": 0}


def test_clear_empty_expected_never_clears():
    """expected_url 空なら (異常入力) 消さない (安全側)."""
    from sheet_updater import clear_sold_backup_cells
    ws = _ws_with_backup({5: ["", "", "", "", ""]})
    cands = [{"row_index": 5, "slot": 1, "expected_url": ""}]
    res = clear_sold_backup_cells(ws, cands)
    assert res["cleared"] == 0
    assert len(res["skipped_mismatch"]) == 1


# ============================================================================
# 売切日時 stamp (AO) 書込
# ============================================================================
def test_sold_at_writes_ao_column():
    """sold_at (非空 str) を渡すと AO 列に書込."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()
    updates = [{"row_index": 7, "is_sold": True, "checked_at": "2026/07/25 10:00:00",
                "sold_at": "2026/07/25 10:00:00"}]
    res = update_listings_sold_marks(ws, updates)
    assert res["sold_at_writes"] == 1
    ranges = [c["range"] for c in ws.batch_update.call_args[0][0]]
    assert "AO7" in ranges


def test_sold_at_absent_skips_ao():
    """sold_at 不在/空なら AO 触らない."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()
    for u in ([{"row_index": 7, "is_sold": True, "checked_at": "t"}],
              [{"row_index": 7, "is_sold": True, "checked_at": "t", "sold_at": ""}]):
        ws.reset_mock()
        res = update_listings_sold_marks(ws, u)
        assert res["sold_at_writes"] == 0
        assert "AO7" not in [c["range"] for c in ws.batch_update.call_args[0][0]]


# ============================================================================
# ensure_sold_at_header 安全性
# ============================================================================
def test_ensure_sold_at_header_writes_when_empty():
    from sheet_updater import ensure_sold_at_header, LISTINGS_SOLD_AT_HEADER
    ws = MagicMock()
    ws.cell = MagicMock(return_value=MagicMock(value=""))
    ws.update = MagicMock()
    assert ensure_sold_at_header(ws) is True
    ws.update.assert_called_once()


def test_ensure_sold_at_header_noop_when_other_label():
    """AO に別ラベルが入っていたら上書きせず False (M12/M13 型破損の回避)."""
    from sheet_updater import ensure_sold_at_header
    ws = MagicMock()
    ws.cell = MagicMock(return_value=MagicMock(value="値下FLG(pp)"))
    ws.update = MagicMock()
    assert ensure_sold_at_header(ws) is False
    ws.update.assert_not_called()


def test_ensure_sold_at_header_noop_when_already_set():
    from sheet_updater import ensure_sold_at_header, LISTINGS_SOLD_AT_HEADER
    ws = MagicMock()
    ws.cell = MagicMock(return_value=MagicMock(value=LISTINGS_SOLD_AT_HEADER))
    ws.update = MagicMock()
    assert ensure_sold_at_header(ws) is False
    ws.update.assert_not_called()
