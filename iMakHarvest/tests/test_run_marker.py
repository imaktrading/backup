"""tests/test_run_marker - 手動長時間収集の「途中で止まった」印.

HQ/ADV 依頼 `2026-09-24_resume_after_crash` (②)。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from run_marker import check_stale, mark_finished, mark_started

pytestmark = pytest.mark.offline


def test_mark_started_then_check_stale_returns_info(tmp_path: Path):
    marker = tmp_path / "x_running.flag"
    dump = tmp_path / "dump.json"
    mark_started(marker, dump)
    info = check_stale(marker)
    assert info is not None
    assert info["dump_path"] == str(dump)
    assert "started_at" in info


def test_mark_finished_removes_marker(tmp_path: Path):
    marker = tmp_path / "x_running.flag"
    mark_started(marker, tmp_path / "dump.json")
    mark_finished(marker)
    assert check_stale(marker) is None


def test_mark_finished_without_marker_is_noop(tmp_path: Path):
    marker = tmp_path / "missing.flag"
    mark_finished(marker)  # 例外にならない
    assert check_stale(marker) is None


def test_check_stale_no_marker_is_none(tmp_path: Path):
    assert check_stale(tmp_path / "nope.flag") is None
