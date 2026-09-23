"""タブ書込は「全部消してから書く」をやめ、上書きしてから余りを消す (2026-09-24)。
消した直後に PC が落ちるとタブが空になり、次に押すと過去の記録 (RESTOCK確定 等) が消えていた。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import sheet_io as S                                           # noqa: E402

SRC = open(os.path.join(HERE, "..", "tools", "sheet_io.py"), encoding="utf-8").read()


def test_no_clear_before_update():
    body = SRC[SRC.index("def write_rows_to_tab"):SRC.index("def pad_rows")]
    assert "ws.clear()" not in body
    assert body.index("ws.update(") < body.index("ws.batch_clear(")


def test_pad_rows_fills_short_rows():
    assert S.pad_rows([["a", "b", "c"], ["x"]], 3) == [["a", "b", "c"], ["x", "", ""]]


def test_leftover_ranges_cover_old_rows_and_columns():
    assert S.leftover_ranges(2, 2, 1000, 26) == ["A3:Z1000", "C1:Z2"]
    assert S.leftover_ranges(5, 3, 5, 3) == []
