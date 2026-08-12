"""復活 (revive) queue の行ズレ耐性 regression test.

★ 2026-08-13 制定。実害: pending_revive は row_index でシートと突合していたが、シートは
行の挿入/削除で常時ずれるため、queue に積んだ時の row_index が数日で別商品を指す。結果、
145 件中 84 件が item_id_changed / row_not_found_in_sheet として **永久に deferred**、
08-08〜08-13 の 6 日間 復活が 1 件も実行されなかった (仕入元に在庫が戻っても eBay は qty=0
のまま = 売れない)。queue も drain されず単調増加。

仕様:
- row_index がずれていても itemID でシート上の行を引き直す。
- 同 itemID が複数行あるときは URL 一致で一意に決まる場合のみ採用、決まらなければ
  fail-closed (誤った行で復活させない)。
- itemID がシートのどこにも無い entry は、一定日数経過後に archive へ退避 (queue 肥大化防止、
  証跡は discarded_revive.jsonl に残す)。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _sheet_row(row_index, item_id, url, sold=""):
    return {"row_index": row_index, "item_id": item_id, "url": url,
            "current_sold": sold, "title": "t", "err_flag_prev": "", "checked_at": ""}


def _collect(queue, rows, label="SHEET"):
    import ebay_actions.revive_csv_generator as rg
    with patch.object(rg, "read_pending_revive", lambda: queue), \
         patch.object(rg, "open_sheet_by_id", lambda *a, **k: object()), \
         patch.object(rg, "get_listings_worksheet", lambda *a, **k: object()), \
         patch.object(rg, "read_listings_rows", lambda ws, **k: rows), \
         patch.object(rg, "build_sheet_key_map", lambda rows: {}):
        return rg.collect_from_pending_revive(
            single_sheet_id="sid", single_sheet_label=label)


@pytest.mark.offline
def test_row_shifted_is_relocated_by_item_id():
    """行がずれても itemID で引き直して候補に載る (恒久 deferred にしない)."""
    queue = [{"sheet": "SHEET", "row_index": 1455, "item_id": "IID1",
              "url": "https://jp.mercari.com/shops/product/AAA", "ts": "2026-08-12T14:47:13"}]
    rows = [_sheet_row(1338, "IID1", "https://jp.mercari.com/shops/product/AAA"),
            _sheet_row(1455, "OTHER", "https://jp.mercari.com/shops/product/ZZZ")]
    cands, skipped, _ = _collect(queue, rows)
    assert len(cands) == 1 and skipped == []
    assert cands[0]["row_index"] == 1338


@pytest.mark.offline
def test_duplicate_item_id_resolved_by_url():
    """同 itemID 複数行 → URL 一致で一意に決まればその行を使う."""
    queue = [{"sheet": "SHEET", "row_index": 99, "item_id": "IID1",
              "url": "https://jp.mercari.com/shops/product/BBB", "ts": "2026-08-12T14:47:13"}]
    rows = [_sheet_row(10, "IID1", "https://jp.mercari.com/shops/product/AAA"),
            _sheet_row(20, "IID1", "https://jp.mercari.com/shops/product/BBB")]
    cands, skipped, _ = _collect(queue, rows)
    assert len(cands) == 1 and cands[0]["row_index"] == 20


@pytest.mark.offline
def test_ambiguous_rows_are_failclosed():
    """URL でも一意に決まらない → 復活させない (誤った行で qty=1 に戻さない)."""
    queue = [{"sheet": "SHEET", "row_index": 99, "item_id": "IID1",
              "url": "", "ts": "2026-08-12T14:47:13"}]
    rows = [_sheet_row(10, "IID1", "https://jp.mercari.com/shops/product/AAA"),
            _sheet_row(20, "IID1", "https://jp.mercari.com/shops/product/BBB")]
    cands, skipped, _ = _collect(queue, rows)
    assert cands == []
    assert skipped[0]["skip_reason"] == "ambiguous_rows_for_item_id"


@pytest.mark.offline
def test_item_id_absent_is_reported_not_silently_kept():
    queue = [{"sheet": "SHEET", "row_index": 99, "item_id": "GONE",
              "url": "https://x", "ts": "2026-08-01T00:00:00"}]
    rows = [_sheet_row(10, "IID1", "https://jp.mercari.com/shops/product/AAA")]
    cands, skipped, _ = _collect(queue, rows)
    assert cands == []
    assert skipped[0]["skip_reason"] == "row_not_found_by_item_id"


# ============================================================================
# prune (queue 肥大化防止)
# ============================================================================
@pytest.mark.offline
def test_prune_moves_only_old_unresolvable_entries(tmp_path):
    import ebay_actions.revive_csv_generator as rg
    pending = tmp_path / "pending_revive.jsonl"
    discarded = tmp_path / "discarded_revive.jsonl"
    old_ts = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
    new_ts = datetime.now().isoformat(timespec="seconds")
    pending.write_text("\n".join([
        json.dumps({"item_id": "OLD_GONE", "ts": old_ts}),
        json.dumps({"item_id": "NEW_GONE", "ts": new_ts}),
        json.dumps({"item_id": "ALIVE", "ts": old_ts}),
    ]) + "\n", encoding="utf-8")
    skipped = [{"item_id": "OLD_GONE", "ts": old_ts, "skip_reason": "row_not_found_by_item_id"},
               {"item_id": "NEW_GONE", "ts": new_ts, "skip_reason": "row_not_found_by_item_id"},
               {"item_id": "ALIVE", "ts": old_ts, "skip_reason": "d_marked_sold"}]
    with patch.object(rg, "PENDING_REVIVE_FILE", pending), \
         patch.object(rg, "DISCARDED_REVIVE_FILE", discarded):
        moved = rg.prune_unresolvable_pending_revive(skipped)
        rest = [json.loads(l)["item_id"] for l in pending.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert moved == 1
    assert rest == ["NEW_GONE", "ALIVE"]          # 新しい/解決可能なものは残す
    arch = [json.loads(l) for l in discarded.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert arch[0]["item_id"] == "OLD_GONE"        # 証跡は残す (silent drop 禁止)


@pytest.mark.offline
def test_prune_noop_when_nothing_expired(tmp_path):
    import ebay_actions.revive_csv_generator as rg
    pending = tmp_path / "pending_revive.jsonl"
    pending.write_text(json.dumps({"item_id": "A", "ts": datetime.now().isoformat()}) + "\n",
                       encoding="utf-8")
    with patch.object(rg, "PENDING_REVIVE_FILE", pending):
        assert rg.prune_unresolvable_pending_revive([]) == 0
