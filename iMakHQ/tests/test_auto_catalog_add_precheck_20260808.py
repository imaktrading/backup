# -*- coding: utf-8 -*-
"""`auto_catalog_add_request` の catalog 実在 pre-check 回帰テスト (2026-08-08).

依頼書: `C:/dev/iMak_data/hq/requests/2026-08-08_auto_catalog_add_needs_same_precheck.md`

なぜ2箇所に要るのか:
    18b36a2 で `post_psa_review._route_none_to_catalog` に pre-check を入れたが、
    **こちらの watcher が素通し**していたため、既に catalog にあるカードの追加依頼が
    毎日 catalog に届き続けていた。ここは書き手を問わない最終防衛線。

固定する挙動:
  1. Case 1 (post_psa_review 由来) で PID が catalog に実在 → 依頼書を作らず log に残す
  2. Case 1 で PID が未収録 → 従来どおり依頼書を作る
  3. Case 2 (psa_to_csv 由来 `<brand>-<num>`) → 判定不能 → 従来どおり依頼書を作る
  4. DB が読めない → 従来どおり依頼書を作る (fail-closed)
  5. カテゴリ跨ぎでは救わない
  6. 混在バッチ: 実在だけ落ち、未収録は依頼書に載る
  7. `_catalog_has_pid` を **再実装していない** (定義は post_psa_review に SSOT)
  8. skip した行は missing_models.csv からも落ちる (= 毎日同じ log を積まない)
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import auto_catalog_add_request as a  # noqa: E402


# --- fixtures ---------------------------------------------------------------


def _seed_catalog(tmp_path: Path) -> Path:
    db = tmp_path / "products.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE products ("
        "id INTEGER PRIMARY KEY, category TEXT NOT NULL, product_id TEXT NOT NULL,"
        "name TEXT NOT NULL, specs TEXT NOT NULL, source TEXT NOT NULL,"
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    for cat, pid, name in [
        ("one_piece_tcg", "OP07-118", "Sabo"),
        ("pokemon_tcg",   "SM12-112", "Arceus & Dialga & Palkia-GX"),
    ]:
        conn.execute(
            "INSERT INTO products(category,product_id,name,specs,source,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (cat, pid, name, "{}", "seed", "2026-01-01", "2026-01-01"),
        )
    conn.commit()
    conn.close()
    return db


@pytest.fixture()
def vd_log(tmp_path, monkeypatch):
    """viewer_disagreement.log を tmp に逃がす (本番 log を汚さない)."""
    path = tmp_path / "viewer_disagreement.log"
    real = a._load_catalog_probe

    def fake():
        has_pid, _ = real()
        return has_pid, path

    monkeypatch.setattr(a, "_load_catalog_probe", fake)
    return path


def _row(model: str) -> dict:
    return {"model": model, "detected_at": "2026-08-08", "category": "one_piece_tcg"}


CASE1_PRESENT = "cert154233090 ONE PIECE [SABO] #118 (auto候補OP07-118=該当なし 要調査)"
CASE1_ABSENT = "cert999999999 ONE PIECE [X] #999 (auto候補OP99-999=該当なし 要調査)"
CASE2 = "ONE PIECE JAPANESE 3RD ANNIVERSARY SET-118"


# --- 1. 実在 → 落とす -------------------------------------------------------


def test_present_pid_is_dropped_and_logged(tmp_path, vd_log):
    db = _seed_catalog(tmp_path)
    new_by_cat = {"one_piece_tcg": [_row(CASE1_PRESENT)]}
    removed = a._filter_catalog_present(new_by_cat, db_path=db)
    assert removed == 1
    assert "one_piece_tcg" not in new_by_cat, "実在なのに依頼対象に残っている"
    body = vd_log.read_text(encoding="utf-8")
    assert "auto_catalog_add_watcher" in body and "OP07-118" in body


# --- 2. 未収録 → 従来どおり -------------------------------------------------


def test_absent_pid_still_requested(tmp_path, vd_log):
    db = _seed_catalog(tmp_path)
    new_by_cat = {"one_piece_tcg": [_row(CASE1_ABSENT)]}
    assert a._filter_catalog_present(new_by_cat, db_path=db) == 0
    assert len(new_by_cat["one_piece_tcg"]) == 1


# --- 3. Case 2 形式 → 判定不能 → 従来どおり ---------------------------------


def test_psa_to_csv_format_is_undecidable_and_kept(tmp_path, vd_log):
    db = _seed_catalog(tmp_path)
    assert a._extract_expected_pid(CASE2) is None
    new_by_cat = {"one_piece_tcg": [_row(CASE2)]}
    assert a._filter_catalog_present(new_by_cat, db_path=db) == 0
    assert len(new_by_cat["one_piece_tcg"]) == 1


# --- 4. DB が読めない → fail-closed ----------------------------------------


def test_unreadable_db_keeps_everything(tmp_path, vd_log):
    missing = tmp_path / "does_not_exist.sqlite"
    new_by_cat = {"one_piece_tcg": [_row(CASE1_PRESENT)]}
    assert a._filter_catalog_present(new_by_cat, db_path=missing) == 0
    assert len(new_by_cat["one_piece_tcg"]) == 1


def test_probe_unavailable_keeps_everything(monkeypatch):
    monkeypatch.setattr(a, "_load_catalog_probe", lambda: (None, None))
    new_by_cat = {"one_piece_tcg": [_row(CASE1_PRESENT)]}
    assert a._filter_catalog_present(new_by_cat) == 0
    assert len(new_by_cat["one_piece_tcg"]) == 1


# --- 5. カテゴリ跨ぎでは救わない -------------------------------------------


def test_cross_category_pid_is_not_rescued(tmp_path, vd_log):
    """SM12-112 は pokemon_tcg に実在するが、one_piece_tcg 行としては未収録扱い."""
    db = _seed_catalog(tmp_path)
    row = _row("cert1 X (auto候補SM12-112=該当なし 要調査)")
    new_by_cat = {"one_piece_tcg": [row]}
    assert a._filter_catalog_present(new_by_cat, db_path=db) == 0
    assert len(new_by_cat["one_piece_tcg"]) == 1


# --- 6. 混在バッチ ----------------------------------------------------------


def test_mixed_batch_drops_only_present(tmp_path, vd_log):
    db = _seed_catalog(tmp_path)
    new_by_cat = {"one_piece_tcg": [_row(CASE1_PRESENT), _row(CASE1_ABSENT), _row(CASE2)]}
    assert a._filter_catalog_present(new_by_cat, db_path=db) == 1
    kept = [r["model"] for r in new_by_cat["one_piece_tcg"]]
    assert kept == [CASE1_ABSENT, CASE2]


# --- 7. 定義は1本 (再実装していない) ----------------------------------------


def test_catalog_has_pid_is_not_reimplemented():
    src = Path(a.__file__).read_text(encoding="utf-8")
    assert "def _catalog_has_pid" not in src, \
        "判定を2箇所に実装している (post_psa_review が SSOT)"


def test_probe_returns_the_ssot_function():
    has_pid, path = a._load_catalog_probe()
    assert has_pid is not None and has_pid.__name__ == "_catalog_has_pid"
    assert str(path).endswith("viewer_disagreement.log")


# --- 8. missing_models.csv からも落ちる (毎日同じ log を積まない) -----------


def test_present_row_is_also_removed_from_missing_models(tmp_path, vd_log):
    db = _seed_catalog(tmp_path)
    row = _row(CASE1_PRESENT)
    unique = {("one_piece_tcg", CASE1_PRESENT): row,
              ("one_piece_tcg", CASE1_ABSENT): _row(CASE1_ABSENT)}
    new_by_cat = {"one_piece_tcg": [row, unique[("one_piece_tcg", CASE1_ABSENT)]]}
    a._filter_catalog_present(new_by_cat, unique, db_path=db)
    assert ("one_piece_tcg", CASE1_PRESENT) not in unique, \
        "csv に残ると毎日同じ行を再判定して log を積む"
    assert ("one_piece_tcg", CASE1_ABSENT) in unique, "未収録まで消してはいけない"


# --- PID 抽出 ---------------------------------------------------------------


def test_extract_pid_variants():
    assert a._extract_expected_pid(CASE1_PRESENT) == "OP07-118"
    assert a._extract_expected_pid("") is None
    assert a._extract_expected_pid("(auto候補=該当なし)") is None
    assert a._extract_expected_pid("何も無い") is None
