"""カタログの公式売り切れ UT から 検索語を作る (2026-09-11 Advisor POC)."""
from __future__ import annotations

import json

import pytest

import uniqlo_catalog_terms as T
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


# --- 2026-09-12 Advisor 依頼: 検索語の並びを「売れている作品」順に ---

def _fake_sold_out_collabs(db_path, include_gone=True, only_anime=False):  # noqa: ARG001
    # 件数順なら ワンピース(2) -> ブルーロック(1) -> 米津玄師(1)
    return {"ワンピース": ["p1", "p2"], "ブルーロック": ["p3"], "米津玄師": ["p4"]}


def test_build_terms_orders_by_demand_score_when_file_present(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "sold_out_collabs", _fake_sold_out_collabs)
    demand = tmp_path / "ut_demand_words.json"
    demand.write_text(json.dumps({"works": [
        {"work_en": "Bluelock", "collab_jp": "ブルーロック", "score": 11},
        {"work_en": "One Piece", "collab_jp": "ワンピース", "score": 29},
    ]}), encoding="utf-8")
    terms = [t["term"] for t in T.build_terms(demand_path=str(demand))]
    # score 順: ワンピース(29) > ブルーロック(11)、score無しの米津玄師は最後
    assert terms == ["ワンピース", "ブルーロック", "米津玄師"]


def test_build_terms_falls_back_to_count_order_when_demand_file_missing(monkeypatch):
    monkeypatch.setattr(T, "sold_out_collabs", _fake_sold_out_collabs)
    terms = [t["term"] for t in T.build_terms(demand_path="C:/nope/does_not_exist.json")]
    # 従来どおり件数順 (止めない)
    assert terms == ["ワンピース", "ブルーロック", "米津玄師"]


def test_build_terms_does_not_drop_any_term(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "sold_out_collabs", _fake_sold_out_collabs)
    demand = tmp_path / "ut_demand_words.json"
    demand.write_text(json.dumps({"works": [
        {"work_en": "One Piece", "collab_jp": "ワンピース", "score": 29},
    ]}), encoding="utf-8")
    terms = [t["term"] for t in T.build_terms(demand_path=str(demand))]
    assert set(terms) == {"ワンピース", "ブルーロック", "米津玄師"}


def test_demand_scores_skips_entries_without_collab_jp(tmp_path):
    demand = tmp_path / "ut_demand_words.json"
    demand.write_text(json.dumps({"works": [
        {"work_en": "No JP name", "score": 5},
        {"work_en": "One Piece", "collab_jp": "ワンピース", "score": 29},
    ]}), encoding="utf-8")
    assert T._demand_scores(str(demand)) == {"ワンピース": 29}


# --- 2026-09-13 user 確定: 公式から消えた商品も対象 / アニメ漫画で絞れる ---

def test_gone_products_are_included_by_default():
    """UT は数ヶ月でページごと消える。『売り切れだが公式に残っている物』だけだと
    アニメ・漫画がほとんど残らない (実測: 341件中ごく一部しか見えなかった)."""
    import inspect
    sig = inspect.signature(T.sold_out_collabs)
    assert sig.parameters["include_gone"].default is True


@pytest.mark.parametrize("specs,anime", [
    ({"collab": "鬼滅の刃（UT）"}, True),
    ({"character_family": "Pokemon", "long_description": "ポケモンのデザイン"}, True),
    ({"collab": "MoMA アート・アイコンズ"}, False),
    ({"collab": "アンディ・ウォーホル"}, False),
])
def test_is_anime(specs, anime):
    assert T.is_anime(specs) is anime
