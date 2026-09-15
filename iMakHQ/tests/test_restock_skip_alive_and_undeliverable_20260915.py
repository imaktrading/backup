# -*- coding: utf-8 -*-
"""🛒 PSA 再仕入れ ②: 仕入元が生きている行 / 上げられない台帳の行は CSV を作らない (2026-09-15)。

ユーザー「直してよ」(残務に回した2件):
・358887214446 カビゴン: 未発送の注文があり D列は空 (仕入元は生きている)。② が在庫1で出し直す
  → 売れた分の補充が「仕入れが済むまで戻さない」と止めているのに、別の口から戻してしまう。
・358514312870 カビゴン SD100: 上げられない台帳に載っているのに、件数表示だけ外して本体は素通り → アップロードされた。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import psa_restock_build as b  # noqa: E402

DEAD = "https://jp.mercari.com/item/m1"
NEW = "https://snkrdunk.com/apparels/1/used/2"


def _rows(*iids):
    return [{"itemID": i, "cost": "9000", "supply_url": "", "confirmed_url": NEW} for i in iids]


def test_alive_supply_row_is_left_to_sold_restock():
    sold = {"dead": DEAD}                                   # "alive" は D列が空 = 地図に居ない
    inp, skipped = b.build_restock_input(_rows("dead", "alive"), {"dead": "C1", "alive": "C2"}, {},
                                         sold_out_supply=sold)
    assert inp["certs"] == ["C1"]
    assert skipped == [("alive", "仕入元が生きている (D列が空) = 売れた分の補充 / 監視くんの担当→生成不可")]


def test_undeliverable_row_is_not_built():
    und = {"x": "カタログでカードを同定できない (必須 C:Rarity が空)"}
    inp, skipped = b.build_restock_input(_rows("x", "y"), {"x": "C1", "y": "C2"}, {},
                                         sold_out_supply={"x": DEAD, "y": DEAD}, undeliverable_ids=und)
    assert inp["certs"] == ["C2"]
    assert skipped[0][0] == "x" and "上げられない台帳" in skipped[0][1]


def test_gates_off_when_materials_missing():
    inp, skipped = b.build_restock_input(_rows("a"), {"a": "C1"}, {})
    assert inp["certs"] == ["C1"] and skipped == []


def test_main_and_hint_pass_undeliverable():
    src = open(b.__file__, encoding="utf-8").read()
    assert src.count("undeliverable_ids=undeliverable()") == 2
