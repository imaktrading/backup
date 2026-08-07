"""事務員 (clerk) の役割境界を固定する (2026-07-30).

事務員は窓口(Advisor)の**事務作業**を肩代わりするために置いた。
判断まで肩代わりさせると、**誰も検証していない状態**になる (headless の下書きを
headless が承認する形) ので、prompt レベルで禁止を固定する。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import clerk_patrol as cp  # noqa: E402


def _p():
    return cp.build_prompt("2026-07-30_0700")


def test_clerk_must_not_judge_or_promote():
    """判断・昇格・コード修正・commit を禁じていること。"""
    p = _p()
    for ng in ("判断しません", "`_response.md` を書かない", "commit しない",
               "コードを直さない", "依頼書を置かない"):
        assert ng in p, f"事務員の禁止事項が prompt から消えた: {ng}"


def test_clerk_covers_the_four_routine_jobs():
    """窓口から剥がした4つの事務作業が全部入っていること。"""
    p = _p()
    assert "worktree_board.py" in p        # 滞留集計
    assert "done_check.py" in p            # 完了報告の証拠チェック
    assert "直近24時間" in p               # cron/ログ巡回
    assert "督促候補" in p                 # 3日以上動いていない依頼


def test_clerk_checks_for_missing_logs():
    """『ログが無い』を必ず見ること。

    2026-07-30 に、夜間 cron が7/28以降ずっと空振りしていたのを
    **ログが1本も無い**ことで発見した (タスクは exit 0 = 成功に見えていた)。
    silent failure の唯一の兆候なので、巡回項目から落とさない。
    """
    p = _p()
    assert "ログが無い" in p and "silent failure" in p


def test_clerk_must_state_scope_when_reporting_no_issue():
    """「異常なし」を書く時は確認範囲を明記させる (空欄で流させない)。"""
    p = _p()
    assert "確認した範囲を明記" in p


def test_clerk_gets_access_to_hq_tools_and_logs():
    """事務員は cwd の外 (HQ の tools と logs) を読む必要がある → --add-dir を渡すこと。

    渡さないと worktree_board.py / done_check.py を実行できず、ログ巡回もできない。
    **何も出せないまま静かに終わる** = 事務員を置いた意味が消える。
    """
    src = open(cp.__file__, encoding="utf-8").read()
    assert '"--add-dir", str(dw.DATA_ROOT)' in src
    assert r'"--add-dir", r"C:\dev\iMak\iMakHQ"' in src


def test_report_path_is_single_and_shared():
    """出力は共有領域の1ファイルだけ (窓口はこれだけ読む)。"""
    p = _p()
    assert str(cp.REPORT_DIR).replace("\\", "\\") in p or "clerk" in p
    assert "他には何も書かない" in p
