# -*- coding: utf-8 -*-
"""入稿後の「プロモを8%に」の回帰テスト (2026-08-18)。

守る性質:
  1. 既に広告に入っている出品の率を勝手に書き換えない (人が別の率にしたものを潰さない)
  2. itemID が無い行を推測で作らない (書き戻し待ちとして残す)
  3. 受け皿キャンペーンと率が固定されている (8.0% で揃っている唯一のキャンペーン)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
from ads_add_new_listings import (itemid_index, resolve_itemids, plan,  # noqa: E402
                                  CAMPAIGN_ID, BID, MARKETPLACE)


def _sheet(rows):
    """rows = [(url, itemid, cert)] → シート2次元配列 (A=url B=itemID I=cert)。"""
    out = [["URL", "itemID", "C", "D", "E", "F", "G", "H", "cert"]]
    for url, iid, cert in rows:
        r = [""] * 9
        r[0], r[1], r[8] = url, iid, cert
        out.append(r)
    return out


def test_受け皿と率は固定():
    assert CAMPAIGN_ID == "165535464010" and BID == "8.0" and MARKETPLACE == "EBAY_US"


def test_certとSKUの両方からitemIDを引ける():
    idx = itemid_index(_sheet([("https://jp.mercari.com/item/m111", "358001", "999")]))
    assert idx["999"] == "358001" and idx["m111"] == "358001"


def test_itemIDが空や非数字の行は索引に入れない():
    idx = itemid_index(_sheet([("https://jp.mercari.com/item/m111", "", "999"),
                               ("https://jp.mercari.com/item/m222", "9999", "888")]))
    assert "999" not in idx
    assert idx["888"] == "9999"      # 見送りマーカー 9999 は数字なので入る (実 itemID と区別は別工程)


def test_引けなかったラベルは推測せず未取得に回す():
    found, missing = resolve_itemids(["PSA10-404"], {})
    assert found == [] and missing == ["PSA10-404"]


def test_既に広告に入っている出品は追加しない():
    found = [("PSA10-1", "358001"), ("PSA10-2", "358002")]
    to_add, already = plan(found, {"358001": "10.0"})
    assert to_add == [("PSA10-2", "358002")]
    assert already == [("PSA10-1", "358001", "10.0")]


def test_同じ率で入っていても触らない():
    to_add, already = plan([("PSA10-1", "358001")], {"358001": "8.0"})
    assert to_add == [] and already[0][2] == "8.0"


def test_広告ゼロなら全部追加対象():
    found = [("PSA10-1", "358001"), ("m222", "358002")]
    to_add, already = plan(found, {})
    assert to_add == found and already == []


def test_PSA自動の締めに載っている():
    """単独ボタンは 2026-08-18 に撤去 (ユーザー指示「1つだけにまとめて」)。
    🤖PSA自動 の締めから呼ばれる形なので、そこに無いと動かない。"""
    cp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control_panel.py")
    src = open(cp, encoding="utf-8").read()
    assert "ads_add_new_listings.py" in src
    # itemID を書いてからでないと itemID を引けない = ボタンの並び順を保証する
    assert src.index("itemid_writeback_audit.py") < src.index("ads_add_new_listings.py")
