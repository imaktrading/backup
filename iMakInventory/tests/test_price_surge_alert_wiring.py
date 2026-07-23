"""価格急増ガード: run_cycle._phase_monitor の集約〜ALERT発報 配線テスト.

★ 2026-07-23: detect_price_surge のロジックは test_price_surge_guard.py で実証済。
  本テストは残る「穴」= process_sheet の price_surge_held を sheet 跨ぎ集約し、
  発火時に desktop ALERT file + gmail (mock) + toast が発報される配線を実送せず検証する
  (`completion_must_be_proven`: 動く証拠。ただし実 gmail は spam なので mock で代替)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_surge_triggers_desktop_alert_and_mail(monkeypatch, tmp_path):
    """process_sheet が surge を返す → grand 集約 + desktop ALERT file + mail 発報."""
    import run_cycle
    import email_notifier
    import auth.encrypted_gmail as encrypted_gmail

    # process_sheet を surge 検知結果に差し替え (実巡回しない)
    def fake_process_sheet(**kwargs):
        return {
            "processed": 12, "newly_sold": 0, "newly_in_stock": 0, "errors": 0,
            "url_alerts": [], "error_rows": [], "persistent_err_rows": [],
            "price_surge_held": ["amazon"],
            "price_surge_stats": {"amazon": {"total": 12, "surged": 9, "ratio": 0.75}},
        }
    monkeypatch.setattr(run_cycle, "process_sheet", fake_process_sheet)

    # desktop 出力先を tmp に (実デスクトップに ALERT file を作らない)
    monkeypatch.setattr(run_cycle.Path, "home", staticmethod(lambda: tmp_path))
    (tmp_path / "OneDrive" / "デスクトップ").mkdir(parents=True, exist_ok=True)

    # toast は no-op、 mail は送信引数を記録 (実送しない)
    monkeypatch.setattr(run_cycle, "_notify_toast", lambda *a, **k: None)
    sent = {}
    monkeypatch.setattr(encrypted_gmail, "load_gmail_config", lambda: ("a@x", "pw", "to@x"))
    monkeypatch.setattr(email_notifier, "_send_via_gmail",
                        lambda a, p, t, subject, body: sent.update(subject=subject, body=body))

    grand = run_cycle._phase_monitor(
        sheet="high", limit=None, test_mode=True,
        single_sheet_id="dummy", single_sheet_label="HIGH",
    )

    # 1. 集約された
    assert len(grand["price_surge"]) == 1
    assert grand["price_surge"][0]["supplier"] == "amazon"
    assert grand["price_surge"][0]["sheet"] == "HIGH"

    # 2. desktop ALERT file が出力された
    alerts = list((tmp_path / "OneDrive" / "デスクトップ").glob("ALERT_iMakInventory_price_surge_*.txt"))
    assert len(alerts) == 1
    txt = alerts[0].read_text(encoding="utf-8")
    assert "amazon" in txt
    assert "取下げ漏れはありません" in txt  # fail-OPEN でない旨を明記

    # 3. mail が発報された (surge 件名)
    assert "価格急増ガード" in sent.get("subject", "")


def test_no_surge_no_alert(monkeypatch, tmp_path):
    """surge が無ければ ALERT file も mail も出さない (誤発報しない)."""
    import run_cycle
    import email_notifier
    import auth.encrypted_gmail as encrypted_gmail

    def fake_process_sheet(**kwargs):
        return {
            "processed": 12, "newly_sold": 0, "newly_in_stock": 0, "errors": 0,
            "url_alerts": [], "error_rows": [], "persistent_err_rows": [],
            "price_surge_held": [], "price_surge_stats": {},
        }
    monkeypatch.setattr(run_cycle, "process_sheet", fake_process_sheet)
    monkeypatch.setattr(run_cycle.Path, "home", staticmethod(lambda: tmp_path))
    (tmp_path / "OneDrive" / "デスクトップ").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(run_cycle, "_notify_toast", lambda *a, **k: None)
    called = {"mail": False}
    monkeypatch.setattr(encrypted_gmail, "load_gmail_config", lambda: ("a", "p", "t"))
    monkeypatch.setattr(email_notifier, "_send_via_gmail",
                        lambda *a, **k: called.update(mail=True))

    grand = run_cycle._phase_monitor(
        sheet="high", limit=None, test_mode=True,
        single_sheet_id="dummy", single_sheet_label="HIGH",
    )

    assert grand["price_surge"] == []
    assert list((tmp_path / "OneDrive" / "デスクトップ").glob("ALERT_*price_surge*.txt")) == []
    assert called["mail"] is False
