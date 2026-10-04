"""棚② 落とす前のオファー (2026-10-05 ユーザー確定)。"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import shelf_offer as SO  # noqa: E402


def _profit(offer, cost):            # 仕入値に対して値段が十分なら黒字、の単純なモデル
    return offer * 150 - cost * 1.3


def test_uses_second_cheapest_source_and_10pct():
    pct, offer, basis, why = SO.choose_discount(200.0, [9000, 20000, 15000], _profit)
    assert (pct, offer, basis) == (10, 180.0, 15000)          # 2番目に安い ¥15,000 で計算


def test_needs_two_buyable_sources():
    pct, _o, _b, why = SO.choose_discount(200.0, [9000], _profit)
    assert pct is None and "1本" in why


def test_shallower_discount_then_none():
    # 2番目 ¥22,000: 10%引き($180)は赤字・5%引き($190)は黒字
    pct, offer, _b, _w = SO.choose_discount(200.0, [9000, 22000], lambda o, c: o * 150 - c * 1.27)
    assert pct is not None and pct < 10 and offer > 180.0
    pct2, _o, _b2, why2 = SO.choose_discount(200.0, [9000, 40000], _profit)
    assert pct2 is None and "赤字" in why2


def test_offer_state_expiry():
    now = datetime.datetime(2026, 10, 5, 12)
    assert SO.offer_state(None, now) is None
    assert SO.offer_state({"expires": "2026-10-07T13:00:00"}, now) == "offering"
    assert SO.offer_state({"expires": "2026-10-05T11:00:00"}, now) == "expired"


def test_offering_items_are_not_dropped_and_expired_are(tmp_path, monkeypatch):
    p = tmp_path / "offers.json"
    SO.save_json(str(p), {"A": {"expires": "2099-01-01T00:00:00"}, "B": {"expires": "2000-01-01T00:00:00"}})
    monkeypatch.setattr(SO, "OFFERS_PATH", str(p))
    picked = [(2, {"item_id": "A", "watch": 1}), (2, {"item_id": "B", "watch": 1}),
              (2, {"item_id": "C", "watch": 0})]
    got = SO.offer_before_drop(picked, lambda r: True, send=False, log=lambda *a: None)
    assert [r["item_id"] for _t, r in got] == ["B", "C"]      # A はオファー中 / B は期限切れで落とす / C はウォッチ無し


def test_no_send_when_eligibility_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(SO, "OFFERS_PATH", str(tmp_path / "o.json"))
    monkeypatch.setattr(SO, "_headers", lambda: {})
    monkeypatch.setattr(SO, "eligible_ids", lambda h: None)
    sent = []
    monkeypatch.setattr(SO, "send_offer", lambda *a: sent.append(a) or (True, ""))
    picked = [(2, {"item_id": "X", "watch": 3, "price": 100})]
    got = SO.offer_before_drop(picked, lambda r: True, send=True, log=lambda *a: None)
    assert got == picked and sent == []                        # 一覧が取れない = 送らずに今までどおり落とす


def test_ads_tool_skips_no_ad_items(tmp_path, monkeypatch):
    import ads_add_new_listings as A
    monkeypatch.setattr(SO, "NO_AD_PATH", str(tmp_path / "noad.json"))
    SO.add_no_ad("111", str(tmp_path / "noad.json"))
    monkeypatch.setattr(SO, "no_ad_ids", lambda path=None: {"111"})
    assert A.create_ads("tok", [("L", "111")]) == []           # eBay を呼ばずに外す


def test_shelf_calls_offer_before_drop():
    src = open(os.path.join(os.path.dirname(__file__), "..", "tools", "shelf_evict.py"), encoding="utf-8").read()
    assert "SO.offer_before_drop(picked" in src and "send=a.end" in src
