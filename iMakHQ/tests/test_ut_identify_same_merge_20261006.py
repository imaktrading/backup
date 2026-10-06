"""UT 目視: 同じシャツが写真違いで何件も出る → 人が「同じ物」を押してカタログにまとめてもらう (案A・2026-10-06 ユーザー確定)。"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import ut_identify as U  # noqa: E402


def test_parse_merges_needs_rep_or_two():
    res = U.parse_result({"merges": [{"rep": "E1", "same": ["FP-02", "FP-08", "E1"]},
                                     {"rep": "", "same": ["A"]},          # 1件だけ・本体なし → 捨てる
                                     {"rep": "", "same": ["B", "C"]}, "x"]})
    assert res["merges"] == [{"rep": "E1", "same": ["FP-02", "FP-08"]}, {"rep": "", "same": ["B", "C"]}]


def test_write_merge_inputs_appends_once(tmp_path):
    m = [{"rep": "E1", "same": ["FP-02"]}]
    assert U.write_merge_inputs(m, str(tmp_path), now="t") == 1
    assert U.write_merge_inputs(m, str(tmp_path), now="t") == 0
    data = json.loads((tmp_path / "ut_merge_input.json").read_text(encoding="utf-8"))
    assert data == [{"rep": "E1", "same": ["FP-02"], "at": "t"}]


def test_alias_rows_are_not_candidates(tmp_path):
    db = tmp_path / "p.sqlite"
    con = sqlite3.connect(db)
    con.execute("create table products (product_id, name, specs, images, category, source, alias_of)")
    sp = json.dumps({"data_level": "design_listable", "collab": "X"})
    con.execute("insert into products values ('E1','a',?, '[]','uniqlo_ut','', null)", (sp,))
    con.execute("insert into products values ('FP-02','b',?, '[]','uniqlo_ut','', 'E1')", (sp,))
    con.commit()
    con.close()
    assert [p["pid"] for p in U.load_catalog(str(db))] == ["E1"]
