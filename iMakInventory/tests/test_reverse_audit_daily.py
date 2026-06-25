"""reverse_audit daily cron エントリ (_run_daily_audit) regression (2026-06-25).

bug: 06-16 のスケジュール再編で run_cycle の `--sheet both` cycle が消滅 →
Phase 5 reverse_audit (取下げ漏れ reconciliation) が自動実行されなくなっていた。
安全原則「定期 reconciliation で乖離ゼロを継続証跡」が本体側で途切れ = fail-OPEN 検出網の穴。

修正: 専用 daily cron で呼ぶ `_run_daily_audit()` を新設。 reverse + ebay_down を共有 qty_map で
両方走らせ、 (1) 乖離 0 でも heartbeat 証跡を必ず残す、 (2) reverse mismatch>0 (取下げ漏れ疑い) /
mismatch==-1 (audit 不能) は alert ログ + toast + email で **非-silent** に通知する。
ebay_down orphan は review シート書出済で自動無害なので alert しない (heartbeat のみ)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import reverse_audit as RA  # noqa: E402


def _patch_logs(monkeypatch, tmp_path):
    hb = tmp_path / "heartbeat.log"
    al = tmp_path / "alert.log"
    monkeypatch.setattr(RA, "HEARTBEAT_LOG", hb)
    monkeypatch.setattr(RA, "ALERT_LOG", al)
    monkeypatch.setattr(RA, "DECISION_LOG_DIR", tmp_path)
    return hb, al


def _patch_channels(monkeypatch):
    calls = {"toast": 0, "email": 0}
    monkeypatch.setattr(RA, "_toast", lambda t, b: calls.__setitem__("toast", calls["toast"] + 1))
    monkeypatch.setattr(RA, "_email_alert", lambda s, b: calls.__setitem__("email", calls["email"] + 1) or True)
    return calls


def _stub_audits(monkeypatch, reverse_res, ebay_down_res):
    monkeypatch.setattr(RA, "_fetch_ebay_qty_map", lambda: {"x": 1})
    monkeypatch.setattr(RA, "run_reverse_audit",
                        lambda write_log=True, qty_map=None: reverse_res)
    monkeypatch.setattr(RA, "run_ebay_down_sheet_active_audit",
                        lambda write_sheet=True, write_log=True, qty_map=None: ebay_down_res)


def _last_heartbeat(hb):
    lines = [l for l in hb.read_text(encoding="utf-8").splitlines() if l.strip()]
    return json.loads(lines[-1])


def test_clean_run_records_heartbeat_no_alert(monkeypatch, tmp_path):
    hb, al = _patch_logs(monkeypatch, tmp_path)
    calls = _patch_channels(monkeypatch)
    _stub_audits(monkeypatch,
                 {"mismatch_count": 0, "by_sheet": {}, "by_supplier": {}, "log_path": "r.jsonl"},
                 {"orphan_count": 0, "by_sheet": {}, "by_state": {}, "log_path": "e.jsonl"})
    res = RA._run_daily_audit()
    assert res["status"] == "OK"
    # 乖離 0 でも継続証跡 heartbeat は必ず残る
    hb_entry = _last_heartbeat(hb)
    assert hb_entry["status"] == "OK" and hb_entry["reverse_mismatch"] == 0
    # alert は一切発火しない
    assert not al.exists()
    assert calls["toast"] == 0 and calls["email"] == 0


def test_mismatch_fires_all_alert_channels(monkeypatch, tmp_path):
    hb, al = _patch_logs(monkeypatch, tmp_path)
    calls = _patch_channels(monkeypatch)
    _stub_audits(monkeypatch,
                 {"mismatch_count": 3, "by_sheet": {"HIGH": 3}, "by_supplier": {"mercari": 3},
                  "log_path": "r.jsonl"},
                 {"orphan_count": 0, "by_sheet": {}, "by_state": {}, "log_path": "e.jsonl"})
    res = RA._run_daily_audit()
    assert res["status"] == "MISMATCH"
    assert _last_heartbeat(hb)["status"] == "MISMATCH"
    # 取下げ漏れ疑い → 永続 alert ログ + toast + email の 3 チャネル全部
    assert al.exists() and "乖離 3 件" in al.read_text(encoding="utf-8")
    assert calls["toast"] == 1 and calls["email"] == 1


def test_audit_error_is_not_silent(monkeypatch, tmp_path):
    # mismatch == -1 (eBay 取得失敗等で fail-closed 中断) = 検出網が動かなかった → alert 必須
    hb, al = _patch_logs(monkeypatch, tmp_path)
    calls = _patch_channels(monkeypatch)
    _stub_audits(monkeypatch,
                 {"mismatch_count": -1, "error": "ebay_active_map_empty",
                  "by_sheet": {}, "by_supplier": {}},
                 {"orphan_count": -1, "error": "ebay_active_map_empty"})
    res = RA._run_daily_audit()
    assert res["status"] == "AUDIT_ERROR"
    assert _last_heartbeat(hb)["status"] == "AUDIT_ERROR"
    assert al.exists() and "実行不能" in al.read_text(encoding="utf-8")
    assert calls["toast"] == 1 and calls["email"] == 1


def test_ebay_down_orphan_alone_does_not_alert(monkeypatch, tmp_path):
    # ebay_down orphan>0 だが reverse は健全 → review シート書出済で自動無害 → heartbeat のみ
    hb, al = _patch_logs(monkeypatch, tmp_path)
    calls = _patch_channels(monkeypatch)
    _stub_audits(monkeypatch,
                 {"mismatch_count": 0, "by_sheet": {}, "by_supplier": {}, "log_path": "r.jsonl"},
                 {"orphan_count": 5, "by_sheet": {"HIGH": 5}, "by_state": {"qty0": 5},
                  "log_path": "e.jsonl"})
    res = RA._run_daily_audit()
    assert res["status"] == "OK"
    assert _last_heartbeat(hb)["ebay_down_orphan"] == 5
    assert not al.exists()
    assert calls["toast"] == 0 and calls["email"] == 0
