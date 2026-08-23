"""CULL 後のスプシ後始末 (2026-08-24 ユーザー決定・案C)。

B列が埋まっている = 出品済み としてシステムが動くので、取り下げても itemID を残すと
**仕入元が復活しても二度と出品されない** (実測: 361件 End のうち 167件 が残っていた)。

決めたこと:
  - B列は空にする (復活したら出品候補に戻す)
  - Q列に `CULL <日付>` を残す (取り下げた事実を消さない)
  - **回数を数える** `CULL <日付>` → `CULL 2 <日付>` → `CULL 3 <日付>` …
    何回で諦めるかは後からデータを見て決める (印の側で打ち切らない)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import cull_writeback as W  # noqa: E402

T = "2026-08-24"


def test_first_cull_stamps_date():
    assert W.next_flag("", T) == "CULL 2026-08-24"
    assert W.next_flag(None, T) == "CULL 2026-08-24"




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

def test_count_increments_each_time():
    """★1回目は番号なし、以降は 2, 3, 4 … と増える."""
    cur = ""
    got = []
    for d in ("2026-08-24", "2026-09-15", "2026-10-02", "2026-11-08"):
        cur = W.next_flag(cur, d)
        got.append((cur, W.cull_count(cur)))
    assert got[0] == ("CULL 2026-08-24", 1)
    assert got[1] == ("CULL 2 2026-09-15", 2)
    assert got[2] == ("CULL 3 2026-10-02", 3)
    assert got[3] == ("CULL 4 2026-11-08", 4)


def test_year_is_not_read_as_count():
    r"""★`CULL\s*(\d*)` だと `CULL 2026-08-24` の「2026」を回数として読む (実際に踏んだ)。
    番号は日付の手前の1〜3桁に限る."""
    assert W.cull_count("CULL 2026-08-24") == 1
    assert W.cull_count("CULL 2 2026-09-15") == 2


def test_count_zero_when_no_cull():
    assert W.cull_count("") == 0
    assert W.cull_count("要確認") == 0


def test_existing_167_rows_count_as_first():
    """8/24 に書いた 167件 (番号なし) を書き直さずに使えること."""
    assert W.next_flag("CULL 2026-08-24", "2026-09-01") == "CULL 2 2026-09-01"
