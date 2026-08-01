"""dispatch watcher が死んだまま放置されない (2026-08-02)。

なぜ要るか (実害):
    8/1 20:48〜8/2 05:49 の **9時間**、全 worktree の dispatch がゼロだった。誰も気づかなかった。
    さらに 8/2 も 06:01 に止まり、ユーザーが「カタログは自動で動くんだよね?」と聞いて初めて発覚。
    2日で3回、人が偶然気づいて手で再起動している = fail-OPEN。

    原因は3つとも「落ちたこと」ではなく **落ちたまま復旧しないこと**:
      ① 多重起動防止を Task Scheduler の Running 状態に任せていた
         → プロセスが無いのに Running に張り付く**幽霊**になると 30分ごとの再起動が全部弾かれる
      ② 死んでもログに何も残らないので死因を追えない
      ③ dispatch が exit1 (usage limit 等) で失敗しても「処理済」に入れており、二度と拾われない
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dispatch_watch as W  # noqa: E402
import dispatch_worktree as dw  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _hb(tmp_path, monkeypatch):
    monkeypatch.setattr(dw, "REVIEW_DIR", tmp_path)
    monkeypatch.setattr(W, "HEARTBEAT", tmp_path / "dispatch_watch.heartbeat")
    monkeypatch.setattr(W, "LOG", tmp_path / "dispatch_watch.log")
    return tmp_path / "dispatch_watch.heartbeat"


# ------------------------------------------------------------------ ① 生存判定
def test_no_heartbeat_means_not_alive(tmp_path, monkeypatch):
    _hb(tmp_path, monkeypatch)
    assert W.heartbeat_age() is None
    assert W.is_alive() is False, "heartbeat が無いのを『生きている』と誤判定してはいけない"


def test_fresh_heartbeat_means_alive(tmp_path, monkeypatch):
    p = _hb(tmp_path, monkeypatch)
    W.beat()
    assert p.exists()
    assert W.is_alive() is True


def test_stale_heartbeat_means_dead_so_a_new_instance_can_take_over(tmp_path, monkeypatch):
    """★幽霊 Running の解除。**古い heartbeat は「死んでいる」と判定する**.

    ここが False のままだと、8/1 のように 30分ごとの再起動トリガが全部無駄撃ちになる。
    """
    p = _hb(tmp_path, monkeypatch)
    W.beat()
    old = time.time() - (W.ALIVE_SEC + 10)
    os.utime(p, (old, old))
    assert W.is_alive() is False
    assert W.heartbeat_age() > W.ALIVE_SEC


def test_liveness_is_not_judged_by_task_scheduler(tmp_path, monkeypatch):
    """判定の根拠が Task Scheduler でないこと (幽霊を掴む経路を持ち込まない)."""
    import io
    src = io.open(os.path.join(ROOT, "iMakHQ", "tools", "dispatch_watch.py"),
                  encoding="utf-8").read()
    body = src.split("def is_alive")[1].split("def beat")[0]
    assert "schtasks" not in body and "Get-ScheduledTask" not in body


# ------------------------------------------------------------------ ③ 失敗の再試行
def _run(monkeypatch, status, done):
    import threading
    monkeypatch.setattr(dw, "acquire_lock", lambda wt=None: True)
    monkeypatch.setattr(dw, "release_lock", lambda wt=None: None)
    monkeypatch.setattr(dw, "_dispatch",
                        lambda wt, dry_run=False, mode="draft": {"status": status, "summary": ""})
    W._run_one("catalog", "x.md", done, ["x.md"], set(), threading.Lock())


def test_failed_dispatch_is_retried(tmp_path, monkeypatch):
    """★exit1 を『処理済』にしない。8/1 の `_BC_response.md` は9時間放置された."""
    _hb(tmp_path, monkeypatch)
    done = {"catalog": set()}
    _run(monkeypatch, "exit1", done)
    assert done["catalog"] == set(), "失敗を処理済にすると二度と拾われない"


def test_successful_dispatch_is_not_retried(tmp_path, monkeypatch):
    _hb(tmp_path, monkeypatch)
    done = {"catalog": set()}
    _run(monkeypatch, "ok", done)
    assert done["catalog"] == {"x.md"}, "成功は処理済にする (同じ依頼を二度走らせない)"


# ------------------------------------------------------------------ ② 死亡の可視化
def test_exit_is_always_logged():
    """落ちた事実を必ず1行残す (8/1・8/2 とも無言で消えて死因を追えなかった)."""
    import io
    src = io.open(os.path.join(ROOT, "iMakHQ", "tools", "dispatch_watch.py"),
                  encoding="utf-8").read()
    tail = src.split('if __name__ ==')[1]
    assert "watch 終了" in tail and "BaseException" in tail


def test_board_warns_when_the_watcher_is_down():
    """現在地に死活が出ること。**出ないと誰も気づけない**のが 9時間停止の真因."""
    import io
    src = io.open(os.path.join(ROOT, "iMakHQ", "tools", "worktree_board.py"),
                  encoding="utf-8").read()
    assert "heartbeat_age" in src
    assert "依頼が誰にも配られていない" in src
    assert "schtasks" in src, "復旧コマンドを併記していないと、気づいても直せない"
