# -*- coding: utf-8 -*-
"""🛒 PSA 再仕入れ ②: 確定した仕入元が監視くんで売り切れなら CSV を作らない (2026-09-15)。

実害になりかけた流れ (9/15 実測):
  一度 再仕入れで戻した出品 (RESTOCK状態=実行済) の仕入元が売り切れ → 監視くんが D列○・在庫0 →
  ③ 確認 が在庫0を見て「入稿待ち」に戻す → 次の ② が **同じ(売り切れの)仕入元のまま** 在庫1の Revise を作る。
  9/15 14:51 の入稿待ち14件のうち 10件がこれ (確定URL = 商品管理シートA列 かつ D列○)。
売り切れ印だけでは止めない。新しく見つけた仕入元で戻す正規の再仕入れも D列○ の状態から始まるため。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import psa_restock_build as b  # noqa: E402

DEAD = "https://jp.mercari.com/item/m16084927978"
NEW = "https://snkrdunk.com/apparels/291940/used/999999"


def _product(rows):
    """商品管理シート風: A=仕入元 / B=itemID / D=売り切れ。"""
    out = [["A", "B", "C", "D"]]
    for iid, a, d in rows:
        out.append([a, iid, "t", d])
    return out


def test_sold_out_map_only_has_marked_rows():
    vals = _product([("1", DEAD, "○"), ("2", NEW, ""), ("", DEAD, "○")])
    assert b.sold_out_supply_by_item(vals) == {"1": DEAD}


def test_same_dead_supply_is_skipped_but_new_supply_is_built():
    rows = [{"itemID": "1", "cost": "9000", "supply_url": "", "confirmed_url": DEAD + "?x=1"},
            {"itemID": "2", "cost": "9000", "supply_url": "", "confirmed_url": NEW}]
    sold = {"1": DEAD, "2": DEAD}           # 2 は仕入元が売り切れだが、確定したのは別の仕入元 = 正規の再仕入れ
    inp, skipped = b.build_restock_input(rows, {"1": "C1", "2": "C2"}, {}, sold_out_supply=sold)
    assert inp["certs"] == ["C2"]
    assert skipped[0][0] == "1" and "売り切れ" in skipped[0][1]


def test_without_sold_out_map_behaves_as_before():
    rows = [{"itemID": "1", "cost": "9000", "supply_url": "", "confirmed_url": DEAD}]
    inp, skipped = b.build_restock_input(rows, {"1": "C1"}, {})
    assert inp["certs"] == ["C1"] and skipped == []


def test_confirmed_url_is_read_from_the_real_header():
    """タブの見出しは「確認済仕入URL」(複数は ' | ' 区切り)。先頭を使う。"""
    rows = [["itemID", "最安¥", "確認済仕入URL", "RESTOCK状態"],
            ["1", "9000", DEAD + " | " + NEW, "入稿待ち(qty=0)"],
            ["2", "9000", NEW, "実行済(qty復活)"]]
    out, done = b._pending_from_confirmed_rows(rows)
    assert done == 1 and out[0]["confirmed_url"] == DEAD


def test_main_and_hint_use_the_same_gate():
    src = open(b.__file__, encoding="utf-8").read()
    assert src.count("sold_out_supply=") >= 2
