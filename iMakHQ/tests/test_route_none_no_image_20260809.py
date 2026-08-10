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


# ===== dummy 画像 (2026-08-09 dragonball) =====
# dragonball は images 空が 0件なのに目視できない。中身が
# `JP_FW_FB07-097_Leader_F_PARA_dummy_s1.png` のようなダミー画像で、
# 「画像がある」と見なすと毎回 目視枠を食う (dragonball 5,577件中 2,750件 = 49% が該当)。

def test_all_dummy_images_count_as_no_image():
    assert p._all_images_are_dummy(
        '["https://files.bandai-tcg-plus.com/card_image/DBFW-JA/FB01/'
        'JP_FW_FB01-071_Leader_F_PARA_dummy.png"]') is True


def test_one_real_image_is_enough():
    """1枚でも実画像が在れば目視できる → 依頼を出さない (量産しない)。"""
    assert p._all_images_are_dummy(
        '["https://x/JP_FW_FB07-097_Leader_F_dummy_s.png",'
        ' "https://www.dbs-cardgame.com/fw/images/cards/card/jp/FB07-097_f_p1.webp"]') is False


def test_non_url_image_entry_is_not_treated_as_dummy():
    """ローカルパス等 URL でない値は判定不能 → 画像あり側に倒す (fail-closed)。"""
    assert p._all_images_are_dummy(
        '["C:/dev/iMak_data/catalog/_don_images/DON-BASIC-001.png"]') is False
    assert p._all_images_are_dummy("") is False
