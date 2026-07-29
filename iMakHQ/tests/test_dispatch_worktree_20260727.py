"""dispatch_worktree の品質ガードが prompt/判定に効いているかの回帰テスト (2026-07-27).

headless 委譲は「対話できない = 誤解に気づけない」のが唯一の品質リスクなので、
それを潰す3点 (draft止め / 証拠必須 / 迷ったら質問) が prompt から消えたら落とす。
"""
import os
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


def test_dispatch_uses_no_window_on_windows():
    """claude.exe を窓なしで起動すること (pythonw 常駐から起動すると黒窓が出っぱなしになる)。

    窓が出る → ユーザーが閉じる → 子プロセスが 0xC000013A で即死、という事故経路を塞ぐため。
    """
    src = Path(dw.__file__).read_text(encoding="utf-8")
    assert "CREATE_NO_WINDOW" in src
    assert "creationflags=no_window" in src
