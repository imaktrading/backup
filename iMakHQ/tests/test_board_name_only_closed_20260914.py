"""名前の末尾だけで決着扱いになる新規依頼を、板で名指しする (残務 №19・2026-09-14).

配り直しはしない (孤立の大半は `<topic>_hq_reply` 等の本物の回答だった)。見えるようにするだけ。
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import worktree_board as wb  # noqa: E402


def _req(tmp_path, monkeypatch):
    d = tmp_path / "catalog" / "requests"
    d.mkdir(parents=True)
    monkeypatch.setattr(wb, "DATA_ROOT", tmp_path)
    return d


def test_orphan_topic_word_is_named(tmp_path, monkeypatch):
    d = _req(tmp_path, monkeypatch)
    (d / "2026-09-14_hq_machine_readable_verdict.md").write_text("依頼", encoding="utf-8")
    assert [p.name for p in wb.name_only_closed("catalog")] == ["2026-09-14_hq_machine_readable_verdict.md"]


def test_real_reply_with_original_is_not_named(tmp_path, monkeypatch):
    d = _req(tmp_path, monkeypatch)
    (d / "2026-09-14_rarity.md").write_text("依頼", encoding="utf-8")
    (d / "2026-09-14_rarity_decision.md").write_text("回答", encoding="utf-8")
    assert wb.name_only_closed("catalog") == []


def test_original_older_than_window_still_counts(tmp_path, monkeypatch):
    d = _req(tmp_path, monkeypatch)
    old = d / "2026-07-01_rarity.md"
    old.write_text("依頼", encoding="utf-8")
    t = time.time() - 60 * 86400
    os.utime(old, (t, t))
    (d / "2026-07-01_rarity_decision.md").write_text("回答", encoding="utf-8")
    assert wb.name_only_closed("catalog") == []


def test_clear_closure_words_and_old_files_are_ignored(tmp_path, monkeypatch):
    d = _req(tmp_path, monkeypatch)
    (d / "2026-09-14_x_processed.md").write_text("済", encoding="utf-8")
    old = d / "2026-06-01_y_verdict.md"
    old.write_text("古い", encoding="utf-8")
    t = time.time() - 60 * 86400
    os.utime(old, (t, t))
    assert wb.name_only_closed("catalog") == []


def test_board_still_treats_it_as_closed(tmp_path, monkeypatch):
    """配り直さない (dispatch の判定は変えない)。"""
    d = _req(tmp_path, monkeypatch)
    (d / "2026-09-14_topic_verdict.md").write_text("依頼", encoding="utf-8")
    mine, theirs, drafts = wb.pending_for("catalog")
    assert (mine, theirs, drafts) == ([], [], [])
