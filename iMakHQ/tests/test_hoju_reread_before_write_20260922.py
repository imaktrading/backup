"""補URL③: 書く直前にシートを読み直し、書いた後に読み返して確かめる (2026-09-22)。
画面を開く前の古い内容で書いていたため、目視の間に同じ行が書き換わると書込が消え、
同じ候補が何度も出ていた (820133533285)。"""
import os

SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools",
                        "psa_hoju_fill.py"), encoding="utf-8").read()


def test_reread_happens_before_planning():
    i = SRC.index("_fresh = _read_high()")
    j = SRC.index("aux_writeback, added_total, dropped, replaced = plan_aux_writeback(")
    assert i < j and "vals = _fresh" in SRC[i:j]


def test_moved_rows_are_skipped_not_written():
    # ★2026-09-27: 全部止めるのではなく、変わった行だけ飛ばす (test_hoju_moved_row_skip_20260927)
    i = SRC.index("_moved_idx = moved_target_indices(item_targets, _fresh)")
    assert "confirmed = {i: u for i, u in confirmed.items() if i not in _moved_idx}" in SRC[i:i + 900]


def test_read_back_after_write():
    i = SRC.index("written = write_aux_urls(aux_writeback)")
    assert "_after = _read_high()" in SRC[i:i + 1200]
