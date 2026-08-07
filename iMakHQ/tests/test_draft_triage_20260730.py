# -*- coding: utf-8 -*-
"""draft_triage.py — 下書きの「窓口必須 / 定型」仕分け規則のテスト.

守りたい性質:
  1. **既定は窓口必須** (fail-closed)。定型に落ちるのは規則が当たった時だけ
  2. 不可逆・事業判断・選択肢提示は必ず必須
  3. 同日の親依頼を「後発版」と誤認しない (2026-07-30 初版の bug)
  4. `worktree` の語だけでは必須にしない (規約引用で全件必須になった 2026-07-30 初版の bug)
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import draft_triage as dt  # noqa: E402


def _mk(tmp_path, name, body, age_days=0.0):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(p, (t, t))
    return p


def _classify(tmp_path, target):
    return dt.classify(target, list(tmp_path.glob("*.md")))


def test_default_is_must_review(tmp_path):
    """どの規則にも当たらない下書きは 必須 (安全側)."""
    p = _mk(tmp_path, "2026-07-30_something_new_draft.md", "普通の調査結果です。")
    kind, why, _ = _classify(tmp_path, p)
    assert kind == "必須"
    assert "安全側" in why


def test_irreversible_is_must(tmp_path):
    p = _mk(tmp_path, "2026-07-30_cleanup_draft.md", "rm -rf で消します。推奨: GO")
    kind, why, _ = _classify(tmp_path, p)
    assert kind == "必須", "破壊的コマンドは GO 推奨でも必須"
    assert "破壊的" in why


def test_business_decision_is_must(tmp_path):
    p = _mk(tmp_path, "2026-07-30_neo_era_draft.md", "Neo era に新規参入するか。推奨: GO")
    kind, _why, _ = _classify(tmp_path, p)
    assert kind == "必須"


def test_option_presentation_is_must(tmp_path):
    p = _mk(tmp_path, "2026-07-30_helper_draft.md", "A案 と B案 のどちらを採るか。")
    kind, _why, _ = _classify(tmp_path, p)
    assert kind == "必須"


def test_price_change_is_must(tmp_path):
    p = _mk(tmp_path, "2026-07-30_rate_draft.md", "送料を値上げします。推奨: GO")
    kind, _why, _ = _classify(tmp_path, p)
    assert kind == "必須", "外向きの価格変更は必須"


def test_recommended_go_is_routine(tmp_path):
    p = _mk(tmp_path, "2026-07-30_tiny_fix_draft.md",
            "import 1語追加のみ。test 4件 pass 済。推奨: GO")
    kind, _why, default = _classify(tmp_path, p)
    assert kind == "定型"
    assert default == "GO"


def test_routine_auto_generated_is_routine(tmp_path):
    p = _mk(tmp_path, "2026-07-30_auto_catalog_add_pokemon_tcg_draft.md", "毎日出る定期物。")
    kind, _why, _ = _classify(tmp_path, p)
    assert kind == "定型"


def test_stale_is_routine(tmp_path):
    p = _mk(tmp_path, "2026-06-01_old_design_draft.md", "5週間前の設計。", age_days=45)
    kind, why, default = _classify(tmp_path, p)
    assert kind == "定型"
    assert "動いていない" in why
    assert "凍結" in default


def test_same_day_parent_is_not_superseded(tmp_path):
    """同日の親依頼書を『後発版』と誤認しない (初版の bug).

    定期 auto 生成の topic を使うと routine 規則が先に当たって検証にならないため、
    **定期物ではない topic** で見る。
    """
    draft = _mk(tmp_path, "2026-07-30_some_investigation_draft.md", "調査結果。")
    time.sleep(0.01)
    _mk(tmp_path, "2026-07-30_some_investigation.md", "元依頼。")  # draft より新しい
    kind, why, _ = _classify(tmp_path, draft)
    assert "後発版" not in why, "同日の親依頼は後発版ではない"
    assert kind == "必須", "後発版でないなら安全側の必須に落ちる"


def test_different_day_successor_is_routine(tmp_path):
    """別日付の後発版があれば closed 扱い."""
    old = _mk(tmp_path, "2026-07-28_audit_fix_draft.md", "旧版。", age_days=2)
    _mk(tmp_path, "2026-07-29_audit_fix_draft.md", "新版。")
    kind, why, default = _classify(tmp_path, old)
    assert kind == "定型"
    assert "後発版" in why
    assert "closed" in default


def test_flags_are_not_treated_as_worktree_name(monkeypatch, capsys):
    """`--record` を worktree 名として拾って全件 skip し「0件」と誤報した bug の回帰.

    フラグしか渡していないのに `only` が立つと、全 worktree が skip されて
    滞留 0件 に見える = 事務員の報告が嘘になる (2026-07-30)。
    """
    calls = []

    def fake_pending(wt, recent_days=None):
        calls.append(wt)
        return [], [], []

    monkeypatch.setattr(dt.wb, "pending_for", fake_pending)
    monkeypatch.setattr(dt, "METRICS", Path(os.devnull))
    monkeypatch.setattr(sys, "argv", ["draft_triage.py", "--record"])
    dt.main()
    capsys.readouterr()
    assert len(calls) == len(dt.wb.WORKTREES), f"全 worktree を見ていない: {calls}"


def test_single_worktree_arg_still_filters(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(dt.wb, "pending_for",
                        lambda wt, recent_days=None: (calls.append(wt), ([], [], []))[1])
    monkeypatch.setattr(sys, "argv", ["draft_triage.py", "catalog"])
    dt.main()
    capsys.readouterr()
    assert calls == ["catalog"]


def test_worktree_word_alone_is_not_must(tmp_path):
    """規約引用で `worktree` が出るだけでは必須にしない (初版の誤検知)."""
    p = _mk(tmp_path, "2026-07-30_note_draft.md",
            "worktree 分離ルールに従います。import 1語のみ。推奨: GO")
    kind, _why, _ = _classify(tmp_path, p)
    assert kind == "定型"
