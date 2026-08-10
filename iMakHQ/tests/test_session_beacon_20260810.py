"""Regression: 2026-08-10 同一 worktree で Catalog セッションが2本同時に動いた.

実害 (Catalog Claude からの報告):
    12:09〜   対話 Catalog セッションが依頼2件を処理中
    12:35-37  headless Catalog が同じ item を先に完遂 → 3コミット
              (803c74a / 6e16270 / 1eef38b)
→ 二重作業 + 誤コミット (49aa7ad、撤回済) を誘発。今回は双方 commit 済で消失は無し。
   ただし CLAUDE.md「1 worktree 1 branch / 並列消失事故」に抵触 (過去3回は実際に消えている)。

真因: `dispatch_<wt>.lock` は **headless 同士**しか見ていない。**人が開いた対話セッションは
lock を取らない**ので、hub から見ると「誰も居ない」。

対策: 全セッションの SessionStart hook が `session_beacon.stamp` を呼び、
worktree 単位で「誰が居るか」を残す。dispatch は起動前にそれを見る。
"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_TOOLS = _ROOT / "iMakHQ" / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import session_beacon as B                               # noqa: E402


# ------------------------------------------------------------------ 対象の切り分け

def test_main_worktree_is_not_gated():
    """★本元 (C:/dev/iMak) は排他しない。窓口4席が意図的に共有している.

    ここを排他すると Advisor / 出品専任 / ALPHA / BRAVO が互いを締め出す。
    """
    for p in (r"C:\dev\iMak", r"C:\dev\iMak\iMakAdvisor", r"C:/dev/iMak/iMakHQ/tools"):
        assert B.wt_for_path(p) is None, p


def test_linked_worktrees_are_gated():
    assert B.wt_for_path(r"C:\dev\iMak_catalog") == "catalog"
    assert B.wt_for_path(r"C:\dev\iMak_catalog\iMakCatalog") == "catalog"
    assert B.wt_for_path(r"C:/dev/iMak_inventory") == "inventory"
    assert B.wt_for_path(r"C:/dev/iMak_harvest") == "harvest"
    assert B.wt_for_path(r"C:/dev/iMak_revise") == "revise"
    assert B.wt_for_path(r"C:/dev/iMak_dedupe") == "dedupe"


def test_unrelated_path_is_not_gated():
    assert B.wt_for_path(r"C:/tmp") is None
    assert B.wt_for_path("") is None


def test_prefix_collision_is_not_matched():
    """`C:/dev/iMak_catalog_old` を catalog と見なさない (前方一致だけで判定しない)."""
    assert B.wt_for_path(r"C:/dev/iMak_catalog_old") is None
    assert B.wt_for_path(r"C:/dev/iMak_catalogue") is None


# ------------------------------------------------------------------ 生存判定

def test_pid_alive_for_self_and_dead():
    import os
    assert B.pid_alive(os.getpid()) is True
    assert B.pid_alive(999999) is False
    assert B.pid_alive(0) is False
    assert B.pid_alive(-1) is False


def test_owning_session_pid_walks_to_claude(monkeypatch):
    """hook 自身の PID ではなく **claude.exe の祖先** を記録する.

    hook プロセスは即死するので、その PID を書いても beacon が一瞬で無効になる。
    """
    table = {10: (20, "python.exe"), 20: (30, "bash.exe"), 30: (40, "claude.exe"), 40: (0, "explorer.exe")}
    assert B.owning_session_pid(start_pid=10, table=table) == 30


def test_owning_session_pid_falls_back_without_claude():
    """claude.exe が見つからなくても **何かは返す** (0 や例外にしない)."""
    table = {10: (20, "python.exe"), 20: (0, "explorer.exe")}
    assert B.owning_session_pid(start_pid=10, table=table) == 20


def test_process_table_is_real_and_contains_self():
    """★wmic ではなく Win32 API で取る (wmic は Windows 11 の新ビルドで削除済).

    2026-08-10 実測: このマシンに wmic が無く、親を辿れず beacon が機能しなかった。
    """
    import os
    tbl = B.process_table()
    if not tbl:
        return                                           # 非 Windows は対象外
    assert os.getpid() in tbl
    assert isinstance(tbl[os.getpid()][0], int)


# ------------------------------------------------------------------ 読み書き

def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(B, "SESSIONS_DIR", tmp_path)


def test_stamp_and_active_session(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    monkeypatch.setattr(B, "_git_root", lambda cwd: r"C:\dev\iMak_catalog")
    rec = B.stamp()
    assert rec and rec["wt"] == "catalog"
    live = B.active_session("catalog")
    assert live and live["pid"] == rec["pid"]
    assert B.active_session("harvest") is None           # 他 worktree は無関係


def test_stamp_is_noop_on_main_worktree(monkeypatch, tmp_path):
    """本元セッションは beacon を書かない (書くと窓口が互いを止める)."""
    _use_tmp(monkeypatch, tmp_path)
    monkeypatch.setattr(B, "_git_root", lambda cwd: r"C:\dev\iMak")
    assert B.stamp() is None
    assert not list(tmp_path.glob("*.json"))


def test_dead_pid_means_no_session(monkeypatch, tmp_path):
    """★閉じたセッションは自動的に無効。release を書き忘れて永久ロックにならない.

    2026-07-29 に孤児 lock で全 worktree が3時間止まった事故の再来を防ぐ。
    """
    _use_tmp(monkeypatch, tmp_path)
    (tmp_path / "catalog.json").write_text(
        json.dumps({"wt": "catalog", "pid": 999999, "at": "2026-08-10T12:00:00"}), encoding="utf-8")
    assert B.active_session("catalog") is None


def test_broken_beacon_means_no_session(monkeypatch, tmp_path):
    """壊れた beacon で dispatch を止めない (fail-open)."""
    _use_tmp(monkeypatch, tmp_path)
    (tmp_path / "catalog.json").write_text("{ ここは JSON ではない", encoding="utf-8")
    assert B.active_session("catalog") is None
    assert B.active_session("dedupe") is None            # そもそも file 無し


def test_pidless_beacon_expires_by_age(monkeypatch, tmp_path):
    """PID が読めない beacon は時間で失効する (最後の保険)."""
    import time
    _use_tmp(monkeypatch, tmp_path)
    (tmp_path / "catalog.json").write_text(
        json.dumps({"wt": "catalog", "at": "2026-08-10T12:00:00"}), encoding="utf-8")
    assert B.active_session("catalog") is not None                       # 直後は有効
    future = time.time() + B.BEACON_MAX_AGE_SEC + 60
    assert B.active_session("catalog", now=future) is None               # 24h 後は失効


# ------------------------------------------------------------------ dispatch 側の配線

def test_dispatch_skips_when_session_is_live(monkeypatch, tmp_path):
    """★本丸: 対話セッションが居る worktree に headless を立てない."""
    import dispatch_worktree as D
    monkeypatch.setattr(B, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(B, "_git_root", lambda cwd: r"C:\dev\iMak_catalog")
    B.stamp()
    assert D._active_session("catalog") is not None
    assert D._active_session("harvest") is None


def test_dispatch_active_session_is_fail_open(monkeypatch):
    """beacon の読取が例外でも None (= 止めない)。全 worktree 停止の方が害が大きい."""
    import dispatch_worktree as D

    def boom(_wt):
        raise RuntimeError("beacon 壊れた")

    monkeypatch.setattr(B, "active_session", boom)
    assert D._active_session("catalog") is None


# ------------------------------------------------------------------ hook の登録

def test_session_start_hook_is_registered():
    """★hook が settings.json に登録されていること.

    ここが外れると beacon は誰にも書かれず、**黙って並列起動が復活する**
    (いちばん質の悪い壊れ方なのでテストで固定する)。
    """
    import io
    p = Path(r"C:/Users/imax2/.claude/settings.json")
    if not p.exists():
        return                                           # 別マシンでは検証しない
    d = json.load(io.open(p, encoding="utf-8"))
    cmds = [h.get("command", "") for g in d.get("hooks", {}).get("SessionStart", [])
            for h in g.get("hooks", []) if h.get("type") == "command"]
    assert any("session_beacon.py" in c for c in cmds), \
        f"SessionStart に session_beacon が無い: {cmds}"
