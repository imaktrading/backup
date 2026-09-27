"""棚②: 公式サイト仕入 (SKU '… official website') を『有在庫？』に出さない (2026-09-27, 残務 №289)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import shelf_evict as se  # noqa: E402


def test_official_sku_is_not_unknown():
    known = {"111"}
    assert se.category_for("999", None, known=known, sku="Wind Blast Parka official website") == se.OFFICIAL
    assert se.category_for("999", None, known=known, sku="m12345678901") == se.ONHAND_UNKNOWN
    assert se.category_for("999", None, known=known) == se.ONHAND_UNKNOWN


def test_official_is_never_dropped():
    assert se.OFFICIAL not in se.STALE_MAX_AGE


def test_funnel_group_uses_same_rule():
    import listing_funnel as lf
    r = {"item_id": "999", "qty": "1", "sku": "graniph official website"}
    assert lf.evict_group(r, known={"111"}) == se.OFFICIAL
