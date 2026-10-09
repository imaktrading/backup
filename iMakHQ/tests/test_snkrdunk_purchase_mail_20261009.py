# -*- coding: utf-8 -*-
"""スニダンの購入はメール (Gmail) から読む (2026-10-09 ユーザー: 購入履歴はアプリにしか無い・メールは来ている)。"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import snkrdunk_purchases as SN

BODY = """様 imax2303
下記商品のご購入が完了しました。
■ 商品情報
・ミュウ [XY 044/171](ハイクラスパック「THE BEST OF 」 XY )
・1枚
・商品金額：¥28,500
■ 支払い情報
・送料：¥300
・支払い金額(税込)：¥28,800
"""


def test_parse_mail():
    p = SN.parse_mail("【SNKRDUNK】ご購入ありがとうございます。(取引ID：47693638)", BODY, dt.datetime(2026, 10, 7, 15, 27))
    assert p["id"] == "47693638" and p["no"] == "044/171" and p["price"] == 28800
    assert SN.parse_mail("😈WEEK5本日開始👿", BODY, None) is None


def test_title_has_no():
    assert SN.title_has_no("PSA 10 Pokemon Japanese The Best of XY #044/171 Mew 2017", "044/171")
    assert SN.title_has_no("PSA 10 One Piece Japanese ... #OP07-085 Stussy", "OP07-085")
    assert not SN.title_has_no("PSA 10 ... #144/171 X", "044/171")


def test_match_one_purchase_per_order_after_order_day():
    buys = [{"id": "1", "no": "044/171", "at": dt.datetime(2026, 10, 7, 15, 0)},
            {"id": "2", "no": "044/171", "at": dt.datetime(2026, 9, 1, 15, 0)}]
    orders = [(158, dt.date(2026, 10, 7), "Mew #044/171"), (159, dt.date(2026, 10, 7), "Mew #044/171")]
    assert {k: v["id"] for k, v in SN.match(orders, buys).items()} == {158: "1"}
