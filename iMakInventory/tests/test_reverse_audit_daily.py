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


def _mk_items(ids, sheet="HIGH", supplier="mercari"):
    return [{"sheet": sheet, "row_index": i, "item_id": str(iid), "ebay_qty": 1,
             "supplier": supplier, "url": "", "title": f"t{iid}"} for i, iid in enumerate(ids)]


def _stub_audits(monkeypatch, reverse_res, ebay_down_res, ack=None):
    monkeypatch.setattr(RA, "_fetch_ebay_qty_map", lambda: {"x": 1})
    monkeypatch.setattr(RA, "run_reverse_audit",
                        lambda write_log=True, qty_map=None: reverse_res)
    monkeypatch.setattr(RA, "run_ebay_down_sheet_active_audit",
                        lambda write_sheet=True, write_log=True, qty_map=None: ebay_down_res)
    # ack allowlist は明示制御 (default 空 = 全件 alert)。 実ファイル読込に依存させない。
    monkeypatch.setattr(RA, "_load_acknowledged", lambda: {k: {"item_id": k} for k in (ack or [])})


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
                  "items": _mk_items(["a", "b", "c"]), "log_path": "r.jsonl"},
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
                 {"mismatch_count": 0, "by_sheet": {}, "by_supplier": {}, "items": [],
                  "log_path": "r.jsonl"},
                 {"orphan_count": 5, "by_sheet": {"HIGH": 5}, "by_state": {"qty0": 5},
                  "log_path": "e.jsonl"})
    res = RA._run_daily_audit()
    assert res["status"] == "OK"
    assert _last_heartbeat(hb)["ebay_down_orphan"] == 5
    assert not al.exists()
    assert calls["toast"] == 0 and calls["email"] == 0


def test_acknowledged_only_suppresses_alert_but_logs(monkeypatch, tmp_path):
    # 乖離が全て承認済み既知偽陽性 → critical alert (toast/email/alert_log) は出さないが、
    # heartbeat には ack 内訳を必ず記録する (= silent drop 禁止)。
    hb, al = _patch_logs(monkeypatch, tmp_path)
    calls = _patch_channels(monkeypatch)
    _stub_audits(monkeypatch,
                 {"mismatch_count": 1, "by_sheet": {"HIGH": 1}, "by_supplier": {"other": 1},
                  "items": _mk_items(["358645217419"], supplier="other"), "log_path": "r.jsonl"},
                 {"orphan_count": 0, "by_sheet": {}, "by_state": {}, "log_path": "e.jsonl"},
                 ack=["358645217419"])
    res = RA._run_daily_audit()
    assert res["status"] == "OK_ACK_ONLY"
    assert res["unack_count"] == 0 and res["ack_count"] == 1
    hb_entry = _last_heartbeat(hb)
    # 乖離自体 (mismatch=1) と ack 内訳は heartbeat に残る = 不可視な握り潰しにしない
    assert hb_entry["status"] == "OK_ACK_ONLY"
    assert hb_entry["reverse_mismatch"] == 1
    assert hb_entry["reverse_unack"] == 0 and hb_entry["reverse_ack"] == 1
    assert hb_entry["acknowledged_ids"] == ["358645217419"]
    # critical alert は一切出ない
    assert not al.exists()
    assert calls["toast"] == 0 and calls["email"] == 0


def test_crash_alert_is_not_silent(monkeypatch, tmp_path):
    # daily_audit が最外周で想定外クラッシュしても heartbeat(AUDIT_CRASH)+alert を必ず残す
    # (2026-06-30 10:00 の silent crash 再発防止)。
    hb, al = _patch_logs(monkeypatch, tmp_path)
    calls = _patch_channels(monkeypatch)
    RA._emit_crash_alert("RuntimeError: boom", "Traceback ... boom")
    hb_entry = _last_heartbeat(hb)
    assert hb_entry["status"] == "AUDIT_CRASH"
    assert "boom" in hb_entry["error"]
    assert al.exists() and "クラッシュ" in al.read_text(encoding="utf-8")
    assert calls["toast"] == 1 and calls["email"] == 1


def test_mixed_ack_and_unack_alerts_only_unack(monkeypatch, tmp_path):
    # 承認済み 1 + 未承認 2 → 未承認 2 件だけで alert 発火 (承認済みは件数に数えない)。
    hb, al = _patch_logs(monkeypatch, tmp_path)
    calls = _patch_channels(monkeypatch)
    _stub_audits(monkeypatch,
                 {"mismatch_count": 3, "by_sheet": {"HIGH": 3}, "by_supplier": {"other": 1, "mercari": 2},
                  "items": _mk_items(["ACKED", "new1", "new2"]), "log_path": "r.jsonl"},
                 {"orphan_count": 0, "by_sheet": {}, "by_state": {}, "log_path": "e.jsonl"},
                 ack=["ACKED"])
    res = RA._run_daily_audit()
    assert res["status"] == "MISMATCH"
    assert res["unack_count"] == 2 and res["ack_count"] == 1
    hb_entry = _last_heartbeat(hb)
    assert hb_entry["reverse_unack"] == 2 and hb_entry["reverse_ack"] == 1
    # alert は未承認の 2 件として発火 (3 ではない)
    assert al.exists()
    txt = al.read_text(encoding="utf-8")
    assert "乖離 2 件" in txt and "ACKED" in txt  # 抑制した ack も本文に明記
    assert calls["toast"] == 1 and calls["email"] == 1
