# -*- coding: utf-8 -*-
"""GitHub に載らない本元のデータも毎朝の zip に入れる (2026-09-30)。

背景: psa_research_cache.json 等の判定の控えが GitHub にも zip にも無く、PC を替えると消えていた。
守るもの: 控えは入る / ログ・.bak・ブラウザのプロファイルは入らない。
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import data_backup as B  # noqa: E402


def test_pick_repo_keeps_data_and_skips_logs(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("*.json\n*.log\n*.bak_x\nchrome_profile_a/\n")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "psa_research_cache.json").write_text("{}")
    (tmp_path / "tools" / "run.log").write_text("x")
    (tmp_path / "tools" / "c.json.bak_x").write_text("x")
    (tmp_path / "chrome_profile_a").mkdir()
    (tmp_path / "chrome_profile_a" / "p.json").write_text("{}")
    got = {rel for _, rel, _ in B.pick_repo(str(tmp_path))}
    assert got == {"_repo/tools/psa_research_cache.json"}


def test_pick_worktrees_names(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.csv").write_text("1")
    got = {rel for _, rel, _ in B.pick_worktrees({"revise/csv_output": str(tmp_path)})}
    assert got == {"_worktrees/revise/csv_output/a/x.csv"}


def test_claude_settings_in_but_login_out():
    """Claude の許可・hook の設定は戻す。ログイン情報は入れない。"""
    assert "settings.json" in B.EXTRA_GLOBS and "settings.local.json" in B.EXTRA_GLOBS
    assert not any("credentials" in g for g in B.EXTRA_GLOBS)


def test_revise_csv_output_is_listed():
    """リバイスくんの回答 (2026-09-30): 値付けの履歴 csv_output を zip に入れる。"""
    assert B.WORKTREE_DIRS["revise/csv_output"].endswith(r"iMakRevise\csv_output")
