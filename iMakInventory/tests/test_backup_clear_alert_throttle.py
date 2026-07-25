"""補URL消込 ALERT throttle の regression test (2026-07-25).

既知 backlog の HOLD を毎 cycle desktop file+mail で量産するとアラート疲労 (デスクトップに堆積)。
throttle: cycle ログには常に残す (非 silent) が、desktop file+mail は
「新規 / +GROWTH悪化 / HEARTBEAT経過 / mismatch有」時のみ。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def rc(monkeypatch, tmp_path):
    import run_cycle
    monkeypatch.setattr(run_cycle, "BACKUP_CLEAR_ALERT_STATE", tmp_path / "state.json")
    return run_cycle


def test_mismatch_always_emits(rc):
    assert rc._should_emit_backup_clear_alert(0, 3) is True   # mismatch は actionable
    assert rc._should_emit_backup_clear_alert(999, 1) is True


def test_first_hold_emits_and_records(rc):
    assert not rc.BACKUP_CLEAR_ALERT_STATE.exists()
    assert rc._should_emit_backup_clear_alert(161, 0) is True   # 初回
    assert rc.BACKUP_CLEAR_ALERT_STATE.exists()                 # state 記録された
    st = json.loads(rc.BACKUP_CLEAR_ALERT_STATE.read_text(encoding="utf-8"))
    assert st["held_max"] == 161


def test_same_within_heartbeat_suppressed(rc):
    rc.BACKUP_CLEAR_ALERT_STATE.write_text(json.dumps(
        {"ts": datetime.now().isoformat(timespec="seconds"), "held_max": 161}), encoding="utf-8")
    # 同水準 (164 <= 161+20) かつ 24h 未満 → 告知しない
    assert rc._should_emit_backup_clear_alert(164, 0) is False
    # 減少もしても抑制 (既知 backlog 継続)
    assert rc._should_emit_backup_clear_alert(64, 0) is False


def test_growth_reemits(rc):
    rc.BACKUP_CLEAR_ALERT_STATE.write_text(json.dumps(
        {"ts": datetime.now().isoformat(timespec="seconds"), "held_max": 100}), encoding="utf-8")
    # +GROWTH(20) 超の悪化 → 再告知
    assert rc._should_emit_backup_clear_alert(121, 0) is True


def test_heartbeat_reemits(rc):
    old = (datetime.now() - timedelta(hours=25)).isoformat(timespec="seconds")
    rc.BACKUP_CLEAR_ALERT_STATE.write_text(json.dumps(
        {"ts": old, "held_max": 161}), encoding="utf-8")
    # 同水準でも 24h 経過 → 墓場化防止で再告知
    assert rc._should_emit_backup_clear_alert(160, 0) is True


def test_zero_hold_no_emit(rc):
    assert rc._should_emit_backup_clear_alert(0, 0) is False
