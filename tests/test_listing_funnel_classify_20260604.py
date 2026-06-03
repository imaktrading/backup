"""listing_funnel.classify() の分類ロジック回帰テスト (2026-06-04)。

3 切り口 (DEAD / STALE / WEAK_TITLE) が想定通り振り分けられることを固定する。
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


def _row(item_id, impr, views, sold):
    vr = round(views / impr, 4) if impr else 0.0
    return {"item_id": item_id, "title": item_id, "impr": impr, "views": views,
            "txn": 0, "ctr": 0, "conv": 0, "vr": vr, "sold_qty": sold, "revenue": 0.0}


def test_dead_requires_low_exposure_and_no_sale():
    """impr/views ともに僅少 + 無販売 → DEAD。1つでも超えれば DEAD ではない。"""
    rows = [
        _row("dead", impr=50, views=2, sold=0),      # 死蔵
        _row("impr_over", impr=500, views=2, sold=0),  # impr 超過 → DEAD でない
        _row("sold", impr=50, views=2, sold=1),        # 売れた → DEAD でない
    ]
    ids = {r["item_id"] for r in classify(rows)["DEAD"]}
    assert ids == {"dead"}


def test_stale_is_viewed_but_unsold():
    """view が付く (>=30) のに 90d 無販売 → STALE。売れていれば除外。"""
    rows = [
        _row("stale", impr=1000, views=80, sold=0),
        _row("sold_well", impr=1000, views=80, sold=3),  # 売れている → 除外
        _row("low_view", impr=1000, views=10, sold=0),    # view 不足 → 除外
    ]
    ids = {r["item_id"] for r in classify(rows)["STALE"]}
    assert ids == {"stale"}


def test_weak_title_is_low_view_rate_among_high_impression():
    """impr は多い (>=200) が view 率が下位 25% → WEAK_TITLE。
    丸め CTR ではなく views/impr で弁別されること。"""
    rows = [
        _row("strong", impr=1000, views=100, sold=0),  # view率 10%
        _row("ok1", impr=1000, views=80, sold=0),       # 8%
        _row("ok2", impr=1000, views=60, sold=0),       # 6%
        _row("weak", impr=1000, views=2, sold=0),       # 0.2% → 下位
        _row("low_impr", impr=50, views=0, sold=0),     # impr 不足 → 対象外
    ]
    result = classify(rows)
    ids = {r["item_id"] for r in result["WEAK_TITLE"]}
    assert "weak" in ids
    assert "strong" not in ids
    assert "low_impr" not in ids  # impr 閾値未満は分母に入れない


def test_weak_title_not_collapsed_when_all_ctr_rounds_to_zero():
    """API CTR が全て 0.00 に丸まっても、view 率で弁別され全件 flag にはならない。"""
    rows = [_row(f"i{i}", impr=1000, views=v, sold=0) for i, v in enumerate([2, 5, 9, 30, 60, 100, 150, 200])]
    weak = classify(rows)["WEAK_TITLE"]
    assert 0 < len(weak) < len(rows)  # 全件でも 0 件でもない
    # 最も view 率が低いものが含まれる
    assert "i0" in {r["item_id"] for r in weak}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
