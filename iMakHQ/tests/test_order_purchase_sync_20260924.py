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


def test_money_cells_match_hand_entered_rows():
    """手で入れていた NO.136 (英国) / NO.139 (アイスランド) と同じ値になる (2026-09-24 実データ)。"""
    uk = _order(cost={"value": "128.25", "currency": "GBP"})
    uk_fin = [{"transactionType": "NON_SALE_CHARGE", "feeType": "AD_FEE", "bookingEntry": "DEBIT",
               "amount": {"value": "18.97", "currency": "USD"}},
              {"transactionType": "SALE", "bookingEntry": "CREDIT",
               "amount": {"value": "140.4", "currency": "USD", "exchangeRate": "1.31869"},
               "totalFeeAmount": {"value": "21.78", "currency": "GBP"},
               "orderLineItems": [{"feeBasisAmount": {"value": "153.9", "currency": "GBP"}}]}]
    c = O.money_cells(uk, uk_fin, "LX330207015JP")
    assert c[O.C_PRICE] == 128.25 and c[O.C_TAX] == 25.65 and c[O.C_FEE] == -28.72
    assert c[O.C_AD] == -18.97 and c[O.C_NET] == 121.43 and c[O.C_TRACK] == "LX330207015JP"
    assert O.C_SHIP not in c
    iceland = _order(cost={"value": "294.98", "currency": "USD"})
    fin = [{"transactionType": "NON_SALE_CHARGE", "feeType": "AD_FEE", "bookingEntry": "DEBIT",
            "amount": {"value": "32.45", "currency": "USD"}},
           {"transactionType": "SALE", "amount": {"value": "250.09", "currency": "USD"},
            "totalFeeAmount": {"value": "44.89", "currency": "USD"},
            "orderLineItems": [{"feeBasisAmount": {"value": "294.98", "currency": "USD"}}]}]
    c = O.money_cells(iceland, fin)
    assert c[O.C_FEE] == -44.89 and c[O.C_AD] == -32.45 and c[O.C_NET] == 217.64
    assert O.C_TAX not in c and O.C_TRACK not in c
    # 入金明細がまだ無い注文は 商品価格だけ
    assert set(O.money_cells(iceland, [])) == {O.C_PRICE}


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


def test_console_button_count():
    """押したら取り込む (夜間自動なし)。件数 = 最後に取り込んだ時点の仕入れ待ち。"""
    sys.path.insert(0, os.path.join(HQ, "console"))
    import server
    assert server.order_job_info({"at": "2026-09-24T15:00:00", "waiting": 2})["n"] == 2
    assert server.order_job_info({"at": "2026-09-24T15:00:00", "waiting": 2})["state"] == "todo"
    assert server.order_job_info({"at": "2026-09-24T15:00:00", "waiting": 0})["state"] == "done"
    assert server.order_job_info(None)["n"] is None
    assert server.group_of("📦 注文の取り込み (仕入れ待ち)") == "offer"      # TOP の枠に出る


def test_parse_mercari_purchases():
    import mercari_purchases as MP
    src = ('<a href="/transaction/m83909619297"><span>ヤドン PSA10 ポケモンカード</span>'
           '<svg><path d="x"/></svg><span>2026/09/24 09:24</span><span>発送待ち</span></a>'
           '<a href="/transaction/m42175948060"><span>ヤドン PSA10</span><span>2026/09/20 02:57</span></a>')
    ps = MP.parse_purchases(src)
    assert [p["id"] for p in ps] == ["m83909619297", "m42175948060"]
    assert ps[0]["url"] == "https://jp.mercari.com/transaction/m83909619297"
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


