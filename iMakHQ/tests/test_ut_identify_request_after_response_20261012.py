# -*- coding: utf-8 -*-
"""回答済みの依頼書に足さない (B-20261012-009)。

10/12 の ut_not_in_catalog.md に _response.md が付いた後、17:34 の10件が同じファイルに足され、
置き場では済んだ扱いで配られなかった。回答済みなら _2 の新しい依頼書に書く。
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import ut_identify as U  # noqa: E402

D = datetime.date(2026, 10, 12)


def test_no_response_appends_to_same_day(tmp_path):
    (tmp_path / "2026-10-12_ut_not_in_catalog.md").write_text("x", encoding="utf-8")
    assert os.path.basename(U.request_path(str(tmp_path), D)) == "2026-10-12_ut_not_in_catalog.md"


def test_answered_goes_to_new_file(tmp_path):
    (tmp_path / "2026-10-12_ut_not_in_catalog.md").write_text("x", encoding="utf-8")
    (tmp_path / "2026-10-12_ut_not_in_catalog_response.md").write_text("y", encoding="utf-8")
    assert os.path.basename(U.request_path(str(tmp_path), D)) == "2026-10-12_ut_not_in_catalog_2.md"


def test_second_also_answered_goes_to_third(tmp_path):
    for n in ("", "_2"):
        (tmp_path / f"2026-10-12_ut_not_in_catalog{n}.md").write_text("x", encoding="utf-8")
        (tmp_path / f"2026-10-12_ut_not_in_catalog{n}_processed.md").write_text("y", encoding="utf-8")
    assert os.path.basename(U.request_path(str(tmp_path), D)) == "2026-10-12_ut_not_in_catalog_3.md"


def test_answer_on_second_does_not_close_first(tmp_path):
    (tmp_path / "2026-10-12_ut_not_in_catalog.md").write_text("x", encoding="utf-8")
    (tmp_path / "2026-10-12_ut_not_in_catalog_2_response.md").write_text("y", encoding="utf-8")
    assert os.path.basename(U.request_path(str(tmp_path), D)) == "2026-10-12_ut_not_in_catalog.md"
