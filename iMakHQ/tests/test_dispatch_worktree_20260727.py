"""dispatch_worktree の品質ガードが prompt/判定に効いているかの回帰テスト (2026-07-27).

headless 委譲は「対話できない = 誤解に気づけない」のが唯一の品質リスクなので、
それを潰す3点 (draft止め / 証拠必須 / 迷ったら質問) が prompt から消えたら落とす。
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dispatch_worktree as dw  # noqa: E402
import worktree_board as wb  # noqa: E402


def _prompt():
    return dw._build_prompt("catalog", [Path(r"C:\dev\iMak_data\catalog\requests\x.md")])


def test_prompt_forces_draft_not_response():
    p = _prompt()
    assert "_draft.md" in p
    assert "`_response.md` は書くな" in p


def test_prompt_requires_evidence_and_failclosed_question():
    p = _prompt()
    assert "証拠添付が必須" in p
    assert "_question.md" in p
    assert "確信が持てないものは書くな" in p


def test_prompt_forbids_code_change_and_commit():
    p = _prompt()
    for ng in ("コード修正をするな", "git commit / push をするな", "破壊的"):
        assert ng in p


def test_prompt_lists_target_files():
    p = _prompt()
    assert "x.md" in p and "処理対象" in p


def test_draft_files_are_not_redispatched(tmp_path, monkeypatch):
    """draft/question は「窓口レビュー待ち」であって依頼ではない。
    ここを間違えると headless が自分の下書きを依頼として無限に処理し続ける。"""
    d = tmp_path / "catalog" / "requests"
    d.mkdir(parents=True)
    (d / "2026-07-27_a.md").write_text("req", encoding="utf-8")
    (d / "2026-07-27_a_draft.md").write_text("draft", encoding="utf-8")
    (d / "2026-07-27_b_question.md").write_text("q", encoding="utf-8")
    monkeypatch.setattr(wb, "DATA_ROOT", tmp_path)

    mine, theirs, drafts = wb.pending_for("catalog")
    names = {p.name for p in mine}
    assert "2026-07-27_a_draft.md" not in names
    assert "2026-07-27_b_question.md" not in names
    # 元依頼は draft が後続として存在するので closed 扱い (二重処理させない)
    assert "2026-07-27_a.md" not in names
    assert {p.name for p in drafts} == {"2026-07-27_a_draft.md", "2026-07-27_b_question.md"}
    assert theirs == []


def test_targets_cover_all_worker_worktrees():
    """CLAUDE.md の worktree 表 + HQ と一致していること (増減時に気づけるように)。

    2026-07-29: `hq` を追加。HQ は専用 worktree を持たず Advisor と C:/dev/iMak を共有するため
    当初は対象外にしていたが、hq/requests の依頼が誰にも読まれず 43h 放置された。
    止まり続けるより同一 worktree の衝突リスクを取る、というユーザー判断。
    """
    assert set(dw.TARGETS) == {"catalog", "dedupe", "inventory", "harvest", "revise", "hq"}
    # HQ だけは他と違い専用 worktree が無い = Advisor と同居。ここが変わったら気づけるように固定。
    assert dw.TARGETS["hq"][0] == r"C:\dev\iMak"


def _dead_pid() -> int:
    """確実に死んでいる PID (Popen が handle を握っているので recycle されない)."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _use_tmp_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(dw, "REVIEW_DIR", tmp_path)
    monkeypatch.setattr(dw, "LOCK_PATH", tmp_path / "dispatch.lock")


def test_pid_alive_distinguishes_self_from_dead():
    assert dw._pid_alive(os.getpid()) is True
    assert dw._pid_alive(_dead_pid()) is False
    assert dw._pid_alive(0) is False


def test_orphan_lock_is_taken_over_without_waiting_3h(tmp_path, monkeypatch):
    """2026-07-29 の実害: watcher 再起動で死んだ前世代の lock が残り、全 worktree が3時間停止した。

    lock が「今さっき」書かれていても、所有者が死んでいれば奪えること。
    """
    _use_tmp_lock(tmp_path, monkeypatch)
    dw.LOCK_PATH.write_text(f"{_dead_pid()} 2026-07-29T17:03:48\n", encoding="utf-8")

    assert dw.acquire_lock() is True                      # 時間切れを待たずに奪う
    assert dw._lock_owner_pid() == os.getpid()            # 自分の PID で取り直している
    dw.release_lock()
    assert not dw.LOCK_PATH.exists()


def test_live_owner_lock_is_respected(tmp_path, monkeypatch):
    """生きている dispatch の lock は奪わない (奪うと同じ worktree に headless が2本立つ)."""
    _use_tmp_lock(tmp_path, monkeypatch)
    dw.LOCK_PATH.write_text(f"{os.getpid()} now\n", encoding="utf-8")
    assert dw.acquire_lock() is False
    assert dw._lock_owner_pid() == os.getpid()            # 破棄されていない


def test_unreadable_pid_is_treated_as_alive(tmp_path, monkeypatch):
    """PID が読めない = 判定不能。安全側 (生存扱い) に倒し、3h の stale 判定に任せる."""
    _use_tmp_lock(tmp_path, monkeypatch)
    dw.LOCK_PATH.write_text("こわれている\n", encoding="utf-8")
    assert dw._lock_owner_pid() is None
    assert dw.acquire_lock() is False


