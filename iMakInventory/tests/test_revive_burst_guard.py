"""復活 急増ガード の regression test (2026-08-07 revive_qty1_impl 完了条件 6).

依頼書 §「仕様」 の④「急増ガード: `INVENTORY_REVIVE_BURST_THRESHOLD` 新設、
初期値 10。 閾値超過で全件 HOLD + action_required.jsonl に出ること」。

誤検知で大量復活が発火 → 履行不能 → BAN の血流を作らない (fail-closed)。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ebay_actions import revive_csv_generator as RC  # noqa: E402
import monitor_listings as ML  # noqa: E402


def _write_pending(pending_p: Path, entries):
    with open(pending_p, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _fake_sheet_state(labels_rows):
    """{(label, row_index): row_dict} を返す。"""
    m = {}
    for label, rows in labels_rows.items():
        for r in rows:
            m[(label, r["row_index"])] = r
    return m


def test_burst_guard_holds_all_and_writes_action_required(tmp_path, monkeypatch):
    """threshold=3、 gate 通過 5 件 → 全 HOLD + action_required.jsonl に 5 行。"""
    # 隔離
    monkeypatch.setattr(RC, "DECISION_LOG_DIR", tmp_path)
    monkeypatch.setattr(RC, "CSV_OUTPUT_DIR", tmp_path / "csv_output")
    monkeypatch.setattr(RC, "PENDING_REVIVE_FILE", tmp_path / "pending_revive.jsonl")
    monkeypatch.setattr(RC, "PROCESSED_REVIVE_FILE",
                        tmp_path / "processed_revive.jsonl")
    monkeypatch.setattr(ML, "DECISION_LOG_DIR", tmp_path)
    monkeypatch.setattr(ML, "ACTION_REQUIRED_FILE",
                        tmp_path / "action_required.jsonl")

    # pending_revive に 5 件 (全て gate 通過するように仕込む)
    pending_entries = []
    sheet_rows = []
    for i in range(5):
        row_idx = 100 + i
        iid = f"IID_BURST_{i:03d}"
        pending_entries.append({
            "ts": "2026-08-07T12:00:00", "sheet": "HIGH", "row_index": row_idx,
            "url": "https://amazon.co.jp/dp/B0000", "item_id": iid,
            "title": iid, "supplier": "amazon", "raw_status": "", "dry_run": False,
        })
        sheet_rows.append({
            "row_index": row_idx, "url": "https://amazon.co.jp/dp/B0000",
            "item_id": iid, "title": iid, "current_sold": "",
            "err_flag_prev": "", "checked_at": "2026/08/07 12:30:00",
            "key_number": "", "category": "G-SHOCK",
            "price": "10000", "current_m_jpy_str": "10000",
            "backup_urls": [], "backup_url_slots": [None] * 5,
            "current_n_jpy_str": "",
        })
    _write_pending(tmp_path / "pending_revive.jsonl", pending_entries)

    # sheet 側の読み込み系を fake
    monkeypatch.setattr(RC, "open_sheet_by_id", lambda sid: object())
    monkeypatch.setattr(RC, "get_listings_worksheet", lambda sh, gid=None: object())
    monkeypatch.setattr(RC, "read_listings_rows",
                        lambda ws, only_with_url=False: sheet_rows)

    # 採算 gate: 全件通過するよう mock
    result = RC.run(
        sheet="high",
        # ★ 2026-08-13: dry_run は状態を変えない契約に変更 (検証実行が要対応キューを
        #   水増ししていたため)。要対応の記録を見る本テストは実行モードで回す。
        #   allowed=0 なので CSV は書かれない。出力先は tmp_path に隔離済。
        dry_run=False,
        burst_threshold=3,  # 5 > 3 で発火
        max_per_cycle=None,
        cycle_started_at=datetime(2026, 8, 7, 12, 0, 0),
        provided_qty_map={},
        fetch_price_fn=lambda iid: (500.0, 0),
        compute_fn=lambda cost, med, cat: {"price": 100.0},
    )

    assert result["reason"] == "REVIVE_BURST_HOLD"
    assert result["allowed"] == 0
    assert result["burst_hold"] == 5
    # action_required.jsonl に 5 行書かれた (silent 化禁止)
    ar_p = tmp_path / "action_required.jsonl"
    assert ar_p.exists()
    lines = [json.loads(l) for l in ar_p.read_text(encoding="utf-8").splitlines() if l.strip()]
    # revive_burst_guard_holdout reason で 5 件
    burst_lines = [ln for ln in lines
                    if ln.get("reason") == "revive_burst_guard_holdout"]
    assert len(burst_lines) == 5


def test_burst_guard_below_threshold_allows_normally(tmp_path, monkeypatch):
    """threshold=10、 gate 通過 3 件 → 通常通り allowed (発火しない)。"""
    monkeypatch.setattr(RC, "DECISION_LOG_DIR", tmp_path)
    monkeypatch.setattr(RC, "CSV_OUTPUT_DIR", tmp_path / "csv_output")
    monkeypatch.setattr(RC, "PENDING_REVIVE_FILE", tmp_path / "pending_revive.jsonl")
    monkeypatch.setattr(RC, "PROCESSED_REVIVE_FILE",
                        tmp_path / "processed_revive.jsonl")

    pending_entries, sheet_rows = [], []
    for i in range(3):
        row_idx = 200 + i
        iid = f"IID_OK_{i}"
        pending_entries.append({
            "ts": "2026-08-07T12:00:00", "sheet": "HIGH", "row_index": row_idx,
            "url": "https://amazon.co.jp/dp/B1111", "item_id": iid,
            "title": iid, "supplier": "amazon", "raw_status": "", "dry_run": False,
        })
        sheet_rows.append({
            "row_index": row_idx, "url": "https://amazon.co.jp/dp/B1111",
            "item_id": iid, "title": iid, "current_sold": "",
            "err_flag_prev": "", "checked_at": "2026/08/07 12:30:00",
            "key_number": "", "category": "G-SHOCK",
            "price": "5000", "current_m_jpy_str": "5000",
            "backup_urls": [], "backup_url_slots": [None] * 5,
            "current_n_jpy_str": "",
        })
    _write_pending(tmp_path / "pending_revive.jsonl", pending_entries)

    monkeypatch.setattr(RC, "open_sheet_by_id", lambda sid: object())
    monkeypatch.setattr(RC, "get_listings_worksheet", lambda sh, gid=None: object())
    monkeypatch.setattr(RC, "read_listings_rows",
                        lambda ws, only_with_url=False: sheet_rows)

    result = RC.run(
        sheet="high", dry_run=True,
        burst_threshold=10,
        cycle_started_at=datetime(2026, 8, 7, 12, 0, 0),
        provided_qty_map={},
        fetch_price_fn=lambda iid: (500.0, 0),
        compute_fn=lambda cost, med, cat: {"price": 50.0},
    )
    assert result["reason"] == "OK"
    assert result["allowed"] == 3
    assert result["burst_hold"] == 0


def test_per_cycle_cap_truncates_excess(tmp_path, monkeypatch):
    """max_per_cycle=2、 5 件 gate 通過 → allowed=2, 残 3 件は deferred (次 cycle 再試行)。"""
    monkeypatch.setattr(RC, "DECISION_LOG_DIR", tmp_path)
    monkeypatch.setattr(RC, "CSV_OUTPUT_DIR", tmp_path / "csv_output")
    monkeypatch.setattr(RC, "PENDING_REVIVE_FILE", tmp_path / "pending_revive.jsonl")
    monkeypatch.setattr(RC, "PROCESSED_REVIVE_FILE",
                        tmp_path / "processed_revive.jsonl")

    pending_entries, sheet_rows = [], []
    for i in range(5):
        row_idx = 300 + i
        iid = f"IID_CAP_{i}"
        pending_entries.append({
            "ts": "2026-08-07T12:00:00", "sheet": "HIGH", "row_index": row_idx,
            "url": "https://amazon.co.jp/dp/B2222", "item_id": iid,
            "title": iid, "supplier": "amazon", "raw_status": "", "dry_run": False,
        })
        sheet_rows.append({
            "row_index": row_idx, "url": "https://amazon.co.jp/dp/B2222",
            "item_id": iid, "title": iid, "current_sold": "",
            "err_flag_prev": "", "checked_at": "2026/08/07 12:30:00",
            "key_number": "", "category": "G-SHOCK",
            "price": "5000", "current_m_jpy_str": "5000",
            "backup_urls": [], "backup_url_slots": [None] * 5,
            "current_n_jpy_str": "",
        })
    _write_pending(tmp_path / "pending_revive.jsonl", pending_entries)

    monkeypatch.setattr(RC, "open_sheet_by_id", lambda sid: object())
    monkeypatch.setattr(RC, "get_listings_worksheet", lambda sh, gid=None: object())
    monkeypatch.setattr(RC, "read_listings_rows",
                        lambda ws, only_with_url=False: sheet_rows)

    result = RC.run(
        sheet="high", dry_run=True,
        burst_threshold=100,   # burst 発火しない
        max_per_cycle=2,       # cap は 2 件
        cycle_started_at=datetime(2026, 8, 7, 12, 0, 0),
        provided_qty_map={},
        fetch_price_fn=lambda iid: (500.0, 0),
        compute_fn=lambda cost, med, cat: {"price": 50.0},
    )
    assert result["allowed"] == 2
    # 残 3 件は per_cycle_cap_exceeded で deferred (次 cycle 再試行)
    # deferred は skip/URL/3点等も含むが、 ここでは 3 件全て per_cycle_cap で落ちる
    assert result["reason"] == "PER_CYCLE_CAP"


def test_burst_guard_does_not_fire_on_old_backlog(tmp_path, monkeypatch):
    """★ 2026-08-13: 積み残し (古い queue) だけでは発火しない = 恒久 HOLD にしない。

    総数で判定していた頃は、詰まった backlog 自体が毎 cycle ガードを発火させ、
    08-08〜08-13 の 6 日間 復活が 1 件も実行されなかった。
    """
    monkeypatch.setattr(RC, "DECISION_LOG_DIR", tmp_path)
    monkeypatch.setattr(RC, "CSV_OUTPUT_DIR", tmp_path / "csv_output")
    monkeypatch.setattr(RC, "PENDING_REVIVE_FILE", tmp_path / "pending_revive.jsonl")
    monkeypatch.setattr(RC, "PROCESSED_REVIVE_FILE", tmp_path / "processed_revive.jsonl")

    pending_entries, sheet_rows = [], []
    for i in range(5):
        row_idx = 300 + i
        iid = f"IID_OLD_{i:03d}"
        pending_entries.append({
            "ts": "2026-08-01T12:00:00",        # cycle 開始の 6 日前 = backlog
            "sheet": "HIGH", "row_index": row_idx,
            "url": "https://amazon.co.jp/dp/B0000", "item_id": iid,
            "title": iid, "supplier": "amazon", "raw_status": "", "dry_run": False,
        })
        sheet_rows.append({
            "row_index": row_idx, "url": "https://amazon.co.jp/dp/B0000",
            "item_id": iid, "title": iid, "current_sold": "",
            "err_flag_prev": "", "checked_at": "2026/08/07 12:30:00",
            "key_number": "", "category": "G-SHOCK",
            "price": "10000", "current_m_jpy_str": "10000",
            "backup_urls": [], "backup_url_slots": [None] * 5,
            "current_n_jpy_str": "",
        })
    _write_pending(tmp_path / "pending_revive.jsonl", pending_entries)
    monkeypatch.setattr(RC, "open_sheet_by_id", lambda sid: object())
    monkeypatch.setattr(RC, "get_listings_worksheet", lambda sh, gid=None: object())
    monkeypatch.setattr(RC, "read_listings_rows", lambda ws, only_with_url=False: sheet_rows)

    result = RC.run(
        sheet="high", dry_run=True, burst_threshold=3, max_per_cycle=None,
        cycle_started_at=datetime(2026, 8, 7, 12, 0, 0),
        provided_qty_map={}, fetch_price_fn=lambda iid: (500.0, 0),
        compute_fn=lambda cost, med, cat: {"price": 100.0},
    )
    assert result["reason"] != "REVIVE_BURST_HOLD"
    assert result["burst_hold"] == 0
    assert result["allowed"] == 5
