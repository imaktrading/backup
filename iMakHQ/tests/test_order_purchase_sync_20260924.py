# -*- coding: utf-8 -*-
"""注文 → 仕入れ の管理 (2026-09-24)。ユーザー「仕入漏れを防ぐために」。"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import order_purchase_sync as O  # noqa: E402


def _order(oid="10-15206-37276", created="2026-09-24T01:00:00.000Z", pay="PAID", ful="NOT_STARTED",
           cancel="NONE_REQUESTED", cost=None, due=None, cc="ID"):
    return {
        "orderId": oid, "creationDate": created, "orderPaymentStatus": pay,
        "orderFulfillmentStatus": ful, "cancelStatus": {"cancelState": cancel},
        "paymentSummary": {"totalDueSeller": due or {"value": "600", "currency": "USD"}},
        "fulfillmentStartInstructions": [{"shippingStep": {"shipTo": {"contactAddress": {"countryCode": cc}}}}],
        "lineItems": [{"legacyItemId": "820153394079", "sku": "m1", "title": "PSA 10 Dragon Ball",
                       "lineItemCost": cost or {"value": "650.0", "currency": "USD"},
                       "lineItemFulfillmentInstructions": {"shipByDate": "2026-10-05T14:59:59.000Z"}}],
    }


def test_new_order_becomes_row_with_purchase_columns():
    rows = O.new_rows([_order()], set(), 147)
    assert len(rows) == 1
    r = rows[0]
    assert r[O.C_NO] == 147 and r[O.C_ORDER] == "10-15206-37276"
    assert r[O.C_DATE] == "2026/09/24" and r[O.C_COUNTRY] == "Indonesia" and r[O.C_PRICE] == 650.0
    assert r[O.C_CAT] == "TCG" and r[O.C_DONE] is False
    assert r[O.C_URL] == ""          # 買った先は購入履歴から結ぶ (A列は入れない)
    assert r[O.C_SHIPBY] == "2026/10/05" and r[O.C_STATE] == "未発送"


def test_order_already_in_sheet_is_not_added_twice():
    # 表の注文番号は頭に改行が入っていることがある
    have = {O.norm_order("\r\n10-15206-37276")}
    assert O.new_rows([_order()], have, 1) == []


def test_cancelled_refunded_unpaid_and_old_orders_are_not_added():
    assert O.new_rows([_order(cancel="CANCELED")], set(), 1) == []
    assert O.new_rows([_order(pay="FULLY_REFUNDED")], set(), 1) == []
    assert O.new_rows([_order(pay="PENDING")], set(), 1) == []
    assert O.new_rows([_order(created="2026-08-20T01:00:00.000Z")], set(), 1) == []


def test_non_usd_price_is_converted_with_payout_rate():
    o = _order(cost={"value": "60.0", "currency": "GBP"},
               due={"value": "59.81", "currency": "USD", "convertedFromValue": "45.56",
                    "convertedFromCurrency": "GBP"})
    assert O.price_usd(o, o["lineItems"][0]) == round(60 * 59.81 / 45.56, 2)


def test_waiting_is_unchecked_and_unshipped_only():
    head = [""] * (O.C_STATE + 1)

    def row(done, state):
        r = [""] * (O.C_STATE + 1)
        r[O.C_DONE], r[O.C_STATE] = done, state
        return r
    rows = [head, row("FALSE", "未発送"), row("TRUE", "未発送"), row("FALSE", "発送済"), row("", "キャンセル")]
    assert [n for n, _r in O.waiting(rows)] == [2]


def test_category_names_match_sheet():
    assert O.category_of("Spy x Family Anya Forger Anime Graphic Tee UNIQLO UT") == "Tシャツ"
    assert O.category_of("CASIO G-SHOCK GA-2100") == "G-shock"
    assert O.category_of("Ichiban Kuji Jujutsu Kaisen H Prize") == "一番くじ"
    assert O.category_of("something else") == ""


def test_console_notice():
    import datetime
    sys.path.insert(0, os.path.join(HQ, "console"))
    import server
    now = datetime.datetime(2026, 9, 24, 12, 0)
    st = {"at": "2026-09-24T11:30:00", "waiting": 6, "earliest_ship_by": "2026/10/02"}
    assert "仕入れ待ち 6件" in server.order_notice(st, now) and "10/02" in server.order_notice(st, now)
    assert server.order_notice(dict(st, waiting=0), now) == ""
    assert "止まっています" in server.order_notice(dict(st, at="2026-09-24T07:00:00"), now)


def test_parse_mercari_purchases():
    import mercari_purchases as MP
    src = ('<a href="/transaction/m83909619297"><span>ヤドン PSA10 ポケモンカード</span>'
           '<svg><path d="x"/></svg><span>2026/09/24 09:24</span><span>発送待ち</span></a>'
           '<a href="/transaction/m42175948060"><span>ヤドン PSA10</span><span>2026/09/20 02:57</span></a>')
    ps = MP.parse_purchases(src)
    assert [p["id"] for p in ps] == ["m83909619297", "m42175948060"]
    assert ps[0]["url"] == "https://jp.mercari.com/item/m83909619297"
    assert ps[0]["title"].startswith("ヤドン") and ps[0]["at"].day == 24


def test_match_same_card_sold_twice_goes_in_order():
    """9/19 と 9/23 に同じヤドンが売れた。9/20 の購入は 9/19 の注文、9/24 の購入は 9/23 の注文。"""
    import datetime as d
    import mercari_purchases as MP
    buys = [{"id": "m2", "at": d.datetime(2026, 9, 24, 9, 24)}, {"id": "m1", "at": d.datetime(2026, 9, 20, 2, 57)},
            {"id": "m9", "at": d.datetime(2026, 9, 21)}]
    orders = [(146, d.date(2026, 9, 23), {"m1", "m2"}), (145, d.date(2026, 9, 19), {"m1", "m2"})]
    hit = MP.match(orders, buys)
    assert hit[145]["id"] == "m1" and hit[146]["id"] == "m2"
    # 候補に無い購入 (m9) は結ばない / 注文より前の購入は結ばない
    assert MP.match([(1, d.date(2026, 9, 25), {"m1", "m9"})], buys) == {}


def test_shipped_orders_are_not_linked_to_purchases():
    """発送済みの注文には購入を結ばない (9/19 発送済みのヤドンに 9/24 の購入が結ばれた実例)。"""
    def row(oid, state, url=""):
        r = [""] * (O.C_STATE + 1)
        r[O.C_ORDER], r[O.C_STATE], r[O.C_URL] = oid, state, url
        return r
    by_id = {k: {"orderId": k} for k in "ABC"}
    rows = [[], row("A", "発送済"), row("B", "未発送"), row("C", "未発送", "https://jp.mercari.com/item/m1")]
    assert [n for n, _r, _o in O.link_targets(rows, by_id)] == [3]