def test_locks_are_per_worktree(tmp_path, monkeypatch):
    """担当ごとに lock を分ける = 別 worktree は **並行**して走れる (2026-07-30)。

    従来は全体で1本の lock だったため、依頼を出した担当が前の担当の終了を待たされていた
    (実測: 出品専任が監視くんの後ろで数分待ち)。worktree は別々で、headless は共有DB/
    スプシへ書けないので、同時に走っても衝突しない。防ぐべきは「同じ worktree に2本」だけ。
    """
    _use_tmp_lock(tmp_path, monkeypatch)
    assert dw.acquire_lock("catalog") is True
    assert dw.acquire_lock("inventory") is True, "別 worktree が待たされている (直列のまま)"
    assert dw.acquire_lock("catalog") is False, "同じ worktree に2本立ってしまう"
    dw.release_lock("catalog")
    assert dw.acquire_lock("catalog") is True     # 解放後は取り直せる
    dw.release_lock("catalog")
    dw.release_lock("inventory")


def test_watcher_runs_worktrees_in_parallel():
    """watcher が並行実行になっていること (直列に戻ったら落とす)。"""
    src = (Path(__file__).parent.parent / "tools" / "dispatch_watch.py").read_text(encoding="utf-8")
    assert "MAX_PARALLEL" in src
    assert "threading.Thread(" in src
    assert "dw.acquire_lock(wt)" in src, "worktree 単位の lock を使っていない"


def test_implement_queue_requires_explicit_token(tmp_path, monkeypatch):
    """実装キューは **明示トークン [IMPLEMENT-GO]** がある response だけ拾う (2026-07-30)。

    最初「実装 GO」等の自然文で拾ったら 7/22・7/26 の **完了済み回答まで**キューに入った。
    誤って再実装させると破壊になりうるので、窓口が意図的に書いた時だけ動かす。
    """
    d = tmp_path / "catalog" / "requests"
    d.mkdir(parents=True)
    (d / "a_response.md").write_text("実装 GO と自然文で書いただけ", encoding="utf-8")
    (d / "b_response.md").write_text("本文\n\n[IMPLEMENT-GO]\n", encoding="utf-8")
    (d / "c_response.md").write_text("[IMPLEMENT-GO]", encoding="utf-8")
    (d / "c_response_done.md").write_text("実装済み", encoding="utf-8")   # 完了印あり
    (d / "d.md").write_text("[IMPLEMENT-GO]", encoding="utf-8")           # response でない
    monkeypatch.setattr(wb, "DATA_ROOT", tmp_path)

    got = {p.name for p in wb.implement_for("catalog")}
    assert got == {"b_response.md"}, f"実装キューの条件が緩い/厳しすぎる: {got}"


def test_implement_mode_allows_commit_but_never_push():
    """実装モードは commit を許し、push/checkout/reset は禁止のまま。

    未 commit で放置する方が危険 (branch 操作で消える。2026-04/05 に同型事故3回)。
    一方 push/reset は履歴と他セッションを壊すので禁止を維持する。
    """
    assert "Bash(git commit:*)" in dw.DENY_TOOLS               # 下書きモードは commit も禁止
    assert "Bash(git commit:*)" not in dw.IMPLEMENT_DENY_TOOLS  # 実装モードは commit 可
    for ng in ("Bash(git push:*)", "Bash(git reset:*)", "Bash(git checkout:*)"):
        assert ng in dw.IMPLEMENT_DENY_TOOLS


def test_hq_is_excluded_from_auto_implement():
    """HQ は Advisor と同じ worktree を共有するので自動実装しない (同時編集で壊れる)。"""
    assert "hq" in dw.NO_AUTO_IMPLEMENT
    assert dw._dispatch("hq", dry_run=True, mode="implement")["status"] == "skip-no-auto-impl"


def test_implement_prompt_requires_tests_and_evidence():
    p = dw._build_implement_prompt("catalog", [Path("x_response.md")])
    for must in ("テストを書く", "1つでも赤いなら commit しない", "_done.md",
                 "git push / checkout / switch / reset は禁止", "_question.md"):
        assert must in p


def test_liveness_check_uses_win32_api_not_os_kill():
    """Windows の os.kill(pid, 0) は TerminateProcess = 生存確認のつもりで相手を殺す。

    nt 分岐が OpenProcess 問い合わせであること (os.kill に書き換えられたら落とす)。
    """
    src = Path(dw.__file__).read_text(encoding="utf-8")
    nt_branch = src.split('if os.name != "nt":')[1].split("def _lock_owner_pid")[0]
    assert "OpenProcess" in nt_branch and "GetExitCodeProcess" in nt_branch
    assert "TerminateProcess" not in nt_branch


def test_dispatch_uses_no_window_on_windows():
    """claude.exe を窓なしで起動すること (pythonw 常駐から起動すると黒窓が出っぱなしになる)。

    窓が出る → ユーザーが閉じる → 子プロセスが 0xC000013A で即死、という事故経路を塞ぐため。
    """
    src = Path(dw.__file__).read_text(encoding="utf-8")
    assert "CREATE_NO_WINDOW" in src
    assert "creationflags=no_window" in src
