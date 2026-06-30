# -*- coding: utf-8 -*-
"""listing_funnel: Summary バケツ表の E列に「対策済ボタン名」を出力する回帰テスト
(2026-06-30 ユーザー指示)。対策ボタン無しバケツ(OVERPRICED等)は空。"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import listing_funnel as lf


def test_remedy_map_keys_are_valid_buckets():
    valid = {"NO_SEARCH", "NO_CLICK", "NO_CONVERT", "OVERPRICED", "NEW_WAIT",
             "RELIST", "RESTOCK", "CULL", "DEAD_SIMPLE"}
    assert set(lf.BUCKET_REMEDY_BUTTON).issubset(valid)
    # ボタン無しバケツは map に入れない (空表示になる)
    for b in ("OVERPRICED", "NEW_WAIT", "DEAD_SIMPLE"):
        assert b not in lf.BUCKET_REMEDY_BUTTON


def test_xlsx_writes_button_name_in_col_E(tmp_path):
    import openpyxl
    p = os.path.join(str(tmp_path), "funnel.xlsx")
    # E列は count 非依存 (BUCKET_REMEDY_BUTTON 由来)。詳細シート生成を避けるため空バケツで検証。
    lf.write_xlsx(p, [], {}, ["summary line"])
    ws = openpyxl.load_workbook(p)["Summary"]
    # バケツ名→E列値 を走査
    e_by_bucket = {}
    for row in ws.iter_rows(values_only=True):
        if row and row[0] in lf.BUCKET_REMEDY_BUTTON or (row and row[0] == "OVERPRICED"):
            e_by_bucket[row[0]] = row[4] if len(row) > 4 else None
    assert e_by_bucket.get("CULL") == lf.BUCKET_REMEDY_BUTTON["CULL"]
    assert e_by_bucket.get("NO_CONVERT") == lf.BUCKET_REMEDY_BUTTON["NO_CONVERT"]
    assert (e_by_bucket.get("OVERPRICED") or "") == ""   # ボタン無し=空
