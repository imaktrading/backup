"""tests/test_high_ready_columns - 行ごとコピーで本番 (HIGH) に足りる列を埋める.

2026-08-18 実測 (HIGH の PSA 行 1,310件):
  N (仕入れ価格) 1310/1310 / R (カテゴリ) 1310/1310 が必ず埋まっている
  → 中間スプシが空だと 行ごとコピーした時に落ちるので収集側で埋める
  ★P (CTR) は HIGH 側が `=countif(A:A,A<row>)` の数式。 値を貼ると重複検出が壊れるので**書かない**
"""
from __future__ import annotations

import pytest

from run_harvest_mercari_psa10 import build_sheet_items
from sheet_writer_amazon import (
    COL_CATEGORY, COL_CERT, COL_PRICE, COL_PURCHASE_PRICE, _build_row,
)

pytestmark = pytest.mark.offline

CTR_COL = 16  # P


def _row(**kw):
    base = {"url": "https://jp.mercari.com/item/m1", "title": "t", "price_jpy": 12345}
    base.update(kw)
    return _build_row(base)


def test_purchase_price_defaults_to_price():
    r = _row(fill_high_columns=True)
    assert r[COL_PRICE - 1] == "12345"
    assert r[COL_PURCHASE_PRICE - 1] == "12345"


def test_category_is_written_when_given():
    assert _row(category="TCG")[COL_CATEGORY - 1] == "TCG"


def test_ctr_column_is_never_written():
    """HIGH の P列は数式。 値を書かない."""
    assert _row(fill_high_columns=True, category="TCG")[CTR_COL - 1] == ""


def test_existing_collectors_are_unchanged():
    """フラグを渡さない収集 (Amazon 等) は 従来どおり N/R 空欄."""
    r = _row()
    assert r[COL_PURCHASE_PRICE - 1] == ""
    assert r[COL_CATEGORY - 1] == ""


def test_psa10_rows_are_copy_ready():
    cand = {"url": "https://jp.mercari.com/item/m2", "title": "PSA10 ルフィ",
            "price_jpy": 9800, "vision": {"cert": "123456789"}, "cert_readable": True}
    item = build_sheet_items([cand], [])[0]
    r = _build_row(item)
    assert r[COL_CERT - 1] == "123456789"
    assert r[COL_PURCHASE_PRICE - 1] == "9800"
    assert r[COL_CATEGORY - 1] == "TCG"
    assert r[CTR_COL - 1] == ""


def test_unreadable_rows_also_get_high_columns():
    """I列空欄で入れる行も、 目視で番号を入れたらそのままコピーできる形にする."""
    cand = {"url": "https://jp.mercari.com/item/m3", "title": "PSA10 ナミ",
            "price_jpy": 5000, "vision": {"cert": ""}, "cert_readable": False}
    r = _build_row(build_sheet_items([], [cand])[0])
    assert r[COL_CERT - 1] == ""
    assert r[COL_PURCHASE_PRICE - 1] == "5000"
    assert r[COL_CATEGORY - 1] == "TCG"
