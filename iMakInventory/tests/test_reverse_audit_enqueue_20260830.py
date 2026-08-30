"""監査が見つけた取下げ漏れを、報告で終わらせずキューに積む — 2026-08-30.

事故: 08-29 に「D=○ なのに eBay で買える」3 件を検出して通知したが、誰も触らず
08-30 も同じ 3 件が残っていた。無在庫なので、その間に売れると発送できない
(キャンセル → Defect Rate)。**報告するだけの監査は fail-OPEN を閉じない。**

固定すること:
  1. 未承認の乖離は取下げキューに積まれる (送信は巡回の既存経路が行う)
  2. 既にキューにあるものは二重に積まない
  3. 件数が多い時は積まない (判定の系統異常の疑い = 誤った一括取下げを避ける)
  4. 承認済み (物理在庫を持っている等) は積まない
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import reverse_audit as ra  # noqa: E402


def _item(iid, sheet="HIGH", row=10):
    return {"item_id": iid, "sheet": sheet, "row_index": row, "url": "https://x/y",
            "title": "t", "supplier": "mercari", "ebay_qty": 1}


def test_unacknowledged_mismatches_are_enqueued():
    appended = []
    with patch("monitor_listings.read_pending_item_ids", return_value=set()), \
         patch("monitor_listings.append_pending_revise",
               side_effect=lambda label, r, dry_run: appended.append((label, r["item_id"]))):
        out = ra._enqueue_takedowns([_item("111"), _item("222")])

    assert out["enqueued"] == ["111", "222"]
    assert [a[1] for a in appended] == ["111", "222"]
    assert out["held"] is False


def test_already_queued_is_not_enqueued_twice():
    appended = []
    with patch("monitor_listings.read_pending_item_ids", return_value={"111"}), \
         patch("monitor_listings.append_pending_revise",
               side_effect=lambda label, r, dry_run: appended.append(r["item_id"])):
        out = ra._enqueue_takedowns([_item("111"), _item("222")])

    assert out["enqueued"] == ["222"]
    assert out["skipped_already_queued"] == ["111"]
    assert appended == ["222"]


def test_too_many_holds_instead_of_mass_takedown():
    """★ 大量に出た時は積まない (誤検知の一括取下げの方が損害が大きい)."""
    appended = []
    items = [_item(str(i)) for i in range(20)]
    with patch("monitor_listings.read_pending_item_ids", return_value=set()), \
         patch("monitor_listings.append_pending_revise",
               side_effect=lambda label, r, dry_run: appended.append(r["item_id"])):
        out = ra._enqueue_takedowns(items, cap=10)

    assert out["held"] is True
    assert out["enqueued"] == []
    assert appended == []          # 1 件も送らない


def test_empty_input_is_noop():
    with patch("monitor_listings.read_pending_item_ids") as reader:
        out = ra._enqueue_takedowns([])
    assert out == {"enqueued": [], "skipped_already_queued": [], "held": False}
    reader.assert_not_called()


def test_entry_records_where_it_came_from():
    """後から「この取下げは監査由来」と分かること."""
    captured = {}
    with patch("monitor_listings.read_pending_item_ids", return_value=set()), \
         patch("monitor_listings.append_pending_revise",
               side_effect=lambda label, r, dry_run: captured.update(r)):
        ra._enqueue_takedowns([_item("111")])

    assert captured["raw_status"] == "reverse_audit_mismatch"
    assert captured["item_id"] == "111"


def test_blank_item_id_is_skipped():
    appended = []
    with patch("monitor_listings.read_pending_item_ids", return_value=set()), \
         patch("monitor_listings.append_pending_revise",
               side_effect=lambda label, r, dry_run: appended.append(r["item_id"])):
        out = ra._enqueue_takedowns([_item(""), _item("222")])

    assert out["enqueued"] == ["222"]
    assert appended == ["222"]
