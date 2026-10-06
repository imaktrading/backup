"""UT 目視: 柄の記録 (design_listable) を候補に出し、色はメルカリの表記・キャラ名は人が入れてカタログに渡す (2026-10-06)。

ユーザー: 廃盤 UT もカタログ化して出品 / 色・サイズは仕入元の文字 / キャラ名は A (タイトル) と C (人が入れる)。
カタログ回答: design_listable 1,930行・写真から読んだキャラ名は specs.character_vision (候補)。
"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import ut_identify as U  # noqa: E402


def _db(tmp_path):
    db = str(tmp_path / "p.sqlite")
    con = sqlite3.connect(db)
    con.execute("create table products (category, product_id, name, specs, images, source)")
    rows = [("FP1-01", {"data_level": "design_listable", "collab": "鬼滅", "character_vision": "竈門炭治郎"},
             "fashion_press_design"),
            ("FP1-02", {"data_level": "fp_design", "not_for_listing": True}, "fashion_press_design"),
            ("FP1-03", {"data_level": "design_listable", "not_for_listing": True}, "fashion_press_design")]
    for pid, s, src in rows:
        con.execute("insert into products values ('uniqlo_ut', ?, 'n', ?, ?, ?)",
                    (pid, json.dumps(s, ensure_ascii=False), json.dumps(["https://x/a.jpg"]), src))
    con.commit(); con.close()
    return db


def test_only_design_listable_rows_are_candidates(tmp_path):
    cat = U.load_catalog(_db(tmp_path))
    pids = {p["pid"] for p in cat}
    assert pids == {"FP1-01"}                                   # fp_design / not_for_listing は出さない
    p = cat[0]
    assert p["design"] and p["character_vision"] == "竈門炭治郎"
    html = U._cards_html([p])
    assert "data-design='1'" in html and "竈門炭治郎" in html and "色はメルカリの表記" in html


def test_design_pick_without_color_is_kept_with_char():
    res = U.parse_result({"picks": [{"idx": 3, "pid": "FP1-01", "color": "", "design": True, "char": " 竈門 炭治郎 "},
                                    {"idx": 4, "pid": "E1", "color": ""}]})              # 普通の商品は色が要る
    assert res["picks"] == [{"idx": 3, "pid": "FP1-01", "color": "", "design": True, "char": "竈門 炭治郎"}]


def test_character_inputs_file(tmp_path):
    assert U.write_character_inputs({"FP1-01": "竈門炭治郎"}, str(tmp_path)) == 1
    U.write_character_inputs({"FP1-02": "我妻善逸", "FP1-03": ""}, str(tmp_path))
    got = json.load(open(tmp_path / "ut_character_input.json", encoding="utf-8"))
    assert got == {"FP1-01": "竈門炭治郎", "FP1-02": "我妻善逸"}
    assert U.write_character_inputs({}, str(tmp_path)) == 0
