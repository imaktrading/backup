"""tests/test_demand_keywords - 需要実証済カードから検索キーワードを作る.

2026-08-18 新設。 ファネル分析の RESTOCK (在庫切れ × 需要あり) から
カード番号を取って検索語にする。 推測で語を作らない (= 番号が取れない行は捨てる) 事を固定する。
"""
from __future__ import annotations

import pytest

from scrapers.demand_keywords import (
    build_keywords_from_rows,
    demand_score,
    extract_card_number,
)

pytestmark = pytest.mark.offline


def _row(title, watch=0, impr=0, sales90=0):
    return {"title": title, "watch": watch, "impr": impr, "sales90": sales90}


def test_extract_card_number_variants():
    assert extract_card_number("PSA 10 One Piece #OP08-106 Nami") == "OP08-106"
    assert extract_card_number("PSA10 Gundam GD02-072 Promo") == "GD02-072"
    assert extract_card_number("PSA 10 SB02 001 Luffy") == "SB02-001"


def test_extract_card_number_none_when_absent():
    """番号が無いタイトルから推測しない (別カードを拾うため)."""
    assert extract_card_number("PSA 10 One Piece Luffy Manga Rare") == ""
    assert extract_card_number("Weiss Schwarz NIKKE #026 RRR") == ""


def test_non_psa_rows_are_ignored():
    rows = [_row("Gundam CCG Edition Beta #GD02-072", watch=9)]
    assert build_keywords_from_rows(rows) == []


def test_keywords_are_sorted_by_demand():
    rows = [
        _row("PSA 10 One Piece #OP01-001", watch=1),
        _row("PSA 10 One Piece #OP02-002", sales90=1),   # 実売が最優先
        _row("PSA 10 One Piece #OP03-003", watch=5),
    ]
    assert build_keywords_from_rows(rows) == [
        "PSA10 OP02-002", "PSA10 OP03-003", "PSA10 OP01-001",
    ]


def test_same_card_is_not_duplicated():
    rows = [_row("PSA 10 #OP08-106 A", watch=1), _row("PSA 10 OP08-106 B", watch=9)]
    assert build_keywords_from_rows(rows) == ["PSA10 OP08-106"]


def test_limit_takes_top_n():
    rows = [_row(f"PSA 10 #OP0{i}-00{i}", watch=i) for i in range(1, 5)]
    assert build_keywords_from_rows(rows, limit=2) == ["PSA10 OP04-004", "PSA10 OP03-003"]


def test_demand_score_handles_dirty_numbers():
    assert demand_score({"watch": "1,000", "impr": "", "sales90": None}) == 10000.0
