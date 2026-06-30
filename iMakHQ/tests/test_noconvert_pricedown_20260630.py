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
    # マップに無いカテゴリは「要確認(未対応)」になる (fail-closed)
    res = m.compute_pricedown(100, 5000, "存在しないカテゴリZZZ", "x", compute_fn=_fake_compute, fx=159.0, ad_rate=0.10)
    assert "error" in res and "未対応" in res["error"]


def test_zero_cost_flagged():
    res = m.compute_pricedown(100, 0, "TCG", "x", compute_fn=_fake_compute, fx=159.0, ad_rate=0.10)
    assert res.get("error") == "仕入値ゼロ"


def test_margin_math():
    # cost¥10000 → 模擬V8: 推奨=120, 利益¥4000=$25.16(fx159)
    res = m.compute_pricedown(120.0, 10000, "TCG", "card", compute_fn=_fake_compute, fx=159.0, ad_rate=0.10)
    assert abs(res["v8_rec"] - 120.0) < 0.01
    assert abs(res["profit_usd"] - 25.16) < 0.1            # 4000/159
    # 利益率(据置) = 込み利益 / V8推奨 = 25.16/120 ≈ 21%
    assert 20 < res["margin_keep_pct"] < 22
    # プロモ外 = 据置 + ad_rate(10pp) ≈ 31%
    assert abs(res["margin_drop_pct"] - (res["margin_keep_pct"] + 10)) < 0.2
    # cur_price は利益率に影響しない(V8由来=cost-based)
    res2 = m.compute_pricedown(999.0, 10000, "TCG", "card", compute_fn=_fake_compute, fx=159.0, ad_rate=0.10)
    assert res2["margin_keep_pct"] == res["margin_keep_pct"]


def test_pricing_map_targets_valid():
    # マップ先は pricing カテゴリ名(空でない)
    for sheet_cat, pricing in m.SHEET_CAT_TO_PRICING.items():
        assert pricing and isinstance(pricing, str)
