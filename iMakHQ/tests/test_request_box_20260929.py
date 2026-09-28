# -*- coding: utf-8 -*-
"""★2026-09-29 別PC (LAPTOP) 用の受け箱。スプシのタブ1枚で依頼と回答をやり取りする。

LAPTOP からは C:/dev/iMak_data が見えないので、requests/ に置いても届かない (9/28 実証)。
ここで見るのは純関数だけ (I/O はスプシ)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from request_box import HEADER, build_row, mark_done, next_id, pending  # noqa: E402


def _rows():
    return [HEADER,
            build_row(1, "監視くん", "ADV", "a.md", "本文A", now="2026-09-29 07:00:00"),
            build_row(2, "監視くん", "ADV", "b.md", "本文B", now="2026-09-29 07:01:00")]


def test_id_is_max_plus_one():
    assert next_id(_rows()) == 3
    assert next_id([HEADER]) == 1


def test_broken_id_does_not_break_numbering():
    rows = _rows()
    rows[1][0] = ""                                   # 途中で壊れても採番は続く
    assert next_id(rows) == 3


def test_pending_is_rows_without_state():
    rows = _rows()
    assert len(pending(rows)) == 2
    done = mark_done(rows, 1, "対応した")
    assert [r[0] for r in pending(done)] == ["2"]
    assert done[1][6] == "処理済" and done[1][8] == "対応した"


def test_mark_done_returns_none_when_id_missing():
    assert mark_done(_rows(), 99) is None


def test_long_body_is_truncated_to_fit_a_cell():
    r = build_row(1, "監視くん", "ADV", "a.md", "あ" * 60000)
    assert len(r[5]) <= 45000 and r[5].endswith("…(以下はファイル)")
