# -*- coding: utf-8 -*-
"""棚② を30日回転にする (2026-09-06 ユーザー確定).

> 出品してから30日で取り下げる / WATCHが少ない順 / VIEWが少ない順 / 金額が多い順 /
> SOLD実績ありは除外

## なぜ日数を自店データで決めるのをやめたか
当店は棚卸をしてこなかったため、月間回転率が **0.8%** (月8.2件 / US出品1,022件) まで
落ちている。eBay の検索順位は sell-through を見るので、表示やCTRが低いのは
**商品ではなく店の順位が下がった結果**の可能性が高い。

その内部データから「何日なら売れるか」を決めると、悪循環をそのまま固定してしまう
(実際、9/2 には「アクセスは結果を変えない」として金額順に変更していた)。
よって **予測をやめて方針で回す**。30日で切り、需要の薄いものから落とす。

★効いたかどうかは月間回転率で測る。2〜3ヶ月 上がらなければ仮説が外れたということ。
"""
from __future__ import annotations

import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import shelf_evict as E  # noqa: E402


def _row(iid, age=60, price=100, watch=0, impr=0, qty=1, sold=0):
    return {"item_id": iid, "age_days": age, "price": price, "watch": watch,
            "impr_total": impr, "qty": qty, "sold_qty": sold, "sales90": 0,
            "title": "t" + iid}


def _shelf(r):
    return float(r["price"])


class TestThirtyDayRotation:
    def test_both_categories_are_thirty_days(self):
        assert E.STALE_MAX_AGE["TCG"] == 30
        assert E.STALE_MAX_AGE["G-shock"] == 30, "G-shock も30日で回す"

    def test_thirty_days_or_less_is_kept(self):
        assert E.tier_of(_row("1", age=30), category="TCG") is None
        assert E.tier_of(_row("2", age=30), category="G-shock") is None

    def test_over_thirty_days_is_dropped(self):
        assert E.tier_of(_row("1", age=31), category="TCG") == E.TIER_STALE
        assert E.tier_of(_row("2", age=31), category="G-shock") == E.TIER_STALE

    def test_sold_is_never_dropped(self):
        """★SOLD実績ありは除外。何日 経っていても落とさない。"""
        assert E.tier_of(_row("1", age=999, sold=1), category="TCG") is None
        assert E.tier_of(_row("2", age=999, sold=1), category="G-shock") is None

    def test_other_categories_are_untouched(self):
        """線を引ける根拠が無いカテゴリは触らない。"""
        assert E.tier_of(_row("1", age=999), category="T-Shirts") is None


class TestDropOrder:
    def _pick(self, rows, target=10 ** 9):
        got, _ = E.pick(rows, target, _shelf, cat_of=lambda r: "TCG",
                        only_tier=E.TIER_STALE)
        return [r["item_id"] for _t, r in got]

    def test_fewest_watch_goes_first(self):
        rows = [_row("watch5", watch=5, price=999),
                _row("watch0", watch=0, price=10)]
        assert self._pick(rows)[0] == "watch0", "ウォッチが少ない方が先"

    def test_then_fewest_views(self):
        rows = [_row("view9000", watch=0, impr=9000, price=999),
                _row("view10", watch=0, impr=10, price=10)]
        assert self._pick(rows)[0] == "view10", "同じウォッチなら表示が少ない方が先"

    def test_then_biggest_amount(self):
        """同じくらい需要が無いなら、少ない件数で枠が空く方から。"""
        rows = [_row("cheap", watch=0, impr=0, price=10),
                _row("rich", watch=0, impr=0, price=500)]
        assert self._pick(rows)[0] == "rich"

    def test_full_order(self):
        rows = [_row("D", watch=3, impr=0, price=900),
                _row("C", watch=0, impr=8000, price=900),
                _row("B", watch=0, impr=100, price=50),
                _row("A", watch=0, impr=100, price=800)]
        assert self._pick(rows) == ["A", "B", "C", "D"]

    def test_tier1_still_goes_by_amount(self):
        """①(買えない)は従来どおり 空く額の大きい順 (End の回数を減らす)。"""
        rows = [_row("small", qty=0, watch=0, price=10),
                _row("big", qty=0, watch=9, price=900)]
        got, _ = E.pick(rows, 10 ** 9, _shelf, cat_of=lambda r: "TCG",
                        only_tier=E.TIER_OOS)
        assert [r["item_id"] for _t, r in got][0] == "big"


def test_reason_is_written_down():
    """なぜ自店データで日数を決めないのかを残す (また同じ議論に戻らないため)。"""
    import io
    src = io.open(os.path.join(_TOOLS, "shelf_evict.py"), encoding="utf-8").read()
    assert "0.8%" in src and "回転率" in src
