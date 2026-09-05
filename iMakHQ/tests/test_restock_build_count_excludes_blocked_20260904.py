# -*- coding: utf-8 -*-
"""②のヒントは「本当に出る件数」を出す (2026-09-04 ユーザー指摘)。

> ヒントテキストでは7件やけど (実際は5件しか CSV にならない)

RESTOCK確定タブの「まだ実行済でない行」をそのまま数えていたが、
**cert# が引けない行は生成できない**。実測でその差は2件だった:
  ・B列=9999 の見送り (Arceus V)
  ・商品管理シートに その itemID の行が無い分 (CULL が B列を消した後 等)
押す前に「本当に何件出るか」が分かるよう、引けない分は blocked として分ける。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOLS = os.path.join(_ROOT, "iMakHQ", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import psa_restock_build as RB                                 # noqa: E402

HDR = ["itemID", "card_no", "title", "最安チャネル", "最安¥", "eBay現$", "V8判定",
       "確認済仕入URL", "ebay_url", "確証日", "RESTOCK状態", "状態確認日"]


def _row(iid, status=""):
    r = [""] * len(HDR)
    r[0] = iid
    r[4] = "12000"
    r[10] = status
    return r


ROWS = [HDR, _row("1"), _row("2"), _row("3"), _row("9", "実行済")]


def test_rows_without_a_cert_are_not_counted_as_actionable():
    """cert が引ける2件だけを『CSVにできる』と言う。"""
    got = RB.count_workload(ROWS, itemid_to_cert={"1": "111", "2": "222"})
    assert got["actionable"] == 2
    assert got["blocked"] == 1
    assert got["done"] == 1
    assert got["total"] == 4


def test_the_blocked_count_is_reported_not_hidden():
    """黙って減らさない。押す前に理由が分かるように出す。"""
    got = RB.count_workload(ROWS, itemid_to_cert={})
    assert got["actionable"] == 0 and got["blocked"] == 3


def test_the_panel_shows_the_blocked_count():
    import io as _io
    s = _io.open(os.path.join(_ROOT, "iMakHQ", "control_panel.py"),
                 encoding="utf-8").read()
    i = s.index("rb_txt = self.todo_line")   # ★2026-09-06 文言統一
    seg = s[i:i + 900]
    assert 'rb.get("blocked")' in seg, "ヒントに出していない"
    assert "生成できない" in seg


def test_counts_match_what_the_generator_will_do():
    """数え方と本体の判定を二重実装しない (同じ純関数を通す)。"""
    pending, done = RB._pending_from_confirmed_rows(ROWS)
    got = RB.count_workload(ROWS, itemid_to_cert={"1": "111", "2": "222"})
    assert got["done"] == done
    assert got["actionable"] + got["blocked"] == len(pending)

# ── ③ も同じ (終了済は押しても動かない) ─────────────────────────
def test_step3_separates_ended():
    import psa_restock_writeback as RW
    rows = [["itemID", "RESTOCK状態"],
            ["1", "実行済(qty復活)"],
            ["2", ""],
            ["3", "終了済(reviseでは戻せない)"],
            ["4", "入稿待ち(qty=0)"]]
    todo, done, ended = RW.pending_rows_from_confirmed(rows)
    assert (todo, done, ended) == (2, 1, 1)
    got = RW.count_workload(rows, itemid_to_cert={"2": "a", "4": "b"})
    assert got["actionable"] == 2 and got["ended"] == 1 and got["total"] == 4
    # cert が引けない行は ③でも青にしない (押しても永久に減らない)
    got2 = RW.count_workload(rows, itemid_to_cert={"2": "a"})
    assert got2["actionable"] == 1 and got2["blocked"] == 1


def test_step2_also_skips_ended():
    """②も終了済は作らない (作っても revise で戻せない)。"""
    rows = [["itemID", "最安¥", "RESTOCK状態"],
            ["1", "1000", "終了済(reviseでは戻せない)"],
            ["2", "2000", ""]]
    got = RB.count_workload(rows, itemid_to_cert={"1": "a", "2": "b"})
    assert got["actionable"] == 1 and got["done"] == 1


def test_panel_shows_the_ended_count_on_step3():
    import io as _io
    s = _io.open(os.path.join(_ROOT, "iMakHQ", "control_panel.py"),
                 encoding="utf-8").read()
    i = s.index('rw_txt = (self.todo_line("restock_wb"')   # ★2026-09-06 文言統一
    assert 'rw.get("ended")' in s[i:i + 700], "③のヒントに終了済を出していない"
