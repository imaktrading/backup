# -*- coding: utf-8 -*-
"""psa_age_level_delete_csv: PSA判定 + Revise CSV(DeletedField=C:Age Level) 回帰テスト
(2026-06-29 依頼① CPSC対応)。"""
import csv
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import psa_age_level_delete_csv as m


def test_is_psa_matches_10_and_9():
    assert m.is_psa("PSA 10 One Piece OP09-062")
    assert m.is_psa("One Piece OP09 #022 PSA10 GEM MT")
    assert m.is_psa("Pokemon Charizard PSA 9")
    assert not m.is_psa("One Piece OP09 raw card")
    assert not m.is_psa("Tomica No.47 Nissan")
    assert not m.is_psa("")


def test_select_failclosed_and_filter():
    rows = [
        {"Item number": "1", "Title": "PSA 10 Luffy", "Available quantity": "1"},
        {"Item number": "", "Title": "PSA 10 NoID", "Available quantity": "1"},   # itemID欠落=除外
        {"Item number": "3", "Title": "raw card", "Available quantity": "1"},      # 非PSA=除外
        {"Item number": "4", "Title": "PSA 9 Pikachu", "Available quantity": "0"},
    ]
    got = m.select_targets(rows, test=False)
    assert [t[0] for t in got] == ["1", "4"]


def test_select_test_prefers_instock():
    rows = [
        {"Item number": "10", "Title": "PSA 10 oos", "Available quantity": "0"},
        {"Item number": "11", "Title": "PSA 10 instock", "Available quantity": "2"},
    ]
    got = m.select_targets(rows, test=True)
    assert len(got) == 1 and got[0][0] == "11"   # 在庫あり優先


def test_write_csv_shape(tmp_path):
    p = os.path.join(str(tmp_path), "out.csv")
    m.write_csv([("358386838040", "PSA 10 Luffy", "1")], p)
    rows = list(csv.reader(open(p, encoding="utf-8")))
    assert rows[0] == m.HEADER
    assert rows[1] == ["Revise", "358386838040", "C:Age Level"]
