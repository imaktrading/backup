"""KEY は目視で確定した版に合わせる (2026-09-22 深堀: 通常版 KEY が84件残っていた)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import key_backfill_live as K  # noqa: E402


def _row(itemid, cert, key, sold=""):
    r = [""] * 40
    r[K.B], r[K.CERT], r[K.KEY], r[K.CAT], r[K.SOLD] = itemid, cert, key, "TCG", sold
    return r


def test_目視の版と違うKEYを拾う():
    vals = [[""] * 40,
            _row("111", "1", "one_piece_tcg:OP01-016"),        # 目視は _p2
            _row("222", "2", "one_piece_tcg:OP11-021_p"),      # 一致 (prefix・大小無視)
            _row("333", "3", "one_piece_tcg:OP02-093", sold="○"),
            _row("9999", "4", "one_piece_tcg:OP02-025")]
    pid = {"1": "OP01-016_p2", "2": "OP11-021_P", "3": "OP02-093_P", "4": "OP02-025_p"}.get
    got = K.find_mismatched(vals, pid)
    assert [t["itemID"] for t in got] == ["111"] and got[0]["old_key"].endswith("OP01-016")


def test_目視の答えが無ければ触らない():
    vals = [[""] * 40, _row("111", "1", "one_piece_tcg:OP01-016")]
    assert K.find_mismatched(vals, lambda c: "") == []


def test_見送り行はKEY空でも対象外():
    vals = [[""] * 40, _row("9999", "1", "")]
    assert K.find_targets(vals) == []
