# -*- coding: utf-8 -*-
"""開けっ放しの窓が配達を4日間 止めていた件 (2026-09-05)。

catalog の VS Code セッションが 2026-09-01 20:03 から開いたままで、
`dispatch_worktree` は「対話セッションが稼働中」として headless を立てず、
9/1 19:55 を最後に **4日間 1件も配達されなかった** (依頼6件が滞留)。
残務№15 (抽出くんで35時間) と同型。

原因は beacon の `at` が **セッションを開いた時刻**で、その後 更新されないこと。
PID が生きている限り「作業中」と見えるので、「開いたまま放置」と区別できなかった。
しかも skip は **無警告**で、板には「要返球6件」としか出ていなかった。

対策:
  1. 活動の有無を会話ログ (.jsonl) の mtime で見る → 放置は「居ない」扱い
  2. 止まっている事実を板に出す (いつから止まっているかも)
  3. 同じ skip を15秒おきに書き続けない (log が117万行になり読めなかった)
"""
import json
import os
import sys
import time

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import dispatch_watch as W  # noqa: E402
import session_beacon as B  # noqa: E402
import worktree_board as BD  # noqa: E402


def _beacon(monkeypatch, tmp_path, pid):
    monkeypatch.setattr(B, "SESSIONS_DIR", tmp_path)
    (tmp_path / "catalog.json").write_text(
        json.dumps({"wt": "catalog", "pid": pid, "at": "2026-09-01T20:03:09"}),
        encoding="utf-8")


# ------------------------------------------------- 1. 放置は「居ない」扱い

def test_idle_session_is_not_treated_as_working(monkeypatch, tmp_path):
    """窓が開いていても最終活動が古ければ配達を止めない (9/5 の実害そのもの)."""
    _beacon(monkeypatch, tmp_path, os.getpid())          # PID は生きている
    monkeypatch.setattr(B, "last_activity",
                        lambda wt: time.time() - B.IDLE_MAX_SEC - 60)
    assert B.active_session("catalog") is None


def test_working_session_still_blocks(monkeypatch, tmp_path):
    """今 作業中の窓は今までどおり止める (二重作業を防ぐ元の目的は壊さない)."""
    _beacon(monkeypatch, tmp_path, os.getpid())
    monkeypatch.setattr(B, "last_activity", lambda wt: time.time() - 60)
    live = B.active_session("catalog")
    assert live is not None and live["idle_sec"] < B.IDLE_MAX_SEC


def test_unknown_activity_keeps_old_behaviour(monkeypatch, tmp_path):
    """会話ログが読めない時は従来どおり「居る」。判定不能で挙動を変えない."""
    _beacon(monkeypatch, tmp_path, os.getpid())
    monkeypatch.setattr(B, "last_activity", lambda wt: None)
    assert B.active_session("catalog") is not None


def test_dead_pid_still_wins(monkeypatch, tmp_path):
    """閉じた窓は活動時刻を見るまでもなく「居ない」."""
    _beacon(monkeypatch, tmp_path, 999999)
    monkeypatch.setattr(B, "last_activity", lambda wt: time.time())
    assert B.active_session("catalog") is None


def test_last_activity_reads_subfolder_sessions(monkeypatch, tmp_path):
    """catalog は `iMakCatalog/` で開かれる。ルートの dir だけ見ると常に古く見える."""
    monkeypatch.setattr(B, "CLAUDE_PROJECTS", tmp_path)
    sub = tmp_path / "c--dev-iMak-catalog-iMakCatalog"
    sub.mkdir()
    (sub / "abc.jsonl").write_text("{}", encoding="utf-8")
    (tmp_path / "c--dev-iMak-harvest").mkdir()
    assert B.last_activity("catalog") is not None
    assert B.last_activity("harvest") is None            # 他 worktree を拾わない


# ------------------------------------------------- 2. 止まっていることを出す

def test_board_warns_when_delivery_is_blocked(monkeypatch, capsys, tmp_path):
    req = tmp_path / "catalog" / "requests"
    req.mkdir(parents=True)
    old = req / "2026-09-02_x.md"
    old.write_text("# x", encoding="utf-8")
    os.utime(old, (time.time() - 72 * 3600,) * 2)
    monkeypatch.setattr(BD, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(BD, "WORKTREES", [("catalog", "カタログ")])
    monkeypatch.setattr(BD, "pending_for", lambda wt, days=None: ([old], [], []))
    monkeypatch.setattr(BD, "_blocking_session",
                        lambda wt: {"pid": 15088, "idle_sec": 30})
    BD.main()
    out = capsys.readouterr().out
    assert "配達が止まっています" in out, out
    assert "15088" in out


def test_board_warning_is_fail_open(monkeypatch):
    """beacon が読めない時に「止まっている」と騒がない."""
    import session_beacon
    monkeypatch.setattr(session_beacon, "active_session",
                        lambda wt: (_ for _ in ()).throw(RuntimeError("boom")))
    assert BD._blocking_session("catalog") is None


# ------------------------------------------------- 3. log を埋め尽くさない

def test_repeated_skip_is_logged_once(monkeypatch):
    said = []
    monkeypatch.setattr(W, "log", said.append)
    monkeypatch.setattr(W, "_last_said", {})
    for _ in range(50):
        W.log_throttled("catalog:draft:done", "[catalog] 完了: skip-session-live")
    assert said == ["[catalog] 完了: skip-session-live"], said


def test_changed_message_is_logged_immediately(monkeypatch):
    """内容が変わったら即座に出す (新しい情報を握り潰さない)."""
    said = []
    monkeypatch.setattr(W, "log", said.append)
    monkeypatch.setattr(W, "_last_said", {})
    W.log_throttled("k", "A")
    W.log_throttled("k", "A")
    W.log_throttled("k", "B")
    assert said == ["A", "B"], said
