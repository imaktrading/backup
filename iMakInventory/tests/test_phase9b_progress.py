"""Phase 9b: ライブ進捗 writer + GUI サマリバー の unit test.

実 GUI / 実 cycle は走らせず、純粋な helper logic を offline 化する。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================================
# progress writer
# ============================================================================
def test_progress_writer_creates_file_on_init(tmp_path, monkeypatch):
    """ProgressWriter() インスタンス化で initial file 作成 (force=True)."""
    import progress as p
    monkeypatch.setattr(p, "DECISION_LOG_DIR", tmp_path)
    pw = p.ProgressWriter(cycle_ts="20260430_180000")
    assert pw.path.exists()
    data = json.loads(pw.path.read_text(encoding="utf-8"))
    assert data["cycle_ts"] == "20260430_180000"
    assert data["phase"] == "init"
    assert data["processed"] == 0


def test_progress_writer_throttle(tmp_path, monkeypatch):
    """update() は 5秒間隔の throttle を持つ (force=False)."""
    import progress as p
    monkeypatch.setattr(p, "DECISION_LOG_DIR", tmp_path)
    monkeypatch.setattr(p, "PROGRESS_THROTTLE_SEC", 100)  # 大きく設定して連続 update を抑制
    pw = p.ProgressWriter(cycle_ts="20260430_180000")
    initial_mtime = pw.path.stat().st_mtime
    time.sleep(0.05)
    # throttle 内なので write されない
    pw.update(processed=10, force=False)
    assert pw.path.stat().st_mtime == initial_mtime
    # force=True なら即書込
    pw.update(processed=20, force=True)
    data = json.loads(pw.path.read_text(encoding="utf-8"))
    assert data["processed"] == 20


def test_progress_writer_finalize_deletes_file(tmp_path, monkeypatch):
    """finalize() で progress file が削除される (= GUI 待機中表示に戻る合図)."""
    import progress as p
    monkeypatch.setattr(p, "DECISION_LOG_DIR", tmp_path)
    pw = p.ProgressWriter(cycle_ts="20260430_180000")
    assert pw.path.exists()
    pw.finalize()
    assert not pw.path.exists()


def test_read_latest_progress_returns_newest(tmp_path, monkeypatch):
    """複数 progress ファイルがあるとき cycle_ts 降順で最新を返す (lock あり時)."""
    import progress as p
    monkeypatch.setattr(p, "DECISION_LOG_DIR", tmp_path)
    # 古い + 新しい
    (tmp_path / "progress_20260101_120000.jsonl").write_text(
        json.dumps({"cycle_ts": "20260101_120000", "phase": "old"}),
        encoding="utf-8",
    )
    (tmp_path / "progress_20260430_180000.jsonl").write_text(
        json.dumps({"cycle_ts": "20260430_180000", "phase": "monitor", "processed": 100}),
        encoding="utf-8",
    )
    # lock があれば 「巡回中」扱いで progress 返す
    (tmp_path / ".cycle.lock").write_text("pid=1234", encoding="utf-8")
    latest = p.read_latest_progress()
    assert latest is not None
    assert latest["cycle_ts"] == "20260430_180000"
    assert latest["phase"] == "monitor"


def test_read_latest_progress_returns_none_if_empty(tmp_path, monkeypatch):
    import progress as p
    monkeypatch.setattr(p, "DECISION_LOG_DIR", tmp_path)
    assert p.read_latest_progress() is None


def test_cleanup_stale_progress(tmp_path, monkeypatch):
    """30 分以上前の progress ファイルは削除される (壊れた cycle 残骸の清掃)."""
    import os
    import progress as p
    monkeypatch.setattr(p, "DECISION_LOG_DIR", tmp_path)
    old = tmp_path / "progress_20260101_120000.jsonl"
    new = tmp_path / "progress_20260430_180000.jsonl"
    old.write_text("{}", encoding="utf-8")
    new.write_text("{}", encoding="utf-8")
    # old を 1h 前に偽装 (30 分閾値を超える)
    one_hour_ago = time.time() - 3600
    os.utime(old, (one_hour_ago, one_hour_ago))
    # default 30 分閾値で削除
    deleted = p.cleanup_stale_progress()
    assert deleted == 1
    assert not old.exists()
    assert new.exists()


def test_read_latest_progress_returns_none_if_no_lock(tmp_path, monkeypatch):
    """progress file あっても .cycle.lock が無ければ None (stale 扱い)."""
    import progress as p
    monkeypatch.setattr(p, "DECISION_LOG_DIR", tmp_path)
    (tmp_path / "progress_20260430_140000.jsonl").write_text(
        json.dumps({"cycle_ts": "20260430_140000", "phase": "monitor"}),
        encoding="utf-8",
    )
    # lock file なし
    assert p.read_latest_progress() is None


def test_read_latest_progress_returns_data_if_lock_exists(tmp_path, monkeypatch):
    """lock file が存在すれば progress data を返す (= 巡回中)."""
    import progress as p
    monkeypatch.setattr(p, "DECISION_LOG_DIR", tmp_path)
    (tmp_path / "progress_20260430_140000.jsonl").write_text(
        json.dumps({"cycle_ts": "20260430_140000", "phase": "monitor", "processed": 50}),
        encoding="utf-8",
    )
    # lock file あり
    (tmp_path / ".cycle.lock").write_text("pid=1234", encoding="utf-8")
    data = p.read_latest_progress()
    assert data is not None
    assert data["phase"] == "monitor"
    assert data["processed"] == 50


# ============================================================================
# integration: run_cycle / monitor_listings に組み込まれている
# ============================================================================
def test_run_cycle_imports_progress_writer():
    """run_cycle.py が ProgressWriter を import している."""
    src = (ROOT / "run_cycle.py").read_text(encoding="utf-8")
    assert "from progress import" in src
    assert "ProgressWriter" in src
    assert "progress_writer.update(" in src
    assert "progress_writer.finalize()" in src


def test_monitor_listings_accepts_progress_callback():
    """process_sheet が progress_callback を受け取る."""
    from monitor_listings import process_sheet
    import inspect
    sig = inspect.signature(process_sheet)
    assert "progress_callback" in sig.parameters


def test_control_panel_has_summary_bar_methods():
    """control_panel に Phase 9b summary bar 関連メソッドが存在する."""
    src = (ROOT / "control_panel.py").read_text(encoding="utf-8")
    assert "_summary_poll" in src
    assert "_summary_refresh" in src
    assert "_render_errors" in src
    assert "_render_cron_info" in src
    assert "ERRORS_WARN_THRESHOLD" in src
    # progress module を import している
    assert "from progress import" in src or "import progress" in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
