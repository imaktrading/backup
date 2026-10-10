"""販売実績の利益を正しく読む (2026-10-11)。

実害: 販売実績シートは赤字を「▲¥3,728」と書くが、money() が読めず 0 にしていた。
またキャンセルの注文 (¥13,453) も売れた件数・利益に入れていた。
10月の利益が ¥69,422 と出たが、正しくは ¥52,241 だった。
"""
import datetime
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import shelf_roi as R


def test_赤字の印を負に読む():
    assert R.money("▲¥3,728") == -3728
    assert R.money("△1,000") == -1000
    assert R.money("−500") == -500
    assert R.money("-$4.06") == -4.06
    assert R.money("¥10,053") == 10053


def _row(date, profit, state, cat="TCG"):
    r = [""] * 26
    r[1], r[4], r[6], r[15], r[17], r[25] = "820000000000", date, "100", profit, cat, state
    return r


def test_キャンセルは数えず赤字は引く():
    rows = [["h"] * 26,
            _row("2026/10/03", "¥13,453", "キャンセル"),
            _row("2026/10/07", "¥38,371", "未発送"),
            _row("2026/10/09", "▲¥3,728", "未発送")]
    out = R.sales_by_category(rows, datetime.date(2026, 10, 1))
    assert out["TCG"]["n"] == 2
    assert out["TCG"]["profit"] == 38371 - 3728
