# -*- coding: utf-8 -*-
"""UT (UNIQLO/GU Tシャツ) 入稿CSV → canonical KEY (2026-09-12).

依頼: iMak_data/dedupe/requests/2026-09-12_ut_key_from_csv_columns.md [IMPLEMENT-GO]

出品くん `iMakMercari/ut_catalog_values.identity_key` と **同一形**:
    uniqlo_ut:<C:Model 6桁>:<C:Color 大文字>:<C:Size 大文字>
シート側 (AI列, ut_key_backfill.py) も同じ文字列を書くので突合できる。
diverg 検出のため、依頼書に載った実例 2つを pin する。
"""
from __future__ import annotations

import pytest

from dedupe import resolver_io
from dedupe.resolver_io import _ut_key_from_csv_row

pytestmark = pytest.mark.offline


def _row(cat="15687", model="", color="", size=""):
    return {"*Category": cat, "C:Model": model, "C:Color": color, "C:Size": size}


# --- 依頼書の実例を pin (SSOT diverg 検出) ---

def test_documented_example_blue_2xl():
    assert _ut_key_from_csv_row(_row(model="480691", color="Blue", size="2XL")) == "uniqlo_ut:480691:BLUE:2XL"


def test_documented_example_white_l():
    # ut_catalog_values docstring の例 uniqlo_ut:486159:WHITE:L
    assert _ut_key_from_csv_row(_row(model="486159", color="White", size="L")) == "uniqlo_ut:486159:WHITE:L"


def test_gu_category_53159_also_builds():
    assert _ut_key_from_csv_row(_row(cat="53159", model="123456", color="Black", size="M")) == "uniqlo_ut:123456:BLACK:M"


def test_color_and_size_uppercased():
    assert _ut_key_from_csv_row(_row(model="480691", color="light blue", size="xl")) == "uniqlo_ut:480691:LIGHT BLUE:XL"


def test_6digit_extracted_from_noisy_model():
    assert _ut_key_from_csv_row(_row(model="UT-480691-x", color="Red", size="S")) == "uniqlo_ut:480691:RED:S"


# --- fail-closed: 対象外 / 材料不足は "" (= 素通り) ---

def test_non_ut_category_returns_empty():
    # TCG 等 別カテゴリは UT KEY を作らない (= 従来 catalog resolve へ)
    assert _ut_key_from_csv_row(_row(cat="183454", model="480691", color="Blue", size="M")) == ""


def test_missing_model_returns_empty():
    assert _ut_key_from_csv_row(_row(model="", color="Blue", size="M")) == ""


def test_missing_color_returns_empty():
    assert _ut_key_from_csv_row(_row(model="480691", color="", size="M")) == ""


def test_missing_size_returns_empty():
    assert _ut_key_from_csv_row(_row(model="480691", color="Blue", size="")) == ""


def test_category_column_without_star_also_read():
    r = {"Category": "15687", "C:Model": "480691", "C:Color": "Blue", "C:Size": "M"}
    assert _ut_key_from_csv_row(r) == "uniqlo_ut:480691:BLUE:M"


# --- resolve_csv_row / _with_category が UT 行で短絡する (offline: catalog を呼ばない) ---

def test_resolve_csv_row_short_circuits_ut():
    key = resolver_io.resolve_csv_row(_row(model="480691", color="Blue", size="2XL"))
    assert key == "uniqlo_ut:480691:BLUE:2XL"


def test_resolve_csv_row_with_category_ut():
    res = resolver_io.resolve_csv_row_with_category(_row(model="480691", color="Blue", size="2XL"))
    assert res == {"product_id": "uniqlo_ut:480691:BLUE:2XL", "category": ""}


def test_ut_key_matches_group_key_of_sheet_key():
    # シートAI列の KEY と候補側の KEY が group_key で一致する (突合成立)
    from dedupe.key_format import group_key
    sheet_key = "uniqlo_ut:480691:BLUE:2XL"          # ut_key_backfill.py が書く値
    cand = resolver_io.resolve_csv_row(_row(model="480691", color="Blue", size="2XL"))
    assert group_key(cand) == group_key(sheet_key) == "uniqlo_ut:480691:BLUE:2XL"
