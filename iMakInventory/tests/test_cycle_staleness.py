"""巡回停止 (staleness) の非-silent 検知 + lock 解放待ちの自己回復 (2026-07-27).

背景: HIGH の所要が 60〜64 分に伸び、LOW 起動 (HIGH 開始 +60 分) と衝突して
skipped_lock_held が 3 連続 → LOW が 25h 止まっていたのを実観測。当時の実装は toast のみで
desktop/mail に出ず「監視が止まっている」ことに誰も気づけなかった (= silent)。
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


def _write_cycle(dirpath: Path, name: str, label: str, status: str, ts: datetime):
    p = dirpath / name
    p.write_text(json.dumps({
        "ts_start": ts.isoformat(timespec="seconds"),
        "ts_end": ts.isoformat(timespec="seconds"),
        "sheet_label": label,
        "status": status,
    }, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture()
def rc_env(tmp_path, monkeypatch):
    """decision_log / alert state を tmp に差し替え、alert を捕捉する。"""
    import run_cycle as rc

    monkeypatch.setattr(rc, "DECISION_LOG_DIR", tmp_path)
    monkeypatch.setattr(rc, "CYCLE_STALE_ALERT_STATE", tmp_path / "stale_state.json")
    emitted = []
    monkeypatch.setattr(rc, "_emit_nonsilent_alert",
                        lambda tag, subject, msg, test_mode=False: emitted.append((tag, subject, msg)))
    return rc, tmp_path, emitted


# ---------------------------------------------------------------- last success
def test_last_success_picks_latest_and_ignores_skips(rc_env):
    rc, d, _ = rc_env
    now = datetime.now()
    _write_cycle(d, "cycle_1.jsonl", "LOW", "success", now - timedelta(hours=30))
    _write_cycle(d, "cycle_2.jsonl", "LOW", "success", now - timedelta(hours=9))
    # 直近は skip (完走ではない) → 完走時刻として採用してはいけない
    _write_cycle(d, "cycle_3.jsonl", "LOW", "skipped_lock_held", now - timedelta(minutes=5))
    got = rc._last_cycle_success("LOW")
    assert got is not None
    assert abs((got - (now - timedelta(hours=9))).total_seconds()) < 5


def test_last_success_ignores_other_label(rc_env):
    rc, d, _ = rc_env
    now = datetime.now()
    _write_cycle(d, "cycle_1.jsonl", "SHEET", "success", now - timedelta(minutes=10))
    assert rc._last_cycle_success("LOW") is None


def test_success_variants_count(rc_env):
    """success_no_upload / success_no_changes も完走扱い"""
    rc, d, _ = rc_env
    now = datetime.now()
    _write_cycle(d, "cycle_1.jsonl", "SHEET", "success_no_upload", now - timedelta(minutes=30))
    assert rc._last_cycle_success("SHEET") is not None


# ---------------------------------------------------------------- staleness
def test_stale_low_fires_alert(rc_env):
    """LOW が 25h 完走なし (想定 8h×2.2=17.6h 超) → 3ch 告知"""
    rc, d, emitted = rc_env
    now = datetime.now()
    _write_cycle(d, "cycle_h.jsonl", "SHEET", "success", now - timedelta(minutes=5))
    _write_cycle(d, "cycle_l.jsonl", "LOW", "success", now - timedelta(hours=25))
    stale = rc._check_cycle_staleness(test_mode=True)
    assert [s["label"] for s in stale] == ["LOW"]
    assert len(emitted) == 1
    assert "巡回が停止" in emitted[0][1]
    assert "LOW" in emitted[0][2]


def test_fresh_cycles_no_alert(rc_env):
    rc, d, emitted = rc_env
    now = datetime.now()
    _write_cycle(d, "cycle_h.jsonl", "SHEET", "success", now - timedelta(hours=3))
    _write_cycle(d, "cycle_l.jsonl", "LOW", "success", now - timedelta(hours=7))
    assert rc._check_cycle_staleness(test_mode=True) == []
    assert emitted == []


def test_no_history_is_not_alerted(rc_env):
    """完走記録ゼロ (初回導入 / 新 label) は判定不能 → 誤報しない"""
    rc, _d, emitted = rc_env
    assert rc._check_cycle_staleness(test_mode=True) == []
    assert emitted == []


def test_alert_throttled_but_still_reported(rc_env):
    """6h 以内の再検知は mail/desktop を出さない (疲労防止) が、戻り値では必ず報告する"""
    rc, d, emitted = rc_env
    now = datetime.now()
    _write_cycle(d, "cycle_l.jsonl", "LOW", "success", now - timedelta(hours=25))
    first = rc._check_cycle_staleness(test_mode=True)
    second = rc._check_cycle_staleness(test_mode=True)
    assert first and second                # 「墓場化」させない = 毎回返す
    assert len(emitted) == 1               # 告知は 1 回だけ


def test_throttle_expired_reemits(rc_env):
    rc, d, emitted = rc_env
    now = datetime.now()
    _write_cycle(d, "cycle_l.jsonl", "LOW", "success", now - timedelta(hours=25))
    rc._check_cycle_staleness(test_mode=True)
    # 前回告知を throttle 期限より古くする
    (d / "stale_state.json").write_text(
        json.dumps({"LOW": (now - timedelta(hours=rc.CYCLE_STALE_ALERT_THROTTLE_HOURS + 1))
                    .isoformat(timespec="seconds")}), encoding="utf-8")
    rc._check_cycle_staleness(test_mode=True)
    assert len(emitted) == 2


def test_broken_state_file_falls_back_to_alerting(rc_env):
    """throttle state 破損時は silent 化させず告知側に倒す (fail-closed)"""
    rc, d, emitted = rc_env
    now = datetime.now()
    _write_cycle(d, "cycle_l.jsonl", "LOW", "success", now - timedelta(hours=25))
    (d / "stale_state.json").write_text("{ broken", encoding="utf-8")
    assert rc._check_cycle_staleness(test_mode=True)
    assert len(emitted) == 1


# ---------------------------------------------------------------- lock wait
def test_acquire_lock_waits_until_released(tmp_path, monkeypatch):
    """保持中でも解放を待って自己回復する (即 skip しない)"""
    import run_cycle as rc

    lock = tmp_path / ".cycle.lock"
    monkeypatch.setattr(rc, "LOCK_FILE", lock)
    lock.write_text("pid=999999 host=other ts=now\n", encoding="utf-8")

    calls = {"n": 0}

    def fake_sleep(_sec):
        calls["n"] += 1
        lock.unlink(missing_ok=True)      # 1 回目の待機中に前 cycle が終わった想定

    monkeypatch.setattr(rc.time, "sleep", fake_sleep)
    monkeypatch.setattr(rc, "LOCK_WAIT_POLL_SEC", 0)
    assert rc._acquire_lock(test_mode=True, wait_minutes=5) is True
    assert calls["n"] == 1
    assert lock.exists()                  # 自分の lock を書いた


def test_acquire_lock_gives_up_after_deadline(tmp_path, monkeypatch):
    """待っても解放されなければ従来通り skip (二重起動しない = 安全側)"""
    import run_cycle as rc

    lock = tmp_path / ".cycle.lock"
    monkeypatch.setattr(rc, "LOCK_FILE", lock)
    lock.write_text("pid=999999 host=other ts=now\n", encoding="utf-8")
    monkeypatch.setattr(rc, "LOCK_WAIT_POLL_SEC", 0)
    monkeypatch.setattr(rc.time, "sleep", lambda _s: None)
    assert rc._acquire_lock(test_mode=True, wait_minutes=0) is False
