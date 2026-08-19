# -*- coding: utf-8 -*-
"""出品メールに「落ちた分と その後どうなるか」を載せる (2026-08-19 ユーザー要望).

それまでメールは出品できた分しか書いておらず、落ちた分は走行ログを開かないと分からなかった。
8/19 は 20件中6件が未回答のまま落ちたのに、メールからは気づけなかった。

載せるのは 件数 / 中身 / 対応状況 の3つ。読めない素材は **黙って省く** (推測で書かない)。
"""
from __future__ import annotations

import io
import os
import sys

CP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "control_panel.py")


def _fn(name):
    """control_panel は tkinter を import するので純関数だけ切り出す."""
    src = io.open(CP, encoding="utf-8").read()
    i = src.index(f"def {name}")
    ns = {"os": os, "sys": sys, "WORKSPACE": r"C:\dev\iMak"}
    exec(src[i:src.index("\ndef ", i + 1)], ns)                # noqa: S102
    return ns[name]


LOG = """
  ⏭️ 枠を選ぶ前に除外 [OUT-OF-SCOPE=参入しないゲーム]: 3件 → ['1','2','3']
  ⏭️ 枠を選ぶ前に除外 [NO-IMAGE=catalogに画像が無く目視不能]: 1件 → ['9']
  📨 NONE/NG 2 件 → catalog 宿題化 (1 件記録)
  ⚠️ Skipping #151235549: selfcheck failed in build_row
  🔎 目視未確定で出品見送り: 8 件 ['a','b']
"""
REMOVED = {"removed": 4, "removed_titles": ["[2] (KEY=x) PSA 10 One Piece Ace",
                                            "[3] (KEY=y) PSA 10 Pokemon Pikachu"]}
HOJU = {"added": 15}


class TestCounts:
    def test_pending_excludes_the_none_ones(self):
        """『見送り8件』は 未回答6 + 該当なし2 の合計。二重に数えない."""
        got = "\n".join(_fn("build_exclusion_lines")(LOG, REMOVED, HOJU))
        assert "目視で未回答 6件" in got
        assert "「該当なし」 2件" in got

    def test_every_kind_appears_once(self):
        got = _fn("build_exclusion_lines")(LOG, REMOVED, HOJU)
        assert len(got) == 6                     # 未回答/該当なし/画像なし/対象外/自己チェック/重複
        assert sum("画像" in x for x in got) == 1

    def test_duplicates_show_where_the_supply_went(self):
        got = "\n".join(_fn("build_exclusion_lines")(LOG, REMOVED, HOJU))
        assert "既に出品中 4件" in got and "補URLに回しました (今回 15本 追加)" in got
        assert "One Piece Ace" in got, "何が落ちたか分かるように中身も出す"

    def test_selfcheck_is_marked_as_our_bug(self):
        got = "\n".join(_fn("build_exclusion_lines")(LOG, REMOVED, HOJU))
        assert "自己チェックで不一致 1件" in got and "こちらの不具合" in got


class TestNeverGuesses:
    def test_empty_inputs_produce_nothing(self):
        assert _fn("build_exclusion_lines")("", {}, {}) == []

    def test_missing_hoju_record_still_reports_duplicates(self):
        got = "\n".join(_fn("build_exclusion_lines")("", REMOVED, {}))
        assert "既に出品中 4件" in got and "補URLの対象になります" in got

    def test_unknown_lines_are_skipped_not_zero_filled(self):
        got = _fn("build_exclusion_lines")("目視未確定で出品見送り: 0 件", {}, {})
        assert got == []


class TestMailBody:
    def test_section_is_appended(self):
        subject, body = _fn("build_upload_mail")({
            "listed": [{"label": "m1", "item_id": "8200"}], "ng": 0, "write": True,
            "excluded_lines": ["・目視で未回答 6件 → 次の走行でまた候補に戻ります"]})
        assert "― 出品しなかった分 ―" in body and "未回答 6件" in body
        assert "8件" not in subject

    def test_no_section_when_nothing_excluded(self):
        _, body = _fn("build_upload_mail")({"listed": [], "ng": 0, "write": True})
        assert "出品しなかった分" not in body
