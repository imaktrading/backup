"""tests/test_rakuten_delivery - 即納判定は **共有の条件表** に従う (2026-08-22).

ケースも表から取る。 ここに条件を書き写さない (3箇所に散ると必ずズレる)。
"""
from __future__ import annotations

import pytest

from rakuten_delivery import IMMEDIATE, PREORDER, SKIP, judge_message, load_rule

pytestmark = pytest.mark.offline


def test_rule_file_exists_and_has_cases():
    r = load_rule()
    assert r["immediate"] and r["deny"] and r["cases"]


def test_all_cases_from_the_shared_table():
    r = load_rule()
    for c in r["cases"]:
        assert judge_message(c["msg"], r) == c["expect"], c["msg"]


def test_empty_is_skip_not_immediate():
    """読めない物を即納に倒さない (fail-closed)."""
    assert judge_message("") == SKIP
    assert judge_message(None) == SKIP


def test_deny_wins_over_immediate():
    """「入荷次第 1〜2日以内に発送」は予約側に倒す."""
    assert judge_message("入荷次第、1〜2日以内に発送いたします") == PREORDER


def test_yotei_alone_is_not_deny():
    assert judge_message("1〜2日以内に発送予定（店舗休業日を除く）") == IMMEDIATE
