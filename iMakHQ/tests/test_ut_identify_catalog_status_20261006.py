"""UT 目視: カタログに追加依頼した行の結果を画面に出す / 回答が来たらすぐ戻す / 新しい参考URLで出し直せる (2026-10-06)。

ユーザー「ちゃんと追加されたかどうかが、この画面でわかる様にならないかな？渡した参考URLが違うなら、
別のを探して渡し続けるから」。
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import ut_identify as U  # noqa: E402

URL = "https://jp.mercari.com/item/m1"
SENT = {"decision": "nocat", "at": "2026-10-06T09:00:00", "ref": "https://www.fashion-press.net/news/1"}


def test_answer_brings_row_back_before_7_days():
    today = datetime.datetime(2026, 10, 7)
    assert not U._retry_nocat(SENT, today)                                        # 回答なし → 7日待つ
    assert U._retry_nocat(SENT, today, {"status": "wrong_ref", "at": "2026-10-06T12:00:00"})
    assert not U._retry_nocat(SENT, today, {"status": "added", "at": "2026-10-05T12:00:00"})  # 依頼より前の回答


def test_status_html_and_summary():
    st = {"status": "wrong_ref", "at": "2026-10-06T12:00:00", "note": "記事の柄と違う", "ref_url": SENT["ref"]}
    h = U.status_html(SENT, st)
    assert "参考URLが違った" in h and "記事の柄と違う" in h and "もう一度" in h
    assert "回答待ち" in U.status_html(SENT, None)
    assert U.status_html({"decision": "go"}, st) == ""
    s = U.status_summary({URL: SENT, "u2": dict(SENT)}, {URL: st})
    assert s == {"wrong_ref": 1, "waiting": 1}
    assert "回答待ち <b>1</b>" in U.catalog_summary_html(s)


def test_resend_same_day_with_new_ref_is_written():
    row = {"url": URL, "title": "t", "ref": "https://www.fashion-press.net/news/1"}
    first = U.request_md([row], datetime.date(2026, 10, 6))
    assert URL in first
    assert U.request_md([row], datetime.date(2026, 10, 6), first) == ""            # 同じ参考URL → 書かない
    again = U.request_md([dict(row, ref="https://www.fashion-press.net/news/2")], datetime.date(2026, 10, 6), first)
    assert "news/2" in again


def test_check_in_catalog_reads_db_directly(tmp_path):
    """「追加した」の申告ではなく、DB の行・画像・出品に使えるかを直接見る (ユーザー「不透明」)。"""
    import json as _j
    import sqlite3
    db = str(tmp_path / "p.sqlite")
    con = sqlite3.connect(db)
    con.execute("create table products (category, product_id, name, images, specs)")
    con.execute("insert into products values ('uniqlo_ut','E1','鬼滅 UT', ?, ?)",
                (_j.dumps(["https://image.uniqlo.com/a.jpg"]), _j.dumps({"data_level": "design_listable"})))
    con.execute("insert into products values ('uniqlo_ut','FP1','柄', '[]', ?)",
                (_j.dumps({"data_level": "fp_design", "not_for_listing": True}),))
    con.commit(); con.close()
    ok = U.check_in_catalog("E1", db)
    assert ok["exists"] and ok["listable"] and len(ok["images"]) == 1
    assert "出品に使える" in U.checked_html(ok) and "画像 <b>1枚</b>" in U.checked_html(ok)
    fp = U.check_in_catalog("FP1", db)
    assert not fp["listable"] and "画像がありません" in U.checked_html(fp)
    assert "まだ在りません" in U.checked_html(U.check_in_catalog("NONE", db))
    assert U.check_in_catalog("", db) is None


def test_load_status_missing_file_is_empty(tmp_path):
    assert U.load_status(str(tmp_path / "none.json")) == {}
