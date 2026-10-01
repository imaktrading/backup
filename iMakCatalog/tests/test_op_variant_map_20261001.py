# -*- coding: utf-8 -*-
"""ワンピの版の対応表 — 絵の比べ方と、決めた対応が正しいことの回帰.

依頼: `requests/2026-10-01_onepiece_variant_md5_map_go.md` [IMPLEMENT-GO]
★md5 は使えない (2つの公式が同じ絵を別の大きさで配っている)。
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP = Path("C:/dev/iMak_data/catalog/op_variant_official_map.json")


def _mod():
    spec = importlib.util.spec_from_file_location(
        "_opvar", ROOT / "tools" / "op_variant_image_map.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_set_code_reads_both_bracket_styles():
    m = _mod()
    assert m.set_code("BOOSTER PACK -WINGS OF THE CAPTAIN- [OP-06]") == "OP06"
    assert m.set_code("双璧の覇者【OP-06】") == "OP06"
    assert m.set_code("プロモーションカード") == "PROMO"
    assert m.set_code("Promotion Card") == "PROMO"
    assert m.set_code("") is None


def test_base_strips_the_variant_mark():
    m = _mod()
    assert m._base("OP06-022_p") == "OP06-022"
    assert m._base("OP06-022_p1") == "OP06-022"
    assert m._base("P-106_2") == "P-106"


def test_map_exists_and_known_pair_is_right():
    assert MAP.exists(), "対応表が無い (tools/op_variant_image_map.py を走らせる)"
    d = json.loads(MAP.read_text(encoding="utf-8"))
    assert d["decided"] > 1500, d["decided"]
    # 実測で確かめた1組 (bandai の _p の絵は公式の _p1 と差 0 / _p2 とは 128)
    assert d["map"].get("OP06-022_p") == "OP06-022_p1"
    # 決まらない行は表に入れない (fail-closed)
    assert all(v for v in d["map"].values())


def test_map_only_points_at_official_rows():
    import sqlite3
    d = json.loads(MAP.read_text(encoding="utf-8"))
    c = sqlite3.connect("C:/dev/iMak_data/catalog/products.sqlite", timeout=120)
    try:
        official = {p for (p,) in c.execute(
            "SELECT product_id FROM products WHERE category='one_piece_tcg' "
            "AND source LIKE 'opcg_official%'")}
    finally:
        c.close()
    bad = [v for v in d["map"].values() if v not in official]
    assert not bad, f"公式でない行を指している: {bad[:5]}"
