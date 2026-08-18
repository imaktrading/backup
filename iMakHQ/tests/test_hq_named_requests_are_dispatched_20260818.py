# -*- coding: utf-8 -*-
"""名前に `hq` が入るだけで依頼が配達されなくなる穴を塞いだこと (2026-08-18).

実害:
  `worktree_board._is_outbound()` は `hq_` で始まる / `_hq_` を含む stem を
  **全部「相手ボール」**に分類していた。dispatch は `mine` しか配らないので、
  HQ が出した依頼のうち名前に hq が入ったものは **担当が一度も起こされない**。
    - 2026-08-03 の ALT ART 実装依頼 = 9日 未配達
      (`2026-08-03_hq_op_reprint_scoring_alt_art_superseded.md` に本人が書いている)
    - 2026-08-01 の pdca resolver = 11日 未配達
  さらに `route_inbox.inject()` は名前から `_to_<相手>` を落とすため
  `hq_to_catalog_<topic>` → `hq_<topic>` になる。**自動投入した依頼ほど確実に埋まる**。

守りたいこと:
  1. `<wt>/requests/` に在る依頼は、**宛先が窓口だと明示されていない限り**
     その worktree のボール = dispatch される。
  2. 担当→窓口 (`to_hq` / `【Catalog → HQ】`) は今までどおり配らない (= 空焚きを増やさない)。
  3. 投入時に **配達されない名前**を作らない (`..._verdict` 等で終わる話題名)。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import route_inbox as ri  # noqa: E402
import worktree_board as wb  # noqa: E402


def _mk(tmp_path, name, body="x", wt="catalog"):
    d = tmp_path / wt / "requests"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(body, encoding="utf-8")
    return p


class TestHqNamedRequestsAreDelivered:
    """★本題: 名前の hq で dispatch から外れない."""

    NAMES = [
        "2026-08-03_hq_op_reprint_scoring_alt_art.md",   # 9日 未配達だった実物
        "2026-08-01_hq_pdca_resolver_and_rarity.md",     # 11日 未配達だった実物
        "hq_response_yodobashi_cadence_GO.md",
        "2026-06-11_gapB_promo_keynaming_HQ_decision2.md",
    ]

    def test_hq_named_requests_land_in_mine(self, tmp_path, monkeypatch):
        for n in self.NAMES:
            _mk(tmp_path, n)
        monkeypatch.setattr(wb, "DATA_ROOT", tmp_path)
        mine, theirs, _drafts = wb.pending_for("catalog")
        assert sorted(p.name for p in mine) == sorted(self.NAMES)
        assert theirs == []


class TestRequestsAddressedToTheDeskAreNotDispatched:
    """担当→窓口 は配らない (配ると担当が自分の質問を処理させられる = 空焚き)."""

    def test_to_hq_in_filename(self, tmp_path, monkeypatch):
        p = _mk(tmp_path, "2026-05-27_to_hq_listing_psa_brand_subject_columns.md")
        _mk(tmp_path, "2026-06-21_catalog_questions_for_HQ_reply_actions.md")
        monkeypatch.setattr(wb, "DATA_ROOT", tmp_path)
        mine, theirs, _ = wb.pending_for("catalog")
        assert mine == []
        assert len(theirs) == 2 and p.name in [x.name for x in theirs]

    def test_addressed_to_desk_in_body(self, tmp_path, monkeypatch):
        """名前は普通でも、冒頭で窓口宛を名乗っていれば配らない."""
        _mk(tmp_path, "2026-08-13_rarity_17rows_naming.md",
            "# 依頼 (catalog → HQ): rarity 17 行の eBay 表記を決めてください\n")
        _mk(tmp_path, "2026-08-10_tcg_ssot_a4_result.md",
            "# 【Catalog → Advisor】A-4 検証結果 + 残る唯一の判断\n")
        monkeypatch.setattr(wb, "DATA_ROOT", tmp_path)
        mine, theirs, _ = wb.pending_for("catalog")
        assert mine == []
        assert len(theirs) == 2

    def test_desk_to_worktree_is_still_dispatched(self, tmp_path, monkeypatch):
        """逆向き (窓口→担当) は配る。`→ Catalog` を `→ HQ` と読み違えない."""
        _mk(tmp_path, "2026-07-29_divers_scope.md",
            "# 【HQ(Advisor) → Catalog】DIVERS スコープ判断 = 全て対象外\n")
        monkeypatch.setattr(wb, "DATA_ROOT", tmp_path)
        mine, theirs, _ = wb.pending_for("catalog")
        assert [p.name for p in mine] == ["2026-07-29_divers_scope.md"]
        assert theirs == []

    def test_quote_deep_in_body_does_not_flip_direction(self, tmp_path, monkeypatch):
        """本文の奥で `Catalog → HQ` を引用しただけでは相手ボールにしない."""
        body = "# 依頼 (HQ → Catalog): 直してください\n" + "\n".join(
            f"- 行{i}" for i in range(30)) + "\n> 【Catalog → HQ】過去の依頼を引用\n"
        _mk(tmp_path, "2026-08-18_fix_something.md", body)
        monkeypatch.setattr(wb, "DATA_ROOT", tmp_path)
        mine, theirs, _ = wb.pending_for("catalog")
        assert [p.name for p in mine] == ["2026-08-18_fix_something.md"]
        assert theirs == []

    def test_hq_inbox_never_marks_outbound(self, tmp_path, monkeypatch):
        """`hq/requests/` は自分の受領箱。何が来ても自分のボール."""
        _mk(tmp_path, "2026-07-27_dedupe_to_hq_pending_reminder.md", wt="hq")
        monkeypatch.setattr(wb, "DATA_ROOT", tmp_path)
        mine, theirs, _ = wb.pending_for("hq")
        assert len(mine) == 1 and theirs == []


class TestInjectNeverCreatesUndeliverableName:
    """投入した瞬間に「決着済」「レビュー待ち」に見える名前を作らない.

    実害: `2026-08-17_hq_machine_readable_verdict.md` は `_verdict` が
    `CLOSED_SUFFIXES` にあるため投入直後から決着済扱いで、catalog に一度も配られなかった。
    """

    def test_closed_suffix_topic_gets_req_suffix(self):
        assert ri.delivery_safe_stem(
            "2026-08-17_hq_machine_readable_verdict") == \
            "2026-08-17_hq_machine_readable_verdict_req"
        assert ri.delivery_safe_stem("2026-08-13_rarity_17rows_naming_decision") == \
            "2026-08-13_rarity_17rows_naming_decision_req"

    def test_draft_suffix_topic_gets_req_suffix(self):
        assert ri.delivery_safe_stem("2026-08-18_open_question") == \
            "2026-08-18_open_question_req"

    def test_normal_stem_is_untouched(self):
        for s in ["2026-08-18_topic", "2026-08-18_hq_topic", "2026-08-18_verdicts"]:
            assert ri.delivery_safe_stem(s) == s

    def test_injected_file_is_actually_dispatchable(self, tmp_path, monkeypatch):
        """投入 → 相手の `mine` に入るところまで通す (E2E)."""
        (tmp_path / "_routing").mkdir(parents=True)
        (tmp_path / "catalog" / "requests").mkdir(parents=True)
        src = tmp_path / "_routing" / "2026-08-17_hq_to_catalog_machine_readable_verdict.md"
        src.write_text("# 依頼: 機械可読な結論行を足してほしい\n", encoding="utf-8")
        monkeypatch.setattr(ri, "DATA_ROOT", tmp_path)
        monkeypatch.setattr(ri, "ROUTING", tmp_path / "_routing")
        monkeypatch.setattr(ri, "ROUTED", tmp_path / "_routing" / "_routed")
        r = ri.inject(src, auto=True)
        assert r["ok"], r
        monkeypatch.setattr(wb, "DATA_ROOT", tmp_path)
        mine, theirs, drafts = wb.pending_for("catalog")
        assert [p.name for p in mine] == \
            ["2026-08-17_hq_machine_readable_verdict_req.md"]
        assert theirs == [] and drafts == []
