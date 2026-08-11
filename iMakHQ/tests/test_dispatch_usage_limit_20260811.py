"""Regression: 2026-08-10 usage 上限に当たったあとも dispatch が叩き続けた.

実測 (`iMakHQ/review_logs/`):

    2026-08-08  総 20本  limit即死   0  実走 20
    2026-08-09  総 13本  limit即死   0  実走 13
    2026-08-10  総199本  limit即死 176  実走 23   ← ★

17:45 に上限到達 → 20:49 まで **3時間**、watcher が 15秒間隔で catalog を叩き続け、
**176本が「You've hit your limit · resets 8:50pm」だけの 53バイトログ**になった。
トークンは食わない (要求が弾かれている) が、claude.exe を 732回起こしており PC が無駄に回る。

対策: 上限を検知したらリセット時刻まで **全 worktree の dispatch を止める**。
時刻が読めなければ 60分。解除は自動 (人の操作を要らなくする)。
"""
import datetime
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_TOOLS = _ROOT / "iMakHQ" / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import dispatch_worktree as D                            # noqa: E402

NOW = datetime.datetime(2026, 8, 10, 17, 45)
MSG = "You've hit your limit · resets 8:50pm (Asia/Tokyo)"


def test_parses_reset_time_same_day():
    assert D._parse_reset_at(MSG, NOW) == datetime.datetime(2026, 8, 10, 20, 50)


def test_reset_already_passed_means_next_day():
    """8:50am は 17:45 時点で過ぎている → 翌朝まで止める (過去を返して即再開しない)."""
    assert D._parse_reset_at("resets 8:50am", NOW) == datetime.datetime(2026, 8, 11, 8, 50)


def test_unparseable_reset_returns_none():
    assert D._parse_reset_at("なんか失敗しました", NOW) is None
    assert D._parse_reset_at("", NOW) is None


def test_note_usage_limit_detects_and_records(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "USAGE_LIMIT_FLAG", tmp_path / "ul.txt")
    assert D._note_usage_limit(MSG, NOW) is True
    assert D.usage_limited_until(NOW) == datetime.datetime(2026, 8, 10, 20, 50)


def test_normal_output_is_not_treated_as_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "USAGE_LIMIT_FLAG", tmp_path / "ul.txt")
    assert D._note_usage_limit("SUMMARY: draft 1件", NOW) is False
    assert D.usage_limited_until(NOW) is None


def test_fallback_window_when_time_unreadable(tmp_path, monkeypatch):
    """時刻が読めなくても止める。ただし**永久停止にはしない**."""
    monkeypatch.setattr(D, "USAGE_LIMIT_FLAG", tmp_path / "ul.txt")
    assert D._note_usage_limit("You've hit your limit", NOW) is True
    until = D.usage_limited_until(NOW)
    assert until == NOW + datetime.timedelta(minutes=D.USAGE_LIMIT_FALLBACK_MIN)


def test_auto_release_after_reset(tmp_path, monkeypatch):
    """★リセット後は自動で解除。人が flag を消す運用にしない
    (2026-07-29 に孤児 lock で全 worktree が3時間止まった前例)."""
    monkeypatch.setattr(D, "USAGE_LIMIT_FLAG", tmp_path / "ul.txt")
    D._note_usage_limit(MSG, NOW)
    assert D.usage_limited_until(datetime.datetime(2026, 8, 10, 20, 51)) is None
    assert not (tmp_path / "ul.txt").exists()            # flag も片付く


def test_broken_flag_is_fail_open(tmp_path, monkeypatch):
    """flag が壊れていたら**動かす**。止める側に倒すと誰も気づかず全停止する."""
    p = tmp_path / "ul.txt"
    p.write_text("これは日時ではない", encoding="utf-8")
    monkeypatch.setattr(D, "USAGE_LIMIT_FLAG", p)
    assert D.usage_limited_until(NOW) is None


def test_missing_flag_is_not_limited(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "USAGE_LIMIT_FLAG", tmp_path / "nope.txt")
    assert D.usage_limited_until(NOW) is None
