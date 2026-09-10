# -*- coding: utf-8 -*-
"""原産国が複数国の UT/GU は countriesOfOrigin を配列のまま持つ (2026-09-09 HQ回答).

回答書 `requests/2026-09-09_ut_country_and_english_decisions_response.md` §1:
eBay の Country of Origin は SINGLE (1つしか選べない) なので Item Specifics は空欄にし、
**catalog は公式の生値 (国コードの配列) をそのまま持つ**。出品くんが説明文
(`China or Vietnam` 等) を組み立てる時の元データになるため、1つに丸めてはいけない。

`scrapers/uniqlo_ut_enrich.py` / `scrapers/uniqlo_ut_discover.py` はどちらも
`[x.get("code") for x in countriesOfOrigin]` の形でリストのまま `specs.countries_of_origin`
に入れている。丸めていないことを実データで固定する。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import api  # noqa: E402


def _rows():
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT product_id, specs FROM products WHERE category IN ('uniqlo_ut', 'gu')"
    ).fetchall()
    db.close()
    return rows


def test_multi_country_rows_keep_a_list_of_codes():
    """2か国以上の行は list[str] で持つ (単一文字列に丸めていない)."""
    multi = []
    for r in _rows():
        s = json.loads(r["specs"] or "{}")
        coo = s.get("countries_of_origin")
        if coo and len(coo) > 1:
            multi.append((r["product_id"], coo))
    assert multi, "2か国以上の実データが無い (母集団が変わっていないか確認)"
    for pid, coo in multi:
        assert isinstance(coo, list), f"{pid}: countries_of_origin が list でない: {coo!r}"
        assert len(coo) == len(set(coo)), f"{pid}: 重複コードが入っている: {coo!r}"
        for code in coo:
            assert isinstance(code, str) and 1 <= len(code) <= 3, \
                f"{pid}: 国コードでない値が混ざっている: {coo!r}"


def test_known_cn_vn_row_is_not_collapsed():
    """依頼書に載っていた E485482-000 が CN/VN 2件のまま (代表実例の固定)."""
    for r in _rows():
        if r["product_id"] == "E485482-000":
            s = json.loads(r["specs"] or "{}")
            assert s.get("countries_of_origin") == ["CN", "VN"]
            return
    import pytest
    pytest.skip("E485482-000 が catalog に無い (廃盤で削除された等)")
