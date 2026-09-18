"""tests/test_treasure_keywords - HQ demand_market.csv からトレジャーハントの検索語を作る.

2026-09-18 新設 (HQ 依頼 `2026-09-18_treasure_hunt_harvest`)。
"""
from __future__ import annotations

import pytest

from scrapers.treasure_keywords import (
    build_cost_limits,
    build_keywords,
    extract_number,
    judge_cost,
)

pytestmark = pytest.mark.offline

ROWS = [
    {"番号": "020/M-P", "和名": "ピカチュウ", "上限仕入れ値(円)": "15000"},
    {"番号": "080/073", "和名": "コイキング", "上限仕入れ値(円)": "25800"},
    {"番号": "P-043", "和名": "", "上限仕入れ値(円)": "19000"},  # product_id 引けず和名空欄
]


def test_build_keywords_uses_name_and_number():
    kw = build_keywords(ROWS)
    assert "PSA10 ピカチュウ" in kw
    assert "PSA10 020/M-P" in kw
    assert "PSA10 P-043" in kw
    # 和名が空の行は番号だけ入る (名前無しの語を作らない)
    assert "PSA10 " not in kw


def test_build_keywords_dedupes():
    kw = build_keywords(ROWS)
    assert len(kw) == len(set(kw))


def test_extract_number_bare_fraction():
    assert extract_number("PSA10 Pikachu 020/M-P Happy Set Promo") == "020/M-P"


def test_extract_number_set_code_style():
    assert extract_number("PSA10 One Piece P-043 Luffy") == "P-043"


def test_extract_number_absent():
    assert extract_number("番号が書かれていないタイトル") == ""


def test_judge_cost_within_limit():
    limits = build_cost_limits(ROWS)
    assert judge_cost("PSA10 020/M-P ピカチュウ", 12000, limits) == "上限内"


def test_judge_cost_over_limit():
    limits = build_cost_limits(ROWS)
    assert judge_cost("PSA10 020/M-P ピカチュウ", 20000, limits) == "超過"


def test_judge_cost_boundary_is_within():
    limits = build_cost_limits(ROWS)
    assert judge_cost("PSA10 020/M-P ピカチュウ", 15000, limits) == "上限内"


def test_judge_cost_unknown_number_is_blank():
    limits = build_cost_limits(ROWS)
    assert judge_cost("番号なしタイトル", 5000, limits) == ""


def test_judge_cost_unknown_price_is_blank():
    limits = build_cost_limits(ROWS)
    assert judge_cost("PSA10 020/M-P ピカチュウ", None, limits) == ""
