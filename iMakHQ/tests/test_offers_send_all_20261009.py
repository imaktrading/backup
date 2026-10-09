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


def test_server_runs_offers_daily():
    src = open(os.path.join(HERE, "..", "console", "server.py"), encoding="utf-8").read()
    assert "threading.Timer(120.0, offers_daily).start()" in src and "#shg-offers" in src
