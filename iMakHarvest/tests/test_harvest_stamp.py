"""harvest_stamp の回帰テスト.

依頼書 2026-07-29_battery_stop_disabled_and_stamp_GO_response.md §3 「warn が出ることを
回帰テストで固定」 + §2 「dry_run 時はスタンプを更新しない (最重要判断)」に対応。

silent 死の検知が目的の module なので、warn が出ないと機能しない。テスト化しないと
「検知器自体が silent に壊れたら意味がない」(response.md §3)。
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.offline

from harvest_stamp import check_previous_stamp, write_stamp


JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 7, 30, 21, 0, 0, tzinfo=JST)


def test_check_missing_stamp_emits_warning(tmp_path):
    """スタンプ不在 → warn stderr に出力 (silent 起動を検知)."""
    stamp = tmp_path / "not_yet.json"
    buf = io.StringIO()
    check_previous_stamp(stamp, 25, label="test", now=NOW, stream=buf)
    out = buf.getvalue()
    assert "warning" in out
    assert "不在" in out
    assert "test" in out


def test_check_stale_stamp_emits_warning_with_age(tmp_path):
    """スタンプが stale_hours より古い → warn + 実際の h 数を含む."""
    stamp = tmp_path / "old.json"
    prev = NOW - timedelta(hours=48)  # 48h 前 = stale (>25h)
    stamp.write_text(json.dumps({"ok_at": prev.isoformat()}), encoding="utf-8")
    buf = io.StringIO()
    check_previous_stamp(stamp, 25, label="test", now=NOW, stream=buf)
    out = buf.getvalue()
    assert "warning" in out
    assert "48" in out  # age 数値が出る
    assert ">25" in out


def test_check_fresh_stamp_no_warning(tmp_path):
    """stale_hours 以内 → warn 出さない (= 正常時は静か)."""
    stamp = tmp_path / "fresh.json"
    prev = NOW - timedelta(hours=1)  # 1h 前 = fresh
    stamp.write_text(json.dumps({"ok_at": prev.isoformat()}), encoding="utf-8")
    buf = io.StringIO()
    check_previous_stamp(stamp, 25, label="test", now=NOW, stream=buf)
    assert buf.getvalue() == ""


def test_check_corrupt_stamp_emits_warning(tmp_path):
    """JSON 壊れ / 必須キー欠 → warn (= 壊れた stamp を fresh と誤判定しない)."""
    stamp = tmp_path / "bad.json"
    stamp.write_text("not valid json {{", encoding="utf-8")
    buf = io.StringIO()
    check_previous_stamp(stamp, 25, label="test", now=NOW, stream=buf)
    out = buf.getvalue()
    assert "warning" in out
    assert "読取失敗" in out


def test_check_uses_alt_timestamp_key(tmp_path):
    """timestamp_key='generated_at' で snapshot 側の既存キーを流用できる."""
    stamp = tmp_path / "snap.json"
    prev = NOW - timedelta(hours=20)  # >10h → stale
    stamp.write_text(json.dumps({"generated_at": prev.isoformat()}), encoding="utf-8")
    buf = io.StringIO()
    check_previous_stamp(stamp, 10, timestamp_key="generated_at",
                         label="snap", now=NOW, stream=buf)
    assert "warning" in buf.getvalue()


def test_write_stamp_creates_file_with_ok_at_and_payload(tmp_path):
    stamp = tmp_path / "sub" / "s.json"
    body = write_stamp(stamp, {"input": 100, "appended": 3, "dry_run": False},
                       now=NOW)
    assert stamp.exists()
    data = json.loads(stamp.read_text(encoding="utf-8"))
    assert data["ok_at"] == NOW.isoformat()
    assert data["input"] == 100
    assert data["appended"] == 3
    assert data["dry_run"] is False
    assert body == data  # 返り値 = 書込内容


def test_write_stamp_then_check_fresh_no_warning(tmp_path):
    """書込 → 直後の check で warn 出ない (round-trip 正当性)."""
    stamp = tmp_path / "rt.json"
    write_stamp(stamp, {"input": 1}, now=NOW)
    buf = io.StringIO()
    check_previous_stamp(stamp, 25, label="rt",
                         now=NOW + timedelta(hours=1), stream=buf)
    assert buf.getvalue() == ""
