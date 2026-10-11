"""メルカリ・Shops の購入をメールから読む (2026-10-11)。

実害: Edge の拡張の購入履歴は30分の控えを使い回し、買った直後 (18:03) に数え直しても
17:57 の控えを見て「仕入れ待ち」のままだった。補URL に無い出品で買った分も結べなかった。
"""
import datetime as dt
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import mercari_mail_purchases as M

MERCARI = """■商品情報
商品ID : m47602546310
商品名 : 【PSA10】セビエ AR スノーハザード 075/071
出品者 : hoko.hoko
■支払い金額
商品代金 : ￥4,800
支払い金額 : ￥4,800"""
SHOPS = """▼商品情報
注文番号 : order_2JVrFhrFBR4xEnBLFUhDR9
商品名 : PSA10　ゼラオラ AR	sv7-109　ワンオーナー品
商品価格 : ¥5,600
注文金額合計　　　：　¥5,600"""
AT = dt.datetime(2026, 10, 11, 18, 3)


def test_メルカリのメール():
    p = M.parse_mail("【メルカリ】ご購入ありがとうございます", MERCARI, AT, "no-reply@mercari.jp")
    assert p["id"] == "m47602546310" and p["price"] == 4800 and p["no"] == "075/071"
    assert p["url"] == "https://jp.mercari.com/transaction/m47602546310" and p["shops"] is False


def test_Shops_のメール():
    p = M.parse_mail("【Y's Collectible】ご購入ありがとうございます", SHOPS, AT, "no-reply@mercari-shops.com")
    assert p["order_id"] == "2JVrFhrFBR4xEnBLFUhDR9" and p["price"] == 5600 and p["shops"] is True


def test_発送のメールは購入ではない():
    assert M.parse_mail("【店】からご購入された商品が発送されました", SHOPS, AT, "no-reply@mercari-shops.com") is None


def test_カード番号():
    assert M.card_no("【PSA-10】【P-043】少年ジャンプ ルフィ") == "P-043"
    assert M.card_no("【PSA10】ベジットFB10-040 アルティメット") == "FB10-040"
    assert M.card_no("ヤドン PSA10 ポケモンカード") == ""


def test_PSA7_は_PSA10_の注文に結ばない():
    buys = [{"id": "name:a", "order_id": "a", "title": "シャワーズex SAR SV8a 205/187 (PSA7)", "no": "205/187",
             "at": dt.datetime(2026, 10, 9, 9, 41)},
            {"id": "name:b", "order_id": "b", "title": "PSA10 シャワーズex 205/187", "no": "205/187",
             "at": dt.datetime(2026, 10, 9, 9, 59)}]
    hit = M.match_by_no([(5, dt.date(2026, 10, 9), "PSA 10 Pokemon Japanese Sv8a #205/187 Vaporeon ex")], buys)
    assert hit[5]["order_id"] == "b"


def test_注文日より前の購入と_番号違いは結ばない():
    buys = [{"id": "m1", "title": "PSA10 セビエ 075/071", "no": "075/071", "at": dt.datetime(2026, 10, 9)},
            {"id": "m2", "title": "PSA10 セビエ 074/071", "no": "074/071", "at": dt.datetime(2026, 10, 11)}]
    assert M.match_by_no([(1, dt.date(2026, 10, 10), "PSA 10 Pokemon #075/071 Frigibax")], buys) == {}
