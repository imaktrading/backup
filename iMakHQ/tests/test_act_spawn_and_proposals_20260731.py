"""Act (監査くん→headless) の起動フラグと提案の行き先 (2026-07-31).

1. **ちらつき**: 中継の先を DETACHED_PROCESS で起こすと、コンソールアプリ(claude.exe)に
   Windows が新しいコンソールを割り当てて CMD が一瞬出る (ユーザー報告)。
   CREATE_NO_WINDOW ならウィンドウ自体が作られない。
   tree-kill 耐性は「中継が即終了して孤児化する」ことで担保しており DETACHED に依存しない
   (実験で両 flags とも中継終了後に子が生存することを確認済)。

2. **提案の行き先**: コード修正提案が ng_act_*.md に書かれるだけで誰も読まず消えていた。
   実測 (7/30): 提案「SDBH SCG が catalog 全体未登録」は妥当だったが放置され、翌日 Advisor が
   同じ問題を再発見して依頼書化 = 二度手間。requests に置けば worktree ボードに載る。
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import csv_auditor as ca  # noqa: E402


def test_spawn_uses_no_window_not_detached():
    src = inspect.getsource(ca._detached_spawn)
    assert "0x08000000" in src, "CREATE_NO_WINDOW になっていない (CMD がちらつく)"
    assert "creationflags=0x00000008" not in src, "DETACHED_PROCESS に戻っている"


def test_spawn_keeps_new_process_group():
    """新プロセスグループは維持 (Ctrl+C 等のシグナルを親から切り離す)。"""
    assert "0x00000200" in inspect.getsource(ca._detached_spawn)


def test_relay_itself_is_windowless():
    """中継 python 自身も window を出さない (これは従来から)。"""
    assert "CREATE_NO_WINDOW" in inspect.getsource(ca._detached_spawn)


def _prompt():
    return ca._build_act_prompt("tcg", "x.csv", "y.log", "z.json", {})


def test_prompt_routes_code_proposals_to_requests():
    p = _prompt()
    assert "hq/requests" in p, "提案の行き先 (requests) が prompt に無い"
    assert "act_code_proposals" in p


def test_prompt_avoids_duplicate_proposal_files():
    """同名があれば skip = 毎日走っても同じ提案が積み上がらない。"""
    p = _prompt()
    assert "skip" in p and "重複投入回避" in p


def test_prompt_requires_evidence_in_proposals():
    """提案には実機で確認した根拠を書かせる (推測の提案は動けない)。"""
    p = _prompt()
    for must in ("現象", "実機で確認した根拠", "影響件数", "修正案", "触るファイル"):
        assert must in p, must


def test_prompt_still_forbids_code_change_and_commit():
    """行き先を作っても、headless 自身が直すのは禁止のまま。"""
    p = _prompt()
    assert "コード修正と git commit はするな" in p
