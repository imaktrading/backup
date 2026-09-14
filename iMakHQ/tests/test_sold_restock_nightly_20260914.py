# -*- coding: utf-8 -*-
"""売れた分を補充を夜間に回す (2026-09-14)。

ユーザー「目視とかないなら、夜間自動でいいのでは？」→「うん」。
- 注文は注文 API から (レポートは週1の手 DL なので待たない)
- 発送より前の巡回の値は使わない (その注文のために買った仕入元をまだ在庫ありと見ていることがある)
- 1回に送る数に上限、送った後は読み直して在庫1を確かめる
- 最初の数晩は一覧だけ (--write なし)
"""
import datetime as dt
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))
sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")

import sold_restock as R  # noqa: E402

NOW = dt.datetime(2026, 9, 14, 23, 30)


def _row(checked):
    r = [""] * 40
    r[R.COL_CHECKED] = checked
    return r


def test_crawl_before_shipment_is_not_current_cost():
    assert R.row_cost_is_current(_row("2026/9/14 4:21:02"), now=NOW, after=dt.date(2026, 9, 8))
    assert not R.row_cost_is_current(_row("2026/9/14 4:21:02"), now=NOW, after=dt.date(2026, 9, 15))


# 2026-09-14 実機の注文 API 応答 (カイロス 820065007508 の注文から必要な項目だけ)
PAID_SHIPPED = {
    "orderId": "21-15112-56587", "creationDate": "2026-09-07T00:18:39.000Z",
    "orderPaymentStatus": "PAID", "orderFulfillmentStatus": "FULFILLED",
    "paymentSummary": {"payments": [{"paymentDate": "2026-09-07T00:18:41.121Z", "paymentStatus": "PAID"}]},
    "pricingSummary": {"total": {"value": "60.0", "currency": "USD"}},
    "lineItems": [{"legacyItemId": "820065007508", "sku": "m28429441340", "quantity": 1,
                   "title": "PSA 10 Pokemon Japanese Sv5a: Crimson Haze #067/066 Pinsir Art Rare 2024"}],
}


def test_api_order_becomes_the_same_row_as_the_report():
    row = R.order_rows_from_api(PAID_SHIPPED, "2026-09-08T07:26:00.000Z")[0]
    assert row["Item Number"] == "820065007508" and row["Custom Label"] == "m28429441340"
    assert (row["Sale Date"], row["Paid On Date"], row["Shipped On Date"]) == ("Sep-07-26", "Sep-07-26", "Sep-08-26")
    assert not R.order_pending(row)


def test_api_unshipped_refunded_and_unpaid():
    unshipped = R.order_rows_from_api(PAID_SHIPPED, "")[0]
    assert R.order_pending(unshipped)
    refunded = R.order_rows_from_api(dict(PAID_SHIPPED, orderPaymentStatus="FULLY_REFUNDED"), "")[0]
    assert refunded["Total Price"] == "0" and not R.order_pending(refunded)
    unpaid = R.order_rows_from_api(dict(PAID_SHIPPED, orderPaymentStatus="PENDING"), "")[0]
    assert unpaid["Paid On Date"] == "" and not R.order_pending(unpaid)
    cancelled = R.order_rows_from_api(dict(PAID_SHIPPED, cancelStatus={"cancelState": "CANCELED"}), "")[0]
    assert not R.order_pending(cancelled)


def test_send_has_a_cap_and_a_read_back():
    src = open(R.__file__, encoding="utf-8").read()
    assert "if acted >= max_send:" in src
    assert "読み直すと" in src and "v_qty >= 1" in src
    assert src.index("if acted >= max_send:") < src.index('call = "RelistFixedPriceItem"')


def test_nightly_bat_runs_list_only_for_now():
    bat = open(os.path.join(HQ, "tools", "run_hoju_search.bat"), "rb").read()
    assert b"\r\n" in bat and b"\n" not in bat.replace(b"\r\n", b"")
    line = next(l for l in bat.decode("ascii").splitlines() if "sold_restock.py" in l)
    assert "--orders-api" in line and "--write" not in line
