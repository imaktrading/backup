"""毎朝の PDCA メールの数字 (2026-10-11)。ユーザー「正確じゃないと意味ない」。

- キャンセルは数えない / ▲ は赤字 / 仕入済・仕入原価・送料がそろった行だけ確定
- 出品の動きは US だけ数える (ミラーは親に付いてくる)
"""
import datetime as dt
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import pdca_daily_mail as P


def _r(date, profit, state="発送済", bought="TRUE", cost="5000", ship="1060", title="PSA 10 X"):
    r = [""] * 26
    r[1], r[2], r[4], r[6], r[12], r[14], r[15], r[21], r[25] = (
        "820", title, date, "100", cost, ship, profit, bought, state)
    return r


def test_キャンセル除外_赤字_確定の判定():
    rows = [["h"] * 26,
            _r("2026/10/03", "¥13,453", state="キャンセル"),
            _r("2026/10/03", "¥4,066"),
            _r("2026/10/09", "▲¥3,728", ship=""),
            _r("2026/10/10", "¥10,053", bought="FALSE", cost="", ship="")]
    s = P.sales_rows(rows)
    assert len(s) == 3
    assert [x["confirmed"] for x in s] == [True, False, False]
    assert s[1]["profit"] == -3728
    assert s[2]["missing"] == ["仕入れが済んでいない", "仕入原価が空", "送料が空"]


def test_今月の進捗():
    rows = [["h"] * 26,
            _r("2026/09/05", "¥3,000"),
            _r("2026/10/03", "¥4,000"),
            _r("2026/10/10", "¥10,000", ship="")]
    ms = P.month_summary(P.sales_rows(rows), dt.date(2026, 10, 11), 100000)
    assert ms["profit"] == 14000 and ms["fixed"] == 4000 and ms["tmp"] == 10000
    assert ms["n"] == 2 and ms["elapsed"] == 10 and ms["remain"] == 21
    assert ms["prev_same_n"] == 1 and ms["prev_profit"] == 3000
    assert len(ms["yesterday"]) == 1


def _l(site, start, end=None, qty="1", title="PSA 10 X", iid="1"):
    return {"Listing site": site, "Start date": start, "End date": end or "",
            "Available quantity": qty, "Title": title, "Item number": iid}


def test_出品の動きは_US_だけ():
    act = [_l("US", "Oct-09-26 01:00:00 PDT", iid="1"), _l("UK", "Oct-09-26 01:00:00 PDT", iid="2"),
           _l("US", "Oct-02-26 01:00:00 PDT", iid="3", qty="0")]
    ina = [_l("US", "Sep-01-26 01:00:00 PDT", "Oct-09-26 02:00:00 PDT", iid="4"),
           _l("US", "Sep-01-26 01:00:00 PDT", "Oct-09-26 02:00:00 PDT", iid="5"),
           _l("CA", "Sep-01-26 01:00:00 PDT", "Oct-09-26 02:00:00 PDT", iid="6")]
    mv = P.listing_moves(act, ina, dt.date(2026, 10, 9))
    assert mv["new"] == 1 and mv["ended"] == 2 and mv["net"] == -1
    assert mv["new_month"] == 2 and mv["live"] == 1


def test_バリエーションは1出品として数える():
    # Tシャツはサイズごとに1行。売り切れのサイズ (数量0) が混ざっても1出品
    act = [_l("US", "Jun-01-26 01:00:00 PDT", iid="9", qty="1"),
           _l("US", "Jun-01-26 01:00:00 PDT", iid="9", qty="0"),
           _l("US", "Jun-01-26 01:00:00 PDT", iid="9", qty="2"),
           _l("US", "Jun-01-26 01:00:00 PDT", iid="8", qty="0"),
           _l("US", "Jun-01-26 01:00:00 PDT", iid="8", qty="0")]
    mv = P.listing_moves(act, [], dt.date(2026, 10, 9))
    assert mv["live"] == 1
