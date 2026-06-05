#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""listing_funnel の promo-aware 露出判定 回帰テスト (2026-06-05)。

バグ: LQR の Daily impressions は organic のみで PL(広告) impressions を見落とす。
全件プロモ運用では露出の主成分が PL なので、organic だけ見ると「impr≈0=検索に
出てない(NO_SEARCH)」と誤判定し、本当は広告で表示されてるがクリックされてない
(NO_CLICK)商品に relist を空振り処方していた (実機 NO_SEARCH 84→9, relist 76→8)。
修正: PLレポート有り時は organic+PL 累計 impr/ctr + 累計閾値で判定。無ければ旧ロジック。
"""
import importlib.util
import io
import os

_FUNNEL = os.path.join(os.path.dirname(__file__), "..", "tools", "listing_funnel.py")
_spec = importlib.util.spec_from_file_location("listing_funnel", _FUNNEL)
lf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lf)


def _row(iid, **kw):
    r = {"item_id": iid, "qty": 1, "sold_qty": 0, "watch": 0, "sales90": 0, "age_days": 60,
         "price": 100.0, "trend_price": 0.0, "impr": 0.0, "ctr": 0.0,
         "impr_total": 0.0, "ctr_total": 0.0, "has_lqr": False, "has_pl": False}
    r.update(kw)
    return r


def _flags(c, iid):
    return {k for k, v in c.items() if isinstance(v, list) and any(r.get("item_id") == iid for r in v)}


def test_pl_high_impr_zero_click_is_noclick_not_nosearch():
    """広告で大量表示(累計500)だがクリック0 → NO_CLICK。relist(NO_SEARCH)には入れない。"""
    rows = [_row("a", has_pl=True, impr_total=500, ctr_total=0.0)]
    # CTR 下位四分位の母数を作る (露出十分な比較対象)
    rows += [_row(f"hi{i}", has_pl=True, impr_total=400, ctr_total=0.02) for i in range(4)]
    c = lf.classify(rows)
    f = _flags(c, "a")
    assert "NO_CLICK" in f
    assert "NO_SEARCH" not in f
    assert all(r["item_id"] != "a" for r in c["RELIST"])  # relist 空振りを起こさない


def test_pl_near_zero_impr_is_nosearch():
    """累計 impr が極小(<=30) → 真の NO_SEARCH。"""
    rows = [_row("dead", has_pl=True, impr_total=10, ctr_total=0.0, age_days=60)]
    rows += [_row(f"hi{i}", has_pl=True, impr_total=400, ctr_total=0.02) for i in range(4)]
    assert "NO_SEARCH" in _flags(lf.classify(rows), "dead")


def test_pl_new_listing_excluded_to_newwait():
    """累計 impr 極小でも 出品<21日 は NEW_WAIT に隔離 (時間不足)。"""
    rows = [_row("new", has_pl=True, impr_total=5, ctr_total=0.0, age_days=10)]
    f = _flags(lf.classify(rows), "new")
    assert "NEW_WAIT" in f and "NO_SEARCH" not in f


def test_fallback_to_lqr_when_no_promoted():
    """PLレポート無し(has_pl 全 False) → 旧 organic-daily 閾値(3/8)で判定。"""
    rows = [_row("o", has_lqr=True, impr=2.0, ctr=0.0, age_days=60)]  # organic 日次 2 <= 3
    assert "NO_SEARCH" in _flags(lf.classify(rows), "o")


def test_load_promoted_sums_pl_and_organic():
    """total impr = PL + organic, total clicks = PL + organic。"""
    csv_text = (
        "Some note line\n\n"
        "Item ID,Promoted Listings Impressions (via eBay Placements),"
        "Total Promoted Listings Clicks,Organic Impressions,Organic Clicks\n"
        "123,600,4,56,1\n"
    )
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8-sig", newline="") as tf:
        tf.write(csv_text)
        path = tf.name
    try:
        out = lf.load_promoted(path)
        assert out["123"] == (656.0, 5.0)
    finally:
        os.unlink(path)


if __name__ == "__main__":
    import pytest
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
