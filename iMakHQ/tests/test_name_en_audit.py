# -*- coding: utf-8 -*-
"""Pokemon name_en 自己整合監査 (name_en_audit) の多数決ロジック。

Durant型 (同一 name_jp で name_en が割れる) を外部Oracle無しで検出する核を守る。
"""
import importlib.util
import os
import sqlite3

_M = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools", "name_en_audit.py"))


def _load():
    spec = importlib.util.spec_from_file_location("name_en_audit_t", _M)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _db(rows):
    """rows: list of (name_jp, name_en, name_en_source, product_id, set_name)."""
    con = sqlite3.connect(":memory:")
    con.execute("""CREATE TABLE products(
        name_jp TEXT, name_en TEXT, name_en_source TEXT, product_id TEXT,
        set_name TEXT, source TEXT)""")
    con.executemany(
        "INSERT INTO products(name_jp,name_en,name_en_source,product_id,set_name,source)"
        " VALUES(?,?,?,?,?,'pokemon_card_jp')", rows)
    return con


def test_majority_minority_split():
    a = _load()
    # ピカチュウ: 多数=Pikachu(3), 少数=Diglett(1) → Diglett が suspect
    con = _db([
        ("ピカチュウ", "Pikachu", "pokeapi_official", "P1", "SetA"),
        ("ピカチュウ", "Pikachu", "pokeapi_official", "P2", "SetB"),
        ("ピカチュウ", "Pikachu", "pokeapi_official", "P3", "SetC"),
        ("ピカチュウ", "Diglett", "pokeapi_official", "X1", "SetD"),
    ])
    groups, suspects = a.audit(con)
    assert groups == 1
    assert len(suspects) == 1
    s = suspects[0]
    assert s["suspect_en"] == "Diglett"
    assert s["majority_en"] == "Pikachu"
    assert s["product_id"] == "X1"


def test_no_conflict_no_suspect():
    a = _load()
    con = _db([
        ("リオル", "Riolu", "pokeapi_official", "R1", "SetA"),
        ("リオル", "Riolu", "pokeapi_official", "R2", "SetB"),
    ])
    groups, suspects = a.audit(con)
    assert groups == 0
    assert suspects == []


def test_confidence_levels():
    a = _load()
    # 多数派>=5 & 少数派<=2 → 高
    con = _db([("A", "Aaa", "s", f"a{i}", "S") for i in range(6)]
              + [("A", "Bbb", "s", "x1", "S")])
    _, suspects = a.audit(con)
    assert suspects[0]["conf"] == "高"
    # 拮抗 (多数派<=少数派) → 低
    con2 = _db([("B", "Bbb", "s", "b1", "S"), ("B", "Ccc", "s", "c1", "S")])
    _, suspects2 = a.audit(con2)
    assert suspects2[0]["conf"].startswith("低")


def test_blank_name_en_excluded():
    a = _load()
    con = _db([
        ("ミュウ", "Mew", "s", "M1", "S"),
        ("ミュウ", "", "s", "M2", "S"),       # 空 name_en は対象外
    ])
    groups, suspects = a.audit(con)
    assert groups == 0
    assert suspects == []
