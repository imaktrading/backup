# -*- coding: utf-8 -*-
"""棚②: ウォッチ0で出品200日超は作品に関係なく先に落とす (2026-09-15)。

ユーザー「WATCHが0で200日以上なら、カテゴリ関係なく、不良在庫＝陳列居座り＝SEOロスじゃないのかな」。
実測 (9/15 ファネル・US 200日超): ウォッチ0 63件 → 90日で売れ1 / ウォッチ1以上 50件 → 売れ2。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import listing_funnel as lf  # noqa: E402
import shelf_evict as se  # noqa: E402


def _row(iid, title, age, watch=0, price=100):
    return {"item_id": iid, "title": title, "qty": 1, "sold_qty": 0, "sales90": 0,
            "watch": watch, "impr_total": 10, "age_days": age, "price": price}


def test_is_dead_shelf():
    assert se.is_dead_shelf(_row("1", "x", 201))
    assert not se.is_dead_shelf(_row("1", "x", 200))
    assert not se.is_dead_shelf(_row("1", "x", 400, watch=1))


def test_dead_g_shock_drops_before_live_gundam():
    rows = [_row("gundam", "PSA 10 Gundam CCG", 60, watch=2),
            _row("gshock", "CASIO G-Shock GA-2100", 250),
            _row("pokemon", "PSA 10 Pokemon SV5a", 300)]
    picked, _ = se.pick(rows, target=1000, shelf_of=lambda r: float(r["price"]),
                        cat_of=lambda r: "G-shock" if "G-Shock" in r["title"] else "TCG",
                        only_tier=se.TIER_STALE)
    ids = [r["item_id"] for _t, r in picked]
    # 居座り2件が先 (その中は今までどおり作品順 = G-SHOCK → ポケモン)、ウォッチのあるガンダムは後
    assert ids == ["gshock", "pokemon", "gundam"], ids


def test_funnel_group_name():
    assert lf.evict_group(_row("1", "CASIO G-Shock GA-2100", 250)) == "落とす1 ウォッチ0・200日超"
    assert lf.evict_group(_row("1", "CASIO G-Shock GA-2100", 250, watch=1)).startswith("落とす4")
    # 有在庫・売れた物は今までどおり残す
    assert lf.evict_group(_row("1", "CASIO G-Shock GA-2100", 250), onhand={"1"}) == lf._EVICT_ONHAND
    sold = dict(_row("1", "CASIO G-Shock GA-2100", 250), sold_qty=1)
    assert lf.evict_group(sold) == lf._EVICT_KEEP_SOLD
