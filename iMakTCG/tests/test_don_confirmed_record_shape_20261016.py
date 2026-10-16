# -*- coding: utf-8 -*-
"""2026-10-16 B-20261016-007: 目視で確定した DON!! (cert 158257739・DON-EN-ANNIV2-001) が Type 空で落ちていた。
api.lookup の生の行を lookup_don と同じ形 (_to_legacy_dict) に直してから流す。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_confirmed_branch_converts_raw_row():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "psa_to_csv.py"),
               encoding="utf-8").read()
    i = src.index('_don_hit = confirmed_catalog_record(cert_number, "one_piece_tcg")')
    block = src[i:i + 900]
    assert "_to_legacy_dict(_don_hit)" in block and "Type=" in block


def test_legacy_dict_has_type_from_card_type_ebay():
    import psa_to_csv as P
    d = P.catalog_psa._to_legacy_dict({"product_id": "DON-X-001", "specs": {"card_type_ebay": "DON!! Card"}})
    assert d["type_en"] == "DON!! Card" and d["card_id"] == "DON-X-001"
