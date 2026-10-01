"""版の数を数える時に language=both の行を外さない (2026-10-01)。

カタログが 9/27〜29 にワンピース等の行を both (日本語版・英語版の両方) にした後、
both を英語版として外していたため EB03-053 (ナミ・版3つ) が「1種類」と数えられ、
名前だけの救済枠から別のカードが目視に出た。
"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import mercari_psa_resource as mp  # noqa: E402


def _db(tmp_path):
    db = str(tmp_path / "p.sqlite")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE products (product_id, name_jp, set_name, images, specs, language, name_en, category)")
    for pid, lang in (("EB03-053", "both"), ("EB03-053_p1", "both"), ("EB03-053_p2", "en"),
                      ("EB03-053_nami_dummy", "ja"), ("OP99-001", "both"), ("OP99-001_x", "en")):
        con.execute("INSERT INTO products VALUES (?,?,?,?,?,?,?,?)",
                    (pid, "ナミ", "", "[]", json.dumps({}), lang, "", "one_piece_tcg"))
    con.commit()
    con.close()
    return db


def test_both_rows_are_japanese_candidates(tmp_path):
    db = _db(tmp_path)
    ids = [v["product_id"] for v in mp._catalog_variants_for_cardno("EB03-053", db, category="one_piece_tcg")]
    assert ids == ["EB03-053", "EB03-053_p1"]          # both は残す / en・dummy は外す


def test_multi_variant_counts_all_languages(tmp_path, monkeypatch):
    db = _db(tmp_path)
    real = mp.catalog_variants_for_cardno
    monkeypatch.setattr(mp, "catalog_variants_for_cardno",
                        lambda cn, **kw: real(cn, _db=db, **kw))
    assert mp._is_multi_variant("EB03-053", "one_piece_tcg", _cache={}) is True
    # 日本語の行が1つでも、en の別の絵があれば複数として数える (候補を出さない側)
    assert mp._is_multi_variant("OP99-001", "one_piece_tcg", _cache={}) is True
