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


def test_purchase_login_failure_reaches_order_card(monkeypatch):
    """購入履歴のログイン切れを神風の注文の枠に出す (2026-10-04: 仕入れ済みのミュウが仕入れ待ちに残った)。"""
    import json
    import tempfile
    import order_purchase_sync as ops
    import mercari_purchases as MP

    def boom():
        raise RuntimeError("メルカリのログインが切れています (https://login.jp.mercari.com/...)")
    monkeypatch.setattr(MP, "fetch_purchases", boom)
    monkeypatch.setattr(ops, "_candidate_lookup", lambda: (lambda sku, iid: {"m1"}))
    monkeypatch.setattr(ops, "LINK_WARN", [])
    assert ops._link_mercari([], {}) == {}
    assert ops.LINK_WARN == ["メルカリの購入履歴を読めません (ログイン切れ)"]
    path = os.path.join(tempfile.mkdtemp(), "st.json")
    monkeypatch.setattr(ops, "STATUS", path)
    ops._write_status([[""] * 30])
    st = json.load(open(path, encoding="utf-8"))
    assert "ログイン切れ" in st["warn"]
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "console"))
    import server as SV
    assert "ログイン切れ" in SV.order_job_info(st)["warn"]


def test_shown_candidates_are_recorded_and_pruned():
    """画面に出したメルカリ候補を注文ごとに残す (売り切れは除く・60日で消す)。"""
    import datetime as dt
    cands = [{"url": "https://jp.mercari.com/item/m111", "buyable": True},
             {"url": "https://jp.mercari.com/item/m222", "buyable": False},
             {"url": "https://snkrdunk.com/apparels/1/used/2", "buyable": True}]
    assert P.shown_ids(cands) == ["m111"]
    st = P.merge_shown({"old": {"at": "2026-07-01", "ids": ["m9"]}}, "27-1", ["m111"], dt.date(2026, 10, 4))
    assert "old" not in st and st["27-1"]["ids"] == ["m111"]
    st = P.merge_shown(st, "27-1", ["m333", "m111"], dt.date(2026, 10, 5))
    assert st["27-1"]["ids"] == ["m111", "m333"]


def test_link_uses_shown_candidates(monkeypatch):
    """画面から買った物 (仕入元・補URL に無い) も注文に結ぶ (2026-10-04)。"""
    import datetime as dt
    import order_purchase_sync as ops
    import mercari_purchases as MP
    import psa_sold_cheapest as PSC
    monkeypatch.setattr(ops, "_candidate_lookup", lambda: (lambda sku, iid: {"m_supply"}))
    monkeypatch.setattr(MP, "fetch_purchases", lambda: [
        {"id": "m_shown", "url": "https://jp.mercari.com/transaction/m_shown", "title": "PSA10 ミュウ",
         "at": dt.datetime(2026, 10, 3, 22, 34)}])
    monkeypatch.setattr(PSC, "load_shown", lambda: {"27-15214-32723": {"at": "2026-10-03", "ids": ["m_shown"]}})
    row = [""] * 30
    row[ops.C_ORDER] = "27-15214-32723"
    order = {"orderId": "27-15214-32723", "creationDate": "2026-10-03T00:47:34.000Z",
             "lineItems": [{"sku": "m48829345464", "legacyItemId": "820169464104"}]}
    hit = ops._link_mercari([(155, row, order)], {})
    assert 155 in hit and hit[155][1].endswith("m_shown")


def test_snkr_existing_url_uses_listing_photo():
    """補URL のスニダンは出品一覧 API の写真を使う (og:image は共通ロゴだった・2026-10-04)。"""
    import snkrdunk_psa_resource as sp
    calls = []

    class SP:
        _parse_listing_url = staticmethod(sp._parse_listing_url)

        @staticmethod
        def fetch_psa10_listings(cid):
            calls.append(cid)
            return [{"listing_id": 48878837, "price": 8000, "image": "https://cdn.snkrdunk.com/x.jpg"}]
    cache = {}
    u = "https://snkrdunk.com/apparels/358113/used/48878837"
    assert P.snkr_listing_now(SP, u, cache) == (True, 8000, "https://cdn.snkrdunk.com/x.jpg")
    assert P.snkr_listing_now(SP, "https://snkrdunk.com/apparels/358113/used/1", cache) == (False, None, "")
    assert calls == ["358113"]                     # 同じカードは1回だけ読む


def test_sync_orders_before_listing(monkeypatch):
    """仕入れ先を探す前に注文の取り込みを走らせる (仕入れ済みが出ていた・2026-10-04)。"""
    import order_purchase_sync as ops
    calls = []
    monkeypatch.setattr(ops, "main", lambda argv: calls.append(("sync", argv)) or 0)
    monkeypatch.setattr(P, "load_waiting_orders", lambda item=None: calls.append(("load", item)) or [])
    assert P.main(["--no-open"]) == 0
    assert calls == [("sync", ["--write"]), ("load", None)]
    calls.clear()
    P.main(["--no-open", "--no-sync"])
    assert calls == [("load", None)]


def test_cancel_in_progress_is_not_waiting():
    """キャンセル手続き中 (返金待ち) は仕入れ待ちに数えない (2026-10-04)。"""
    import order_purchase_sync as ops
    o = {"cancelStatus": {"cancelState": "IN_PROGRESS"}, "orderPaymentStatus": "PAID",
         "orderFulfillmentStatus": "NOT_STARTED"}
    assert ops.order_state(o) == "キャンセル中"
    o["cancelStatus"]["cancelState"] = "NONE_REQUESTED"
    assert ops.order_state(o) == "未発送"
