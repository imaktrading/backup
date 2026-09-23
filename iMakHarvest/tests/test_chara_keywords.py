"""tests/test_chara_keywords - HQ chara_market.csv からキャラ軸の検索語を作る.

2026-09-21 新設 (HQ 依頼 `2026-09-21_chara_keywords_draft`)。
"""
from __future__ import annotations

import pytest

from scrapers.chara_keywords import build_keywords

pytestmark = pytest.mark.offline

ROWS = [
    {"和名": "ピカチュウ", "上限仕入れ値(円)": ""},
    {"和名": "コイキング", "上限仕入れ値(円)": ""},
    {"和名": "", "上限仕入れ値(円)": ""},  # 和名空欄の行は語を作らない
]


def test_build_keywords_uses_name_only():
    kw = build_keywords(ROWS)
    assert kw == ["PSA10 ピカチュウ", "PSA10 コイキング"]


def test_build_keywords_skips_blank_name():
    kw = build_keywords(ROWS)
    assert "PSA10 " not in kw


def test_build_keywords_dedupes():
    kw = build_keywords(ROWS + [{"和名": "ピカチュウ"}])
    assert len(kw) == len(set(kw)) == 2


def test_build_keywords_preserves_row_order():
    # CSV の行順 = 優先順 (市場+うち → うち → 市場)。 並び替えない
    rows = [{"和名": "B"}, {"和名": "A"}]
    assert build_keywords(rows) == ["PSA10 B", "PSA10 A"]
