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


# ===================== 決定論NG digest(PDCA担保) =====================

def _find(cat="tcg", item="X", field="catalog_add", ft="catalog_gap", seen=2, status="pending"):
    return {"category": cat, "item_id": item, "target_field": field,
            "finding_type": ft, "seen_count": seen, "status": status}


def test_recurring_findings_pending_and_seen_threshold():
    """pending かつ seen_count>=min_seen のみ再発扱い。done や単発は除外。"""
    rows = [
        _find(item="SWSH-014", seen=13),                 # 再発(13回)
        _find(item="BOA-013", seen=8),                   # 再発(8回)
        _find(item="ONESHOT", seen=1),                   # 単発 → 除外
        _find(item="FIXED", seen=9, status="done"),      # 解決済 → 除外
    ]
    out = ca.recurring_findings(rows, min_seen=2)
    items = [r["item_id"] for r in out]
    assert items == ["SWSH-014", "BOA-013"]              # seen 降順・pending のみ


def test_recurring_findings_sorted_by_seen():
    rows = [_find(item="A", seen=3), _find(item="B", seen=10), _find(item="C", seen=2)]
    assert [r["item_id"] for r in ca.recurring_findings(rows)] == ["B", "A", "C"]


def test_ng_digest_counts():
    d = ca._build_ng_digest("tcg", [("sku1", "msg1")], ["error: 2件"], [_find(seen=2)])
    assert d["counts"] == {"program": 1, "log": 1, "recurring_missing": 1}


def test_act_prompt_with_digest_mandates_disposition():
    """digest を渡すと『各項目に必ず処分・無言で飛ばすな』と再発のコード提案指示が入る。"""
    d = ca._build_ng_digest("tcg", [("s", "m")], [], [_find(item="SWSH-014", seen=13)])
    p = ca._build_act_prompt("tcg", "x.csv", None, "review_logs/ng_digest_x.json", d)
    assert "ng_digest_x.json" in p
    assert "必ず処分" in p and "無言で飛ばすな" in p
    assert "recurring_missing" in p and "コード修正提案を必ず" in p


def test_act_prompt_without_digest_has_no_digest_line():
    p = ca._build_act_prompt("tcg", "x.csv", None)
    assert "決定論NG digest" not in p   # digest 無しなら該当行は出さない
