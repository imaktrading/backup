# -*- coding: utf-8 -*-
"""新規の目視: 特定した KEY で出品中と重なる物・同じ回の2件目を出さない (2026-09-29 ユーザー指摘)。

実例: M-P-KC-019 が2件 / EB03-026_p1 が2件 (片方は出品中) が同じ目視画面に並んだ。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dup_guard as D  # noqa: E402
import post_psa_review as R  # noqa: E402


def _t(cert, pid, cat="one_piece_tcg"):
    return {"cert": cert, "category": cat, "csv_expected": pid}


def test_live_and_second_copy_are_dropped():
    targets = [_t("1", "EB03-026_p1"), _t("2", "M-P-KC-019", "pokemon_tcg"),
               _t("3", "M-P-KC-019", "pokemon_tcg"), _t("4", ""), _t("5", "OP01-001")]
    live = {D.group_key("one_piece_tcg:EB03-026_p1"): ["820153394715"]}
    keep, dropped = R.drop_same_card_after_identify(targets, live)
    assert [t["cert"] for t in keep] == ["2", "4", "5"]             # KEY が決まらない物 (4) は残す
    assert [(t["cert"], why) for t, _, why in dropped] == [("1", "出品中"), ("3", "同じ回の2件目")]


def test_unknown_live_index_only_checks_within_the_batch():
    keep, dropped = R.drop_same_card_after_identify([_t("1", "A-1"), _t("2", "A-1")], None)
    assert [t["cert"] for t in keep] == ["1"] and dropped[0][2] == "同じ回の2件目"
