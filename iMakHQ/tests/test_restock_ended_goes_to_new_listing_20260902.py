# -*- coding: utf-8 -*-
"""在庫が戻った時、出品が終了していたらリストックではなく新規出品に回す (2026-09-02)。

## 実害
リストックは「**生きている出品の数量を戻す**」機能。なのに終了した出品まで
「RESTOCK確定」に入れていたので、何度ボタンを押しても
`cert#未解決(商品管理シートI列に無い)→生成不可` で止まり、先へ進む道が無かった。
実測: 5件が 7/24 の確証から **40日** その状態のまま。

ユーザー指摘「リストックの対象が間違っているのでは？」がそのまま正しい。
**在庫が戻った時点で行き先を分ける**のが直し方。

## fail-closed
出品状態が読めなかった時は **リストック側に残す**。勝手に新規出品へ回して二重出品を作らない。
"""
import os
import sys

_HQ_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _HQ_TOOLS not in sys.path:
    sys.path.insert(0, _HQ_TOOLS)

import psa_resource_gate as G  # noqa: E402


def _row(iid, title="PSA 10 ...", urls="https://a/1 | https://a/2 | https://a/3"):
    # [itemID, card_no, title, channel, cost, cur, v8, urls, ebay_url, 確証日]
    return [iid, "SB02-033", title, "snkrdunk", "25000", "248.98", "", urls, "", "2026-09-02"]


def test_ended_listing_goes_to_new_listing():
    alive = {"live": True, "ended": False}
    restock, relist = G.split_confirmed_by_listing_alive(
        [_row("live"), _row("ended")], alive.get)
    assert [r[0] for r in restock] == ["live"]
    assert [r[0] for r in relist] == ["ended"]


def test_unknown_status_stays_in_restock():
    """状態が読めない時は新規出品に回さない (二重出品を作らない)。"""
    restock, relist = G.split_confirmed_by_listing_alive([_row("x")], lambda _i: None)
    assert [r[0] for r in restock] == ["x"]
    assert relist == []


def test_new_listing_row_has_empty_itemid_and_no_cert():
    """B列(itemID)が空 = 出品くんが拾う。鑑定番号は現物ごとに変わるので入れない。"""
    rows = G.new_listing_rows_from_confirmed([_row("ended", title="Son Goku SB02-033")])
    r = rows[0]
    assert r[1] == ""                       # B itemID 空
    assert r[8] == ""                       # I 鑑定番号 空
    assert r[0] == "https://a/1"            # A 仕入元URL = 先頭
    assert r[2] == "Son Goku SB02-033"      # C タイトル
    assert r[17] == "TCG"                   # R カテゴリ
    assert r[28] == "https://a/2" and r[29] == "https://a/3"   # 補URL


def test_new_listing_row_survives_single_url():
    rows = G.new_listing_rows_from_confirmed([_row("ended", urls="https://only/1")])
    assert rows[0][0] == "https://only/1"
    assert rows[0][28] == ""
