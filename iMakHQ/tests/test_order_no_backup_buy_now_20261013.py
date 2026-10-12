# -*- coding: utf-8 -*-
"""予備の仕入元 (補URL) が無い仕入れ待ちは「待たずにすぐ買う」と出す (2026-10-13)。

売れた後は買い手キャンセルに備えて少し置いてから仕入れる。その間に唯一の仕入元が売れた
(バリヤード CLK 013/032・820209548828・補URL 0本 → どこにも在庫なし)。
"""
import os
import sys

_T = os.path.join(os.path.dirname(__file__), "..", "tools")
sys.path.insert(0, _T)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "console"))
import order_purchase_sync as O  # noqa: E402
import sheet_io  # noqa: E402


def _row(iid, aux):
    r = [""] * (sheet_io.PRODUCT_COL_AUX_START + sheet_io.PRODUCT_AUX_MAX)
    r[0], r[1] = "https://jp.mercari.com/item/m89162783214", iid
    for k, u in enumerate(aux):
        r[sheet_io.PRODUCT_COL_AUX_START + k] = u
    return r


def test_backup_counts():
    rows = [["h"], _row("820209548828", []), _row("111", ["https://a", "https://b"])]
    assert O.backup_counts(rows, ["820209548828", "111", "999"]) == {"820209548828": 0, "111": 2, "999": None}


def test_console_lists_only_zero_backup():
    import server
    st = {"waiting": 3, "items": [{"title": "A", "ship_by": "2026/10/21", "backups": 0},
                                  {"title": "B", "ship_by": "", "backups": 2},
                                  {"title": "C", "ship_by": "", "backups": None}]}
    assert server.order_job_info(st)["no_backup"] == [{"title": "A", "ship_by": "2026/10/21"}]
