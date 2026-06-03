"""listing_funnel.classify() の分類ロジック回帰テスト (2026-06-04)。

4 切り口 (DEAD / STALE / WEAK_TITLE / WATCHED) が想定通り振り分けられることを固定する。
ネットワークには触れない (classify は純関数)。
"""
import importlib.util
import os

import pytest

_SPEC_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools", "listing_funnel.py")
)
_spec = importlib.util.spec_from_file_location("listing_funnel", _SPEC_PATH)
listing_funnel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(listing_funnel)
classify = listing_funnel.classify


def _row(item_id, impr=0, views=0, sold=0, watch=0, age=10):
    vr = round(views / impr, 4) if impr else 0.0
    return {"item_id": item_id, "title": item_id, "price": 100.0, "watch": watch,
            "start": "", "age_days": age, "url": "", "impr": impr, "views": views,
            "txn": 0, "ctr": 0, "conv": 0, "vr": vr, "sold_qty": sold, "revenue": 0.0}


def test_dead_is_zero_impression_unsold():
    """30d impression ほぼゼロ + 無販売 → DEAD。impr が立てば DEAD でない。"""
    rows = [
        _row("dead", impr=0, sold=0),          # 露出ゼロ = 死蔵
        _row("dead_lo", impr=5, sold=0),       # 閾値内 = 死蔵
        _row("has_impr", impr=500, sold=0),    # 露出あり → DEAD でない
        _row("sold", impr=0, sold=1),          # 売れた → DEAD でない
    ]
    ids = {r["item_id"] for r in classify(rows)["DEAD"]}
    assert ids == {"dead", "dead_lo"}


def test_dead_sorted_oldest_first():
    """死蔵は出品日が古い (age_days 大) 順に並ぶ。"""
    rows = [_row("new", impr=0, age=10), _row("old", impr=0, age=300), _row("mid", impr=0, age=100)]
    order = [r["item_id"] for r in classify(rows)["DEAD"]]
    assert order == ["old", "mid", "new"]


def test_stale_is_viewed_but_unsold():
    """view が付く (>=30) のに無販売 → STALE。売れていれば除外。"""
    rows = [
        _row("stale", impr=1000, views=80, sold=0),
        _row("sold_well", impr=1000, views=80, sold=3),
        _row("low_view", impr=1000, views=10, sold=0),
    ]
    ids = {r["item_id"] for r in classify(rows)["STALE"]}
    assert ids == {"stale"}


def test_weak_title_is_low_view_rate_among_high_impression():
    """impr は多い (>=200) が view 率が下位25% → WEAK_TITLE。views/impr で弁別。"""
    rows = [
        _row("strong", impr=1000, views=100),  # 10%
        _row("ok1", impr=1000, views=80),
        _row("ok2", impr=1000, views=60),
        _row("weak", impr=1000, views=2),       # 0.2% → 下位
        _row("low_impr", impr=50, views=0),     # impr 不足 → 対象外
    ]
    ids = {r["item_id"] for r in classify(rows)["WEAK_TITLE"]}
    assert "weak" in ids
    assert "strong" not in ids
    assert "low_impr" not in ids


def test_weak_title_not_collapsed_when_all_ctr_rounds_to_zero():
    """API CTR が全て 0.00 に丸まっても、view 率で弁別され全件 flag にはならない。"""
    rows = [_row(f"i{i}", impr=1000, views=v) for i, v in enumerate([2, 5, 9, 30, 60, 100, 150, 200])]
    weak = classify(rows)["WEAK_TITLE"]
    assert 0 < len(weak) < len(rows)
    assert "i0" in {r["item_id"] for r in weak}


def test_watched_is_watchcount_without_sale():
    """WatchCount>=3 なのに無販売 → WATCHED。売れていれば除外。watch 多い順。"""
    rows = [
        _row("hot", impr=500, views=50, sold=0, watch=12),
        _row("warm", impr=500, views=50, sold=0, watch=4),
        _row("sold", impr=500, views=50, sold=2, watch=9),   # 売れた → 除外
        _row("no_watch", impr=500, views=50, sold=0, watch=1),  # watch 不足 → 除外
    ]
    watched = classify(rows)["WATCHED"]
    assert [r["item_id"] for r in watched] == ["hot", "warm"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
