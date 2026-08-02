"""依頼書の回答は **起票した窓口に戻る** (2026-08-02).

実害 (2026-08-02):
  BRAVO が起票した pokemon の件を Catalog が `_draft.md` で返した後、**Advisor が裁定して
  GO まで出した**。BRAVO は自分の依頼が決着したことを知らないままだった。
  claim には `- 担当:` を読んで他窓口に渡さない仕組みが既にあったのに、
  **依頼書の起票者を誰も owner にしていなかった**ので draft は「誰のものでもない」状態だった。

守りたいこと:
  - `X_draft.md` の持ち主は **元依頼 `X.md` を書いた窓口**
  - 明示の `- 担当:` があればそちらが勝つ
  - board に **起票者が必ず出る** (書いていなければ「起票者不明」と出して促す)
  - `claim next` は他窓口が起票した draft を渡さない
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import claim  # noqa: E402
import worktree_board as wb  # noqa: E402


@pytest.fixture
def reqdir(tmp_path, monkeypatch):
    d = tmp_path / "catalog" / "requests"
    d.mkdir(parents=True)
    monkeypatch.setattr(wb, "DATA_ROOT", tmp_path)
    return d


def _write(d: Path, name: str, body: str) -> Path:
    p = d / name
    p.write_text(body, encoding="utf-8")
    return p


class TestRequesterOf:
    def test_draft_inherits_requester_from_base_request(self, reqdir):
        _write(reqdir, "2026-08-02_topic.md",
               "# 依頼\n\n- 依頼日: 2026-08-02 / 窓口: **BRAVO** / 緊急度: 中\n")
        draft = _write(reqdir, "2026-08-02_topic_draft.md",
                       "# 【Catalog → 窓口】draft\n\n- 回答者: **Catalog Claude**\n")
        assert wb.requester_of(draft) == "BRAVO"

    def test_question_also_inherits(self, reqdir):
        _write(reqdir, "t.md", "- 回答日: 2026-08-02 / 窓口: Advisor\n")
        q = _write(reqdir, "t_question.md", "- 回答者: Catalog\n")
        assert wb.requester_of(q) == "Advisor"

    def test_bracket_form(self, reqdir):
        p = _write(reqdir, "t.md", "- 起票: 2026-08-01 20:45 [ALPHA]\n")
        assert wb.requester_of(p) == "ALPHA"

    def test_alias_is_normalized(self, reqdir):
        p = _write(reqdir, "t.md", "- 依頼日: 2026-08-02 / 窓口: adv\n")
        assert wb.requester_of(p) == "Advisor"

    def test_unknown_name_is_empty(self, reqdir):
        p = _write(reqdir, "t.md", "- 依頼日: 2026-08-02 / 窓口: だれか\n")
        assert wb.requester_of(p) == ""

    def test_missing_base_falls_back_to_self(self, reqdir):
        """元依頼が消えていても draft 自身から読めるなら読む (落ちない)."""
        d = _write(reqdir, "orphan_draft.md", "- 依頼日: 2026-08-02 / 窓口: **BRAVO**\n")
        assert wb.requester_of(d) == "BRAVO"

    def test_draft_writer_is_not_taken_as_requester(self, reqdir):
        """draft を書いたのは headless 担当。**そこに書いてある名前を起票者にしない**."""
        _write(reqdir, "t.md", "- 依頼日: 2026-08-02 / 窓口: **BRAVO**\n")
        draft = _write(reqdir, "t_draft.md", "- 回答日: 2026-08-02 / 窓口: ALPHA\n")
        assert wb.requester_of(draft) == "BRAVO", "元依頼の起票者が勝つこと"


class TestClaimOwner:
    def _items(self, monkeypatch, kind_paths):
        monkeypatch.setattr(wb, "WORKTREES", [("catalog", "カタログ")])
        monkeypatch.setattr(wb, "pending_for", lambda wt, *a, **k: kind_paths)
        return claim.request_items()

    def test_review_item_is_owned_by_requester(self, reqdir, monkeypatch):
        _write(reqdir, "t.md", "- 依頼日: 2026-08-02 / 窓口: **BRAVO**\n")
        draft = _write(reqdir, "t_draft.md", "- 回答者: Catalog\n")
        items = self._items(monkeypatch, ([], [], [draft]))
        assert [i["owner"] for i in items] == ["BRAVO"]

    def test_explicit_owner_wins(self, reqdir, monkeypatch):
        _write(reqdir, "t.md", "- 依頼日: 2026-08-02 / 窓口: **BRAVO**\n")
        draft = _write(reqdir, "t_draft.md", "- 担当: 出品専任\n")
        items = self._items(monkeypatch, ([], [], [draft]))
        assert [i["owner"] for i in items] == ["出品専任"]

    def test_next_skips_other_desks_draft(self, reqdir, monkeypatch, tmp_path):
        """他窓口が起票した draft は `next` で渡さない (今回の事故そのもの)."""
        _write(reqdir, "t.md", "- 依頼日: 2026-08-02 / 窓口: **BRAVO**\n")
        draft = _write(reqdir, "t_draft.md", "- 回答者: Catalog\n")
        monkeypatch.setattr(claim, "backlog_items", lambda: [])
        monkeypatch.setattr(claim, "CLAIMS", tmp_path / "_claims")
        items = self._items(monkeypatch, ([], [], [draft]))
        monkeypatch.setattr(claim, "all_items", lambda: items)
        got = claim.next_item("Advisor")
        assert got.get("item") is None, "Advisor には渡らないこと"
        assert claim.next_item("BRAVO").get("item"), "起票者 BRAVO には渡ること"

    def test_inbound_request_is_not_auto_owned(self, reqdir, monkeypatch):
        """要返球 (相手の受領箱に届いた依頼) は起票者で縛らない。
        担当を明示していない限り誰でも取れる (窓口の手すきで回すため)。"""
        p = _write(reqdir, "t.md", "- 依頼日: 2026-08-02 / 窓口: **BRAVO**\n")
        items = self._items(monkeypatch, ([p], [], []))
        assert [i["owner"] for i in items] == [""]


class TestBoardShowsRequester:
    def test_board_prints_requester_and_your_ball(self, reqdir, monkeypatch, capsys):
        _write(reqdir, "t.md", "- 依頼日: 2026-08-02 / 窓口: **BRAVO**\n")
        _write(reqdir, "t_draft.md", "- 回答者: Catalog\n")
        monkeypatch.setattr(wb, "WORKTREES", [("catalog", "カタログ")])
        monkeypatch.setattr(wb, "current_desk", lambda: "BRAVO")
        wb.main()
        out = capsys.readouterr().out
        assert "起票: **BRAVO**" in out
        assert "あなたのボール" in out

    def test_board_marks_unknown_requester(self, reqdir, monkeypatch, capsys):
        """起票者が書いていない依頼は **黙って通さない** (次に書く人に促す)."""
        _write(reqdir, "t.md", "# 依頼\n\n- 依頼日: 2026-08-02\n")
        _write(reqdir, "t_draft.md", "- 回答者: Catalog\n")
        monkeypatch.setattr(wb, "WORKTREES", [("catalog", "カタログ")])
        monkeypatch.setattr(wb, "current_desk", lambda: "BRAVO")
        wb.main()
        out = capsys.readouterr().out
        assert "起票者不明" in out
        assert "あなたのボール" not in out

    def test_other_desk_sees_no_star(self, reqdir, monkeypatch, capsys):
        _write(reqdir, "t.md", "- 依頼日: 2026-08-02 / 窓口: **BRAVO**\n")
        _write(reqdir, "t_draft.md", "- 回答者: Catalog\n")
        monkeypatch.setattr(wb, "WORKTREES", [("catalog", "カタログ")])
        monkeypatch.setattr(wb, "current_desk", lambda: "Advisor")
        wb.main()
        out = capsys.readouterr().out
        assert "起票: **BRAVO**" in out, "誰の件かは全窓口に見えること"
        assert "あなたのボール" not in out