def test_uniqlo_purchase_parse_and_match():
    """ユニクロ公式の購入履歴 → 在庫監視シートの 商品番号+色 と eBay のサイズ (JP) で結ぶ。"""
    import datetime as d
    import uniqlo_purchases as UQ
    text = "\n".join(["ポケモン UT", "商品番号: 486159", "カラー: 00 WHITE", "サイズ: MEN XXL",
                      "購入日: 2026/9/25", "購入場所: オンラインストア", "レビューを書く",
                      "ポケモン UT", "商品番号: 486159", "カラー: 00 WHITE", "サイズ: MEN XL",
                      "購入日: 2026/9/25", "購入場所: ユニクロ なんばマルイ店"])
    ps = UQ.parse_purchases(text)
    assert [(p["pid"], p["color"], p["size"], p["day"]) for p in ps] == [
        ("486159", "00", "MEN XXL", d.date(2026, 9, 25)), ("486159", "00", "MEN XL", d.date(2026, 9, 25))]
    keys = UQ.official_keys(["https://www.uniqlo.com/jp/ja/products/E486159-000/00?colorDisplayCode=00&sizeDisplayCode=004"])
    assert keys == {("486159", "00")}
    assert UQ.size_key("US XL(JP XXL)") == "XXL" and UQ.size_key("MEN XXL") == "XXL"
    hit = UQ.match([(9, d.date(2026, 9, 24), keys, "XXL")], ps)
    assert hit[9]["size"] == "MEN XXL"                      # サイズ違い (XL) は結ばない
    assert UQ.match([(9, d.date(2026, 9, 24), {("486159", "01")}, "XXL")], ps) == {}   # 色違い
    assert UQ.match([(9, d.date(2026, 9, 26), keys, "XXL")], ps) == {}                 # 注文より前の購入


def test_mercari_item_price_parse():
    """商品ページの値段 (送料込み) を読む。2026-09-24 実際の HTML の形。"""
    import mercari_purchases as MP
    src = ('<div data-testid="price" class="sc-33425bfe-0 hifYq"><span class="currency">¥</span>'
           '<span>68,888</span></div><p>(税込) 送料込み</p>')
    assert MP.parse_item_price(src) == 68888
    assert MP.parse_item_price("<div>売り切れ</div>") is None


def test_uniqlo_order_detail_parse():
    """受け取り前のオンライン注文は「商品一覧」に出ない。注文詳細から読む (2026-09-25 アーニャ UT の実例)。"""
    import datetime as d
    import uniqlo_purchases as UQ
    text = "\n".join(["注文番号: 0120050002609240834-2256034", "注文日", "2026/9/24", "注文状況: 出荷準備中",
                      "注文内容", "マンガUT 集英社創業100周年 SPY×FAMILY", "商品番号: 489653", "カラー: 00 WHITE",
                      "サイズ: MEN XXL", "¥1,990", "数量: 1", "小計: ¥1,990"])
    ps = UQ.parse_order_detail(text, "https://www.uniqlo.com/jp/ja/member/orders/online-store/0120")
    assert len(ps) == 1
    p = ps[0]
    assert (p["pid"], p["color"], p["size"], p["day"], p["price"]) == ("489653", "00", "MEN XXL", d.date(2026, 9, 24), 1990)
    assert p["url"].endswith("/0120")
    keys = UQ.official_keys(["https://www.uniqlo.com/jp/ja/products/E489653-000/00?colorDisplayCode=00&sizeDisplayCode=004"])
    assert UQ.match([(152, d.date(2026, 9, 24), keys, UQ.size_key("US XL(JP XXL)"))], ps)[152]["price"] == 1990


def test_purchase_already_linked_to_other_order_is_not_reused():
    """ユーザー「仕入れてないのに、仕入済となるのが一番きつい」(2026-09-25)。
    9/24 のヤドンの購入は 16-15191 に結んだ。同じヤドンがもう1枚売れても、その購入を新しい注文に結ばない。"""
    import datetime as d
    import mercari_purchases as MP
    buys = [{"id": "m83909619297", "at": d.datetime(2026, 9, 24, 9, 24)}]
    keys = O.purchase_keys(buys, "mercari")
    assert keys == ["mercari:m83909619297#1"]
    linked = {"mercari:m83909619297#1": "16-15191-59943"}
    free = O.unused_purchases(buys, keys, linked, {160: "99-99999-99999"})
    assert free == []
    assert MP.match([(160, d.date(2026, 9, 24), {"m83909619297"})], [p for p, _k in free]) == {}
    # 結んだ相手の注文そのもの (やり直し) なら使える
    assert len(O.unused_purchases(buys, keys, linked, {150: "16-15191-59943"})) == 1


def test_two_identical_uniqlo_purchases_get_different_keys():
    import datetime as d
    b = [{"day": d.date(2026, 9, 24), "pid": "489653", "color": "00", "size": "MEN XXL", "place": "店"}] * 2
    assert O.purchase_keys(b, "uniqlo")[0] != O.purchase_keys(b, "uniqlo")[1]


def test_headless_uses_normal_chrome_name():
    """ログインが1日で切れた (3回)。窓なしが HeadlessChrome と名乗り、別の端末に見えていた。"""
    import mercari_purchases as MP
    ua = MP.normal_ua(154)
    assert "Headless" not in ua and "Chrome/154.0.0.0" in ua
