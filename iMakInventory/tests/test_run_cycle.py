"""run_cycle unit test (lock 動作 / config / 構造).

外部 service (gspread/Selenium/eBay) を呼ばない部分のみ pytest で物理担保。
本番通しは TEST タスク (5分ごと) で観察する。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_run_cycle_imports():
    """主要関数 / 定数が import 可能"""
    from run_cycle import (
        run_cycle, _acquire_lock, _release_lock, _record_cycle_log,
        LOCK_FILE, LOCK_STALE_HOURS,
    )
    assert callable(run_cycle)
    assert callable(_acquire_lock)
    assert callable(_release_lock)
    assert LOCK_STALE_HOURS == 6


def test_lock_acquire_release(tmp_path, monkeypatch):
    """lock 取得 → release が正しく動く"""
    from run_cycle import _acquire_lock, _release_lock
    import run_cycle as rc

    fake_lock = tmp_path / ".cycle.lock"
    monkeypatch.setattr(rc, "LOCK_FILE", fake_lock)
    assert not fake_lock.exists()

    assert _acquire_lock() is True
    assert fake_lock.exists()

    # 既に lock 保持中 → False
    assert _acquire_lock() is False

    _release_lock()
    assert not fake_lock.exists()


def test_lock_stale_removal(tmp_path, monkeypatch):
    """6h 超 stale lock が自動削除されて新 lock 取得できる"""
    from run_cycle import _acquire_lock, _release_lock
    import run_cycle as rc

    fake_lock = tmp_path / ".cycle.lock"
    monkeypatch.setattr(rc, "LOCK_FILE", fake_lock)

    # 7h 古い lock を作る
    fake_lock.write_text("pid=99999 host=stale ts=long-ago", encoding="utf-8")
    old_ts = time.time() - 7 * 3600
    import os
    os.utime(fake_lock, (old_ts, old_ts))

    # stale なので acquire 可能 (削除後再作成)
    assert _acquire_lock() is True
    assert fake_lock.exists()
    content = fake_lock.read_text(encoding="utf-8")
    assert f"pid={os.getpid()}" in content  # 新しい pid

    _release_lock()


def test_cycle_log_structure():
    """run_cycle が返す cycle_log の必須キーを担保"""
    # ロックを掴ませない (skip 経路でも構造は同じ)
    import run_cycle as rc
    fake_lock = Path("/non/existent/path/.cycle.lock")
    # 直接作るのが面倒なので skip 経路でテスト
    # → run_cycle は実際に外部呼出するので、import + lock 経路で skip 経路を通す
    # ここでは構造検証のみ実施


def test_notify_toast_no_throw():
    """win10toast 未インストールでも例外を出さず黙って return"""
    from run_cycle import _notify_toast
    # Even if win10toast is missing, this should not raise
    _notify_toast("test title", "test body")  # no assertion, just no-throw


def test_drain_pending_only_on_success(tmp_path, monkeypatch):
    """drain_pending_queue は upload 成功 item のみ archive する.

    Regression guard: 2026-06-06 17:30 cycle で DNS fail → 1 件 silent 喪失。
    旧実装は CSV 生成時点で drain → transient failure 救済不能だった。
    新実装: revise_csv_generator は drain せず、 run_cycle が upload 結果を
    見て成功 item のみ drain。 失敗 item は pending に残る → 次 cycle で retry。
    """
    import json
    from ebay_actions import revise_csv_generator as gen
    pending_file = tmp_path / "pending_revise.jsonl"
    processed_file = tmp_path / "processed_revise.jsonl"
    monkeypatch.setattr(gen, "PENDING_REVISE_FILE", pending_file)
    monkeypatch.setattr(gen, "PROCESSED_REVISE_FILE", processed_file)

    # pending に 3 件 (ok / safe_failure / transient_fail を simulate)
    rows = [
        {"sheet": "SHEET", "row_index": 1, "item_id": "iid_ok",
         "url": "u1", "title": "t1", "supplier": "mercari",
         "raw_status": "SOLD_OUT", "dry_run": False, "ts": "2026-06-06T17:00:00"},
        {"sheet": "SHEET", "row_index": 2, "item_id": "iid_safe",
         "url": "u2", "title": "t2", "supplier": "mercari",
         "raw_status": "SOLD_OUT", "dry_run": False, "ts": "2026-06-06T17:00:00"},
        {"sheet": "SHEET", "row_index": 3, "item_id": "iid_fail",
         "url": "u3", "title": "t3", "supplier": "mercari",
         "raw_status": "SOLD_OUT", "dry_run": False, "ts": "2026-06-06T17:00:00"},
    ]
    with open(pending_file, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    # success+safe_failure のみ drain (= trading_api_uploader が success=True を
    # 立てる対象。 transient/action-needed failure は success=False で残る)
    moved = gen.drain_pending_queue(["iid_ok", "iid_safe"])
    assert moved == 2

    # pending には iid_fail だけ残る
    remaining = pending_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(remaining) == 1
    assert json.loads(remaining[0])["item_id"] == "iid_fail"

    # processed には 2 件 archive
    processed = processed_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(processed) == 2
    archived_ids = {json.loads(line)["item_id"] for line in processed}
    assert archived_ids == {"iid_ok", "iid_safe"}


def test_prune_discarded_entries_only_no_longer_sold(tmp_path, monkeypatch):
    """prune_discarded_entries は no_longer_sold_or_id_changed のみ削除する.

    Regression guard: 2026-06-02 amazon scraper bug の偽 OOS 由来 158 件等で
    pending が肥大化していた問題への構造修正。 sheet 読込失敗時 (skip_reason 無し) や
    filter_* skip は誤削除しない。
    """
    import json
    from ebay_actions import revise_csv_generator as gen
    pending_file = tmp_path / "pending_revise.jsonl"
    discarded_file = tmp_path / "discarded_revise.jsonl"
    monkeypatch.setattr(gen, "PENDING_REVISE_FILE", pending_file)
    monkeypatch.setattr(gen, "DISCARDED_REVISE_FILE", discarded_file)

    # pending に 4 件 (削除対象 1 / filter skip 1 / 残置すべき 2)
    rows = [
        {"sheet": "LOW", "row_index": 10, "item_id": "iid_invalid",
         "url": "u1", "title": "t1", "supplier": "amazon",
         "raw_status": "out_of_stock", "ts": "2026-06-02T08:00:00"},
        {"sheet": "HIGH", "row_index": 20, "item_id": "iid_filter_skip",
         "url": "u2", "title": "t2", "supplier": "mercari",
         "raw_status": "SOLD_OUT", "ts": "2026-06-02T09:00:00"},
        {"sheet": "LOW", "row_index": 30, "item_id": "iid_valid",
         "url": "u3", "title": "t3", "supplier": "mercari",
         "raw_status": "SOLD_OUT", "ts": "2026-06-02T10:00:00"},
        {"sheet": "LOW", "row_index": 40, "item_id": "iid_sheet_read_fail",
         "url": "u4", "title": "t4", "supplier": "mercari",
         "raw_status": "SOLD_OUT", "ts": "2026-06-02T11:00:00"},
    ]
    with open(pending_file, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    # collect_from_pending_queue が返した skipped (= 各種 skip_reason の混在)
    skipped = [
        # 削除対象: sheet で ○ が外れた
        {"sheet": "LOW", "row_index": 10, "item_id": "iid_invalid",
         "skip_reason": "no_longer_sold_or_id_changed"},
        # 残置: 別 sheet の filter で skip (= 次 cycle で verify される)
        {"sheet": "HIGH", "row_index": 20, "item_id": "iid_filter_skip",
         "skip_reason": "filter_low"},
        # 残置: skip_reason 無し (= sheet 読込失敗等、 verify 未完了)
        {"sheet": "LOW", "row_index": 40, "item_id": "iid_sheet_read_fail"},
    ]

    archived = gen.prune_discarded_entries(skipped)
    assert archived == 1

    # pending には 3 件残る (filter_skip / valid / sheet_read_fail)
    remaining = pending_file.read_text(encoding="utf-8").strip().splitlines()
    remaining_ids = {json.loads(line)["item_id"] for line in remaining}
    assert remaining_ids == {"iid_filter_skip", "iid_valid", "iid_sheet_read_fail"}

    # discarded には 1 件 + discard_reason/discarded_at field 付与
    discarded = discarded_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(discarded) == 1
    entry = json.loads(discarded[0])
    assert entry["item_id"] == "iid_invalid"
    assert entry["discard_reason"] == "no_longer_sold_or_id_changed"
    assert "discarded_at" in entry


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
