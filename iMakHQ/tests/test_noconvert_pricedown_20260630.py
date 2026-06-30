# -*- coding: utf-8 -*-
"""noconvert_pricedown: NO_CONVERT 値下げ余地 算出の回帰テスト (2026-06-30)。
売切=仕入不可除外 / カテゴリ未対応=要確認(fail-closed) / floor=損益分岐 を検証。"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import noconvert_pricedown as m


def _fake_compute(cost_jpy, median, cat, title):
    # V8模擬: 推奨= cost/100 + 20, 利益= cost*0.4 (¥)
    return {"price": cost_jpy / 100.0 + 20, "profit_jpy": cost_jpy * 0.4,
            "category_resolved": cat}


def test_sold_out_detection():
    assert m.is_sold_out("○") and m.is_sold_out("〇")
    assert not m.is_sold_out("") and not m.is_sold_out("x")


def test_unmapped_category_is_flagged():
    res = m.compute_pricedown(100, 5000, "グッズ", "x", compute_fn=_fake_compute, fx=159.0, ad_rate=0.10)
    assert "error" in res and "未対応" in res["error"]


def test_zero_cost_flagged():
    res = m.compute_pricedown(100, 0, "TCG", "x", compute_fn=_fake_compute, fx=159.0, ad_rate=0.10)
    assert res.get("error") == "仕入値ゼロ"


def test_floor_and_room_math():
    # cost¥10000, cur$120, fx159, ad0.10。推奨=120, 利益¥4000=$25.16
    res = m.compute_pricedown(120.0, 10000, "TCG", "card", compute_fn=_fake_compute, fx=159.0, ad_rate=0.10)
    assert abs(res["v8_rec"] - 120.0) < 0.01
    assert abs(res["profit_usd"] - 25.16) < 0.1            # 4000/159
    # floor据置 = 推奨 - 利益$ = 120 - 25.16 = 94.84
    assert abs(res["floor_keep"] - 94.84) < 0.1
    # floor外 = floor据置 - ad*推奨 = 94.84 - 12 = 82.84
    assert abs(res["floor_drop"] - 82.84) < 0.1
    # 値下げ余地(据置) = (120-94.84)/120 ≈ 21%
    assert 20 < res["room_keep_pct"] < 22
    # プロモ外す方が余地大
    assert res["room_drop_pct"] > res["room_keep_pct"]


def test_pricing_map_targets_valid():
    # マップ先は pricing カテゴリ名(空でない)
    for sheet_cat, pricing in m.SHEET_CAT_TO_PRICING.items():
        assert pricing and isinstance(pricing, str)
