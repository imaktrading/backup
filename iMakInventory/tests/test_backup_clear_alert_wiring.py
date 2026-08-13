"""補URL消込: run_cycle._phase_monitor の集約〜ALERT発報 配線テスト (実送なし).

★ 2026-07-25: clear_sold_backup_cells のロジックは test_backup_url_clear.py で実証済。
  本テストは「消込急増ガード HOLD / compare-and-clear mismatch を run_cycle が集約し、
  desktop ALERT file + gmail(mock) + toast で非-silent 告知する」配線を検証する
  (`completion_must_be_proven`。実 gmail は spam のため mock)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _patch_common(monkeypatch, tmp_path, sent):
    import run_cycle
    import email_notifier
    import auth.encrypted_gmail as encrypted_gmail
    monkeypatch.setattr(run_cycle.Path, "home", staticmethod(lambda: tmp_path))
    (tmp_path / "OneDrive" / "デスクトップ").mkdir(parents=True, exist_ok=True)
    # throttle state を tmp に隔離 (実 decision_log の state に依存しない = 初回 emit を保証)
    monkeypatch.setattr(run_cycle, "BACKUP_CLEAR_ALERT_STATE", tmp_path / "bc_alert_state.json")
    monkeypatch.setattr(run_cycle, "_notify_toast", lambda *a, **k: None)
    monkeypatch.setattr(encrypted_gmail, "load_gmail_config", lambda: ("a", "p", "t"))
    monkeypatch.setattr(email_notifier, "_send_via_gmail",
                        lambda a, p, t, subject, body: sent.update(subject=subject, body=body))
    return run_cycle


def _base_stats(**over):
    d = {"processed": 5, "newly_sold": 0, "newly_in_stock": 0, "errors": 0,
         "url_alerts": [], "error_rows": [], "persistent_err_rows": [],
         "price_surge_held": [], "price_surge_stats": {},
         "backup_clear": {"cleared": 0, "skipped_mismatch": [], "held": False,
                          "candidate_count": 0, "surge": False}}
    d.update(over)
    return d


def test_backup_clear_surge_hold_alerts(monkeypatch, tmp_path):
    """消込急増ガード HOLD → desktop ALERT + mail 発報."""
    sent = {}
    run_cycle = _patch_common(monkeypatch, tmp_path, sent)
    stats = _base_stats(backup_clear={"cleared": 0, "skipped_mismatch": [], "held": True,
                                      "candidate_count": 44, "surge": True})
    monkeypatch.setattr(run_cycle, "process_sheet", lambda **k: stats)

    grand = run_cycle._phase_monitor(sheet="high", limit=None, test_mode=True,
                                     single_sheet_id="dummy", single_sheet_label="HIGH")
    assert len(grand["backup_clear_held"]) == 1
    alerts = list((tmp_path / "OneDrive" / "デスクトップ").glob("ALERT_iMakInventory_backup_clear_*.txt"))
    assert len(alerts) == 1
    assert "fail-OPEN ではない" in alerts[0].read_text(encoding="utf-8")
    assert "補URL消込" in sent.get("subject", "")


def test_backup_clear_mismatch_alerts(monkeypatch, tmp_path):
    """compare-and-clear mismatch のうち **要対応のものだけ** ALERT (silent drop 禁止)。

    ★ 2026-08-13 改: セル値が「別の生きた URL」= HQ 差替は正常な競合で人の手が要らないため
      告知しない。ここでは URL でない値が入った異常系を要対応として検証する。
    """
    sent = {}
    run_cycle = _patch_common(monkeypatch, tmp_path, sent)
    stats = _base_stats(backup_clear={
        "cleared": 2,
        "skipped_mismatch": [{"row_index": 10, "slot": 1,
                              "expected_url": "https://old", "actual": "売切"}],
        "held": False, "candidate_count": 3, "surge": False})
    monkeypatch.setattr(run_cycle, "process_sheet", lambda **k: stats)

    grand = run_cycle._phase_monitor(sheet="high", limit=None, test_mode=True,
                                     single_sheet_id="dummy", single_sheet_label="HIGH")
    assert grand["backup_clear_cleared"] == 2
    assert len(grand["backup_clear_mismatch"]) == 1
    alerts = list((tmp_path / "OneDrive" / "デスクトップ").glob("ALERT_iMakInventory_backup_clear_*.txt"))
    assert len(alerts) == 1


def test_backup_clear_hq_url_swap_does_not_alert(monkeypatch, tmp_path):
    """HQ が別の生きた仕入元URLに差し替えただけ → 記録はするが ALERT は出さない。

    ★ 2026-08-13: 18:49 にこれで desktop ALERT が出た。消さなかったのが正解で、次 cycle が
      新URLを普通に見る = 人が何もすることがない通知だった。
    """
    sent = {}
    run_cycle = _patch_common(monkeypatch, tmp_path, sent)
    stats = _base_stats(backup_clear={
        "cleared": 2,
        "skipped_mismatch": [{"row_index": 1348, "slot": 1,
                              "expected_url": "https://jp.mercari.com/shops/product/OLD",
                              "actual": "https://jp.mercari.com/shops/product/NEW"}],
        "held": False, "candidate_count": 3, "surge": False})
    monkeypatch.setattr(run_cycle, "process_sheet", lambda **k: stats)

    grand = run_cycle._phase_monitor(sheet="high", limit=None, test_mode=True,
                                     single_sheet_id="dummy", single_sheet_label="HIGH")
    assert len(grand["backup_clear_mismatch"]) == 1          # 記録は残す
    alerts = list((tmp_path / "OneDrive" / "デスクトップ").glob("ALERT_iMakInventory_backup_clear_*.txt"))
    assert alerts == []                                       # 告知はしない
    assert not sent.get("mail")


def test_backup_clear_clean_no_alert(monkeypatch, tmp_path):
    """消込が正常 (HOLD なし mismatch なし) なら ALERT を出さない."""
    sent = {}
    run_cycle = _patch_common(monkeypatch, tmp_path, sent)
    stats = _base_stats(backup_clear={"cleared": 3, "skipped_mismatch": [], "held": False,
                                      "candidate_count": 3, "surge": False})
    monkeypatch.setattr(run_cycle, "process_sheet", lambda **k: stats)

    grand = run_cycle._phase_monitor(sheet="high", limit=None, test_mode=True,
                                     single_sheet_id="dummy", single_sheet_label="HIGH")
    assert grand["backup_clear_cleared"] == 3
    assert grand["backup_clear_held"] == []
    assert grand["backup_clear_mismatch"] == []
    assert list((tmp_path / "OneDrive" / "デスクトップ").glob("ALERT_*backup_clear*.txt")) == []
    assert sent == {}
