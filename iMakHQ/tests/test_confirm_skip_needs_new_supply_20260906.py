# -*- coding: utf-8 -*-
"""判断を押しても翌日また同じ候補が出る (2026-09-06 ユーザー指摘).

> PSA10シロナのミカルゲ … とか、PSA補URL③に何度も出てくるけど、不具合ない？

設計 (2026-07-29) は「短い cooldown + **新供給が出た時だけ出す**」の併用だった。
ところが実装は新供給を **cooldown 中の前倒し表示** にしか使っておらず、1日経つと
**候補が1件も変わっていなくても必ず戻ってきた**。押した判断が翌日 無かったことになる。

2026-06-22 に「同じ3件が毎回出る」と指摘されたのと同じ形。cooldown を短縮した時に、
新供給の条件を満了側に付けなかったので再発した。

## 決めたこと (ユーザー確定 2026-09-06「日数に関わらず、出さなければいいのでは？」)

**日数では戻さない。新しい供給が出るまで出さない。**
同じ候補をもう一度見せても、前回と同じ判断をするだけで意味が無い。

2026-07-29 の「一度外すと永久に丸腰」には戻らない。あの時は新供給の判定自体が
無かったのが原因で、今は市場に新しい出品が1件でも出れば その時点で出る。
"""
from __future__ import annotations

import io
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import psa_hoju_fill as H  # noqa: E402

HDR = H.CONFIRM_SKIP_HEADER


def _row(iid, reason="見送り", date="2026-09-01", seen=()):
    return [iid, "", "t", reason, date, "|".join(seen)]


class TestHideUntilNewSupply:
    def test_same_supply_stays_hidden_no_matter_how_old(self):
        """★本丸。何日 経っても、候補が同じなら出さない。"""
        rows = [HDR, _row("111", date="2026-01-01", seen=["https://a/1"])]
        for today in ("2026-09-02", "2026-09-20", "2027-01-01"):
            assert "111" in H.skip_iids_now(rows, {"111": ["https://a/1"]}), today

    def test_new_supply_shows_it_at_once(self):
        """新しい出品が1件でも出れば、その時点で出す (永久に丸腰にしない)。"""
        rows = [HDR, _row("111", date="2026-09-06", seen=["https://a/1"])]
        got = H.skip_iids_now(rows, {"111": ["https://a/1", "https://a/2"]})
        assert "111" not in got

    def test_supply_shrinking_is_not_new(self):
        """候補が減っただけ (売り切れ) では出さない。見るものは増えていない。"""
        rows = [HDR, _row("111", seen=["https://a/1", "https://a/2"])]
        assert "111" in H.skip_iids_now(rows, {"111": ["https://a/1"]})

    def test_url_case_and_query_do_not_count_as_new(self):
        """大文字小文字やクエリ違いを「新供給」と誤認しない。"""
        rows = [HDR, _row("111", seen=["https://a/ABC"])]
        assert "111" in H.skip_iids_now(rows, {"111": ["https://A/abc?utm=1"]})

    def test_no_candidates_stays_hidden(self):
        """候補ゼロは出しても見るものが無い。"""
        rows = [HDR, _row("111", seen=["https://a/1"])]
        assert "111" in H.skip_iids_now(rows, {"111": []})
        assert "111" in H.skip_iids_now(rows, {})

    def test_old_ledger_rows_without_seen_urls_are_shown(self):
        """前回の候補を記録していない旧行は、判断材料が無いので出す。"""
        rows = [HDR, _row("111", seen=[])]
        assert "111" not in H.skip_iids_now(rows, {"111": ["https://a/1"]})

    def test_empty_ledger(self):
        assert H.skip_iids_now([HDR], {}) == set()
        assert H.skip_iids_now([], {}) == set()

    def test_blank_rows_are_ignored(self):
        rows = [HDR, ["", "", "", "", "", ""], _row("111", seen=["https://a/1"])]
        assert H.skip_iids_now(rows, {"111": ["https://a/1"]}) == {"111"}


class TestNoTimeBasedRelease:
    def test_the_day_valve_is_gone(self):
        """日数で戻す仕掛けを残さない (残っていると また同じ候補が湧く)。"""
        src = io.open(os.path.join(_TOOLS, "psa_hoju_fill.py"), encoding="utf-8").read()
        i = src.index("def skip_iids_now(")
        body = src[i:src.index("\ndef ", i + 10)]
        assert "MAX_HIDE" not in body and "days" not in body
        assert "_skip_row_active" not in body, "cooldown 判定が残っている"

    def test_context_uses_the_new_rule(self):
        src = io.open(os.path.join(_TOOLS, "psa_hoju_fill.py"), encoding="utf-8").read()
        i = src.index("def build_confirm_context(")
        body = src[i:i + 1600]
        assert "skip_iids_now(_skip_rows, _cands_by_iid)" in body
        assert "_skip_iids_from_tab(_skip_rows, today=today)" not in body
