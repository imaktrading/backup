# -*- coding: utf-8 -*-
"""catalog に行は在るが **画像が無い** 件を catalog 依頼に流す回帰テスト (2026-08-09).

経緯:
  2026-08-07 に入れた実在 pre-check が「products に行が在るか」だけを見て
  「catalog は正しい」と判定し、missing_models に書かず viewer_disagreement.log
  (読み手ゼロ) に流していた。しかし viewer の実際の詰まりは **画像が無くて現物と
  照合できない** ことで、行の存在とは別物。人は「該当なし」を押すしかなく、
  その結果 8/7 以降 catalog 依頼が止まって出品が毎回そこで削られていた。

  2026-08-09 実測: 10件処理のうち pokemon_tcg:SM12a-214 / BDK-006 の2件が該当。
  pokemon_tcg 22,018件中 images 空はわずか17件で、その17件を引いていた。

固定する挙動:
  1. 行あり + 画像あり  → 依頼を出さない (viewer 側の食い違い。従来どおり)
  2. 行あり + 画像なし  → **依頼を出す**。理由に「画像が無く目視できない」と書く
  3. 行なし             → 従来どおり依頼を出す
  4. images 列が無い schema → 画像の有無を判定できない。依頼を増やさない側に倒す
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import post_psa_review as p  # noqa: E402


def _seed(tmp_path: Path, with_images_col: bool = True) -> Path:
    db = tmp_path / "products.sqlite"
    conn = sqlite3.connect(str(db))
    if with_images_col:
        conn.execute(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, category TEXT, product_id TEXT,"
            " name TEXT, images TEXT)"
        )
        rows = [
            ("pokemon_tcg", "M3-082", "モクロー", '["https://example.com/a.jpg"]'),
            ("pokemon_tcg", "SM12a-214", "ジラーチGX", "[]"),
            ("pokemon_tcg", "BDK-006", "わるいヘルガー", ""),
        ]
        conn.executemany(
            "INSERT INTO products(category,product_id,name,images) VALUES(?,?,?,?)", rows
        )
    else:
        conn.execute(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, category TEXT, product_id TEXT,"
            " name TEXT)"
        )
        conn.execute(
            "INSERT INTO products(category,product_id,name) VALUES(?,?,?)",
            ("pokemon_tcg", "M3-082", "モクロー"),
        )
    conn.commit()
    conn.close()
    return db


@pytest.fixture()
def paths(tmp_path):
    return {
        "db": _seed(tmp_path),
        "missing": tmp_path / "missing_models.csv",
        "vd": tmp_path / "viewer_disagreement.log",
    }


def _route(rec, paths):
    return p._route_none_to_catalog(
        [rec], missing_path=paths["missing"], trigger_request=False,
        viewer_disagreement_path=paths["vd"], catalog_db=paths["db"],
    )


def _rec(cert, pid):
    return {"cert": cert, "category": "pokemon_tcg", "expected": pid, "choice": "NONE"}


def test_state_distinguishes_missing_image(paths):
    st = p._catalog_pid_state
    assert st("pokemon_tcg", "M3-082", db_path=paths["db"]) is p._PID_OK
    assert st("pokemon_tcg", "SM12a-214", db_path=paths["db"]) is p._PID_NO_IMAGE, \
        "images='[]' を『在る』扱いしている (依頼が止まる)"
    assert st("pokemon_tcg", "BDK-006", db_path=paths["db"]) is p._PID_NO_IMAGE
    assert st("pokemon_tcg", "NOPE-999", db_path=paths["db"]) is p._PID_MISSING


def test_no_image_is_routed_to_catalog(paths):
    written = _route(_rec("140936782", "SM12a-214"), paths)
    assert written == 1, "画像欠が catalog 依頼に流れていない (8/7 の pre-check 事故の再発)"
    body = paths["missing"].read_text(encoding="utf-8")
    assert "SM12a-214" in body
    assert "画像" in body, "依頼書に『画像が無い』という理由が書かれていない"


def test_row_with_image_is_not_routed(paths):
    written = _route(_rec("154543135", "M3-082"), paths)
    assert written == 0, "画像が在る = viewer 側の食い違い。catalog に依頼を出さないこと"
    assert paths["vd"].exists() and "M3-082" in paths["vd"].read_text(encoding="utf-8")


def test_absent_row_still_routed(paths):
    assert _route(_rec("999000111", "NOPE-999"), paths) == 1


def test_schema_without_images_column_does_not_add_requests(tmp_path):
    db = _seed(tmp_path, with_images_col=False)
    assert p._catalog_pid_state("pokemon_tcg", "M3-082", db_path=db) is p._PID_OK, \
        "images 列が無い schema で判定不能→依頼を量産してはいけない"


# ===== 2026-08-10 撤回: `_dummy` を「画像なし」扱いにした判定は誤りだった =====
# `_dummy` は bandai のファイル名規則で、中身は実画像 (Advisor が実取得して確認。
# 4枚ともバイト数が違う = 共通 placeholder ではない)。そのまま入れていれば dragonball
# 5,577件のうち 2,750件 (49.3%) を目視対象から外していた。
# 教訓: ファイル名パターンだけで中身を判定しない (URL を開いて確かめる)。


def test_dummy_filename_is_not_treated_as_missing_image():
    """ファイル名に `_dummy` が入っていても画像あり扱いのままであること (再発防止)。"""
    import sqlite3
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    db = d / "products.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, category TEXT,"
                 " product_id TEXT, name TEXT, images TEXT)")
    conn.execute("INSERT INTO products(category,product_id,name,images) VALUES(?,?,?,?)",
                 ("dragonball_scg", "FB01-071_PARA", "孫悟飯:少年期",
                  '["https://files.bandai-tcg-plus.com/card_image/DBFW-JA/FB01/'
                  'JP_FW_FB01-071_Leader_F_PARA_dummy.png"]'))
    conn.commit(); conn.close()
    assert p._catalog_pid_state("dragonball_scg", "FB01-071_PARA", db_path=db) is p._PID_OK,         "`_dummy` を placeholder と誤判定している (dragonball の 49.3% を目視から外す事故)"
    assert not hasattr(p, "_all_images_are_dummy"),         "撤回した判定関数が復活している"
