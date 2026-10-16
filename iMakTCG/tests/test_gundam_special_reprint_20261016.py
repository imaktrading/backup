# -*- coding: utf-8 -*-
"""2026-10-16 B-20261016-010: ガンダム GD05 の SPECIAL 再録 (元の番号 ST01-011 のまま) を、番号だけで GD05-011 に当てて落としていた。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROWS = [("ST01-011_GD05_SP_dummy_EN_260611", "Suletta Mercury"), ("ST04-010_GD05_SP_dummy_EN_260611", "Kira Yamato"),
        ("GD05-011", "Calamity Gundam & Raider Gundam")]


def _lk(cat, pid):
    return {"product_id": pid, "name": "x", "specs": {}}


def test_special_label_picks_the_reprint_row(monkeypatch):
    import psa_to_csv as P
    monkeypatch.setattr(P.catalog_psa, "_to_legacy_dict_gundam", lambda r: {"card_id": r["product_id"]})
    r = P.gundam_special_reprint("GUNDAM JAPANESE GD05-FREEDOM ASCENSION", "011", "SULETTA MERCURY SPECIAL", "SPECIAL",
                                 db_rows=ROWS, lookup_fn=_lk)
    assert r == {"card_id": "ST01-011_GD05_SP_dummy_EN_260611"}


def test_no_special_or_name_mismatch_returns_none():
    import psa_to_csv as P
    b = "GUNDAM JAPANESE GD05-FREEDOM ASCENSION"
    assert P.gundam_special_reprint(b, "011", "SULETTA MERCURY", "", db_rows=ROWS, lookup_fn=_lk) is None      # SPECIAL でない
    assert P.gundam_special_reprint(b, "011", "AMURO RAY SPECIAL", "SPECIAL", db_rows=ROWS, lookup_fn=_lk) is None  # 名前違い
    assert P.gundam_special_reprint(b, "012", "SULETTA MERCURY SPECIAL", "SPECIAL", db_rows=ROWS, lookup_fn=_lk) is None  # 番号違い
