"""オファーを送る仕組み (2026-10-05 ユーザー確定)。送るのは Seller Hub の画面から (拡張)。"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import shelf_offer as SO  # noqa: E402

NOW = datetime.datetime(2026, 10, 5, 12)


def _profit(offer, cost):            # 仕入値に対して値段が十分なら黒字、の単純なモデル
    return offer * 150 - cost * 1.3


def test_uses_second_cheapest_source_and_10pct():
    pct, offer, basis, why = SO.choose_discount(200.0, [9000, 20000, 15000], _profit)
    assert (pct, offer, basis) == (10, 180.0, 15000)          # 2番目に安い ¥15,000 で計算


def test_needs_two_buyable_sources():
    pct, _o, _b, why = SO.choose_discount(200.0, [9000], _profit)
    assert pct is None and "1本" in why


def test_shallower_discount_but_not_below_5pct():
    pct, offer, _b, _w = SO.choose_discount(200.0, [9000, 22000], lambda o, c: o * 150 - c * 1.27)
    assert pct is not None and 5 <= pct < 10 and offer > 180.0
    pct2, _o, _b2, why2 = SO.choose_discount(200.0, [9000, 29000], _profit)   # 5%引き ($190) でも赤字
    assert pct2 is None and "5%" in why2


def test_floor_price_is_break_even_at_basis():
    f = SO.floor_price(200.0, 15000, _profit)                 # 150*p >= 19500 → p >= 130
    assert 130.0 <= f < 130.5


def test_offer_states():
    s = SO.offer_state
    assert s(None, NOW) is None
    assert s({"status": SO.WAITING, "planned": "2026-10-05T08:00:00"}, NOW) == "waiting"
    assert s({"status": SO.WAITING, "planned": "2026-10-02T08:00:00"}, NOW) == "waiting_over"
    assert s({"status": SO.SENT, "expires": "2026-10-08T00:00:00"}, NOW) == "offering"
    assert s({"status": SO.SENT, "expires": "2026-10-04T00:00:00"}, NOW) == "expired"
    assert s({"status": "落とす"}, NOW) == "done"


def test_held_items_are_not_dropped(tmp_path, monkeypatch):
    p = tmp_path / "offers.json"
    SO.save_json(str(p), {"A": {"status": SO.SENT, "expires": "2099-01-01T00:00:00"},
                          "W": {"status": SO.WAITING, "planned": NOW.isoformat()},
                          "B": {"status": SO.SENT, "expires": "2000-01-01T00:00:00"}})
    monkeypatch.setattr(SO, "OFFERS_PATH", str(p))
    monkeypatch.setattr(SO, "plan_items", lambda *a, **k: set())
    picked = [(2, {"item_id": i, "watch": 1}) for i in ("A", "W", "B", "C")]
    got = SO.offer_before_drop(picked, lambda r: True, send=False, now=NOW, log=lambda *a: None,
                               live_ids={"A", "W", "B", "C"})
    assert [r["item_id"] for _t, r in got] == ["B", "C"]     # 送った / 送る待ち は落とさない・期限切れは落とす


def test_new_offer_candidates_are_held_not_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(SO, "OFFERS_PATH", str(tmp_path / "o.json"))
    monkeypatch.setattr(SO, "plan_items", lambda rows, ledger, **k: {"X"})
    picked = [(2, {"item_id": "X", "watch": 3}), (2, {"item_id": "Y", "watch": 0})]
    got = SO.offer_before_drop(picked, lambda r: True, send=False, now=NOW, log=lambda *a: None)
    assert [r["item_id"] for _t, r in got] == ["Y"]


def test_settle_sent_and_waiting(tmp_path, monkeypatch):
    monkeypatch.setattr(SO, "OFFERS_PATH", str(tmp_path / "o.json"))
    monkeypatch.setattr(SO, "NO_AD_PATH", str(tmp_path / "noad.json"))
    old = "2000-01-01T00:00:00"
    ledger = {"SOLD": {"status": SO.SENT, "expires": old}, "DROP": {"status": SO.SENT, "expires": old},
              "KEEP": {"status": SO.SENT, "expires": old},
              "WAIT_AD": {"status": SO.WAITING, "planned": old, "ad_removed": old},
              "WAIT_NOAD": {"status": SO.WAITING, "planned": old},
              "LIVE": {"status": SO.SENT, "expires": "2099-01-01T00:00:00"}}
    calls = []
    monkeypatch.setattr(SO, "restore_ads", lambda iids, log=None: calls.append(sorted(iids)) or set(iids))
    SO.settle(ledger, {"DROP"}, {"DROP", "KEEP", "WAIT_AD", "WAIT_NOAD", "LIVE"}, write=True,
              log=lambda *a: None, now=NOW)
    assert ledger["SOLD"]["status"] == "売れた・終了"
    assert ledger["DROP"]["status"] == "落とす"
    assert ledger["KEEP"]["status"] == "広告を戻した"
    assert ledger["WAIT_AD"]["status"] == "送らずに終了" and ledger["WAIT_NOAD"]["status"] == "送らずに終了"
    assert calls == [["KEEP", "WAIT_AD"]]                     # 広告を外した物だけ付け直す
    assert ledger["LIVE"]["status"] == SO.SENT


def test_prepare_and_mark_sent(tmp_path, monkeypatch):
    monkeypatch.setattr(SO, "OFFERS_PATH", str(tmp_path / "o.json"))
    monkeypatch.setattr(SO, "NO_AD_PATH", str(tmp_path / "noad.json"))
    SO.save_json(SO.OFFERS_PATH, {"X": {"status": SO.WAITING, "planned": NOW.isoformat(), "pct": 10}})
    monkeypatch.setattr(SO, "_headers", lambda: {})
    monkeypatch.setattr(SO, "remove_ad", lambda h, iid: True)
    assert SO.prepare("X")["ok"] and "X" in SO.no_ad_ids()
    assert not SO.prepare("NOPE")["ok"]
    assert SO.mark_sent("X", 10)["ok"]
    e = SO.load_json(SO.OFFERS_PATH, {})["X"]
    assert e["status"] == SO.SENT and e["expires"]


def test_ads_tool_skips_no_ad_items(tmp_path, monkeypatch):
    import ads_add_new_listings as A
    monkeypatch.setattr(SO, "no_ad_ids", lambda path=None: {"111"})
    assert A.create_ads("tok", [("L", "111")]) == []           # eBay を呼ばずに外す


def test_offers_are_not_sent_anymore():
    """★2026-10-05 ユーザー判断: こちらからオファーを送らない → ★2026-10-09 ユーザー確定で再開
    (「送れるものには全部送る」・送ったオファー中も数量0が通ることを実機で確認)。
    棚②の落とす前のオファーは「全部送る」に含まれるので個別には通さない。拡張は出品中一覧 (送る画面) で動く。"""
    here = os.path.join(os.path.dirname(__file__), "..")
    src = open(os.path.join(here, "tools", "shelf_evict.py"), encoding="utf-8").read()
    assert "SO.offer_before_drop(" not in src
    import json
    man = json.load(open(os.path.join(here, "tools", "sellerhub_grab", "manifest.json"), encoding="utf-8"))
    assert any("lst/active" in m for c in man["content_scripts"] for m in c["matches"])
    cp = open(os.path.join(here, "control_panel.py"), encoding="utf-8").read()
    assert "💌 オファーの送る一覧を作る" not in cp
