# -*- coding: utf-8 -*-
"""オファーは送れる出品に全部送る (2026-10-09 ユーザー確定: US 8%引き・仕入元が生きている・返事待ちが無い)。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import shelf_offer as SO


def _row(d=""):
    r = [""] * 40
    r[3] = d
    return r


def test_pick_rows():
    rows = [{"item_id": i} for i in ("1", "2", "3", "4", "5")]
    sheet = {"1": _row(), "2": _row("○"), "3": _row(), "5": _row()}
    got = {r["item_id"]: why for r, why in SO.pick_rows(rows, {"1", "2", "3", "4"}, sheet, {"3"})}
    assert got == {"1": "", "2": "仕入元が売り切れ", "3": "バイヤーからのオファーが返事待ち", "4": "商品管理シートに無い"}


def test_discount_is_us_promo_rate():
    assert SO.OFFER_PCT_US == 8


def test_extension_handles_send_page():
    m = json.load(open(os.path.join(HERE, "..", "tools", "sellerhub_grab", "manifest.json"), encoding="utf-8"))
    assert "https://www.ebay.com/sh/lst/active*" in m["content_scripts"][0]["matches"]
    js = open(os.path.join(HERE, "..", "tools", "sellerhub_grab", "content.js"), encoding="utf-8").read()
    assert 'sendOffers("all")' in js and "shgOffersAt" in js


def test_sent_by_button_not_automatically():
    """ユーザー「突然送られると他業務の邪魔になるから、ボタン化して」(2026-10-09)。"""
    src = open(os.path.join(HERE, "..", "console", "server.py"), encoding="utf-8").read()
    assert "offers_daily" not in src
    sys.path.insert(0, os.path.join(HERE, ".."))
    import control_panel as cp
    b = [s for s in cp.SCRIPTS if s["label"] == "💌 オファーを送る (送れる出品に8%引き)"][0]
    assert b["cmd"] == ["python", "shelf_offer.py", "send"] and "#shg-offers" in SO.SEND_URL


def test_extension_closes_sent_modal():
    js = open(os.path.join(HERE, "..", "tools", "sellerhub_grab", "content.js"), encoding="utf-8").read()
    assert "await closeSentModal();" in js and "Got it" in js


def test_count_sendable_is_shown_next_to_psa_new():
    """ユーザー「新規に出せる PSA 221枚 の横にして。送れる件数を表示して」(2026-10-09)。"""
    cnt = open(os.path.join(HERE, "..", "console", "counts.py"), encoding="utf-8").read()
    assert '"offer_send": lambda: __import__("shelf_offer").count_sendable()' in cnt
    js = open(os.path.join(HERE, "..", "console", "static", "app.js"), encoding="utf-8").read()
    i, j = js.index("新規に出せる PSA <b>"), js.index("オファーを送れる <b>")
    assert 0 < j - i < 800


def test_send_batch_is_10_by_watch(monkeypatch):
    """ユーザー「一気処理だと時間かかるよね？1回10件とかにしない？」(2026-10-09)。ウォッチの多い順に10件。"""
    assert SO.SEND_BATCH == 10
    rows = [{"item_id": str(i), "watch": str(i), "price": "100"} for i in range(1, 16)]
    monkeypatch.setattr(SO, "_headers", lambda: {})
    monkeypatch.setattr(SO, "eligible_ids", lambda h: {str(i) for i in range(1, 16)})
    monkeypatch.setattr(SO, "active_offer_ids", lambda: set())
    import psa_hoju_fill as H
    monkeypatch.setattr(H, "_read_high", lambda *a, **k: [["h"]] + [[""] + [str(i)] + [""] * 38 for i in range(1, 16)])
    ledger = {}
    got = SO.plan_items(rows, ledger, log=lambda *a: None, limit=10)
    assert got == {str(i) for i in range(6, 16)}
