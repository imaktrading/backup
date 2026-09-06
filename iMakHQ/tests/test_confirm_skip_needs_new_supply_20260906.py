# -*- coding: utf-8 -*-
"""判断を押しても翌日また同じ候補が出る (2026-09-06 ユーザー指摘).

> PSA10シロナのミカルゲ … とか、PSA補URL③に何度も出てくるけど、不具合ない？

設計 (2026-07-29) は「短い cooldown + **新供給が出た時だけ出す**」の併用だった。
ところが実装は新供給を **cooldown 中の前倒し表示** にしか使っておらず、1日経つと
**候補が1件も変わっていなくても必ず戻ってきた**。押した判断が翌日 無かったことになる。

これは 2026-06-22 に「同じ3件が毎回出る」と指摘されたのと同じ形。短縮だけして
新供給の条件を付けなかったので再発した。

直し方: cooldown 満了の側にも新供給の条件を付ける。ただし **供給が動かない出品を
永久に伏せない** (2026-07-29 の「一度外すと永久に丸腰」に戻さない)。安全弁が MAX_HIDE。
"""
from __future__ import annotations

import os
import sys

import pytest

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import psa_hoju_fill as H  # noqa: E402

HDR = H.CONFIRM_SKIP_HEADER


def _row(iid, reason="見送り", date="2026-09-01", seen=()):
    return [iid, "", "t", reason, date, "|".join(seen)]


class TestSameSupplyStaysHidden:
    def test_expired_cooldown_but_nothing_new_stays_hidden(self):
        """★本丸。1日経っても候補が同じなら出さない。"""
        rows = [HDR, _row("111", date="2026-09-01", seen=["https://a/1"])]
        got = H.skip_iids_now(rows, "2026-09-05", {"111": ["https://a/1"]})
        assert "111" in got, "供給が同じなのに再表示している"

    def test_new_supply_shows_even_during_cooldown(self):
        """新しい出品が market に出たら、伏せている最中でも出す。"""
        rows = [HDR, _row("111", date="2026-09-05", seen=["https://a/1"])]
        got = H.skip_iids_now(rows, "2026-09-05", {"111": ["https://a/1", "https://a/2"]})
        assert "111" not in got

    def test_within_cooldown_stays_hidden(self):
        rows = [HDR, _row("111", date="2026-09-05", seen=["https://a/1"])]
        got = H.skip_iids_now(rows, "2026-09-05", {"111": ["https://a/1"]})
        assert "111" in got

    def test_url_case_and_query_do_not_count_as_new(self):
        """大文字小文字やクエリ違いを「新供給」と誤認しない。"""
        rows = [HDR, _row("111", date="2026-09-01", seen=["https://a/ABC"])]
        got = H.skip_iids_now(rows, "2026-09-05", {"111": ["https://A/abc?utm=1"]})
        assert "111" in got


class TestNeverHideForever:
    def test_after_max_hide_it_comes_back(self):
        """★供給が動かない出品を永久に伏せない (2026-07-29 の反省)。"""
        rows = [HDR, _row("111", date="2026-08-01", seen=["https://a/1"])]
        got = H.skip_iids_now(rows, "2026-09-05", {"111": ["https://a/1"]},
                              max_hide_days=14)
        assert "111" not in got

    def test_the_valve_is_configurable_and_sane(self):
        assert 7 <= H.CONFIRM_SKIP_MAX_HIDE_DAYS <= 60


class TestSafeSide:
    def test_unreadable_date_stays_hidden(self):
        """日付が壊れている行で毎回出さない (安全側)。"""
        rows = [HDR, _row("111", date="こわれた", seen=["https://a/1"])]
        assert "111" in H.skip_iids_now(rows, "2026-09-05", {"111": ["https://a/1"]})

    def test_no_candidates_means_nothing_to_show(self):
        """候補ゼロは「新供給」ではない。出しても見るものが無い。"""
        rows = [HDR, _row("111", date="2026-09-01", seen=["https://a/1"])]
        assert "111" in H.skip_iids_now(rows, "2026-09-05", {"111": []})

    def test_old_ledger_rows_without_seen_urls_are_shown(self):
        """前回の候補を記録していない旧行は、判断材料が無いので出す。"""
        rows = [HDR, _row("111", date="2026-09-01", seen=[])]
        assert "111" not in H.skip_iids_now(rows, "2026-09-05", {"111": ["https://a/1"]})

    def test_empty_ledger(self):
        assert H.skip_iids_now([HDR], "2026-09-05", {}) == set()
        assert H.skip_iids_now([], "2026-09-05", {}) == set()


def test_context_uses_the_new_rule():
    """build_confirm_context が新しい判定を通していること。"""
    import io
    src = io.open(os.path.join(_TOOLS, "psa_hoju_fill.py"), encoding="utf-8").read()
    i = src.index("def build_confirm_context(")
    body = src[i:i + 1600]
    assert "skip_iids_now(_skip_rows, today, _cands_by_iid)" in body
    assert "_skip_iids_from_tab(_skip_rows, today=today)" not in body, \
        "古い cooldown だけの判定が残っている"
