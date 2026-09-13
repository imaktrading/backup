# -*- coding: utf-8 -*-
"""その国でしか売っていない UT は候補に出さない (2026-09-13)。

catalog が各国の公式 API から UT を取れるようになり、**米国にしか無い 37件**
(ディズニー×F1 / PIXAR / NY POP ART / PEACE FOR ALL) が catalog に入った
(`specs.region_only=true`)。

出品くんの仕入れは「メルカリ日本の新品未使用」が前提 ([[ut_catalog_purpose_mercari_nwt]])
なので、日本の店に並んでいない物は国内に新品が出てくる経路が無い。
目視の候補に混ぜると取り違えの元にしかならないので、読み込みの時点で落とす。
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "iMakHQ" / "tools", ROOT / "iMakMercari", ROOT / "iMakeBayAPI"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import ut_identify as U  # noqa: E402


def _db(tmp_path, rows):
    p = tmp_path / "t.sqlite"
    con = sqlite3.connect(p)
    con.execute("create table products (product_id text, category text, name text, "
                "specs text, images text)")
    for pid, specs in rows:
        con.execute("insert into products values (?,?,?,?,?)",
                    (pid, "uniqlo_ut", pid, json.dumps(specs), "[]"))
    con.commit()
    con.close()
    return str(p)


def test_region_only_is_dropped(tmp_path):
    db = _db(tmp_path, [
        ("E481120-000", {"in_stock": False}),
        ("E999999-000", {"in_stock": False, "region_only": True, "region": "us"}),
    ])
    got = {p["pid"] for p in U.load_catalog(db)}
    assert got == {"E481120-000"}


def test_region_flag_alone_does_not_drop(tmp_path):
    """`region` が付いているだけの行は落とさない (日本でも売っている品がある)。"""
    db = _db(tmp_path, [("E481120-000", {"in_stock": False, "region": "us"})])
    assert len(U.load_catalog(db)) == 1


def test_kids_still_dropped(tmp_path):
    db = _db(tmp_path, [("E111111-000", {"in_stock": False, "gender": "KIDS"})])
    assert U.load_catalog(db) == []
