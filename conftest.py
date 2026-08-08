"""worktree を跨いでテストを通すための共通 fixture (2026-08-08).

なぜ:
    pre-commit は commit のたびに `pytest tests/ iMakHQ/tests/` を回すが、
    **本元 (master) でしか緑にならない**状態だった。
    実測 2026-08-08: master 2029 passed / 0 failed に対し、dedupe worktree では
    同じコード・同じスコープで 6 failed + 6 errors。
    結果、重複くんは 8/04 から commit できず、8/08 に窓口が `--no-verify` を
    例外許可してようやく通した。**他5worktreeでは gate が最初から機能していない。**

    原因は **git 管理外のローカル状態への依存**。決定的な例:
    `iMakHQ/tests/test_status_now_20260801.py::test_new_desks_have_session_start_hook` は
    `iMakAdvisor/.claude/settings.json` の存在を assert しているが、
    `.gitignore:107` の `**/.claude/` で **git 管理外**なので他 worktree には存在しない。

方針 (fail-OPEN にしない):
    「前提が無いなら skip」を無条件にやると、**本元でも前提が壊れた時に黙って通る**。
    そうならないよう、skip の条件は **「ここは linked worktree だ」という構造的事実**にする
    (ファイルの有無ではない)。本元では従来どおり必ず実行され、落ちれば落ちる。
"""
from __future__ import annotations

import subprocess

import pytest


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              timeout=15).stdout.strip()
    except Exception:                                   # noqa: BLE001
        return ""


def is_linked_worktree() -> bool:
    """linked worktree (git worktree add で切り出した側) なら True。

    本元は `--git-dir` と `--git-common-dir` が同じ場所を指す。
    linked worktree では `--git-dir` が `.git/worktrees/<name>` になるのでズレる。
    判定不能 (git が無い等) は **False = 本元扱い** に倒す
    (skip する側に倒すと gate が黙って消えるため)。
    """
    d, common = _git("rev-parse", "--absolute-git-dir"), _git("rev-parse", "--path-format=absolute", "--git-common-dir")
    if not d or not common:
        return False
    return d.replace("\\", "/").rstrip("/") != common.replace("\\", "/").rstrip("/")


@pytest.fixture(scope="session")
def main_worktree_only():
    """本元 (`C:/dev/iMak`) の**ローカル環境**を検査するテスト専用。

    窓口の机 (`iMakAdvisor/.claude/settings.json` 等) は git 管理外なので、
    他 worktree では存在しない。そこで落ちても直しようがなく、
    **全 worktree の commit を止めてしまう**ので skip する。
    """
    if is_linked_worktree():
        pytest.skip("linked worktree では本元のローカル環境 (git管理外) を検査できない")
