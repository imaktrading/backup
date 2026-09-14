# -*- coding: utf-8 -*-
"""UT 補URL / 再仕入れ: PSA 補URL③ と同じ並び順 (2026-09-15)。

ユーザー「PSAと同じように動いてるねんな？」→ 並び順だけ違う (行の順) と答え →「そうしとこ」。
補充 (補0〜3本) は 補が少ない順 → ウォッチ多い順 / 入れ替え (補4〜5本)・再仕入れは ウォッチ多い順。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import sheet_io  # noqa: E402
import ut_hoju_fill as U  # noqa: E402

TITLE = "One Piece Luffy Anime Graphic T-Shirt UNIQLO UT Black US L (JP XL) NWT"


def _row(iid, aux=0, sold=""):
    r = [""] * 45
    r[0] = f"https://jp.mercari.com/item/m{iid}"
    r[sheet_io.PRODUCT_COL_ITEMID] = iid
    r[2] = TITLE
    r[3] = sold
    r[sheet_io.PRODUCT_COL_CATEGORY] = U.CATEGORY
    for k in range(aux):
        r[sheet_io.PRODUCT_COL_AUX_START + k] = f"https://jp.mercari.com/item/m{iid}{k}"
    return r


def _ids(rows, **kw):
    return [t["itemID"] for t in U.select_targets([[""] * 45] + rows, **kw)]


def test_thin_backups_first_then_watch():
    rows = [_row("111", aux=1), _row("222", aux=1), _row("333", aux=0)]
    assert _ids(rows, max_backups=4, watch={"222": 9, "111": 1}) == ["333", "222", "111"]


def test_swap_and_restock_order_by_watch_only():
    rows = [_row("444", aux=4), _row("555", aux=5)]
    assert _ids(rows, min_backups=4, max_backups=6, watch={"555": 10}) == ["555", "444"]
    sold = [_row("666", sold="売り切れ"), _row("777", sold="売り切れ")]
    assert _ids(sold, sold_out=True, watch={"777": 3}) == ["777", "666"]


def test_no_watch_keeps_row_order():
    rows = [_row("111", aux=1), _row("333", aux=0)]
    assert _ids(rows, max_backups=4) == ["111", "333"]
    assert _ids(rows, max_backups=4, watch={}) == ["111", "333"]


def test_search_and_both_screens_pass_watch():
    src = open(U.__file__, encoding="utf-8").read()
    assert src.count("watch=load_watch()") == 3
    assert "for iid, c in cache.items():" not in src.split("def restore_qty")[0].split("def confirm")[1]
