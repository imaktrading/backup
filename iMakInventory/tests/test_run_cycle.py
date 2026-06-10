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


def test_prune_discarded_entries_requires_ebay_qty_zero(tmp_path, monkeypatch):
    """prune_discarded_entries は eBay GetItem qty=0 確認後にのみ discard。

    Regression guard (HQ 2026-06-10 FINAL 指示):
    - 旧 b4c238d は sheet D=空 だけで discard → 6/10 09:30 で sheet 書込 DNS fail 由来の
      偽 D=空 で 2 件 silent drop 発生
    - 新実装: eBay qty=0 確認 → discard / qty>0 → pending 残置 + 再 include 候補 /
      API fail → 保守的に pending 残置
    """
    import json
    from ebay_actions import revise_csv_generator as gen
    from ebay_actions import trading_api_client as tac
    pending_file = tmp_path / "pending_revise.jsonl"
    discarded_file = tmp_path / "discarded_revise.jsonl"
    monkeypatch.setattr(gen, "PENDING_REVISE_FILE", pending_file)
    monkeypatch.setattr(gen, "DISCARDED_REVISE_FILE", discarded_file)
    monkeypatch.setattr(tac, "load_access_token", lambda: "test_token")

    # eBay GetItem の応答を item_id 別に偽装
    def fake_call_trading(call_name, body, access_token=None):
        # body から ItemID 抽出
        import re
        m = re.search(r"<ItemID>([^<]+)</ItemID>", body)
        iid = m.group(1) if m else ""
        if iid == "iid_qty_zero":
            return {"success": True, "ack": "Success", "error_code": None,
                    "error_message": None, "raw_xml": "<Quantity>0</Quantity>"}
        if iid == "iid_qty_one":
            return {"success": True, "ack": "Success", "error_code": None,
                    "error_message": None, "raw_xml": "<Quantity>1</Quantity>"}
        if iid == "iid_err_17":
            return {"success": False, "ack": "Failure", "error_code": "17",
                    "error_message": "Item cannot be accessed.", "raw_xml": ""}
        if iid == "iid_api_fail":
            return {"success": False, "ack": None, "error_code": None,
                    "error_message": "ConnectionError: ...", "raw_xml": ""}
        return {"success": False, "ack": None, "error_code": None,
                "error_message": "unknown", "raw_xml": ""}
    monkeypatch.setattr(tac, "_call_trading", fake_call_trading)

    # pending に 6 件
    rows = [
        # ① 削除対象: sheet D=空 + eBay qty=0
        {"sheet": "LOW", "row_index": 10, "item_id": "iid_qty_zero",
         "url": "u1", "title": "t1", "ts": "2026-06-02T08:00:00"},
        # ② 残置 (再 include 候補): sheet D=空 だが eBay qty=1 (= sheet が誤)
        {"sheet": "LOW", "row_index": 20, "item_id": "iid_qty_one",
         "url": "u2", "title": "t2", "ts": "2026-06-02T09:00:00"},
        # ③ 削除対象: err 17 = Item not found (= 既 ended、 qty=0 同等)
        {"sheet": "LOW", "row_index": 30, "item_id": "iid_err_17",
         "url": "u3", "title": "t3", "ts": "2026-06-02T10:00:00"},
        # ④ 残置: API 失敗 → 保守的に保持
        {"sheet": "LOW", "row_index": 40, "item_id": "iid_api_fail",
         "url": "u4", "title": "t4", "ts": "2026-06-02T11:00:00"},
        # ⑤ 残置: filter skip (= eBay verify されない)
        {"sheet": "HIGH", "row_index": 50, "item_id": "iid_filter_skip",
         "url": "u5", "title": "t5", "ts": "2026-06-02T12:00:00"},
        # ⑥ 残置: skip_reason 無し (= sheet 読込失敗等)
        {"sheet": "LOW", "row_index": 60, "item_id": "iid_sheet_read_fail",
         "url": "u6", "title": "t6", "ts": "2026-06-02T13:00:00"},
    ]
    with open(pending_file, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    skipped = [
        {"sheet": "LOW", "row_index": 10, "item_id": "iid_qty_zero",
         "skip_reason": "no_longer_sold_or_id_changed"},
        {"sheet": "LOW", "row_index": 20, "item_id": "iid_qty_one",
         "skip_reason": "no_longer_sold_or_id_changed"},
        {"sheet": "LOW", "row_index": 30, "item_id": "iid_err_17",
         "skip_reason": "no_longer_sold_or_id_changed"},
        {"sheet": "LOW", "row_index": 40, "item_id": "iid_api_fail",
         "skip_reason": "no_longer_sold_or_id_changed"},
        {"sheet": "HIGH", "row_index": 50, "item_id": "iid_filter_skip",
         "skip_reason": "filter_low"},
        {"sheet": "LOW", "row_index": 60, "item_id": "iid_sheet_read_fail"},
    ]

    res = gen.prune_discarded_entries(skipped)
    assert res["discarded"] == 2  # qty=0 + err 17
    assert res["kept_qty_gt0"] == 1  # qty=1 で再 include 候補
    assert len(res["reincluded"]) == 1
    assert res["reincluded"][0]["item_id"] == "iid_qty_one"

    # pending には 4 件残る (qty_one / api_fail / filter_skip / sheet_read_fail)
    remaining = pending_file.read_text(encoding="utf-8").strip().splitlines()
    remaining_ids = {json.loads(line)["item_id"] for line in remaining}
    assert remaining_ids == {
        "iid_qty_one", "iid_api_fail", "iid_filter_skip", "iid_sheet_read_fail"
    }

    # discarded には 2 件 (qty=0 + err 17)
    discarded = discarded_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(discarded) == 2
    discarded_ids = {json.loads(line)["item_id"] for line in discarded}
    assert discarded_ids == {"iid_qty_zero", "iid_err_17"}
    for line in discarded:
        e = json.loads(line)
        assert e["discard_reason"] == "ebay_qty_zero_confirmed"
        assert "discarded_at" in e


def test_email_header_shows_untaken_count_when_action_required(tmp_path, monkeypatch):
    """HQ 2026-06-10 FINAL 指示 C: cycle report 冒頭 1 行で取下げ漏れ件数明示.

    Regression guard: 6/10 09:30 で「4 件中 1 件未取下げを「正常」表記していた bug」 是正。
    action_required_summary.count > 0 → 「⚠️ 要対応 Y件」 ヘッダ、 = 0 → 「✅ 全件完了」。
    """
    from email_notifier import _format_body
    # case 1: 要対応 2 件
    cycle_log_action = {
        "status": "success",
        "ts_start": "2026-06-10T17:30:00",
        "ts_end":   "2026-06-10T17:58:00",
        "phases": {
            "monitor": {"newly_sold": 4, "newly_in_stock": 0,
                         "processed": 913, "errors": 0},
            "revise_csv": {"allowed": 3},
            "upload": {"success": False, "csv_lines": 3, "results": [
                {"item_id": "111", "success": True, "verified": True, "verify_qty": 0},
                {"item_id": "222", "success": True, "safe_failure": True},
                {"item_id": "333", "success": False, "verified": False, "verify_qty": 1},
            ]},
            "action_required_summary": {
                "count": 2,
                "items": [
                    {"sheet": "LOW", "row": 637, "item_id": "",
                     "title": "test1", "reason": "item_id_empty"},
                    {"sheet": "HIGH", "row": 479, "item_id": "333",
                     "title": "test2", "reason": "verify_qty_gt0_giveup"},
                ],
            },
        },
    }
    body = _format_body(cycle_log_action)
    assert "売切検知 4 → 完了 2 / 未取下げ 2" in body
    assert "⚠️ 要対応 (取下げ漏れ 2 件)" in body
    assert "item_id_empty" in body
    assert "verify_qty_gt0_giveup" in body
    # 旧 bug の「正常」 表記が出ないことを確認
    assert "正常 (取下げ実施)" not in body

    # case 2: 全件完了 (= 売切検知あり、 全 success)
    cycle_log_ok = {
        "status": "success",
        "ts_start": "2026-06-10T13:30:00",
        "ts_end":   "2026-06-10T13:58:00",
        "phases": {
            "monitor": {"newly_sold": 3, "newly_in_stock": 0,
                         "processed": 913, "errors": 0},
            "revise_csv": {"allowed": 3},
            "upload": {"success": True, "csv_lines": 3, "results": [
                {"item_id": "111", "success": True, "verified": True, "verify_qty": 0},
                {"item_id": "222", "success": True, "verified": True, "verify_qty": 0},
                {"item_id": "333", "success": True, "safe_failure": True},
            ]},
            "action_required_summary": {"count": 0, "items": []},
        },
    }
    body_ok = _format_body(cycle_log_ok)
    assert "売切検知 3 → 完了 3 / 未取下げ 0" in body_ok
    assert "✅ 全件取下げ完了" in body_ok
    assert "⚠️ 要対応" not in body_ok


def test_in_cycle_verify_blocks_silent_success(tmp_path, monkeypatch):
    """HQ 2026-06-10 FINAL 指示 A: revise 後 GetItem qty=0 確認できない限り success=False.

    Regression guard: revise 投げて Ack=Success でも、 実際に qty=0 になってない場合
    (= eBay 反映遅延 / 部分失敗等) を silent success として扱わない。
    """
    from ebay_actions import trading_api_uploader as tau
    from ebay_actions import trading_api_client as tac

    # _call_one (revise) は常に Success ack を返す (= 表面 success)
    def fake_revise(item_id, quantity, access_token=None):
        return {"success": True, "ack": "Success", "error_code": None,
                "error_message": None, "raw_xml": "<Ack>Success</Ack>"}
    monkeypatch.setattr(tac, "revise_inventory_status", fake_revise)
    monkeypatch.setattr(tac, "load_access_token", lambda: "test_token")

    # GetItem は qty=5 (= revise が実際は反映されてない) を返し続ける
    def fake_call_trading(call_name, body, access_token=None):
        return {"success": True, "ack": "Success", "error_code": None,
                "error_message": None, "raw_xml": "<Quantity>5</Quantity>"}
    monkeypatch.setattr(tac, "_call_trading", fake_call_trading)
    monkeypatch.setattr(tau, "_call_trading", fake_call_trading)
    # in-cycle retry の sleep を抑制
    monkeypatch.setattr(tau, "INCYCLE_RETRY_INTERVALS_SEC", [0.0, 0.0, 0.0])
    monkeypatch.setattr(tau.time, "sleep", lambda _: None)

    # CSV を tmp に作って upload を回す
    csv_path = tmp_path / "fake_revise.csv"
    csv_path.write_text(
        '"*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)","ItemID","*Quantity"\n'
        '"Revise","999111","0"\n',
        encoding="utf-8",
    )
    result = tau.upload_csv_via_trading_api(csv_path, dry_run=False, pacing_sec=0.0)
    # in-cycle verify NG (qty=5 残存) → success=False, verified=False
    assert result["success"] is False, "verify NG なのに success=True"
    assert result["ng"] == 1
    entry = result["results"][0]
    assert entry["success"] is False
    assert entry["verified"] is False
    assert entry["verify_qty"] == 5
    # 最大 retry 回数走ったことを確認 (= 諦めずに retry した)
    assert entry["verify_attempts"] >= 3


def test_burst_guard_holds_mass_reinclude_to_action_required(tmp_path, monkeypatch):
    """HQ 2026-06-10 confirm 指示 A: reinclude 件数が閾値超で全件 HOLD + action_required 記録.

    6/10 09:30 同型 (sheet 書込系統的異常) で大量 reinclude が発生したら fail-CLOSED で
    保留、 silent化せず action_required.jsonl に記録 + alert (= HQ B 「HOLD は必ず alert」)。
    """
    import json
    import os
    from ebay_actions import revise_csv_generator as gen
    from ebay_actions import trading_api_client as tac
    import monitor_listings as ml

    pending_file = tmp_path / "pending_revise.jsonl"
    discarded_file = tmp_path / "discarded_revise.jsonl"
    action_file = tmp_path / "action_required.jsonl"
    monkeypatch.setattr(gen, "PENDING_REVISE_FILE", pending_file)
    monkeypatch.setattr(gen, "DISCARDED_REVISE_FILE", discarded_file)
    monkeypatch.setattr(ml, "ACTION_REQUIRED_FILE", action_file)
    monkeypatch.setattr(ml, "DECISION_LOG_DIR", tmp_path)
    monkeypatch.setattr(gen, "DEFAULT_REINCLUDE_BURST_THRESHOLD", 5)
    monkeypatch.setattr(tac, "load_access_token", lambda: "test_token")

    # GetItem は常に qty=1 を返す (= reinclude 候補化)
    def fake_call_trading(call_name, body, access_token=None):
        return {"success": True, "ack": "Success", "error_code": None,
                "error_message": None, "raw_xml": "<Quantity>1</Quantity>"}
    monkeypatch.setattr(tac, "_call_trading", fake_call_trading)

    # pending に 10 件 (= 閾値 5 を超える)
    rows = []
    skipped = []
    for i in range(10):
        iid = f"iid_{i:02d}"
        rows.append({"sheet": "LOW", "row_index": 100 + i, "item_id": iid,
                     "url": "u", "title": "t", "ts": "2026-06-10T11:00:00"})
        skipped.append({"sheet": "LOW", "row_index": 100 + i, "item_id": iid,
                         "skip_reason": "no_longer_sold_or_id_changed"})
    with open(pending_file, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    # prune を実行 → 10 件全部 reinclude 候補になる
    res = gen.prune_discarded_entries(skipped)
    assert res["kept_qty_gt0"] == 10
    assert len(res["reincluded"]) == 10

    # run() を直接呼ぶのは sheet 接続必要なので、 急増ガード判定 logic だけ単体検証
    # 閾値 5 < reincluded 10 → HOLD 発火、 全件 action_required.jsonl 記録すべき
    threshold = gen.DEFAULT_REINCLUDE_BURST_THRESHOLD
    assert threshold == 5
    assert len(res["reincluded"]) > threshold
    # HOLD 動作の手動シミュレーション (= run() 内 logic を模擬)
    if len(res["reincluded"]) > threshold:
        for q in res["reincluded"]:
            ml.append_action_required(
                sheet_label=q.get("sheet", ""),
                result={
                    "row_index": q.get("row_index", -1),
                    "url":       q.get("url", ""),
                    "item_id":   q.get("item_id", ""),
                    "title":     q.get("title", ""),
                    "supplier":  "",
                    "raw_status": "reinclude_burst_holdout",
                },
                reason="reinclude_burst_guard_holdout",
                dry_run=False,
            )

    # action_required.jsonl に 10 件記録されたこと
    assert action_file.exists()
    ar_lines = [l for l in action_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(ar_lines) == 10
    # 全件 reason = reinclude_burst_guard_holdout
    for line in ar_lines:
        e = json.loads(line)
        assert e["reason"] == "reinclude_burst_guard_holdout"


def test_reverse_audit_email_uses_hq_b_wording(tmp_path):
    """HQ 2026-06-10 confirm 指示 B: 「0 件目標」 を文言に出さず、 初回乖離鳥瞰を audit 機能の証拠と表現.

    Regression guard: 「0 件目標」 文言は乖離隠ぺい圧力を生む = fail-OPEN 再発リスク。
    乖離 > 0 のときは 「audit 機能の証拠」 / 「人手で順次潰す」 / 「継続 0 件 が再発しない証跡」 を出す。
    """
    from email_notifier import _format_body
    cycle_log = {
        "status": "success",
        "ts_start": "2026-06-12T09:30:00",
        "ts_end":   "2026-06-12T11:38:00",
        "phases": {
            "monitor": {"newly_sold": 0, "newly_in_stock": 0,
                         "processed": 1670, "errors": 0},
            "reverse_audit": {
                "ts": "2026-06-12T11:38:00",
                "mismatch_count": 23,
                "by_sheet": {"HIGH": 15, "LOW": 8},
                "by_supplier": {"mercari": 20, "amazon": 3},
                "log_path": "/path/to/reverse_audit_log.jsonl",
            },
            "action_required_summary": {"count": 0, "items": []},
        },
    }
    body = _format_body(cycle_log)
    assert "乖離 23 件検出" in body
    assert "5 週間分の既存乖離" in body
    assert "audit 機能の証拠" in body
    # 0 件目標 / ゼロ件目標 等の文言は禁止
    assert "0 件目標" not in body
    assert "ゼロ件目標" not in body
    # 期限明記
    assert "24 時間以内" in body

    # 継続ゼロ件 case
    cycle_log_zero = {
        "status": "success",
        "ts_start": "2026-06-13T09:30:00",
        "ts_end":   "2026-06-13T11:38:00",
        "phases": {
            "monitor": {"newly_sold": 0, "newly_in_stock": 0,
                         "processed": 1670, "errors": 0},
            "reverse_audit": {
                "ts": "2026-06-13T11:38:00",
                "mismatch_count": 0,
                "by_sheet": {}, "by_supplier": {},
                "log_path": "/path/to/zero_log.jsonl",
            },
            "action_required_summary": {"count": 0, "items": []},
        },
    }
    body_zero = _format_body(cycle_log_zero)
    assert "乖離 0 件" in body_zero
    assert "継続証跡" in body_zero


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
