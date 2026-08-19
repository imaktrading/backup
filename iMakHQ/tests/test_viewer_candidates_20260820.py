# -*- coding: utf-8 -*-
"""目視の候補に正解が出ること (2026-08-19 ユーザー指摘「引き方が間違っているのでは」).

3件の cert が「候補に出てこない」と報告された。調べると原因は全部 **引き方** だった:

  cert84299672 (FILM RED アンコールパック / NEW GENESIS)
    brand からセット記号を取れず、PROMOS と同じ扱いで DON!! カードを30枚並べていた。
    候補62件のうち50件が DON!!。しかも枠が埋まったせいでキャラ名救済の窓が 40→12 に縮み、
    catalog に在る正解 ST11-004_p1 が1件も出なかった。

  cert168157629 (チョッパー / PROMOS)
    セット記号 PROMOS + 番号 003 から `PROMOS-003` という **存在しない ID** を期待値にしていた。

  cert154233090 (3rd ANNIVERSARY SET / SABO)
    公式にまだ載っていない商品なので catalog に在るはずがないのに、promo fallback が
    score=10 で別の刷り (OP07-118) を期待値に据えていた。人が✅を押すと別カードで出品される。
"""
from __future__ import annotations

import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

from post_psa_review import (                                    # noqa: E402
    diversify_by_base, exact_name_pids, name_match_first,
    promo_first, synthesized_expected, weak_promo_guess,
)


class TestNoFabricatedId:
    """存在しない ID を期待値にしない."""

    def test_product_name_is_not_a_set_code(self):
        assert synthesized_expected("PROMOS", "003") is None
        assert synthesized_expected("EVENT", "003") is None
        assert synthesized_expected("KUMAMON", "003") is None

    def test_real_set_codes_still_work(self):
        assert synthesized_expected("ST13", "003") == "ST13-003"
        assert synthesized_expected("OP07", "118") == "OP07-118"
        assert synthesized_expected("SV7", "130") == "SV7-130"

    def test_missing_parts_produce_nothing(self):
        assert synthesized_expected(None, "003") is None
        assert synthesized_expected("ST13", "") is None


class TestWeakGuessIsNotAsserted:
    """当てずっぽうを期待値にしない (人が✅を押すと別カードで出品される)."""

    LOW = "🎯 iMakCatalog hit (promo fallback): OP07-118 Sabo (Subject='SABO' と一致, 8件中 score=10)"
    HIGH = "🎯 iMakCatalog hit (promo fallback): OP05-060_P Luffy (Subject='LUFFY' と一致, score=150)"

    def test_low_score_is_weak(self):
        assert weak_promo_guess(self.LOW) is True

    def test_score_that_has_been_right_is_kept(self):
        """実測 (人の回答771件) で score150 は 13/13 一致。ここを弾くと正解を捨てる."""
        assert weak_promo_guess(self.HIGH) is False

    def test_direct_hit_is_never_weak(self):
        assert weak_promo_guess("🎯 iMakCatalog hit: ST14-001 Monkey.D.Luffy") is False
        assert weak_promo_guess("") is False


class TestExactNameComesFirst:
    """名前がぴったり一致するカードを先に出す (後ろに回ると枠から落ちる)."""

    ROWS = [("OP02-001", "New Kama Kenpo"), ("OP02-004", "Newgate"),
            ("ST11-004_p1", "New Genesis"), ("ST11-004", "New Genesis")]

    def test_exact_match_is_ranked_first(self):
        got = name_match_first(self.ROWS, "NEW GENESIS")
        assert got[:2] == ["ST11-004_p1", "ST11-004"]

    def test_subject_with_extra_words_still_matches_the_name(self):
        rows = [("OP01-001", "Roronoa Zoro"), ("OP02-013", "Portgas D. Ace")]
        assert name_match_first(rows, "PORTGAS D. ACE ALTERNATE ART")[0] == "OP02-013"

    def test_nothing_is_dropped(self):
        assert sorted(name_match_first(self.ROWS, "NEW GENESIS")) == sorted(
            [p for p, _ in self.ROWS])

    def test_exact_pids_are_identified(self):
        assert exact_name_pids(self.ROWS, "NEW GENESIS") == {"ST11-004_p1", "ST11-004"}
        assert exact_name_pids(self.ROWS, "") == set()


class TestVariantsOfTheRightCardAreNotCutTooHard:
    """同じカードの別の刷りは人が見比べる対象。枠2件で切ると正解が落ちる."""

    PIDS = ["ST11-004", "ST11-004_D", "ST11-004_P", "ST11-004_ST16", "ST11-004_p1"]

    def test_two_per_base_drops_the_right_print(self):
        """★これが起きていた: _D と _P に枠を取られ、正解 _p1 が落ちた."""
        assert "ST11-004_p1" not in diversify_by_base(self.PIDS, 40)

    def test_exact_name_group_is_not_capped(self):
        """名前が完全一致する = そのカードの別の刷り。全部見せる (上限をかけない)."""
        assert exact_name_pids(
            [(p, "New Genesis") for p in self.PIDS], "NEW GENESIS") == set(self.PIDS)

    def test_other_cards_are_still_spread_out(self):
        """名前が違うカードは従来どおり2件までで散らす (変種で枠を埋めない)."""
        pids = ["EB01-006", "EB01-006_P", "EB01-006_p1", "EB01-006_p2", "P-065", "P-089"]
        got = diversify_by_base(pids, 6)
        assert got.count("EB01-006_p1") == 0 and "P-065" in got and "P-089" in got


class TestPromoOrderIsKept:
    def test_promo_cards_come_first_when_psa_says_promo(self):
        got = promo_first(["EB01-006", "P-065", "OP01-003_P"], True)
        assert got[0] == "P-065"

    def test_order_is_untouched_otherwise(self):
        pids = ["EB01-006", "P-065", "OP01-003_P"]
        assert promo_first(pids, False) == pids
