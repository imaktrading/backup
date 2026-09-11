"""カタログの公式売り切れ UT から 検索語を作る (2026-09-11 Advisor POC)."""
from __future__ import annotations

import pytest

from uniqlo_catalog_terms import clean_term, query_for

pytestmark = pytest.mark.offline


@pytest.mark.parametrize("collab,terms", [
    ("ピーナッツ（UT）", ["ピーナッツ"]),
    ("アンディ・ウォーホル / ジャン＝ミシェル・バスキア / キース・ヘリング（UT）",
     ["アンディ・ウォーホル", "ジャン＝ミシェル・バスキア", "キース・ヘリング"]),
    ("その他", []),            # 汎用すぎる
    ("", []),
])
def test_clean_term(collab, terms):
    assert clean_term(collab) == terms


def test_query_adds_brand_and_tee():
    assert query_for("ピーナッツ") == "ユニクロ ピーナッツ Tシャツ"


def test_sanrio_is_dropped_by_the_excluded_filter():
    """サンリオは user 判断で扱わない。検索語にも入れない."""
    from scrapers.rakuten_search import is_excluded_category
    assert is_excluded_category("サンリオキャラクターズ")


def test_material_columns_are_x_and_y_not_key():
    """目視材料は X / Y。KEY (AI列) には書かない (user 判断 2026-09-11)."""
    from sheet_writer_amazon import COL_KEY, _build_row
    row = _build_row({"url": "https://jp.mercari.com/item/m1", "title": "t",
                      "price_jpy": 2000, "found_by_term": "ピーナッツ",
                      "tag_number": "486159"})
    assert row[23] == "ピーナッツ" and row[24] == "486159"
    assert row[COL_KEY - 1] == ""
    assert row[13] == ""      # N には書かない


def test_parse_tag_answer():
    from scrapers.ut_tag_vision import parse_answer
    assert parse_answer("486159") == "486159"
    assert parse_answer("NONE") == ""
    assert parse_answer("商品番号は 4861590 です") == ""     # 7桁は6桁と認めない
