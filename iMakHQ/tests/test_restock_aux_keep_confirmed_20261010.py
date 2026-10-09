# -*- coding: utf-8 -*-
"""再仕入れで確定した仕入元を捨てない (2026-10-10 ユーザー「都度10枚程度確定しているのに何回も出てくる」)。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
sys.path.insert(0, os.path.join(HERE, ".."))
import restock_aux as R  # noqa: E402
import sheet_io  # noqa: E402

H = ["itemID", "card_no", "title", "最安チャネル", "最安¥", "eBay現$", "V8判定", "確認済仕入URL", "ebay_url",
     "確証日", "RESTOCK状態", "状態確認日"]
W = sheet_io.PRODUCT_COL_AUX_START + sheet_io.PRODUCT_AUX_MAX + 2


def prow(iid, a, sold="", aux=(), hold=False):
    r = [""] * max(W, sheet_io.PRODUCT_COL_FLG + 1)
    r[0], r[1], r[3] = a, iid, sold
    for k, u in enumerate(aux):
        r[sheet_io.PRODUCT_COL_AUX_START + k] = u
    if hold:
        r[sheet_io.PRODUCT_COL_FLG] = sheet_io.HOLD_MARK
    return r


def crow(iid, urls, st=""):
    return [iid, "", "", "", "", "", "", " | ".join(urls), "", "2026-10-10", st, ""]


def test_rest_of_confirmed_go_to_empty_aux_slots():
    pv = [["h"], prow("1", "u1", aux=["x1"])]
    plan, exp, added, owned = R.plan_aux([H, crow("1", ["u1", "u2", "u3"], "実行済(qty復活)")], pv, R.owner_map(pv))
    assert plan == {2: ["x1", "u2", "u3", "", ""]} and exp == {2: "1"} and added == 2


def test_first_url_is_never_put_in_aux_and_full_aux_unchanged():
    pv = [["h"], prow("1", "old", sold="○", aux=["a", "b", "c", "d", "e"])]
    plan, _, added, _ = R.plan_aux([H, crow("1", ["u1", "u2"])], pv, R.owner_map(pv))
    assert plan == {} and added == 0


def test_url_used_by_other_listing_or_dead_is_skipped():
    pv = [["h"], prow("1", "u1"), prow("2", "u2")]
    plan, _, added, owned = R.plan_aux([H, crow("1", ["u1", "u2", "u3", "u4"])], pv, R.owner_map(pv),
                                       dead={"u3"})
    assert plan == {2: ["u4", "", "", "", ""]} and owned == 1 and added == 1


def test_hold_and_ended_rows_untouched():
    pv = [["h"], prow("1", "u1", hold=True), prow("2", "v1")]
    rows = [H, crow("1", ["u1", "u2"]), crow("2", ["v1", "v2"], "終了済(reviseでは戻せない)")]
    assert R.plan_aux(rows, pv, R.owner_map(pv))[0] == {}


def test_dead_first_rotates_to_next_alive_confirmed():
    rows = [H, crow("9", ["dead", "gone", "live", "unknown"], "入稿待ち(qty=0)")]
    out, rotated, dropped = R.rotate_dead_first(rows, {"9": "dead"}, {"gone": False, "live": True})
    assert rotated == ["9"] and dropped == []
    assert out[1][7] == "live" and out[1][10] == ""


def test_dead_first_without_alive_rest_goes_back_to_step1():
    rows = [H, crow("9", ["dead", "unknown"])]
    out, rotated, dropped = R.rotate_dead_first(rows, {"9": "dead"}, {})
    assert dropped == ["9"] and len(out) == 1


def test_done_rows_and_other_supply_not_rotated():
    rows = [H, crow("9", ["dead", "live"], "実行済(qty復活)"), crow("8", ["new", "live2"])]
    out, rotated, dropped = R.rotate_dead_first(rows, {"9": "dead", "8": "oldA"}, {"live": True, "live2": True})
    assert rotated == [] and dropped == [] and out == rows
