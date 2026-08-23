"""CULL 後のスプシ後始末 (2026-08-24 ユーザー決定・案C)。

B列が埋まっている = 出品済み としてシステムが動くので、取り下げても itemID を残すと
**仕入元が復活しても二度と出品されない** (実測: 361件 End のうち 167件 が残っていた)。

決めたこと:
  - B列は空にする (復活したら出品候補に戻す)
  - Q列に `CULL <日付>` を残す (取り下げた事実を消さない)
  - 2回目は `CULL×2` (在庫切れ中は検索から隠れるので、1回目の低評価は不当かもしれない。
    1回はやり直しの機会を与え、2回繰り返したら諦める)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import cull_writeback as W  # noqa: E402

T = "2026-08-24"


def test_first_cull_stamps_date():
    assert W.next_flag("", T) == "CULL 2026-08-24"
    assert W.next_flag(None, T) == "CULL 2026-08-24"


def test_second_cull_becomes_x2():
    """★1回目 → 2回目で印が変わる (これが「もう出さない」の根拠になる)."""
    assert W.next_flag("CULL 2026-07-01", T) == "CULL×2 2026-08-24"


def test_third_time_does_not_grow():
    """×3 ×4 と増やさない (印は2段階で十分)."""
    assert W.next_flag("CULL×2 2026-08-01", T) == "CULL×2 2026-08-01"


def test_other_flag_is_not_destroyed():
    """他の用途で使われていたら壊さず足す."""
    got = W.next_flag("要確認", T)
    assert "要確認" in got and "CULL 2026-08-24" in got


def test_ended_ids_reads_only_success(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("Line Number,Action,Status,ErrorCode,ItemID\n"
                 "2,End,Success,,111\n"
                 "3,End,Failure,1047,222\n"
                 "4,End,Success,,333\n", encoding="utf-8")
    assert W.ended_ids_from_results([str(p)]) == {"111", "333"}


def test_ended_ids_missing_file_is_ignored():
    assert W.ended_ids_from_results(["C:/no/such/file.csv"]) == set()


def test_flg_column_is_q():
    """Q列(17)を使う。全行空なのを 2026-08-24 に確認済."""
    assert W.FLG_COL == 17
    assert W._col_letter(17) == "Q"
    assert W.ITEM_COL == 2 and W._col_letter(2) == "B"
