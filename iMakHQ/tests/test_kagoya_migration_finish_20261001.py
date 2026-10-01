"""KAGOYA への移行の残り (2026-10-01・切り替えは後でユーザーが決める)。

- 在庫の確認を API で (Chrome を開かない)。読めない物だけ Chrome に回す
- 🌱 の目視待ちの在庫を KAGOYA が先に確かめ、昼のボタンはそれを使う (offload.json "newcand_stock")
- 入れ替えの間隔を offload.json "swap_every_days" で変えられる (既定 2)
"""
import datetime
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import kagoya_offload as K  # noqa: E402
import mercari_psa_resource as mp  # noqa: E402
import newcand_confirm as NC  # noqa: E402


def test_swap_every_days():
    assert K.swap_every_days({}) == K.SWAP_EVERY_DAYS
    assert K.swap_every_days({"swap_every_days": 1}) == 1
    assert K.swap_every_days({"swap_every_days": 0}) == K.SWAP_EVERY_DAYS
    assert K.swap_every_days({"swap_every_days": "x"}) == K.SWAP_EVERY_DAYS
    assert K.swap_every_days(None) == K.SWAP_EVERY_DAYS


def test_stock_seen_status_uses_only_fresh():
    now = datetime.datetime(2026, 10, 2, 9, 0)
    led = {
        "u1": {"ok": True, "title": "PSA10 A", "at": "2026-10-02T03:00:00"},
        "u2": {"ok": False, "title": "", "at": "2026-10-02T01:00:00"},
        "u3": {"ok": True, "title": "", "at": "2026-10-01T08:00:00"},   # 25時間前 = 使わない
        "u4": {"ok": "yes", "at": "2026-10-02T03:00:00"},                # 壊れている = 使わない
    }
    st, titles = NC.stock_seen_status(["u1", "u2", "u3", "u4", "u5"], led=led, now=now)
    assert st == {"u1": "in_stock", "u2": "sold"}
    assert titles == {"u1": "PSA10 A"}


def test_api_stock_check_with_fake_api(monkeypatch):
    class Item:
        def __init__(self, status, auction=None, name="n"):
            self.status, self.auction_info, self.name = status, auction, name

    class V:
        def __init__(self, q):
            self.quantity = q

    class PD:
        def __init__(self, qs):
            self.variants = [V(q) for q in qs]
            self.shipping_payer = types.SimpleNamespace(code="SELLER")

    class Prod:
        def __init__(self, qs):
            self.product_detail, self.display_name = PD(qs), "shop"

    items = {"m1": Item("on_sale"), "m2": Item("sold_out"), "m3": Item("on_sale", auction=object()),
             "m4": None}
    prods = {"S1": Prod(["2"]), "S2": Prod(["0"])}

    class FakeApi:
        async def item(self, i):
            if i == "m9":
                raise KeyError("data")
            return items[i]

        async def product(self, p):
            return prods[p]

    monkeypatch.setitem(sys.modules, "mercapi", types.SimpleNamespace(Mercapi=FakeApi))
    base = "https://jp.mercari.com/"
    urls = [base + "item/m1", base + "item/m2", base + "item/m3", base + "item/m4", base + "item/m9",
            base + "shops/product/S1", base + "shops/product/S2", "https://snkrdunk.com/apparels/1/used/2"]
    ok, titles, unknown = mp.api_stock_check(urls, sleep=0)
    assert ok == {urls[0]: True, urls[1]: False, urls[2]: False, urls[3]: False,
                  urls[5]: True, urls[6]: False}
    assert set(unknown) == {urls[4], urls[7]}            # 通信の失敗・メルカリ以外 = Chrome で見る
    assert titles[urls[0]] == "n" and titles[urls[5]] == "shop"
