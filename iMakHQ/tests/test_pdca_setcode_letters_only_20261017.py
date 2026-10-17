# -*- coding: utf-8 -*-
"""B-20261017-012: CLF-016 (英字-番号) も候補に取り、画像が入った行を発行前の見直しで閉じる。"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import pdca_store as P   # noqa: E402


def test_letters_only_setcode_is_candidate():
    ids = P.candidate_ids("PSA10-152908476 CLF-016 | (画像なし) | pokemon_tcg")["ids"]
    assert "CLF-016" in ids
    assert "CLF-016_p1" in P.candidate_ids("x CLF-016_p1 y")["ids"]
    assert "152908476" not in " ".join(ids[1:])          # 鑑定番号は拾わない


def test_images_row_closes_when_catalog_has_images(tmp_path):
    db = tmp_path / "c.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE products (category TEXT, product_id TEXT, alias_of TEXT, images TEXT, name TEXT)")
    con.execute("INSERT INTO products VALUES ('pokemon_tcg','CLF-016','', '[\"https://x/1.jpg\"]', 'x')")
    con.commit(); con.close()
    verify = P.make_pre_emit_verifier(str(db), classify_fn=lambda *a: {}, certs_dir=str(tmp_path))
    row = {"finding_type": "catalog_gap", "category": "pokemon_tcg", "item_id": "PSA10-152908476",
           "target_field": "images", "identity": "CLF-016 | (画像なし) | pokemon_tcg", "evidence": ""}
    assert verify(row) is True
