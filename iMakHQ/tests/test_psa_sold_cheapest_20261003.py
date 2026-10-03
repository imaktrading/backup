# -*- coding: utf-8 -*-
"""売れた PSA10 の仕入れ先を買う直前に探し直す画面 (2026-10-03)。

ユーザー「売れたら仕入元URLと補URLに加えて、改めてメルカリとスニダンで最安値を調べて購入している。
この部分を精度高く」→ 目視画面 / ボタン / メルカリは条件外も印を付けて出す。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import mercari_psa_resource as mp  # noqa: E402
import psa_sold_cheapest as P  # noqa: E402


def test_marks_follow_supply_rules():
    ok = {"channel": "mercari", "buyable": True, "ship": "送料込み", "reviews": 300, "shops": False, "version": ""}
    assert P.marks_of(ok) == []
    assert P.marks_of({**ok, "reviews": 15}) == ["評価15件"]
    assert P.marks_of({**ok, "ship": "着払い"}) == ["着払い"]
    assert P.marks_of({**ok, "shops": True, "reviews": None}) == []          # Shops は評価を見ない
    assert P.marks_of({**ok, "version": "版未確認"}) == ["版未確認"]
    assert P.marks_of({**ok, "buyable": False}) == ["売り切れ"]
    assert P.marks_of({"channel": "snkrdunk", "buyable": True, "version": ""}) == []


def test_version_label_from_title():
    assert P.version_label(True, True) == ""
    assert P.version_label(True, False) == "版未確認"
    assert P.version_label(False, True) == "番号未確認"


def test_merge_keeps_existing_label_and_sorts_sold_last():
    ex = [{"src": "補1", "url": "https://jp.mercari.com/item/m1", "price": None, "buyable": True},
          {"src": "仕入元", "url": "https://jp.mercari.com/item/m2", "price": 9000, "buyable": False}]
    found = [{"src": "メルカリ", "url": "https://jp.mercari.com/item/m1?x=1", "price": 5000, "buyable": True},
             {"src": "スニダン", "url": "https://snkrdunk.com/apparels/1/used/2", "price": 7000, "buyable": True}]
    out = P.sort_candidates(P.merge_candidates(ex, found))
    assert [c["src"] for c in out] == ["補1", "スニダン", "仕入元"]
    assert out[0]["price"] == 5000


def test_other_name_with_katakana_tail_is_other_card():
    """ミュウ の候補にミュウツーが出ていた (2026-10-03)。空白で区切られた続きは同じカード。"""
    assert mp._name_is_other_card("【美品】ポケモンカード　ミュウツー EX PSA10", "ミュウ")
    assert mp._name_is_other_card("ミュウツーvstar psa10", "ミュウ")
    assert not mp._name_is_other_card("【PSA10】ミュウ 002/028 25th", "ミュウ")
    assert not mp._name_is_other_card("ミュウ ポケカ PSA10", "ミュウ")


def test_psa_order_row():
    r = [""] * 20
    r[2], r[17] = "PSA 10 Pokemon Japanese S8a #002/028 Mew", "TCG"
    assert P.is_psa_order_row(r, 2, 17)
    r[2] = "G-SHOCK GW-M5610"
    assert not P.is_psa_order_row(r, 2, 17)


def test_today_order_card_counts_psa():
    """今日やることの「注文」枠 (2026-10-04): うち PSA の件数と一番近い発送期限を出す。"""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "console"))
    import server as SV
    st = {"at": "2026-10-03T22:00:00", "waiting": 3, "earliest_ship_by": "2026/10/14",
          "items": [{"title": "PSA 10 Pokemon Mew"}, {"title": "G-SHOCK GW-M5610"}, {"title": "PSA 10 Latios"}]}
    d = SV.order_job_info(st)
    assert d["n"] == 3 and d["psa"] == 2 and d["ship_by"] == "2026/10/14"


def test_read_only_button_does_not_recount():
    """読むだけのボタンは押した後に全部数え直さない (3〜8分「数え直し中」のままだった)。"""
    import control_panel as cp
    b = [s for s in cp.SCRIPTS if "仕入れ先を探す" in s["label"]][0]
    assert b.get("no_recount") is True
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "console", "server.py"),
               encoding="utf-8").read()
    assert 'script.get("no_recount")' in src
