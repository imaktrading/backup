# -*- coding: utf-8 -*-
"""CSV監査くん → headless Claude Act合図 回帰テスト (2026-06-26)。

監査完了後に headless Claude(claude -p)をBG起動して NG対応を回す機能。
- 安全ガード: dry-run / CSV_AUDITOR_NO_SIGNAL / pytest 実行中 は spawn しない(誤起動防止)。
- 指示文(prompt): 優先順位①CSV→②依頼 + 「コード修正/commit/入稿はするな」制約を含む。
(pre-commit が collect する iMakHQ/tests/ に配置)
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "tools")))

import csv_auditor as ca  # noqa: E402


def test_signal_skipped_under_pytest_never_spawns():
    """pytest 実行中は必ず skip(本物の claude を起動しない)。"""
    assert ca._signal_claude_act("tcg", "x.csv", None, dry_run=False) == "skipped"


def test_signal_skipped_on_dry_run():
    assert ca._signal_claude_act("tcg", "x.csv", None, dry_run=True) == "skipped"


def test_act_prompt_priority_csv_up_before_catalog():
    """優先順位: ①CSV手直し → ②CSV UPシグナル → ③カタログ依頼。UPが依頼より先。"""
    p = ca._build_act_prompt("tcg", "C:/x/tcg_upload.csv", None)
    assert "①CSVを手直し" in p
    assert "②CSV UPシグナル" in p
    assert "③カタログ依頼" in p
    # UPシグナルが ③カタログ より前に出てくる(=優先される)
    assert p.index("②CSV UPシグナル") < p.index("③カタログ依頼")
    # UPシグナルは notify ヘルパをBG実行する指示
    assert "notify_csv_ready.py" in p and "バックグラウンド" in p


def test_act_prompt_has_constraints():
    p = ca._build_act_prompt("tcg", "C:/x/tcg_upload.csv", None)
    # コード修正/commit/入稿はさせない(修正が修正を生む防止)。入稿はheadlessがしない。
    assert "コード修正" in p and "commit" in p and "するな" in p
    assert "入稿(eBayアップ)自体はするな" in p
    assert "tcg_upload.csv" in p
    assert "ng_items_need_proactive_action" in p


def test_act_prompt_points_to_act_report_output():
    p = ca._build_act_prompt("tcg", "x.csv", None)
    assert "ng_act_" in p   # Act レポート出力先を指示


def test_notify_csv_ready_message():
    """UP通知本文に件数とCSV名と『UP』が入る(純関数)。"""
    sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "tools")))
    import notify_csv_ready as ncr
    m = ncr.build_message(7, "C:/x/tcg_upload_20260626.csv")
    assert "7件" in m and "tcg_upload_20260626.csv" in m and "UP" in m
