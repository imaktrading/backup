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


def test_moved_rows_are_relocated_not_skipped():
    # ★2026-09-27: 全部止めない → 変わった行は itemID で今の行を探し直して書く。見つからない物だけ飛ばす
    i = SRC.index("_moved_idx = moved_target_indices(item_targets, _fresh)")
    blk = SRC[i:i + 1800]
    assert "_sio.find_current_row(item_targets[i][\"itemID\"], _fresh" in blk
    assert "confirmed = {i: u for i, u in confirmed.items() if i not in _lost}" in blk


def test_read_back_after_write():
    i = SRC.index("written = write_aux_urls(aux_writeback,")
    assert "_after = _read_high()" in SRC[i:i + 1200]
