"""pre-commit は **その worktree の担当分だけ** テストを走らせる (2026-08-12).

実害: 従来は全 worktree で monorepo 全体 (`tests/ iMakHQ/tests/`) を走らせていたため、
linked worktree では自分が触っていないプロジェクトの stale なテストで必ず赤くなり、
gate が最初から機能していなかった。重複くんは 8/04〜8/08 commit 不能、
リバイスくんは daily_report 1行の commit すら通せていない (561 commit 遅れ)。

正本は `tools/hooks/pre-commit` (`.git/hooks/` は git 管理外)。
"""
import io
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HOOK = os.path.join(ROOT, "tools", "hooks", "pre-commit")


def _src():
    return io.open(HOOK, encoding="utf-8").read()


def test_hook_source_exists():
    assert os.path.exists(HOOK), "tools/hooks/pre-commit (正本) が無い"


def test_each_worktree_has_its_own_suite():
    """5つの linked worktree すべてに担当 suite が割り当たっていること."""
    src = _src()
    for wt, suite in (
        ("iMak_catalog", "iMakCatalog/tests"),
        ("iMak_dedupe", "iMakDedupe/tests"),
        ("iMak_harvest", "iMakHarvest/tests"),
        ("iMak_revise", "iMakRevise/tests"),
        ("iMak_inventory", "iMakInventory/tests"),
    ):
        assert wt in src, f"{wt} の分岐が無い"
        assert suite in src, f"{wt} に {suite} が割り当たっていない"


def test_main_worktree_still_runs_whole_monorepo():
    """本元 (HQ/Advisor) は従来どおり全体を走らせる — ここを緩めない."""
    src = _src()
    assert "tests/ iMakHQ/tests/" in src


def test_linked_worktree_does_not_run_monorepo_suite():
    """linked worktree に monorepo 全体を割り当て直していないこと (退行防止)."""
    src = _src()
    for line in src.splitlines():
        s = line.strip()
        if not s.startswith("*\"/dev/iMak_"):
            continue
        if "SUITES=" not in s:
            continue
        assert "iMakHQ/tests" not in s, f"linked worktree に monorepo suite が復活している: {s}"


def test_missing_suite_is_loud_not_silent():
    """suite が見つからない時に黙って通さない (fail-OPEN を隠さない)."""
    src = _src()
    assert "テスト gate 無しで commit します" in src


def test_inventory_offline_gate_kept():
    """在庫巡回の offline ゲート (2026-06-21) を消していないこと."""
    src = _src()
    assert "offline gate" in src
    assert "-m offline" in src
