# -*- coding: utf-8 -*-
"""依頼書の名前づけ規約が dispatcher の実装と食い違わないこと (2026-08-07).

実害:
  窓口が catalog への質問を `2026-08-03_..._question.md` という名前で置いた。
  規約 (CLAUDE.md) に「`_question` / `_draft` で先に聞く」と書いてあったため。
  ところが `worktree_board.DRAFT_SUFFIXES` は `_question` を
  **「担当が書いた下書き = 窓口レビュー待ち」** と解釈する。結果その依頼は
  `pending_for()` の `mine` (= dispatch 対象) から外れ、**4日間 catalog に配られなかった**。
  その間 8/03〜8/06 の4日連続で重複が入稿CSVに載り、毎晩人が手で外していた。

  同種の穴がもう1つ: 窓口が `_response.md` に「実装 GO」と日本語で書いても、
  `IMPLEMENT_MARKERS` は `[IMPLEMENT-GO]` の明示トークンしか見ないので実装キューに入らない。
  8/04 の重複くん回答が3日動かなかった原因。

守りたいこと:
  **規約の文面と dispatcher の実装を、片方だけ動かせないようにする。**
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import worktree_board as wb  # noqa: E402

CLAUDE_MDS = [
    r"C:\Users\imax2\.claude\CLAUDE.md",
    r"C:\dev\iMak\iMakAdvisor\CLAUDE.md",
    r"C:\dev\iMak\iMakAlpha\CLAUDE.md",
    r"C:\dev\iMak\iMakBravo\CLAUDE.md",
    r"C:\dev\iMak\iMakHQ\CLAUDE.md",
]


def _docs():
    return [(p, open(p, encoding="utf-8").read())
            for p in CLAUDE_MDS if os.path.exists(p)]


class TestDispatcherContract:
    def test_question_and_draft_are_review_suffixes(self):
        assert "_question" in wb.DRAFT_SUFFIXES
        assert "_draft" in wb.DRAFT_SUFFIXES

    def test_implement_marker_is_an_explicit_token(self):
        assert wb.IMPLEMENT_MARKERS == ("[IMPLEMENT-GO]",)

    def test_draft_suffixed_files_are_not_dispatched(self, tmp_path, monkeypatch):
        """`_question.md` は `mine` に入らない (= 相手に配られない) ことの実証."""
        d = tmp_path / "wt" / "requests"
        d.mkdir(parents=True)
        (d / "2026-08-03_topic_question.md").write_text("q", encoding="utf-8")
        (d / "2026-08-07_topic.md").write_text("plain", encoding="utf-8")
        monkeypatch.setattr(wb, "DATA_ROOT", tmp_path)
        mine, _theirs, drafts = wb.pending_for("wt")
        assert [p.name for p in mine] == ["2026-08-07_topic.md"]
        assert [p.name for p in drafts] == ["2026-08-03_topic_question.md"]

    def test_japanese_go_does_not_enter_implement_queue(self, tmp_path, monkeypatch):
        d = tmp_path / "wt" / "requests"
        d.mkdir(parents=True)
        (d / "a_response.md").write_text("実装 GO でお願いします", encoding="utf-8")
        (d / "b_response.md").write_text("[IMPLEMENT-GO]\n実装 GO", encoding="utf-8")
        monkeypatch.setattr(wb, "DATA_ROOT", tmp_path)
        assert [p.name for p in wb.implement_for("wt")] == ["b_response.md"]


class TestDocsWarnAboutIt:
    """規約側にも書いてあること (片方だけ直すと事故が再発する)."""

    def test_docs_exist(self):
        assert _docs(), "CLAUDE.md が1つも読めない"

    def test_outbound_questions_must_not_use_question_suffix(self):
        for p, s in _docs():
            assert "窓口から出す質問に `_question` / `_draft` を付けてはいけない" in s, p

    def test_docs_mention_the_dispatcher_reason(self):
        for p, s in _docs():
            assert "DRAFT_SUFFIXES" in s, f"{p}: なぜ配られないかの理由が書かれていない"

    def test_docs_mention_the_implement_token(self):
        for p, s in _docs():
            assert "[IMPLEMENT-GO]" in s, f"{p}: 実装トークンが書かれていない"

    def test_docs_keep_question_for_pushback_direction(self):
        """担当→窓口の差し戻しには `_question` が正しい (消してしまわないこと)."""
        for p, s in _docs():
            assert "`_question.md` で指摘して止める" in s, p
