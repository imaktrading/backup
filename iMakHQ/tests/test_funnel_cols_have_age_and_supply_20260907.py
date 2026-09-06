"""ファネル分析スプシの列に age_days / supply_url が在ることを固定する (2026-09-07).

背景:
  「在庫ありで落とす候補」は **出品からの日数** で切る (30日回転 / 2026-09-06 決定) のに、
  スプシのタブに age_days が無く、CSV を開かないと切り分けられなかった。
  supply_url (戻せるかの判断材料) も同様。列を落とすと同じことが起きるので固定する。
"""
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import listing_funnel as lf  # noqa: E402


def test_cols_include_age_and_supply():
    assert "age_days" in lf.FUNNEL_COLS
    assert "supply_url" in lf.FUNNEL_COLS


def test_vals_line_up_with_cols():
    """値の並びが列と1対1であること (ズレると別の列に値が入る)."""
    r = {"item_id": "1", "title": "t", "site": "US", "price": 1.0, "trend_price": 0,
         "qty": 1, "sold_qty": 0, "watch": 2, "impr": 3.0, "ctr": 0.01,
         "age_days": 45, "supply_url": "https://jp.mercari.com/item/m1"}
    vals = lf._funnel_vals(r)
    assert len(vals) == len(lf.FUNNEL_COLS)
    by_col = dict(zip(lf.FUNNEL_COLS, vals))
    assert by_col["age_days"] == 45
    assert by_col["supply_url"] == "https://jp.mercari.com/item/m1"
    assert by_col["ebay_url"].endswith("/1")


def test_ebay_url_stays_last():
    """在庫なしタブは末尾に「状態」を足すので、URL は最後のままであること."""
    assert lf.FUNNEL_COLS[-1] == "ebay_url"
